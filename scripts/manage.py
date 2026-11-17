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
sys.path.insert(0,str(ROOT))
from monitor import autostart


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
    process=None
    if autostart.enabled(RUNTIME):
        autostart.ensure_agents()
    else:
        with (RUNTIME/"service.log").open("ab") as log:
            process=subprocess.Popen([sys.executable,"-m","monitor.server","--runtime",str(RUNTIME)],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    for _ in range(50):
        state=live_state()
        if state:
            return state
        if process and process.poll() is not None:
            raise RuntimeError("服务启动失败，请查看 "+str(RUNTIME/"service.log"))
        time.sleep(.1)
    if process:process.terminate()
    raise RuntimeError("服务启动超时")


def main():
    parser=argparse.ArgumentParser(description="Context Monitor 本地控制")
    parser.add_argument("action",choices=["start","stop","status","toolbar","enable-autostart","disable-autostart","launch"])
    parser.add_argument("--thread",help="面板固定绑定的 Codex 会话 UUID")
    parser.add_argument("--port",type=int,default=9222,help="已开启的本地 Codex DevTools 端口")
    parser.add_argument("--app",type=Path,default=Path('/Applications/ChatGPT.app'),help="原桌面应用路径")
    parser.add_argument("--no-dock",action='store_true',help="安装常驻服务但不修改 Dock 入口")
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
            result=state or {"running":False}
            result['persistent']=autostart.enabled(RUNTIME)
            if result['persistent']:result['agents']=autostart.agent_status()
            print(json.dumps(result,ensure_ascii=False))
        elif args.action=="enable-autostart":
            if not 1<=args.port<=65535:raise ValueError('无效端口')
            print(json.dumps(autostart.install(ROOT,RUNTIME,args.app,args.port,not args.no_dock),ensure_ascii=False))
        elif args.action=="disable-autostart":
            print(json.dumps(autostart.disable(RUNTIME),ensure_ascii=False))
        elif args.action=="launch":
            print(json.dumps(autostart.launch(RUNTIME),ensure_ascii=False))
        elif args.action=="toolbar":
            state=start()
            if autostart.enabled(RUNTIME):
                autostart.ensure_agents()
                print('常驻采集器已启动，会自动等待应用并恢复状态条。')
                return
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
            if autostart.enabled(RUNTIME):
                autostart.pause()
                print('监控已暂停；start 可恢复，下次登录也会自动启动。永久关闭请使用 disable-autostart。')
                return
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
