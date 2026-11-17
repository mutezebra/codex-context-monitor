#!/bin/sh
# 必须在用户自行退出应用后运行，避免中断其他聊天。
set -eu
plugin_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
app_path=${CONTEXT_MONITOR_APP:-/Applications/ChatGPT.app}
debug_port=${CONTEXT_MONITOR_PORT:-9222}
case "$debug_port" in ''|*[!0-9]*) echo '调试端口必须为数字' >&2; exit 1;; esac
if pgrep -f "$app_path/Contents/MacOS/" >/dev/null; then
  echo '应用仍在运行。请先等待其他任务完成并正常退出，再执行本脚本；本脚本不会强制退出应用。' >&2
  exit 2
fi
open -a "$app_path" --args --remote-debugging-address=127.0.0.1 --remote-debugging-port="$debug_port"
echo '已请求以本地调试模式启动。进入目标聊天后运行：'
printf 'python3 "%s/scripts/manage.py" toolbar --port %s\n' "$plugin_root" "$debug_port"
