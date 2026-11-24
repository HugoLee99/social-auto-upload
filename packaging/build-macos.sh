#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGING="$PROJECT_ROOT/packaging"
PYTHON="$PROJECT_ROOT/.venv-macos/bin/python"
export PLAYWRIGHT_BROWSERS_PATH="$PACKAGING/playwright-browsers"
export SAU_BUNDLE_BROWSER=1

cd "$PROJECT_ROOT"
uv venv --python 3.12 .venv-macos
uv pip install --python "$PYTHON" -e ".[web]"
uv pip install --python "$PYTHON" pyinstaller pillow

cd "$PROJECT_ROOT/sau_frontend"
npm install --ignore-scripts --no-audit --no-fund
npm run build

cd "$PROJECT_ROOT"
"$PYTHON" "$PACKAGING/make_icons.py"
"$PYTHON" -m patchright install chromium
"$PYTHON" -m PyInstaller --noconfirm --clean "$PACKAGING/daydream_dispatch.spec"

mkdir -p "$PROJECT_ROOT/release"
DMG="$PROJECT_ROOT/release/DaydreamDispatch-0.1.0-macOS.dmg"
rm -f "$DMG"
hdiutil create -volname "白日梦内容分发助手" -srcfolder "$PROJECT_ROOT/dist/白日梦内容分发助手.app" -ov -format UDZO "$DMG"
echo "Created: $DMG"
