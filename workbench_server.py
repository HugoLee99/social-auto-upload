"""Local publishing workbench for social-auto-upload.

The server deliberately keeps platform checks in a low-frequency background loop.
The browser UI reads cached results, so keeping the workbench open does not hammer
creator portals or increase account risk.
"""
from __future__ import annotations

import json
import os
import re
import shlex
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

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS


IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def default_data_root() -> Path:
    configured = os.getenv("SAU_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if not IS_FROZEN:
        return Path(__file__).resolve().parent
    if sys.platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "DaydreamDispatch"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/DaydreamDispatch"
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "daydream-dispatch"


ROOT = default_data_root()
ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("SAU_DATA_DIR", str(ROOT))
bundled_browsers = RESOURCE_ROOT / "ms-playwright"
if IS_FROZEN and bundled_browsers.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled_browsers))
RUNTIME = ROOT / ".local" / "workbench"
UPLOADS = RUNTIME / "uploads"
LOGS = RUNTIME / "logs"
REGISTRY_FILE = RUNTIME / "accounts.json"
TASKS_FILE = RUNTIME / "tasks.json"
FRONTEND_DIST = RESOURCE_ROOT / "sau_frontend" / "dist"
CHECK_INTERVAL = max(600, int(os.getenv("SAU_CHECK_INTERVAL", "600")))
WORKBENCH_PORT = int(os.getenv("SAU_PORT", "5409"))
SUPPORTED_PLATFORMS = {
    "xiaohongshu": {"name": "小红书", "accent": "red", "schedule": True},
    "douyin": {"name": "抖音", "accent": "cyan", "schedule": True},
    "tencent": {"name": "视频号", "accent": "green", "schedule": True},
    "bilibili": {"name": "Bilibili", "accent": "blue", "schedule": True},
    "youtube": {"name": "YouTube", "accent": "red", "schedule": True},
    "instagram": {"name": "Instagram", "accent": "purple", "schedule": False},
}
AI_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek-flash",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
    },
    "openai": {
        "name": "OpenAI",
        "default_model": "gpt-6-astra",
        "models": ["gpt-6-astra", "gpt-5.5"],
    },
}
AI_ACTIONS = {"generate_all", "optimize_title", "optimize_description", "optimize_tags"}
AI_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
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
    if IS_FROZEN:
        cli_name = "DaydreamCLI.exe" if sys.platform == "win32" else "DaydreamCLI"
        return [str(Path(sys.executable).with_name(cli_name)), *parts]
    return [sys.executable, str(RESOURCE_ROOT / "sau_cli.py"), *parts]


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def build_ai_copy_prompt(action: str, brief: str, title: str, description: str, tags: str) -> str:
    action_instruction = {
        "generate_all": "根据创作意图生成完整的标题、正文描述和标签。",
        "optimize_title": "只重点优化标题；描述和标签保持原意并原样返回。",
        "optimize_description": "只重点优化正文描述；标题和标签保持原意并原样返回。",
        "optimize_tags": "只重点优化标签；标题和正文描述保持原意并原样返回。",
    }[action]
    return (
        f"任务：{action_instruction}\n"
        f"创作意图：{brief or '未单独填写，请根据现有内容判断'}\n"
        f"现有标题：{title or '未填写'}\n"
        f"现有正文：{description or '未填写'}\n"
        f"现有标签：{tags or '未填写'}\n\n"
        "写作要求：中文自然、具体、不过度营销；不得虚构亲身体验、效果、数据或事实。"
        "标题不超过100字；正文适合短视频多平台发布；标签提供3到8个，不带#号。"
        "只返回一个JSON对象，严格包含 title、description、tags 三个字符串字段，"
        "tags 使用英文逗号分隔。"
    )


