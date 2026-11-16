"""Local publishing workbench for social-auto-upload.

The server deliberately keeps platform checks in a low-frequency background loop.
The browser UI reads cached results, so keeping the workbench open does not hammer
creator portals or increase account risk.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".local" / "workbench"
UPLOADS = RUNTIME / "uploads"
LOGS = RUNTIME / "logs"
REGISTRY_FILE = RUNTIME / "accounts.json"
TASKS_FILE = RUNTIME / "tasks.json"
FRONTEND_DIST = ROOT / "sau_frontend" / "dist"
CHECK_INTERVAL = max(600, int(os.getenv("SAU_CHECK_INTERVAL", "600")))
SUPPORTED_PLATFORMS = {
    "xiaohongshu": {"name": "小红书", "accent": "red", "schedule": True},
    "douyin": {"name": "抖音", "accent": "cyan", "schedule": True},
    "tencent": {"name": "视频号", "accent": "green", "schedule": True},
    "bilibili": {"name": "Bilibili", "accent": "blue", "schedule": True},
    "youtube": {"name": "YouTube", "accent": "red", "schedule": True},
    "instagram": {"name": "Instagram", "accent": "purple", "schedule": False},
}
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
ALLOWED_VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}

for directory in (RUNTIME, UPLOADS, LOGS):
    directory.mkdir(parents=True, exist_ok=True)


def utc_stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback


def save_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:6]}.tmp"
    )
    try:
        temporary.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


registry_lock = threading.RLock()
task_lock = threading.RLock()
accounts: dict[str, dict[str, Any]] = load_json(REGISTRY_FILE, {})
tasks: dict[str, dict[str, Any]] = load_json(TASKS_FILE, {})
login_processes: dict[str, subprocess.Popen] = {}
publish_processes: dict[str, subprocess.Popen] = {}
publish_process_lock = threading.RLock()
stop_monitor = threading.Event()

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PUBLISH_PHASES = [
    {"key": "checking", "label": "校验账号"},
    {"key": "opening", "label": "打开平台"},
    {"key": "uploading", "label": "上传视频"},
    {"key": "editing", "label": "填写文案"},
    {"key": "cover", "label": "设置封面"},
    {"key": "submitting", "label": "点击发布"},
    {"key": "receipt", "label": "等待回执"},
]


def account_key(platform: str, alias: str) -> str:
    return f"{platform}:{alias}"


def validate_account(platform: str, alias: str) -> None:
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError("暂不支持这个平台")
    if not ALIAS_RE.fullmatch(alias):
        raise ValueError("账号别名只能包含字母、数字、下划线或短横线")


def cli_command(*parts: str) -> list[str]:
    return [sys.executable, str(ROOT / "sau_cli.py"), *parts]


def discover_accounts() -> None:
    cookie_dir = ROOT / "cookies"
    for platform in SUPPORTED_PLATFORMS:
        prefix = f"{platform}_"
        for cookie in cookie_dir.glob(f"{prefix}*.json") if cookie_dir.exists() else []:
            alias = cookie.stem[len(prefix):]
            if ALIAS_RE.fullmatch(alias):
                key = account_key(platform, alias)
                accounts.setdefault(key, {
                    "platform": platform,
                    "alias": alias,
                    "status": "unknown",
                    "message": "等待首次检测",
                    "last_checked": None,
                    "latency_ms": None,
                })
    save_json(REGISTRY_FILE, accounts)


def public_account(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result["platform_name"] = SUPPORTED_PLATFORMS[result["platform"]]["name"]
    result["login_running"] = account_key(result["platform"], result["alias"]) in login_processes
    return result


def check_account(platform: str, alias: str) -> dict[str, Any]:
    key = account_key(platform, alias)
    started = time.monotonic()
    with registry_lock:
        current = accounts.get(key)
        if not current:
            raise KeyError(key)
        if key in login_processes:
            return public_account(current)
        current.update(status="checking", message="正在连接平台…")

    try:
        result = subprocess.run(
            cli_command(platform, "check", "--account", alias),
            cwd=ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = (result.stdout or result.stderr or "").strip().splitlines()
        message = output[-1][:180] if output else ("账号已联通" if result.returncode == 0 else "登录已失效")
        status = "connected" if result.returncode == 0 else "disconnected"
    except subprocess.TimeoutExpired:
        status, message = "error", "平台响应超时，下轮将自动重试"
    except OSError as exc:
        status, message = "error", f"检测器启动失败：{exc}"

    with registry_lock:
        current = accounts.get(key)
        if current:
            current.update(
                status=status,
                message=message,
                last_checked=utc_stamp(),
                latency_ms=round((time.monotonic() - started) * 1000),
            )
            save_json(REGISTRY_FILE, accounts)
            return public_account(current)
    raise KeyError(key)


def monitor_accounts() -> None:
    while not stop_monitor.is_set():
        cycle_started = time.monotonic()
        with registry_lock:
            targets = [(item["platform"], item["alias"]) for item in accounts.values()]
        if targets:
            # Start the whole account batch together. Each account remains isolated,
            # and the next batch is anchored to this cycle's start time.
            with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix="account-check") as pool:
                futures = [pool.submit(check_account, platform, alias) for platform, alias in targets]
                wait(futures)
        elapsed = time.monotonic() - cycle_started
        stop_monitor.wait(max(0, CHECK_INTERVAL - elapsed))


def watch_login(key: str, process: subprocess.Popen, log_handle) -> None:
    process.wait()
    log_handle.close()
    with registry_lock:
        login_processes.pop(key, None)
    platform, alias = key.split(":", 1)
    try:
        check_account(platform, alias)
    except KeyError:
        pass


def safe_upload(file, destination: Path, allowed: set[str], label: str) -> Path:
    original = Path(file.filename or "").name
    suffix = Path(original).suffix.lower()
    if not original or suffix not in allowed:
        formats = "、".join(sorted(item.lstrip(".").upper() for item in allowed))
        raise ValueError(f"{label}文件格式不支持，请使用 {formats}")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{uuid.uuid4().hex[:10]}{suffix}"
    file.save(target)
    return target


def build_publish_command(task: dict[str, Any], target: dict[str, str]) -> list[str]:
    platform, alias = target["platform"], target["alias"]
    cmd = cli_command(platform, "upload-video", "--account", alias, "--file", task["video"],
                      "--title", task["title"], "--desc", task.get("description", ""),
                      "--tags", task.get("tags", ""))
    cover = task.get("cover") or task.get("cover_portrait")
    if cover:
        cmd.extend(["--thumbnail", cover])
    if task.get("cover_portrait") and platform in {"douyin", "tencent"}:
        cmd.extend(["--thumbnail-portrait", task["cover_portrait"]])
    if task.get("schedule") and SUPPORTED_PLATFORMS[platform]["schedule"]:
        cmd.extend(["--schedule", task["schedule"]])
    if platform == "bilibili":
        cmd.extend(["--tid", str(task.get("bilibili_tid", 21))])
    if platform == "youtube":
        cmd.extend(["--visibility", task.get("youtube_visibility", "public")])
    cmd.append("--headed" if task.get("headed", False) else "--headless")
    return cmd


def read_log_tail(path: str | None, limit: int = 1200) -> str:
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return ANSI_RE.sub("", text[-limit:]).strip()
    except OSError:
        return ""


def infer_publish_phase(log_text: str, status: str = "") -> str:
    """Translate uploader log evidence into a stable workbench phase."""
    if status == "success" or "发布成功" in log_text:
        return "success"
    if status in {"failed", "stopped", "cancelled"}:
        return status
    checks = (
        ("receipt", ("等待平台回执", "等待审核", "发布完成")),
        ("submitting", ("冲刺发布", "点击发布", "短信验证码", "等待验证码")),
        ("cover", ("设置封面", "设置视频封面", "封面设置", "封面已上传", "编辑封面")),
        ("editing", ("填标题", "描述和话题", "商品链接", "自主声明", "添加合集")),
        ("uploading", ("搬运视频", "上传视频", "正在努力上传", "上传失败", "视频已经传完")),
        ("opening", ("上传主页", "上传前检查通过", "进入视频发布页面")),
    )
    for phase, needles in checks:
        if any(needle in log_text for needle in needles):
            return phase
    return "checking"


def stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        process.terminate()


def run_publish_task(task_id: str) -> None:
    with task_lock:
        task = tasks[task_id]
        task.update(status="publishing", started_at=utc_stamp())
        save_json(TASKS_FILE, tasks)

    for target in task["targets"]:
        with task_lock:
            if task.get("cancel_requested"):
                break
        key = account_key(target["platform"], target["alias"])
        result_item = {**target, "status": "checking", "phase": "checking", "started_at": utc_stamp()}
        task["results"].append(result_item)
        try:
            account = check_account(target["platform"], target["alias"])
            if account["status"] != "connected":
                raise RuntimeError("账号未联通，已跳过发布")
            result_item["status"] = "publishing"
            result_item["phase"] = "opening"
            log_path = LOGS / f"publish-{task_id}-{target['platform']}-{target['alias']}.log"
            screenshot_path = UPLOADS / task_id / f"failure-{target['platform']}-{target['alias']}.png"
            result_item["log_file"] = str(log_path)
            result_item["message"] = "发布进程已启动，等待平台成功回执"
            environment = dict(os.environ)
            environment["PYTHONUNBUFFERED"] = "1"
            environment["SAU_FAILURE_SCREENSHOT"] = str(screenshot_path)
            with log_path.open("a", encoding="utf-8") as log_handle:
                process = subprocess.Popen(
                    build_publish_command(task, target), cwd=ROOT, stdout=log_handle,
                    stderr=subprocess.STDOUT, text=True, env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                result_item["pid"] = process.pid
                process_key = f"{task_id}:{key}"
                with publish_process_lock:
                    publish_processes[process_key] = process
                started_wait = time.monotonic()
                try:
                    while process.poll() is None:
                        if task.get("cancel_requested"):
                            stop_process_tree(process)
                            break
                        if time.monotonic() - started_wait > 3600:
                            stop_process_tree(process)
                            raise subprocess.TimeoutExpired(process.args, 3600)
                        tail = read_log_tail(str(log_path), 1200)
                        if tail:
                            result_item["message"] = tail
                            result_item["phase"] = infer_publish_phase(tail, result_item["status"])
                        if screenshot_path.exists():
                            result_item["failure_screenshot"] = screenshot_path.name
                        with task_lock:
                            save_json(TASKS_FILE, tasks)
                        time.sleep(2)
                    return_code = process.poll()
                finally:
                    with publish_process_lock:
                        publish_processes.pop(process_key, None)
            output = read_log_tail(str(log_path))
            if task.get("cancel_requested"):
                result_item.update(status="stopped", phase="stopped", message="任务已由用户停止")
            else:
                result_item.update(
                    status="success" if return_code == 0 else "failed",
                    phase="success" if return_code == 0 else "failed",
                    message=(output or "发布命令已完成"),
                )
            if screenshot_path.exists():
                result_item["failure_screenshot"] = screenshot_path.name
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            if task.get("cancel_requested"):
                result_item.update(status="stopped", phase="stopped", message="任务已由用户停止")
            else:
                result_item.update(status="failed", phase="failed", message=str(exc))
        result_item["finished_at"] = utc_stamp()
        with task_lock:
            save_json(TASKS_FILE, tasks)

    with task_lock:
        if task.get("cancel_requested"):
            task.update(status="stopped", finished_at=utc_stamp(), message="任务已由用户停止")
            save_json(TASKS_FILE, tasks)
            return
        successes = sum(item["status"] == "success" for item in task["results"])
        task.update(
            status="completed" if successes == len(task["targets"]) else "partial",
            finished_at=utc_stamp(),
        )
        save_json(TASKS_FILE, tasks)


def mark_interrupted_tasks() -> None:
    """A restarted server cannot infer success from a detached browser process."""
    changed = False
    with task_lock:
        for task in tasks.values():
            if task.get("status") not in {"queued", "publishing"}:
                continue
            task["status"] = "verification_required"
            task["finished_at"] = utc_stamp()
            task["message"] = "工作台重启前未收到平台成功回执，请先到平台作品管理核对，勿直接重发"
            for result in task.get("results", []):
                if result.get("status") in {"checking", "publishing"}:
                    result["status"] = "verification_required"
                    result["message"] = task["message"]
                    result["finished_at"] = utc_stamp()
            changed = True
        if changed:
            save_json(TASKS_FILE, tasks)


def verify_douyin_task(task_id: str, target: dict[str, str]) -> None:
    """Read-only verification against Douyin Creator Center."""
    from patchright.sync_api import sync_playwright

    title = tasks[task_id]["title"]
    account_file = ROOT / "cookies" / f"douyin_{target['alias']}.json"
    checked_at = utc_stamp()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(storage_state=str(account_file))
            page = context.new_page()
            page.goto("https://creator.douyin.com/creator-micro/content/manage",
                      wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7000)
            search = page.locator('input[type="text"]').first
            if search.count():
                search.fill(title)
                search.press("Enter")
                page.wait_for_timeout(10000)
            body = page.locator("body").inner_text()
            found = title in body
            published = found and "已发布" in body
            browser.close()

        with task_lock:
            task = tasks[task_id]
            task["verification"] = {
                "status": "published" if published else ("found" if found else "not_found"),
                "checked_at": checked_at,
                "platform": "douyin",
                "alias": target["alias"],
                "message": (
                    "抖音作品管理已找到该标题，并显示已发布"
                    if published else
                    "抖音作品管理找到该标题，但尚未确认已发布"
                    if found else
                    "本次在抖音作品管理中未找到该标题；可能仍在上传或尚未进入作品列表"
                ),
            }
            if published:
                task.update(status="completed", finished_at=utc_stamp())
                for result in task.get("results", []):
                    if result.get("platform") == "douyin" and result.get("alias") == target["alias"]:
                        result.update(status="success", message=task["verification"]["message"],
                                      finished_at=utc_stamp())
            save_json(TASKS_FILE, tasks)
    except Exception as exc:
        with task_lock:
            task = tasks.get(task_id)
            if task:
                task["verification"] = {
                    "status": "error", "checked_at": checked_at,
                    "platform": "douyin", "alias": target["alias"],
                    "message": f"自动复查失败：{str(exc)[:240]}",
                }
                save_json(TASKS_FILE, tasks)


def open_review_browser(platform: str, alias: str) -> None:
    """Open the platform's management page with the saved automation login."""
    if platform != "douyin":
        return
    from patchright.sync_api import sync_playwright

    account_file = ROOT / "cookies" / f"douyin_{alias}.json"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,
                executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(storage_state=str(account_file))
            page = context.new_page()
            page.goto("https://creator.douyin.com/creator-micro/content/manage",
                      wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(30 * 60 * 1000)
            browser.close()
    except Exception:
        pass


def terminate_task_processes(task: dict[str, Any]) -> list[int]:
    """Terminate only uploader processes that can be tied to this exact task."""
    task_id = str(task.get("id", ""))
    if not re.fullmatch(r"[0-9a-f]{12}", task_id):
        raise ValueError("任务编号无效，拒绝停止进程")
    process_ids = {
        int(result["pid"]) for result in task.get("results", [])
        if str(result.get("pid", "")).isdigit()
    }
    if os.name == "nt":
        script = (
            f"$needle='{task_id}'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -like ('*'+$needle+'*') -and "
            "$_.CommandLine -like '*sau_cli.py*' -and $_.CommandLine -like '*upload-video*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        found = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, errors="replace", timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        process_ids.update(int(line.strip()) for line in found.stdout.splitlines() if line.strip().isdigit())

    stopped: list[int] = []
    for pid in sorted(process_ids):
        try:
            if os.name == "nt":
                result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                        capture_output=True, timeout=20,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode == 0:
                    stopped.append(pid)
            else:
                os.kill(pid, 15)
                stopped.append(pid)
        except (OSError, subprocess.SubprocessError):
            continue
    return stopped


def make_retry_draft(task: dict[str, Any]) -> dict[str, Any]:
    new_id = uuid.uuid4().hex[:12]
    folder = UPLOADS / new_id
    folder.mkdir(parents=True, exist_ok=False)
    retry = json.loads(json.dumps(task))
    for field in ("video", "cover", "cover_portrait"):
        source_value = task.get(field)
        if not source_value:
            retry[field] = None
            continue
        source = Path(source_value).resolve()
        if not source.is_file() or UPLOADS.resolve() not in source.parents:
            shutil.rmtree(folder, ignore_errors=True)
            raise ValueError(f"原任务的{field}文件已不存在，无法生成重试草稿")
        destination = folder / source.name
        shutil.copy2(source, destination)
        retry[field] = str(destination)
    for field in ("started_at", "finished_at", "message", "verification"):
        retry.pop(field, None)
    retry.update(
        id=new_id, status="draft", created_at=utc_stamp(), results=[], retry_of=task["id"],
    )
    return retry


app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:5173", "http://127.0.0.1:5173"]}})
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024


@app.get("/api/health")
def health():
    return jsonify(ok=True, monitor_interval=CHECK_INTERVAL, now=utc_stamp())


@app.get("/api/platforms")
def platforms():
    return jsonify(SUPPORTED_PLATFORMS)


@app.get("/api/accounts")
def list_accounts():
    with registry_lock:
        values = [public_account(item) for item in accounts.values()]
    values.sort(key=lambda item: (item["platform"], item["alias"]))
    return jsonify(values)


@app.post("/api/accounts")
def add_account():
    data = request.get_json(force=True)
    platform, alias = str(data.get("platform", "")), str(data.get("alias", "")).strip()
    try:
        validate_account(platform, alias)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    key = account_key(platform, alias)
    with registry_lock:
        accounts.setdefault(key, {"platform": platform, "alias": alias, "status": "unknown",
                                  "message": "尚未检测", "last_checked": None, "latency_ms": None})
        save_json(REGISTRY_FILE, accounts)
        value = public_account(accounts[key])
    threading.Thread(target=check_account, args=(platform, alias), daemon=True).start()
    return jsonify(value), 201


@app.delete("/api/accounts/<platform>/<alias>")
def remove_account(platform: str, alias: str):
    key = account_key(platform, alias)
    with registry_lock:
        if key in login_processes:
            return jsonify(error="登录窗口仍在运行，暂不能移除"), 409
        accounts.pop(key, None)
        save_json(REGISTRY_FILE, accounts)
    return jsonify(ok=True)


@app.post("/api/accounts/<platform>/<alias>/check")
def refresh_account(platform: str, alias: str):
    try:
        validate_account(platform, alias)
        return jsonify(check_account(platform, alias))
    except KeyError:
        return jsonify(error="账号不存在"), 404
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/accounts/<platform>/<alias>/login")
def login_account(platform: str, alias: str):
    try:
        validate_account(platform, alias)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    key = account_key(platform, alias)
    with registry_lock:
        accounts.setdefault(key, {"platform": platform, "alias": alias, "status": "unknown",
                                  "message": "等待登录", "last_checked": None, "latency_ms": None})
        if key in login_processes:
            return jsonify(error="这个账号的登录窗口已经打开"), 409
        log_path = LOGS / f"login-{platform}-{alias}.log"
        log_handle = log_path.open("a", encoding="utf-8")
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        login_parts = [platform, "login", "--account", alias]
        if platform != "bilibili":
            login_parts.append("--headed")
        process = subprocess.Popen(cli_command(*login_parts),
                                   cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT,
                                   creationflags=flags)
        login_processes[key] = process
        accounts[key].update(status="login_required", message="登录窗口已打开，请在窗口中完成登录")
        save_json(REGISTRY_FILE, accounts)
    threading.Thread(target=watch_login, args=(key, process, log_handle), daemon=True).start()
    return jsonify(ok=True, pid=process.pid, message="登录窗口已打开")


@app.get("/api/tasks")
def list_tasks():
    with task_lock:
        values = sorted(tasks.values(), key=lambda item: item["created_at"], reverse=True)
    return jsonify(values[:30])


@app.post("/api/tasks")
def create_task():
    try:
        metadata = json.loads(request.form.get("metadata", "{}"))
        targets = metadata.get("targets", [])
        if not targets:
            raise ValueError("至少选择一个发布账号")
        title = str(metadata.get("title", "")).strip()
        if not title:
            raise ValueError("请填写标题")
        for target in targets:
            validate_account(str(target.get("platform", "")), str(target.get("alias", "")))
            if account_key(target["platform"], target["alias"]) not in accounts:
                raise ValueError(f"账号 {target['alias']} 不在工作台中")
        video_file = request.files.get("video")
        if not video_file:
            raise ValueError("请选择视频文件")
        task_id = uuid.uuid4().hex[:12]
        folder = UPLOADS / task_id
        video = safe_upload(video_file, folder, ALLOWED_VIDEO, "视频")
        cover_file = request.files.get("cover")
        cover = safe_upload(cover_file, folder, ALLOWED_IMAGE, "封面") if cover_file else None
        portrait_cover_file = request.files.get("cover_portrait")
        portrait_cover = safe_upload(portrait_cover_file, folder, ALLOWED_IMAGE, "竖屏封面") if portrait_cover_file else None
        task = {
            "id": task_id, "status": "draft", "created_at": utc_stamp(), "title": title,
            "description": str(metadata.get("description", "")), "tags": str(metadata.get("tags", "")),
            "schedule": str(metadata.get("schedule", "")), "video": str(video),
            "video_name": video_file.filename, "cover": str(cover) if cover else None,
            "cover_name": cover_file.filename if cover_file else None, "targets": targets, "results": [],
            "cover_portrait": str(portrait_cover) if portrait_cover else None,
            "cover_portrait_name": portrait_cover_file.filename if portrait_cover_file else None,
            "bilibili_tid": int(metadata.get("bilibili_tid", 21)),
            "youtube_visibility": metadata.get("youtube_visibility", "public"),
            "headed": bool(metadata.get("headed", True)),
        }
        with task_lock:
            tasks[task_id] = task
            save_json(TASKS_FILE, tasks)
        return jsonify(task), 201
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/tasks/<task_id>/publish")
def publish_task(task_id: str):
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return jsonify(error="需要明确确认后才会开始发布"), 400
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        if task["status"] != "draft":
            return jsonify(error="任务已经启动，不能重复发布"), 409
        task["status"] = "queued"
        save_json(TASKS_FILE, tasks)
    threading.Thread(target=run_publish_task, args=(task_id,), daemon=True).start()
    return jsonify(ok=True, task=task)


@app.get("/api/tasks/<task_id>/logs")
def task_logs(task_id: str):
    try:
        limit = min(max(int(request.args.get("limit", "16000")), 1000), 50000)
    except ValueError:
        limit = 16000
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        result_items = [dict(item) for item in task.get("results", [])]
    logs = []
    for item in result_items:
        text = read_log_tail(item.get("log_file"), limit)
        screenshot = item.get("failure_screenshot")
        logs.append({
            "platform": item.get("platform"),
            "alias": item.get("alias"),
            "status": item.get("status"),
            "phase": item.get("phase") or infer_publish_phase(text, item.get("status", "")),
            "text": text,
            "screenshot_url": (
                f"/api/tasks/{task_id}/artifacts/{screenshot}" if screenshot else None
            ),
        })
    return jsonify(phases=PUBLISH_PHASES, logs=logs)


@app.get("/api/tasks/<task_id>/artifacts/<filename>")
def task_artifact(task_id: str, filename: str):
    with task_lock:
        if task_id not in tasks:
            return jsonify(error="任务不存在"), 404
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        return jsonify(error="文件名无效"), 400
    return send_from_directory(UPLOADS / task_id, filename)


@app.post("/api/tasks/<task_id>/stop")
def stop_publish_task(task_id: str):
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return jsonify(error="需要明确确认后才能停止任务"), 400
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        previous_status = task.get("status")
        if previous_status not in {"queued", "publishing", "stopping", "verification_required", "partial"}:
            return jsonify(error="当前任务不在运行中"), 409
        task["cancel_requested"] = True
        task["status"] = "stopping"
        task["message"] = "正在停止发布进程"
        save_json(TASKS_FILE, tasks)
    stopped = terminate_task_processes(task)
    with task_lock:
        if previous_status == "partial" and not stopped:
            task["status"] = previous_status
            task.pop("cancel_requested", None)
            task["message"] = "没有找到仍在运行的遗留进程"
            save_json(TASKS_FILE, tasks)
            return jsonify(error=task["message"]), 409
        task["status"] = "stopped"
        task["finished_at"] = utc_stamp()
        task["message"] = "任务已由用户停止；停止操作不代表平台已撤回已提交内容"
        task["stopped_processes"] = stopped
        for result in task.get("results", []):
            if result.get("status") in {"checking", "publishing", "verification_required"}:
                result.update(status="stopped", phase="stopped", message=task["message"], finished_at=utc_stamp())
        save_json(TASKS_FILE, tasks)
    return jsonify(ok=True, task=task, stopped_processes=stopped)


@app.post("/api/tasks/<task_id>/verify")
def verify_task(task_id: str):
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        if task.get("status") not in {"verification_required", "partial", "completed"}:
            return jsonify(error="当前状态不需要人工复查"), 409
        target = next((item for item in task.get("targets", []) if item.get("platform") == "douyin"), None)
        if not target:
            return jsonify(error="当前只支持抖音任务自动复查，请使用平台后台人工核对"), 400
        if task.get("verification", {}).get("status") == "checking":
            return jsonify(error="复查正在进行中"), 409
        task["verification"] = {
            "status": "checking", "checked_at": utc_stamp(), "platform": "douyin",
            "alias": target["alias"], "message": "正在只读查询抖音作品管理…",
        }
        save_json(TASKS_FILE, tasks)
    threading.Thread(target=verify_douyin_task, args=(task_id, target), daemon=True).start()
    return jsonify(ok=True, message="已开始自动复查，不会重新上传")


@app.post("/api/tasks/<task_id>/open-review")
def open_task_review(task_id: str):
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        target = next((item for item in task.get("targets", []) if item.get("platform") == "douyin"), None)
        if not target:
            return jsonify(error="当前只支持直接打开抖音作品管理"), 400
    threading.Thread(target=open_review_browser, args=("douyin", target["alias"]), daemon=True).start()
    return jsonify(ok=True, message="抖音作品管理窗口正在打开")


@app.post("/api/tasks/<task_id>/retry-draft")
def retry_task_draft(task_id: str):
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return jsonify(error="需要明确确认停止旧流程并生成重试草稿"), 400
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        if task.get("status") != "verification_required":
            return jsonify(error="只有结果未知的任务可以安全重试"), 409
        if task.get("verification", {}).get("status") != "not_found":
            return jsonify(error="请先自动复查，并确认平台暂未找到作品"), 409
        stopped = terminate_task_processes(task)
        retry = make_retry_draft(task)
        task.update(
            status="cancelled_for_retry", finished_at=utc_stamp(),
            message="旧上传流程已停止，已生成新的待确认重试草稿",
            stopped_processes=stopped,
        )
        for result in task.get("results", []):
            if result.get("status") == "verification_required":
                result.update(status="cancelled", message=task["message"], finished_at=utc_stamp())
        tasks[retry["id"]] = retry
        save_json(TASKS_FILE, tasks)
    return jsonify(ok=True, task=retry, stopped_processes=stopped,
                   message="旧流程已停止，重试草稿已生成；再次确认后才会发布")


@app.delete("/api/tasks/<task_id>")
def delete_task(task_id: str):
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        if task["status"] not in {"draft", "completed", "partial"}:
            return jsonify(error="运行中的任务不能删除"), 409
        tasks.pop(task_id)
        save_json(TASKS_FILE, tasks)
    folder = UPLOADS / task_id
    if folder.resolve().parent == UPLOADS.resolve():
        shutil.rmtree(folder, ignore_errors=True)
    return jsonify(ok=True)


@app.get("/")
def index():
    if (FRONTEND_DIST / "index.html").exists():
        return send_from_directory(FRONTEND_DIST, "index.html")
    return jsonify(message="前端尚未构建，请运行 start-workbench.bat 或在 sau_frontend 中执行 npm run dev")


@app.get("/<path:path>")
def static_files(path: str):
    return send_from_directory(FRONTEND_DIST, path)


def main() -> None:
    discover_accounts()
    mark_interrupted_tasks()
    threading.Thread(target=monitor_accounts, name="account-monitor", daemon=True).start()
    if os.getenv("SAU_OPEN_BROWSER") == "1":
        threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5409")).start()
    app.run(host="127.0.0.1", port=5409, debug=False, threaded=True)


if __name__ == "__main__":
    main()
