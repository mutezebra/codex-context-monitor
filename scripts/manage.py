#!/usr/bin/env python3
"""启动或停止用户自己的本地监控服务。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("XDG_STATE_HOME", Path.home()/".local/state")) / "codex-context-monitor"


def live_state():
    try:
        state=json.loads((RUNTIME/"server.json").read_text())
        with urlopen(state["url"]+"health", timeout=1) as r:
            if json.load(r).get("service")=="codex-context-monitor":
                return state
    except (OSError, ValueError, KeyError):
        return None


def start():
    state=live_state()
    if state:
        return state
    with (RUNTIME/"service.log").open("ab") as log:
        process=subprocess.Popen([sys.executable,"-m","monitor.server","--runtime",str(RUNTIME)],
            cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    for _ in range(50):
        state=live_state()
        if state:
            return state
        if process.poll() is not None:
            raise RuntimeError("服务启动失败，请查看 "+str(RUNTIME/"service.log"))
        time.sleep(.1)
    process.terminate()
    raise RuntimeError("服务启动超时")


def main():
    parser=argparse.ArgumentParser(description="Context Monitor 本地控制")
    parser.add_argument("action",choices=["start","stop","status","toolbar"])
    parser.add_argument("--thread",help="面板固定绑定的 Codex 会话 UUID")
    parser.add_argument("--port",type=int,default=9222,help="已开启的本地 Codex DevTools 端口")
    args=parser.parse_args()
    RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (RUNTIME/"control.lock").open("w") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if args.action=="start":
            state=start()
            if args.thread:
                sys.path.insert(0,str(ROOT))
                from monitor.server import UUID
                if not UUID.fullmatch(args.thread):
                    raise ValueError("无效会话 UUID")
                state={**state,"panel_url":state["url"]+"?"+urlencode({"thread":args.thread})}
            print(json.dumps(state,ensure_ascii=False))
        elif args.action=="status":
            state=live_state()
            print(json.dumps(state or {"running":False},ensure_ascii=False))
        elif args.action=="toolbar":
            state=start()
            result=subprocess.run(["node",str(ROOT/"scripts/attach.mjs"),"--port",str(args.port),
                                   "--runtime",str(RUNTIME),"--once"])
            if result.returncode:
                sys.exit(result.returncode)
            try:
                old=json.loads((RUNTIME/"toolbar.json").read_text())
                command=subprocess.run(["ps","-p",str(old["pid"]),"-o","command="],capture_output=True,text=True).stdout
                if str(ROOT/"scripts/attach.mjs") in command:
                    print("工具栏采集器已运行")
                    return
            except (OSError, ValueError, KeyError):
                pass
            with (RUNTIME/"toolbar.log").open("ab") as log:
                process=subprocess.Popen(["node",str(ROOT/"scripts/attach.mjs"),"--port",str(args.port),"--runtime",str(RUNTIME)],
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
            (RUNTIME/"toolbar.json").write_text(json.dumps({"pid":process.pid}))
            print("工具栏采集器已启动")
        else:
            state=live_state()
            if state:
                # 验证 PID 仍指向本服务，防止旧状态文件误杀复用的进程号。
                command=subprocess.run(["ps","-p",str(state["pid"]),"-o","command="],capture_output=True,text=True).stdout
                if "monitor.server" in command and str(RUNTIME) in command:
                    os.kill(state["pid"],signal.SIGTERM)
                    print("监控服务已停止；面板会显示断开，工具栏采集器将自动移除注入。")
                else:
                    raise RuntimeError("服务进程身份不匹配，未停止")
            else:
                print("监控服务未运行")


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError) as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
