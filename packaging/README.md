# 白日梦内容分发助手：桌面发行包

## Windows

```powershell
.\packaging\build-windows.ps1
```

输出 Windows 便携 ZIP；安装 Inno Setup 6 后同时输出 `Setup-Windows-x64.exe`。Windows 版复用系统自带的 Microsoft Edge，使用用户级安装且不要求管理员权限。运行数据、Cookie 和任务素材保存在 `%LOCALAPPDATA%\DaydreamDispatch`，卸载不会主动删除这些用户数据。安装目录保留上游 MIT `LICENSE.txt` 与 `THIRD_PARTY_NOTICES.txt`。

## macOS

必须在真实 Mac 上运行：

```bash
chmod +x packaging/build-macos.sh
./packaging/build-macos.sh
```

输出 `release/DaydreamDispatch-0.1.0-macOS.dmg`。运行数据保存在 `~/Library/Application Support/DaydreamDispatch`。

公开销售前应使用 Apple Developer ID 对 `.app` 签名并执行 notarization；未签名版本首次打开时可能被 Gatekeeper 拦截。