def _request_ai_json(url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=(15, 120),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"无法连接模型服务：{exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        try:
            message = str(response.json().get("error", {}).get("message", "")).strip()
        except (ValueError, AttributeError):
            message = ""
        if response.status_code in {401, 403}:
            raise RuntimeError("API Key 无效、无权限，或该模型尚未开通")
        raise RuntimeError(message[:240] or f"模型服务返回 HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("模型服务没有返回有效 JSON") from exc


def _extract_openai_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    return ""


def _parse_ai_copy(text: str) -> dict[str, str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("模型没有返回可识别的文案 JSON")
    try:
        result = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("模型返回的文案格式无法解析，请重试") from exc
    raw_tags = result.get("tags", "")
    if isinstance(raw_tags, list):
        raw_tags = ",".join(str(item) for item in raw_tags)
    tags = []
    for raw_tag in re.split(r"[,，\n]+", str(raw_tags)):
        tag = raw_tag.strip().lstrip("#")[:30]
        if tag and tag not in tags:
            tags.append(tag)
    return {
        "title": _bounded_text(result.get("title"), 100),
        "description": _bounded_text(result.get("description"), 3000),
        "tags": ", ".join(tags[:8]),
    }


def generate_ai_copy(provider: str, api_key: str, model: str, action: str,
                     brief: str, title: str, description: str, tags: str) -> dict[str, str]:
    if provider not in AI_PROVIDERS:
        raise ValueError("请选择 OpenAI 或 DeepSeek")
    if not api_key or len(api_key) > 512:
        raise ValueError("请填写有效的 API Key")
    if not AI_MODEL_RE.fullmatch(model):
        raise ValueError("模型名称格式无效")
    if action not in AI_ACTIONS:
        raise ValueError("不支持这个 AI 文案操作")
    brief = _bounded_text(brief, 4000)
    title = _bounded_text(title, 200)
    description = _bounded_text(description, 5000)
    tags = _bounded_text(tags, 1000)
    if not any((brief, title, description, tags)):
        raise ValueError("请先填写创作意图或至少一个现有文案字段")
    prompt = build_ai_copy_prompt(action, brief, title, description, tags)
    system_prompt = (
        "你是内容创作者的中文文案编辑。输出必须是JSON，不要使用Markdown。"
        "忠于用户提供的信息，不得编造未提供的体验、数据、身份或产品效果。"
    )
    if provider == "openai":
        payload = _request_ai_json(
            "https://api.openai.com/v1/responses",
            api_key,
            {"model": model, "instructions": system_prompt, "input": prompt, "store": False},
        )
        text = _extract_openai_text(payload)
    else:
        payload = _request_ai_json(
            "https://api.deepseek.com/chat/completions",
            api_key,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "stream": False,
            },
        )
        choices = payload.get("choices") or []
        text = str(choices[0].get("message", {}).get("content", "")) if choices else ""
    if not text.strip():
        raise RuntimeError("模型没有返回文案内容")
    return _parse_ai_copy(text)


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


def watch_login(key: str, process: subprocess.Popen, log_handle=None) -> None:
    process.wait()
    if log_handle is not None:
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
    # 小红书只使用工作台里的 3:4 竖屏封面，不能被通用横屏封面覆盖。
    # 其他平台保持原有兼容逻辑：优先通用封面，缺失时回退竖屏封面。
    cover = (
        task.get("cover_portrait")
        if platform == "xiaohongshu"
        else task.get("cover") or task.get("cover_portrait")
    )
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
    if platform != "bilibili":
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
            from conf import LOCAL_CHROME_PATH
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            }
            if LOCAL_CHROME_PATH:
                launch_kwargs["executable_path"] = LOCAL_CHROME_PATH
            browser = playwright.chromium.launch(**launch_kwargs)
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
            from conf import LOCAL_CHROME_PATH
            launch_kwargs: dict[str, Any] = {
                "headless": False,
                "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            }
            if LOCAL_CHROME_PATH:
                launch_kwargs["executable_path"] = LOCAL_CHROME_PATH
            browser = playwright.chromium.launch(**launch_kwargs)
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


def make_draft_copy(task: dict[str, Any], relation_field: str) -> dict[str, Any]:
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
    for field in (
        "started_at", "finished_at", "message", "verification", "cancel_requested",
        "stopped_processes", "retry_of", "copied_from",
    ):
        retry.pop(field, None)
    retry.update(
        id=new_id, status="draft", created_at=utc_stamp(), results=[],
    )
    retry[relation_field] = task["id"]
    return retry


def make_retry_draft(task: dict[str, Any]) -> dict[str, Any]:
    return make_draft_copy(task, "retry_of")


def make_preset_draft(task: dict[str, Any]) -> dict[str, Any]:
    preset = make_draft_copy(task, "copied_from")
    # A previous scheduled time may already be invalid. Reusing the template
    # always requires the creator to choose the new publish time explicitly.
    preset["schedule"] = ""
    return preset


app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:5173", "http://127.0.0.1:5173"]}})
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024


@app.get("/api/health")
def health():
    return jsonify(ok=True, monitor_interval=CHECK_INTERVAL, now=utc_stamp())


@app.get("/api/platforms")
def platforms():
    return jsonify(SUPPORTED_PLATFORMS)


@app.get("/api/ai/providers")
def ai_providers():
    return jsonify(AI_PROVIDERS)


@app.post("/api/ai/generate")
def ai_generate():
    data = request.get_json(silent=True) or {}
    try:
        result = generate_ai_copy(
            provider=str(data.get("provider", "")),
            api_key=str(data.get("api_key", "")),
            model=str(data.get("model", "")),
            action=str(data.get("action", "")),
            brief=str(data.get("brief", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            tags=str(data.get("tags", "")),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 502


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
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        login_parts = [platform, "login", "--account", alias]
        if platform != "bilibili":
            login_parts.append("--headed")
        log_handle = None
        if platform == "bilibili" and os.name == "nt":
            # biliup renders its QR code in the terminal and refuses to run when
            # stdin/stdout are redirected. cmd /k gives it a real interactive
            # Windows terminal and deliberately keeps the window open if setup
            # or login fails, so the user can read the error instead of seeing
            # the console flash and disappear.
            process = subprocess.Popen(
                ["cmd.exe", "/d", "/k", *cli_command(*login_parts)],
                cwd=ROOT,
                creationflags=flags,
            )
        elif platform == "bilibili" and sys.platform == "darwin":
            script_path = RUNTIME / f"login-bilibili-{alias}.command"
            command = " ".join(shlex.quote(part) for part in cli_command(*login_parts))
            script_path.write_text(
                "#!/bin/zsh\n"
                f"cd {shlex.quote(str(ROOT))}\n"
                f"{command}\n"
                "echo\nread -k 1 '?登录完成。按任意键关闭窗口…'\n",
                encoding="utf-8",
            )
            script_path.chmod(0o700)
            process = subprocess.Popen(["open", "-a", "Terminal", str(script_path)], cwd=ROOT)
        else:
            log_path = LOGS / f"login-{platform}-{alias}.log"
            log_handle = log_path.open("a", encoding="utf-8")
            process = subprocess.Popen(
                cli_command(*login_parts),
                cwd=ROOT,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
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


@app.post("/api/tasks/<task_id>/duplicate")
def duplicate_task_as_preset(task_id: str):
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify(error="任务不存在"), 404
        preset = make_preset_draft(task)
        tasks[preset["id"]] = preset
        save_json(TASKS_FILE, tasks)
    return jsonify(
        ok=True,
        task=preset,
        message="已复用上次发布设置并生成待确认草稿；请重新选择发布时间后再发布",
    )


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
        url = f"http://127.0.0.1:{WORKBENCH_PORT}"
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=WORKBENCH_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
