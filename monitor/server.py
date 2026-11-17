"""带随机访问路径的本地指标服务。只返回结构化摘要。"""

import argparse
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from .metrics import Metrics

ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


class Store:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def snapshot(self, thread_id):
        if not UUID.fullmatch(thread_id):
            raise ValueError("无效会话 ID")
        with self.lock:
            db_path = self.home / "state_5.sqlite"
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
                row = db.execute("select rollout_path,title from threads where id=?", (thread_id,)).fetchone()
            if not row:
                raise FileNotFoundError("未找到此会话的本地日志")
            path = Path(row[0]).resolve()
            if not any(path.is_relative_to(self.home / sub) for sub in ("sessions", "archived_sessions")):
                raise ValueError("会话日志路径不在允许目录内")
            stat = path.stat()
            state = self.cache.get(thread_id)
            if not state or state["inode"] != stat.st_ino or stat.st_size < state["offset"] or state["path"] != path:
                state = {"metrics": Metrics(), "inode": stat.st_ino, "offset": 0, "bad_lines": 0, "path": path}
                self.cache[thread_id] = state
            with path.open("rb") as stream:
                stream.seek(state["offset"])
                for _ in range(200000):
                    line = stream.readline()
                    if not line or not line.endswith(b"\n"):
                        break
                    state["offset"] = stream.tell()
                    try:
                        state["metrics"].feed(json.loads(line))
                    except (ValueError, TypeError, AttributeError):
                        state["bad_lines"] += 1
            self.cache.move_to_end(thread_id)
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
            result = state["metrics"].snapshot()
            result.update(thread_id=thread_id, title=row[1], bad_lines=state["bad_lines"],
                          fetched_at=time.time()*1000, log_modified_at=stat.st_mtime*1000,
                          loading=state["offset"] < stat.st_size)
            return result


def make_server(store, token, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_body(self, status, data, mime="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def error(self, status, message):
            self.send_body(status, json.dumps({"error": message}, ensure_ascii=False).encode())

        def do_GET(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host or self.headers.get("Origin") not in (None, "http://"+host):
                return self.error(403, "不允许跨来源访问")
            path = urlsplit(self.path).path
            prefix = "/" + token + "/"
            if not path.startswith(prefix):
                return self.error(404, "未找到")
            route = path[len(prefix):]
            if route == "health":
                return self.send_body(200, b'{"service":"codex-context-monitor","version":"0.2.0"}')
            if route.startswith("api/session/"):
                try:
                    result = store.snapshot(route[len("api/session/"):])
                    return self.send_body(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
                except (ValueError, FileNotFoundError):
                    return self.error(404, "未找到有效的本地会话日志")
                except (OSError, sqlite3.Error):
                    return self.error(503, "本地日志暂时不可读")
            assets = {"": ("index.html", "text/html"), "panel.js": ("panel.js", "text/javascript"),
                      "panel.css": ("panel.css", "text/css"), "bootstrap.js": ("bootstrap.js", "text/javascript")}
            if route not in assets:
                return self.error(404, "未找到")
            file, mime = assets[route]
            self.send_body(200, (ROOT / "ui" / file).read_bytes(), mime)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home()/".codex")))
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    args.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(24)
    port = 0
    state_file = args.runtime / "server.json"
    # 保留本机面板书签；端口已被占用时重新分配，不连接未知服务。
    try:
        previous = urlsplit(json.loads(state_file.read_text())["url"])
        previous_token = previous.path.strip("/")
        if previous.scheme == "http" and previous.hostname == "127.0.0.1" and re.fullmatch(r"[A-Za-z0-9_-]{32}", previous_token):
            port = previous.port or 0
            token = previous_token
    except (OSError, ValueError, KeyError):
        pass
    try:
        server = make_server(Store(args.home), token, port)
    except OSError:
        if not port:
            raise
        token = secrets.token_urlsafe(24)
        server = make_server(Store(args.home), token)
    state = {"pid":os.getpid(), "url":f"http://127.0.0.1:{server.server_port}/{token}/", "root":str(ROOT)}
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(state_file)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
