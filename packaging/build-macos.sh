#!/usr/bin/env bash
#
# 白日梦内容分发助手 / Daydream Dispatch —— macOS 原生发行包
#
# 产物：release/DaydreamDispatch-<版本>-macOS-<架构>.dmg
#       DMG 内是 .app 与 /Applications 快捷方式，用户拖进去即可安装。
#
# 只能在真实 macOS 上运行：PyInstaller 打包的是宿主平台二进制，Patchright 的
# Chromium 也按 CPU 架构下载，Windows / Linux 无法交叉编译 macOS 产物。
#
# 用法：
#   chmod +x packaging/build-macos.sh
#   ./packaging/build-macos.sh                    # 本机架构 + ad-hoc 签名（内测可用）
#   ./packaging/build-macos.sh --skip-frontend    # 复用已构建的前端
#
#   DEVELOPER_ID="Developer ID Application: 名称 (TEAMID)" \
#   APPLE_ID="me@example.com" APPLE_APP_PASSWORD="abcd-abcd-abcd-abcd" \
#   APPLE_TEAM_ID="TEAMID" \
#   ./packaging/build-macos.sh                    # 正式签名 + 公证 + 装订票据
#
# 可选环境变量：
#   DAYDREAM_VERSION=0.1.0        版本号，默认读 pyproject.toml
#   PLAYWRIGHT_DOWNLOAD_HOST=...  Chromium 下载镜像，国内可用 https://npmmirror.com/mirrors/playwright
#   SKIP_BROWSER=1                不内嵌 Chromium（体积小，但依赖用户自装 Chrome/Edge）
#
set -euo pipefail

APP_NAME="白日梦内容分发助手"
BUNDLE_ID="com.daydream.dispatch"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGING="$PROJECT_ROOT/packaging"
PYTHON="$PROJECT_ROOT/.venv-macos/bin/python"
APP_BUNDLE="$PROJECT_ROOT/dist/${APP_NAME}.app"
RELEASE="$PROJECT_ROOT/release"
ENTITLEMENTS="$PACKAGING/macos/entitlements.plist"
ARCH="$(uname -m)"
SKIP_FRONTEND=0

for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[1;36m[白日梦]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[完成]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[注意]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }

trap 'fail "第 $LINENO 行执行失败，已中止。"' ERR

# ---------------------------------------------------------------- 0. 环境检查
[ "$(uname -s)" = "Darwin" ] || fail "本脚本只能在 macOS 上运行（当前系统：$(uname -s)）。macOS 二进制无法从其他平台交叉编译，请在 Mac 或 GitHub Actions 的 macos runner 上执行。"

xcode-select -p >/dev/null 2>&1 || fail "缺少 Xcode Command Line Tools，请先执行：xcode-select --install"

command -v node >/dev/null 2>&1 || fail "缺少 Node.js（构建前端需要），请先安装 Node.js 18+：https://nodejs.org 或 brew install node"
command -v npm  >/dev/null 2>&1 || fail "缺少 npm，请随 Node.js 一起安装。"

if ! command -v uv >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    log "未检测到 uv，正在安装（Python 环境管理工具，写入 ~/.local/bin）"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || fail "uv 安装失败，请手动安装后重试：https://docs.astral.sh/uv/"
  fi
fi

VERSION="${DAYDREAM_VERSION:-$(sed -n 's/^version *= *"\(.*\)"/\1/p' "$PROJECT_ROOT/pyproject.toml" | head -n1)}"
[ -n "$VERSION" ] || VERSION="0.1.0"

log "开始构建：版本 $VERSION / 架构 $ARCH"
log "工程目录：$PROJECT_ROOT"

# ---------------------------------------------------------------- 1. Python 环境
log "准备 Python 3.12 虚拟环境（.venv-macos）"
uv venv --python 3.12 --allow-existing "$PROJECT_ROOT/.venv-macos"

# 直接安装运行依赖，避免 editable 安装触发项目元数据里的历史遗留模块声明。
RUNTIME_DEPS=(
  "loguru==0.7.3"
  "opencv-python>=4.13.0.92"
  "patchright==1.64.4"
  "playwright==1.52.0"
  "xhs==0.2.13"
  "qrcode==8.2"
  "requests==2.32.3"
  "segno>=1.6.6"
  "tinycss2>=1.4.0,<2"
  "Flask[async]==3.1.1"
  "flask-cors==6.0.0"
)
log "安装运行依赖与打包工具"
uv pip install --python "$PYTHON" "${RUNTIME_DEPS[@]}"
uv pip install --python "$PYTHON" pyinstaller pillow

