# 白日梦内容分发助手：桌面发行包

## Windows

```powershell
.\packaging\build-windows.ps1
```

输出 Windows 便携 ZIP；安装 Inno Setup 6 后同时输出 `Setup-Windows-x64.exe`。Windows 版复用系统自带的 Microsoft Edge，使用用户级安装且不要求管理员权限。运行数据、Cookie 和任务素材保存在 `%LOCALAPPDATA%\DaydreamDispatch`，卸载不会主动删除这些用户数据。安装目录保留上游 MIT `LICENSE.txt` 与 `THIRD_PARTY_NOTICES.txt`。

## macOS

完整的安装方式、签名与 Gatekeeper 说明见 [docs/install-macos.md](../docs/install-macos.md)。三种路线：

### 1. 引导安装包（任意电脑都能生成，推荐给内测用户）

```powershell
python packaging/macos/build_bootstrap.py --mode installer
# 或同时刷新原生构建源码包
python packaging/macos/build_bootstrap.py --mode all
```

输出 `release/DaydreamDispatch-<版本>-macOS-Installer.zip`。用户解压后双击 `安装白日梦.command`，脚本在本机用 uv 下载对应架构的 Python 3.12 与 Chromium，并在 `~/Applications` 生成可双击的 `.app`。不需要 Mac 参与构建，也不需要开发者证书；代价是首次安装要联网下载约 300–400MB。

### 2. 原生 DMG（必须在真实 Mac 上）

```bash
chmod +x packaging/build-macos.sh
./packaging/build-macos.sh
```

输出 `release/DaydreamDispatch-<版本>-macOS-<arm64|x86_64>.dmg`，内含 `.app` 与 `Applications` 快捷方式。启动时自动打开 `http://127.0.0.1:5409`，运行数据保存在 `~/Library/Application Support/DaydreamDispatch`。

- 未配置证书时自动 ad-hoc 签名（`codesign -s -`），确保 Apple Silicon 能启动；对外分发仍需 Developer ID + 公证。
- 配置 `DEVELOPER_ID`、`APPLE_ID`、`APPLE_APP_PASSWORD`、`APPLE_TEAM_ID` 后自动签名、公证、装订票据。
- `--skip-frontend` 复用已构建前端；`SKIP_BROWSER=1` 不内嵌 Chromium。

### 3. GitHub Actions

`.github/workflows/build-macos.yml` 同时构建 arm64（`macos-14`）与 x86_64（`macos-15-intel`），支持手动触发与 `v*` 标签自动发版；签名/公证凭 4 个 Secrets 注入，未配置时产出 ad-hoc DMG。

> 说明：PyInstaller 与 Chromium 均为宿主平台二进制，Windows 无法交叉编译 macOS 产物，因此「原生 DMG」必须在 Mac 或 macOS runner 上构建；「引导安装包」是无需 Mac 的兜底路线。
