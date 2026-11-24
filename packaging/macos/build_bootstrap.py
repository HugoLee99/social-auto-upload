"""打包 macOS 发行物：引导安装包（本机即可生成）与原生构建源码包。

为什么需要这一步：
  PyInstaller / Patchright Chromium 都是按宿主平台编译的产物，Windows 无法
  交叉编译 macOS 的 .app，所以「原生 DMG」必须在 Mac 或 CI 上构建（见
  packaging/build-macos.sh 与 .github/workflows/build-macos.yml）。
  与此同时，这个脚本生成一个「安装时才落地」的 macOS 引导安装包：用户
  双击 .command，脚本会用 uv 下载对应架构的 Python 3.12 与 Chromium，
  在 ~/Applications 生成可双击的 .app。Intel / Apple Silicon 都能用。

用法：
    python packaging/macos/build_bootstrap.py --mode installer
    python packaging/macos/build_bootstrap.py --mode buildkit
    python packaging/macos/build_bootstrap.py --mode all
"""
from __future__ import annotations

import argparse
import stat
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
BOOTSTRAP = PACKAGING / "macos" / "bootstrap"
RELEASE = ROOT / "release"

IGNORED_DIRS = {
    "__pycache__", ".git", ".venv", ".venv-macos", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "playwright-browsers", ".local",
}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".DS_Store", ".log"}

PAYLOAD_ROOT_FILES = [
    "workbench_server.py", "sau_cli.py", "conf.py", "conf.example.py", "__init__.py",
    "LICENSE", "THIRD_PARTY_NOTICES.txt",
]
PAYLOAD_DIRS = ["sau_commands", "uploader", "utils", "myUtils", "sau_frontend/dist"]

KIT_EXTRA_DIRS = ["packaging", "skills", "docs", "examples"]
KIT_EXTRA_FILES = [
    "README.md", "CHANGELOG.md", "WORKBENCH.md", "pyproject.toml", "requirements.txt",
    "uv.lock", "start-workbench.bat", "start-win.bat", "setup-workbench.bat",
]


def read_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def iter_tree(src: Path):
    """产出 (文件路径, 相对路径)，跳过缓存与构建目录。"""
    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if item.is_file() and item.suffix in IGNORED_SUFFIXES:
            continue
        yield item, rel


def add_entry(zf: zipfile.ZipFile, arcname: str, mode: int, data: bytes | None = None, path: Path | None = None) -> None:
    info = zipfile.ZipInfo(arcname)
    info.date_time = (2025, 1, 1, 0, 0, 0)
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    if path is not None:
        data = path.read_bytes()
    zf.writestr(info, data if data is not None else b"")


def add_tree(zf: zipfile.ZipFile, src: Path, prefix: str) -> int:
    count = 0
    for item, rel in iter_tree(src):
        arc = f"{prefix}/{rel.as_posix()}"
        if item.is_dir():
            add_entry(zf, arc + "/", (stat.S_IFDIR | 0o755))
        else:
            executable = item.suffix in {".command", ".sh"} or item.name in {"Daydream"}
            mode = stat.S_IFREG | (0o755 if executable else 0o644)
            add_entry(zf, arc, mode, path=item)
            count += 1
    return count


def build_installer(version: str) -> Path:
    top = f"DaydreamDispatch-{version}-macOS-Installer"
    out = RELEASE / f"DaydreamDispatch-{version}-macOS-Installer.zip"
    payload_stage = ROOT / "build" / "macos-payload"

    if payload_stage.exists():
        import shutil
        shutil.rmtree(payload_stage)
    payload_stage.mkdir(parents=True)

    for name in PAYLOAD_ROOT_FILES:
        source = ROOT / name
        if source.exists():
            (payload_stage / name).write_bytes(source.read_bytes())
    for name in PAYLOAD_DIRS:
        source = ROOT / name
        if not source.exists():
            raise SystemExit(f"缺少必要目录：{source}")
        target = payload_stage / name
        import shutil
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "node_modules"))
    icon = PACKAGING / "icons" / "daydream-512.png"
    if icon.exists():
        (payload_stage / "daydream-512.png").write_bytes(icon.read_bytes())

    RELEASE.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_entry(zf, f"{top}/", (stat.S_IFDIR | 0o755))
        add_entry(zf, f"{top}/payload/", (stat.S_IFDIR | 0o755))
        for name in ("安装白日梦.command", "卸载白日梦.command", "使用说明.txt"):
            src = BOOTSTRAP / name
            if not src.exists():
                raise SystemExit(f"缺少安装器资源：{src}")
            mode = stat.S_IFREG | (0o755 if name.endswith(".command") else 0o644)
            add_entry(zf, f"{top}/{name}", mode, path=src)
        add_tree(zf, payload_stage, f"{top}/payload")
    return out


def build_buildkit(version: str) -> Path:
    top = f"DaydreamDispatch-{version}-macOS-build-source"
    out = RELEASE / f"DaydreamDispatch-{version}-macOS-build-source.zip"
    RELEASE.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_entry(zf, f"{top}/", (stat.S_IFDIR | 0o755))
        for name in PAYLOAD_ROOT_FILES + KIT_EXTRA_FILES:
            src = ROOT / name
            if src.exists():
                add_entry(zf, f"{top}/{name}", stat.S_IFREG | (0o755 if src.suffix == ".sh" else 0o644), path=src)
        extra_dirs = list(PAYLOAD_DIRS)
        for name in KIT_EXTRA_DIRS:
            if (ROOT / name).exists():
                extra_dirs.append(name)
        for name in extra_dirs:
            add_tree(zf, ROOT / name, f"{top}/{name}")
        workflow = ROOT / ".github" / "workflows" / "build-macos.yml"
        if workflow.exists():
            add_entry(zf, f"{top}/.github/workflows/build-macos.yml", stat.S_IFREG | 0o644, path=workflow)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 macOS 发行物")
    parser.add_argument("--mode", choices=["installer", "buildkit", "all"], default="all")
    args = parser.parse_args()

    version = read_version()
    produced: list[Path] = []
    if args.mode in {"installer", "all"}:
        produced.append(build_installer(version))
    if args.mode in {"buildkit", "all"}:
        produced.append(build_buildkit(version))

    for path in produced:
        size = path.stat().st_size / 1024 / 1024
        print(f"创建：{path}（{size:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