# ---------------------------------------------------------------- 2. 前端
if [ "$SKIP_FRONTEND" -eq 0 ]; then
  log "构建 Vue 前端"
  cd "$PROJECT_ROOT/sau_frontend"
  npm install --ignore-scripts --no-audit --no-fund
  npm run build
  cd "$PROJECT_ROOT"
else
  warn "已跳过前端构建，使用 sau_frontend/dist 现有产物"
fi
[ -f "$PROJECT_ROOT/sau_frontend/dist/index.html" ] || fail "sau_frontend/dist/index.html 不存在，请先构建前端"

# ---------------------------------------------------------------- 3. 图标
log "生成 macOS 图标（.icns）"
"$PYTHON" "$PACKAGING/make_icons.py"
[ -f "$PACKAGING/icons/daydream.icns" ] || fail "iconutil 生成 .icns 失败，请确认 Xcode CLT 完整安装"

# ---------------------------------------------------------------- 4. 内嵌浏览器
export PLAYWRIGHT_BROWSERS_PATH="$PACKAGING/playwright-browsers"
if [ "${SKIP_BROWSER:-0}" = "1" ]; then
  export SAU_BUNDLE_BROWSER=0
  warn "已按 SKIP_BROWSER=1 跳过 Chromium，安装包只会在用户机器的 Chrome/Edge 上运行"
else
  export SAU_BUNDLE_BROWSER=1
  log "下载并内嵌 Patchright Chromium（${ARCH}）"
  if ! "$PYTHON" -m patchright install chromium; then
    warn "python -m patchright 失败，改用 patchright 命令行重试"
    "$PROJECT_ROOT/.venv-macos/bin/patchright" install chromium
  fi
fi

# ---------------------------------------------------------------- 5. PyInstaller
log "PyInstaller 打包 .app"
cd "$PROJECT_ROOT"
"$PYTHON" -m PyInstaller --noconfirm --clean "$PACKAGING/daydream_dispatch.spec"
[ -d "$APP_BUNDLE" ] || fail "未生成 ${APP_BUNDLE}，请查看上方 PyInstaller 日志"

# 许可证随包分发（上游为 MIT）
mkdir -p "$APP_BUNDLE/Contents/Resources"
cp "$PROJECT_ROOT/LICENSE" "$APP_BUNDLE/Contents/Resources/LICENSE.txt"
cp "$PROJECT_ROOT/THIRD_PARTY_NOTICES.txt" "$APP_BUNDLE/Contents/Resources/THIRD_PARTY_NOTICES.txt"
xattr -cr "$APP_BUNDLE" 2>/dev/null || true

# ---------------------------------------------------------------- 5.5 内嵌 Chromium
# 不能交给 PyInstaller 收 datas：它会对 Mach-O 重新签名，而 Chrome for Testing 的
# framework 带 Google 签名，重签会报 "bundle format unrecognized, invalid, or unsuitable"。
# 因此在 PyInstaller 结束后整目录拷贝，保留浏览器自身签名。
if [ "${SKIP_BROWSER:-0}" != "1" ] && [ -d "$PACKAGING/playwright-browsers" ]; then
  log "内嵌 Chromium（保留 Google 原有签名，不参与 PyInstaller 签名）"
  DATA_ROOT="$APP_BUNDLE/Contents/Frameworks"
  if [ -d "$APP_BUNDLE/Contents/Resources/sau_frontend" ]; then
    DATA_ROOT="$APP_BUNDLE/Contents/Resources"
  fi
  mkdir -p "$DATA_ROOT"
  rm -rf "$DATA_ROOT/ms-playwright"
  cp -R "$PACKAGING/playwright-browsers" "$DATA_ROOT/ms-playwright"
  [ -d "$DATA_ROOT/ms-playwright" ] || fail "Chromium 拷贝失败"
  ok "Chromium 已内嵌（$(du -sh "$DATA_ROOT/ms-playwright" | cut -f1)）"
else
  warn "未内嵌 Chromium，运行时会退回用户机器上的 Chrome/Edge"
