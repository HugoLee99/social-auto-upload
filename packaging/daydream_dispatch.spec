# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
import sys
import tomllib

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH).parent

version = "0.1.0"
try:
    with open(project_root / "pyproject.toml", "rb") as fh:
        version = tomllib.load(fh)["project"]["version"]
except Exception:
    pass
frontend = project_root / "sau_frontend" / "dist"
browser_root = project_root / "packaging" / "playwright-browsers"
icon_dir = project_root / "packaging" / "icons"

workbench_datas = [(str(frontend), "sau_frontend/dist")]
cli_datas = collect_data_files("patchright")
cli_datas += collect_data_files("utils")
# 注意：内嵌的 Patchright Chromium 不放进 datas。
# PyInstaller 6 会把数据目录里的 Mach-O 当作待签名二进制处理，而 Chrome for Testing
# 的 framework 自带 Google 签名，重签会直接报 "bundle format unrecognized"。
# 浏览器改由 build-macos.sh 在 PyInstaller 完成后整目录拷进 .app（见第 5.5 步）。

hiddenimports = []
for package in ("sau_commands", "uploader", "utils", "myUtils"):
    hiddenimports += collect_submodules(package)

icon_path = icon_dir / ("daydream.icns" if sys.platform == "darwin" else "daydream.ico")

workbench_analysis = Analysis(
    [str(project_root / "workbench_server.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=workbench_datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
cli_analysis = Analysis(
    [str(project_root / "sau_cli.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=cli_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
MERGE(
    (workbench_analysis, "DaydreamDispatch", "DaydreamDispatch"),
    (cli_analysis, "DaydreamCLI", "DaydreamCLI"),
)

workbench_pyz = PYZ(workbench_analysis.pure)
workbench_exe = EXE(
    workbench_pyz, workbench_analysis.scripts, [], exclude_binaries=True,
    name="DaydreamDispatch", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    icon=str(icon_path) if icon_path.exists() else None,
)
cli_pyz = PYZ(cli_analysis.pure)
cli_exe = EXE(
    cli_pyz, cli_analysis.scripts, [], exclude_binaries=True,
    name="DaydreamCLI", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=True,
    icon=str(icon_path) if icon_path.exists() else None,
)
coll = COLLECT(
    workbench_exe, cli_exe,
    workbench_analysis.binaries, workbench_analysis.datas,
    cli_analysis.binaries, cli_analysis.datas,
    strip=False, upx=True, name="DaydreamDispatch",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="白日梦内容分发助手.app",
        icon=str(icon_path) if icon_path.exists() else None,
        bundle_identifier="com.daydream.dispatch",
        info_plist={
            "CFBundleDisplayName": "白日梦内容分发助手",
            "CFBundleName": "Daydream Dispatch",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "CFBundleInfoDictionaryVersion": "6.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "MIT License",
            # 冻结版双击启动后自动打开 http://127.0.0.1:5409 控制台
            "LSEnvironment": {"SAU_OPEN_BROWSER": "1"},
        },
    )
