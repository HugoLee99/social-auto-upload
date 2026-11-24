#!/bin/bash
#
# 白日梦内容分发助手 · macOS 一键安装
# 双击运行（若提示“无法验证开发者”，右键 → 打开）。
# 也可以打开“终端”，执行： bash "$(dirname "$0")/安装白日梦.command"
#
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="白日梦内容分发助手"
APP_SUPPORT="$HOME/Library/Application Support/DaydreamDispatch"
APP_PATH="$HOME/Applications/${APP_NAME}.app"
PAYLOAD_SRC="$(pwd)/payload"
PAYLOAD_DST="$APP_SUPPORT/app"
VENV="$APP_SUPPORT/venv"
BROWSERS="$APP_SUPPORT/ms-playwright"
ICON_SRC="$PAYLOAD_SRC/daydream-512.png"

say() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m! %s\033[0m\n' "$*"; }
die() {
  printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2
  printf '\n按任意键关闭窗口…\n'
  read -r -n 1 -s || true
  exit 1
}
trap 'die "安装中断（第 $LINENO 行）。请把窗口里的报错发给我们。"' ERR

[ "$(uname -s)" = "Darwin" ] || die "这个安装包只能在 macOS 上运行。"
[ -d "$PAYLOAD_SRC" ] || die "安装包不完整：缺少 payload 目录。请重新解压完整的 zip。"

printf '\n==============================================\n'
printf '  %s · macOS 安装\n' "$APP_NAME"
printf '==============================================\n\n'

ARCH="$(uname -m)"
say "系统架构：$ARCH（macOS $(sw_vers -productVersion)）"
[ "$ARCH" = "arm64" ] || [ "$ARCH" = "x86_64" ] || die "不支持的架构：$ARCH"

# ---------------------------------------------------------------- 1. 复制程序
say "复制程序到 $PAYLOAD_DST"
mkdir -p "$APP_SUPPORT"
rm -rf "$PAYLOAD_DST"
cp -R "$PAYLOAD_SRC" "$PAYLOAD_DST"

# 部分上传器按 conf.BASE_DIR/utils/stealth.min.js 读取反检测脚本，
# 而打包版的 BASE_DIR 指向数据目录，这里补一份到数据目录，避免运行时找不到文件。
if [ -f "$PAYLOAD_DST/utils/stealth.min.js" ]; then
  mkdir -p "$APP_SUPPORT/utils"
  cp "$PAYLOAD_DST/utils/stealth.min.js" "$APP_SUPPORT/utils/stealth.min.js"
fi
ok "程序文件已就位"

# ---------------------------------------------------------------- 2. uv
if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
  UV="$HOME/.local/bin/uv"
else
  say "安装 uv（Python 环境管理工具，装到 ~/.local/bin）"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV="$HOME/.local/bin/uv"
  [ -x "$UV" ] || die "uv 安装失败。请检查网络/代理后重新双击安装。"
fi
ok "uv：$UV"

# ---------------------------------------------------------------- 3. Python 环境
say "创建 Python 3.12 环境（首次约 2-5 分钟）"
"$UV" venv --python 3.12 --allow-existing "$VENV"

say "安装依赖（约 150-250MB，需要联网）"
"$UV" pip install --python "$VENV/bin/python" \
  "loguru==0.7.3" \
  "opencv-python>=4.13.0.92" \
  "patchright==1.64.4" \
  "playwright==1.52.0" \
  "xhs==0.2.13" \
  "qrcode==8.2" \
  "requests==2.32.3" \
  "segno>=1.6.6" \
  "tinycss2>=1.4.0,<2" \
  "Flask[async]==3.1.1" \
  "flask-cors==6.0.0"
ok "Python 依赖安装完成"

# ---------------------------------------------------------------- 4. Chromium
say "安装内置 Chromium（约 130MB，首次较慢）"
if ! PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" "$VENV/bin/python" -m patchright install chromium; then
  warn "内置 Chromium 未安装成功：程序会自动改用你机器上的 Google Chrome / Microsoft Edge。"
  warn "建议之后在终端执行下面这条命令补装："
  printf '    PLAYWRIGHT_BROWSERS_PATH="%s" "%s/bin/python" -m patchright install chromium\n' "$BROWSERS" "$VENV"
fi

# ---------------------------------------------------------------- 5. 生成 .app
say "生成应用：$APP_PATH"
rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"

cat > "$APP_PATH/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>白日梦内容分发助手</string>
    <key>CFBundleDisplayName</key>
    <string>白日梦内容分发助手</string>
    <key>CFBundleExecutable</key>
    <string>Daydream</string>
    <key>CFBundleIdentifier</key>
    <string>com.daydream.dispatch</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

cat > "$APP_PATH/Contents/MacOS/Daydream" <<'LAUNCH'
#!/bin/bash
# 白日梦内容分发助手启动器
set -e
APP_SUPPORT="$HOME/Library/Application Support/DaydreamDispatch"
export SAU_DATA_DIR="$APP_SUPPORT"
export PLAYWRIGHT_BROWSERS_PATH="$APP_SUPPORT/ms-playwright"
export SAU_OPEN_BROWSER=1
PORT="${SAU_PORT:-5409}"

# 已经在运行就直接打开控制台，避免重复起服务
if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/" 2>/dev/null | grep -q "白日梦"; then
  open "http://127.0.0.1:${PORT}"
  exit 0
fi

cd "$APP_SUPPORT/app"
exec "$APP_SUPPORT/venv/bin/python" workbench_server.py
LAUNCH
chmod 755 "$APP_PATH/Contents/MacOS/Daydream"

if [ -f "$ICON_SRC" ]; then
  ICONSET="$APP_PATH/Contents/Resources/daydream.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z "$s" "$s" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1 || true
    sips -z "$((s * 2))" "$((s * 2))" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1 || true
  done
  if iconutil -c icns "$ICONSET" -o "$APP_PATH/Contents/Resources/AppIcon.icns" >/dev/null 2>&1; then
    ok "应用图标已生成"
  else
    warn "图标生成失败，不影响使用"
  fi
  rm -rf "$ICONSET"
fi

# 本机生成的 .app 不走 Gatekeeper，但补一次 ad-hoc 签名更稳
codesign --force --deep --sign - "$APP_PATH" >/dev/null 2>&1 || warn "ad-hoc 签名失败，通常不影响本机运行"
xattr -dr com.apple.quarantine "$APP_PATH" 2>/dev/null || true
ok "应用已生成"

# ---------------------------------------------------------------- 6. 启动
say "安装完成，正在启动"
open "$APP_PATH"

printf '\n'
ok "浏览器会自动打开 http://127.0.0.1:5409，若没弹出请手动打开这个地址。"
printf '  应用位置：%s\n' "$APP_PATH"
printf '  数据目录：%s\n' "$APP_SUPPORT"
printf '  日志目录：%s\n' "$APP_SUPPORT/.local/workbench/logs"
printf '\n以后从“启动台 / 应用程序”打开“%s”即可。\n' "$APP_NAME"
printf '需要关闭服务时：右键 Dock 图标 → 退出，或在“活动监视器”结束 python 进程。\n\n'
printf '按任意键关闭此窗口…\n'
read -r -n 1 -s || true