fi

# ---------------------------------------------------------------- 6. 代码签名
sign_darwin() {
  local target="$1"
  if [ -n "${DEVELOPER_ID:-}" ]; then
    local args=(--force --timestamp --options runtime --sign "$DEVELOPER_ID")
    if [ -f "$ENTITLEMENTS" ]; then args+=(--entitlements "$ENTITLEMENTS"); fi
    codesign "${args[@]}" "$target"
  else
    codesign --force --deep --sign - "$target"
  fi
}

if [ -n "${DEVELOPER_ID:-}" ]; then
  log "Developer ID 签名（由内向外，含内嵌 Chromium）"
  xattr -cr "$APP_BUNDLE" 2>/dev/null || true
  while IFS= read -r -d '' item; do
    sign_darwin "$item"
  done < <(find "$APP_BUNDLE" -depth \( -name "*.framework" -o -name "*.app" -o -name "*.dylib" -o -name "*.so" \) ! -path "$APP_BUNDLE" ! -path '*/ms-playwright/*' -print0)
  sign_darwin "$APP_BUNDLE"
  codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
  ok "签名校验通过"
  warn "内嵌 Chromium 保留 Google 签名、未做 Developer ID 重签，公证大概率会被 Apple 拒绝；需要可公证的安装包请用 SKIP_BROWSER=1 构建（运行时用用户自己的 Chrome）。"
else
  warn "未配置 DEVELOPER_ID，改用 ad-hoc 签名。下载分发后首次打开需要右键→打开，或执行 xattr 去隔离。"
  # 逐项 ad-hoc 签名；跳过内嵌 Chromium（它自带 Google 签名，重签会破坏 bundle）
  while IFS= read -r -d '' item; do
    codesign --force --sign - "$item" >/dev/null 2>&1 || warn "逐项签名失败：$item"
  done < <(find "$APP_BUNDLE" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) ! -path '*/ms-playwright/*' -print0)
  codesign --force --sign - "$APP_BUNDLE"
  codesign --verify --strict --verbose=2 "$APP_BUNDLE" || fail "ad-hoc 签名校验失败，请检查 .app 结构"
  ok "ad-hoc 签名完成"
fi

# ---------------------------------------------------------------- 7. DMG
log "制作 DMG 安装镜像"
STAGE="$PROJECT_ROOT/build/dmg-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP_BUNDLE" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

mkdir -p "$RELEASE"
DMG="$RELEASE/DaydreamDispatch-${VERSION}-macOS-${ARCH}.dmg"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME $VERSION" -srcfolder "$STAGE" -format UDZO -ov "$DMG" >/dev/null
[ -f "$DMG" ] || fail "DMG 生成失败"

if [ -n "${DEVELOPER_ID:-}" ]; then
  sign_darwin "$DMG"
fi

# ---------------------------------------------------------------- 8. 公证
if [ -n "${DEVELOPER_ID:-}" ] && [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
  PASSWORD="${APPLE_APP_PASSWORD:-${APPLE_PASSWORD:-}}"
  [ -n "$PASSWORD" ] || fail "缺少 APPLE_APP_PASSWORD（App Store Connect 的 app-specific 密码）"
  log "提交 Apple 公证（通常 2-10 分钟）"
  xcrun notarytool submit "$DMG" \
    --apple-id "$APPLE_ID" --password "$PASSWORD" --team-id "$APPLE_TEAM_ID" \
    --wait
  log "装订公证票据"
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  spctl --assess --type open --context context:primary-signature -vv "$DMG" || warn "spctl 评估未通过，请核对证书与公证结果"
  ok "已签名并公证，用户双击 DMG 可直接安装"
else
  warn "未提供 APPLE_ID / APPLE_TEAM_ID / APPLE_APP_PASSWORD，跳过公证（对外分发建议补全这三项）"
fi

# ---------------------------------------------------------------- 9. 收尾
SIZE="$(du -h "$DMG" | cut -f1)"
SHA="$(shasum -a 256 "$DMG" | cut -d' ' -f1)"
printf '\n'
ok "构建完成"
printf '  安装包：%s（%s）\n' "$DMG" "$SIZE"
printf '  SHA256：%s\n' "$SHA"
printf '  应用：%s\n\n' "$APP_BUNDLE"
