#!/bin/bash
#
# 白日梦内容分发助手 · macOS 卸载
# 双击运行；会先停止后台服务，再删除应用，最后询问是否清空账号 Cookie 与任务数据。
#
set -uo pipefail
cd "$(dirname "$0")"

APP_NAME="白日梦内容分发助手"
APP_PATH="$HOME/Applications/${APP_NAME}.app"
APP_SUPPORT="$HOME/Library/Application Support/DaydreamDispatch"

printf '\n==============================================\n'
printf '  %s · 卸载\n' "$APP_NAME"
printf '==============================================\n\n'

read -r -p "确认卸载 ${APP_NAME}？[y/N] " CONFIRM
case "$CONFIRM" in
  y|Y) ;;
  *) echo "已取消。"; read -r -n 1 -s; exit 0 ;;
esac

echo "停止后台服务…"
pkill -f "DaydreamDispatch/app/workbench_server.py" 2>/dev/null || true
pkill -f "DaydreamDispatch/venv/bin/python" 2>/dev/null || true

if [ -d "$APP_PATH" ]; then
  rm -rf "$APP_PATH"
  echo "已删除应用：$APP_PATH"
else
  echo "未找到应用，跳过。"
fi

printf '\n账号 Cookie、任务记录、上传素材和运行环境在：\n  %s\n' "$APP_SUPPORT"
read -r -p "是否一并删除这些用户数据？[y/N] " PURGE
case "$PURGE" in
  y|Y)
    rm -rf "$APP_SUPPORT"
    echo "已清空用户数据。"
    ;;
  *)
    echo "已保留用户数据，下次安装会继续沿用登录状态。"
    ;;
esac

printf '\n卸载完成。按任意键关闭窗口…\n'
read -r -n 1 -s || true
