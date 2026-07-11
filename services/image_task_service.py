from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config, local_time_text
from services.content_filter import request_text
from services.log_service import LOG_TYPE_CALL, apply_image_log_detail, log_service
from services.protocol import openai_v1_image_edit, openai_v1_image_generations

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_ERROR = "error"
TERMINAL_STATUSES = {TASK_STATUS_SUCCESS, TASK_STATUS_ERROR}
UNFINISHED_STATUSES = {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING}
STALE_TASK_MIN_SECONDS = 30 * 60
STALE_TASK_POLL_TIMEOUT_MULTIPLIER = 10
MAX_TASK_STATUS_LOGS = 120
PROGRESS_LABELS = {
    "sync_request_started": "请求已提交",
    "uploading": "正在上传图片",
    "bootstrapping": "正在初始化会话",
    "getting_token": "正在获取令牌",
    "preparing_conversation": "正在准备对话",
    "starting_generation": "正在启动生成",
    "generating": "正在生成图片",
    "getting_account": "正在分配账号",
    "image_stream_resolve_start": "正在解析图片结果",
    "receiving_image": "正在接收图片",
}
PROGRESS_PERCENT = {
    "sync_request_started": 5,
    "getting_account": 10,
    "uploading": 20,
    "bootstrapping": 30,
    "getting_token": 40,
    "preparing_conversation": 50,
    "starting_generation": 60,
    "generating": 75,
    "image_stream_resolve_start": 88,
    "receiving_image": 95,
}


def _now_iso() -> str:
    return local_time_text()


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:26], fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _clean(value: object, default: str = "") -> str:
    return str(value or default).strip()


def _short_text(value: object, limit: int = 260) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _progress_label(value: object) -> str:
    text = _clean(value)
    return PROGRESS_LABELS.get(text, text)


def _progress_percent(task: dict[str, Any]) -> int:
    status = _clean(task.get("status"))
    if status == TASK_STATUS_SUCCESS:
        return 100
    progress = _clean(task.get("progress"))
    if progress in PROGRESS_PERCENT:
        return PROGRESS_PERCENT[progress]
    if status == TASK_STATUS_RUNNING:
        return 10
    return 0


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _is_admin(identity: dict[str, object]) -> bool:
    return _clean(identity.get("role")).lower() == "admin"


def _task_key(owner_id: str, task_id: str) -> str:
    return f"{owner_id}:{task_id}"


def _task_activity_ts(task: dict[str, Any]) -> float:
    for key in ("updated_ts", "started_ts", "created_ts"):
        value = task.get(key)
        if isinstance(value, int | float) and value > 0:
            return float(value)
    return _timestamp(task.get("updated_at")) or _timestamp(task.get("created_at"))


def _stale_task_seconds() -> float:
    try:
        poll_timeout = float(config.image_poll_timeout_secs)
    except Exception:
        poll_timeout = 120.0
    return max(float(STALE_TASK_MIN_SECONDS), poll_timeout * STALE_TASK_POLL_TIMEOUT_MULTIPLIER)


def _collect_image_urls(data: list[Any]) -> list[str]:
    urls: list[str] = []
    for item in data:
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str) and url:
                urls.append(url)
    return urls


def _image_route_from_result(result: object) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    route = result.get("_image_route")
    return dict(route) if isinstance(route, dict) else {}


def _image_route_attempts_from_result(result: object) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    attempts = result.get("_image_route_attempts")
    return _dedupe_image_route_attempts([dict(item) for item in attempts if isinstance(item, dict)]) if isinstance(attempts, list) else []


def _image_route_from_exception(exc: Exception) -> dict[str, Any]:
    route = getattr(exc, "image_route", None)
    return dict(route) if isinstance(route, dict) else {}


def _image_route_attempts_from_exception(exc: Exception) -> list[dict[str, Any]]:
    attempts = getattr(exc, "image_route_attempts", None)
    return _dedupe_image_route_attempts([dict(item) for item in attempts if isinstance(item, dict)]) if isinstance(attempts, list) else []


def _dedupe_image_route_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: dict[tuple[object, ...], dict[str, Any]] = {}
    for item in attempts:
        marker = (
            item.get("attempt"),
            item.get("index"),
            item.get("account_email"),
            item.get("backend_model"),
            item.get("image_route"),
        )
        existing = seen.get(marker)
        if existing is not None:
            existing.update({key: value for key, value in item.items() if value not in (None, "")})
            continue
        seen[marker] = item
        deduped.append(item)
    return deduped


def _unique_attempt_accounts(attempts: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(
        _clean(item.get("account_email")) or _clean(item.get("account_token")) or _clean(item.get("token"))
        for item in attempts
        if _clean(item.get("account_email")) or _clean(item.get("account_token")) or _clean(item.get("token"))
    ))


def _failed_attempt_count(attempts: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in attempts
        if _clean(item.get("status")).lower() in {"failed", "error"} or bool(_clean(item.get("error")))
    )


def _duration_text(duration_ms: object) -> str:
    if not isinstance(duration_ms, int | float):
        return ""
    if duration_ms < 1000:
        return f"{int(duration_ms)}ms"
    return f"{float(duration_ms) / 1000:.1f}s"


def _status_log(
    message: object,
    *,
    level: str = "info",
    event: str = "",
    details: dict[str, Any] | None = None,
    time_text: str = "",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "time": time_text or _now_iso(),
        "level": _clean(level, "info") or "info",
        "event": _clean(event),
        "message": _short_text(message, 500),
    }
    clean_details = {
        str(key): value
        for key, value in (details or {}).items()
        if value not in (None, "", [], {})
    }
    if clean_details:
        item["details"] = clean_details
    return item


def _public_status_logs(task: dict[str, Any]) -> list[dict[str, Any]]:
    logs = task.get("status_logs")
    if not isinstance(logs, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in logs[-MAX_TASK_STATUS_LOGS:]:
        if not isinstance(entry, dict):
            continue
        message = _clean(entry.get("message"))
        if not message:
            continue
        item = {
            "time": _clean(entry.get("time")),
            "level": _clean(entry.get("level"), "info") or "info",
            "event": _clean(entry.get("event")),
            "message": message,
        }
        details = entry.get("details")
        if isinstance(details, dict):
            item["details"] = {
                str(key): value
                for key, value in details.items()
                if value not in (None, "", [], {})
            }
        items.append(item)
    return items


def _latest_status_text(task: dict[str, Any]) -> str:
    logs = _public_status_logs(task)
    if logs:
        return _clean(logs[-1].get("message"))
    status = _clean(task.get("status"))
    if status == TASK_STATUS_SUCCESS:
        return "任务已完成"
    if status == TASK_STATUS_ERROR:
        return _short_text(task.get("error") or "任务失败")
    if task.get("progress"):
        return _progress_label(task.get("progress"))
    if status == TASK_STATUS_QUEUED:
        return "排队中"
    if status == TASK_STATUS_RUNNING:
        return "处理中"
    return status or "未知"


def _apply_image_route_detail(
    detail: dict[str, Any],
    image_route: dict[str, Any] | None = None,
    image_route_attempts: list[dict[str, Any]] | None = None,
) -> None:
    apply_image_log_detail(detail, image_route, image_route_attempts)


def _build_log_detail(
    identity: dict[str, object],
    *,
    endpoint: str,
    model: str,
    started: float,
    request_preview: str = "",
    status: str = "success",
    error: str = "",
    urls: list[str] | None = None,
    account_email: str = "",
    conversation_id: str = "",
    request_params: dict[str, Any] | None = None,
    image_route: dict[str, Any] | None = None,
    image_route_attempts: list[dict[str, Any]] | None = None,
    finished: bool = True,
) -> dict[str, Any]:
    detail = {
        "key_id": identity.get("id"),
        "key_name": identity.get("name"),
        "role": identity.get("role"),
        "endpoint": endpoint,
        "model": model,
        "started_at": local_time_text(started),
        "duration_ms": int((time.time() - started) * 1000) if finished else 0,
        "status": status,
    }
    if finished:
        detail["ended_at"] = _now_iso()
    else:
        detail["submitted_at"] = _now_iso()
    if request_preview:
        detail["request_text"] = request_preview
    if request_params:
        detail["request_params"] = request_params
    if error:
        detail["error"] = error
    if account_email:
        detail["account_email"] = account_email
    if conversation_id:
        detail["conversation_id"] = conversation_id
    if urls:
        detail["urls"] = list(dict.fromkeys(urls))
    _apply_image_route_detail(detail, image_route, image_route_attempts)
    return detail


def _request_params_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    params = {
        key: payload.get(key)
        for key in ("n", "size", "quality", "response_format", "stream")
        if key in payload
    }
    images = payload.get("images")
    if isinstance(images, list):
        params["image_count"] = len(images)
    masks = payload.get("mask")
    if isinstance(masks, list):
        params["mask_count"] = len(masks)
    return params


def _image_result_meta(data: object) -> dict[str, Any]:
    _ = data
    return {}


def _public_image_data(data: object) -> list[Any]:
    if not isinstance(data, list):
        return []
    items: list[Any] = []
    for item in data:
        if isinstance(item, dict):
            items.append({key: value for key, value in item.items() if key != "_b64_json"})
        else:
            items.append(item)
    return items


def _public_task(task: dict[str, Any], *, include_logs: bool = False) -> dict[str, Any]:
    item = {
        "id": task.get("id"),
        "status": task.get("status"),
        "mode": task.get("mode"),
        "model": task.get("model"),
        "size": task.get("size"),
        "quality": task.get("quality"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "progress_percent": _progress_percent(task),
        "realtime_status": _latest_status_text(task),
        "status_log_count": len(_public_status_logs(task)),
    }
    if task.get("conversation_id"):
        item["conversation_id"] = task.get("conversation_id")
    if task.get("data") is not None:
        item["data"] = _public_image_data(task.get("data"))
    if task.get("usage") is not None:
        item["usage"] = task.get("usage")
    if task.get("error"):
        item["error"] = task.get("error")
    if task.get("progress") and task.get("status") in UNFINISHED_STATUSES:
        item["progress"] = _progress_label(task.get("progress"))
    if task.get("duration_ms") is not None:
        item["duration_ms"] = task.get("duration_ms")
    attempts = task.get("image_route_attempts")
    if isinstance(attempts, list) and attempts:
        attempt_items = [dict(attempt) for attempt in attempts if isinstance(attempt, dict)]
        item["image_route_attempt_count"] = len(attempt_items)
        item["used_account_count"] = len(_unique_attempt_accounts(attempt_items))
        failed_accounts = _unique_attempt_accounts([
            attempt
            for attempt in attempt_items
            if _clean(attempt.get("status")).lower() in {"failed", "error"} or _clean(attempt.get("error"))
        ])
        if failed_accounts:
            item["failed_account_count"] = len(failed_accounts)
    if task.get("client_retry_count"):
        item["client_retry_count"] = int(task.get("client_retry_count") or 0)
    if task.get("run_count"):
        item["run_count"] = int(task.get("run_count") or 0)
    if task.get("cancelled"):
        item["cancelled"] = True
    if task.get("status") in (TASK_STATUS_RUNNING, TASK_STATUS_QUEUED):
        if task.get("status") == TASK_STATUS_RUNNING:
            # RUNNING 状态仅在 started_ts 被设置后（image_stream_resolve_start）才计时
            base_ts = task.get("started_ts")
        else:
            # QUEUED 状态从 created_ts 开始计时（排队等待中）
            base_ts = task.get("created_ts") or task.get("updated_ts")
        if base_ts:
            item["elapsed_secs"] = round(time.time() - base_ts, 1)
    if include_logs:
        item["status_logs"] = _public_status_logs(task)
    return item


class ImageTaskService:
    def __init__(
        self,
        path: Path,
        *,
        generation_handler: Callable[[dict[str, Any]], dict[str, Any]] = openai_v1_image_generations.handle,
        edit_handler: Callable[[dict[str, Any]], dict[str, Any]] = openai_v1_image_edit.handle,
        retention_days_getter: Callable[[], int] | None = None,
    ):
        self.path = path
        self.generation_handler = generation_handler
        self.edit_handler = edit_handler
        self.retention_days_getter = retention_days_getter or (lambda: config.image_retention_days)
        self._lock = threading.RLock()
        self._sync_condition = threading.Condition(self._lock)
        self._tasks: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._tasks = self._load_locked()
            changed = self._recover_unfinished_locked()
            changed = self._cleanup_locked() or changed
            if changed:
                self._save_locked()

    def _append_status_log_locked(
        self,
        task: dict[str, Any],
        message: object,
        *,
        level: str = "info",
        event: str = "",
        details: dict[str, Any] | None = None,
        time_text: str = "",
    ) -> None:
        logs = task.get("status_logs")
        if not isinstance(logs, list):
            logs = []
            task["status_logs"] = logs
        item = _status_log(
            message,
            level=level,
            event=event,
            details=details,
            time_text=time_text,
        )
        # 避免高频轮询/重复回调写出连续重复日志。
        if logs:
            last = logs[-1]
            if (
                isinstance(last, dict)
                and _clean(last.get("event")) == _clean(item.get("event"))
                and _clean(last.get("message")) == _clean(item.get("message"))
            ):
                last["time"] = item["time"]
                if item.get("details"):
                    last["details"] = item["details"]
                return
        logs.append(item)
        if len(logs) > MAX_TASK_STATUS_LOGS:
            del logs[: len(logs) - MAX_TASK_STATUS_LOGS]

    def _ensure_status_logs_locked(self, task: dict[str, Any]) -> bool:
        logs = _public_status_logs(task)
        if logs:
            if not isinstance(task.get("status_logs"), list):
                task["status_logs"] = logs[-MAX_TASK_STATUS_LOGS:]
                return True
            return False
        created_at = _clean(task.get("created_at"), _now_iso())
        task["status_logs"] = [
            _status_log(
                "任务已创建",
                event="created",
                details={
                    "mode": task.get("mode"),
                    "model": task.get("model"),
                    "size": task.get("size"),
                    "quality": task.get("quality"),
                },
                time_text=created_at,
            )
        ]
        status = _clean(task.get("status"))
        if status == TASK_STATUS_SUCCESS:
            message = "任务已完成"
            level = "success"
            event = "success"
        elif status == TASK_STATUS_ERROR:
            message = _short_text(task.get("error") or "任务失败")
            level = "error"
            event = "error"
        elif status == TASK_STATUS_RUNNING:
            message = _progress_label(task.get("progress")) if task.get("progress") else "任务正在处理"
            level = "processing"
            event = "progress" if task.get("progress") else "running"
        else:
            message = "任务排队中"
            level = "info"
            event = "queued"
        self._append_status_log_locked(
            task,
            message,
            level=level,
            event=event,
            details={
                "progress_percent": _progress_percent(task),
                "conversation_id": task.get("conversation_id"),
                "duration": _duration_text(task.get("duration_ms")),
            },
            time_text=_clean(task.get("updated_at"), _now_iso()),
        )
        return True

    def _append_update_logs_locked(
        self,
        task: dict[str, Any],
        updates: dict[str, Any],
        *,
        previous_status: str,
        previous_progress: str,
        previous_conversation_id: str,
        previous_attempt_count: int,
    ) -> None:
        status = _clean(task.get("status"))
        progress = _clean(task.get("progress"))
        attempts = task.get("image_route_attempts")
        attempt_items = [dict(item) for item in attempts if isinstance(item, dict)] if isinstance(attempts, list) else []
        if len(attempt_items) > previous_attempt_count:
            self._append_status_log_locked(
                task,
                f"账号尝试更新：已调用 {len(_unique_attempt_accounts(attempt_items))} 个账号，失败 {_failed_attempt_count(attempt_items)} 次",
                level="processing" if status in UNFINISHED_STATUSES else "info",
                event="route_attempts",
                details={
                    "attempt_count": len(attempt_items),
                    "used_account_count": len(_unique_attempt_accounts(attempt_items)),
                    "failed_attempt_count": _failed_attempt_count(attempt_items),
                },
            )

        if "status" in updates and status != previous_status:
            if status == TASK_STATUS_RUNNING:
                self._append_status_log_locked(task, "任务开始运行", level="processing", event="running")
            elif status == TASK_STATUS_SUCCESS:
                self._append_status_log_locked(
                    task,
                    "任务已完成",
                    level="success",
                    event="success",
                    details={"duration": _duration_text(task.get("duration_ms"))},
                )
            elif status == TASK_STATUS_ERROR:
                self._append_status_log_locked(
                    task,
                    _short_text(task.get("error") or "任务失败"),
                    level="error",
                    event="error",
                    details={"duration": _duration_text(task.get("duration_ms"))},
                )
            elif status == TASK_STATUS_QUEUED:
                self._append_status_log_locked(task, "任务进入队列", event="queued")

        if "progress" in updates and progress and progress != previous_progress:
            self._append_status_log_locked(
                task,
                _progress_label(progress),
                level="processing",
                event="progress",
                details={"progress": progress, "progress_percent": _progress_percent(task)},
            )

        conversation_id = _clean(task.get("conversation_id"))
        if conversation_id and conversation_id != previous_conversation_id:
            self._append_status_log_locked(
                task,
                f"获取到会话 ID：{conversation_id}",
                event="conversation_id",
                details={"conversation_id": conversation_id},
            )

        if updates.get("quota_consumed") is True:
            self._append_status_log_locked(task, "已扣除本次图片额度", event="quota_consumed")

    def submit_generation(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        quality: str = "auto",
        base_url: str = "",
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "model": model,
            "n": 1,
            "size": size,
            "quality": quality,
            "response_format": "url",
            "base_url": base_url,
        }
        return self._submit(identity, client_task_id=client_task_id, mode="generate", payload=payload)

    def submit_edit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        quality: str = "auto",
        base_url: str = "",
        images: list[tuple[bytes, str, str]] | None = None,
        masks: list[tuple[bytes, str, str]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "images": images or [],
            "mask": masks or [],
            "model": model,
            "n": 1,
            "size": size,
            "quality": quality,
            "response_format": "url",
            "base_url": base_url,
        }
        return self._submit(identity, client_task_id=client_task_id, mode="edit", payload=payload)

    def list_tasks(self, identity: dict[str, object], task_ids: list[str]) -> dict[str, Any]:
        requested_ids = [_clean(task_id) for task_id in task_ids if _clean(task_id)]
        with self._lock:
            if self._cleanup_locked():
                self._save_locked()
            items = []
            missing_ids = []
            for task_id in requested_ids:
                _, task = self._find_task_locked(identity, task_id)
                if task is None:
                    missing_ids.append(task_id)
                else:
                    items.append(_public_task(task))
            if not requested_ids:
                if _is_admin(identity):
                    items = [_public_task(task) for task in self._tasks.values()]
                else:
                    owner = _owner_id(identity)
                    items = [
                        _public_task(task)
                        for task in self._tasks.values()
                        if task.get("owner_id") == owner
                    ]
                items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
                missing_ids = []
            return {"items": items, "missing_ids": missing_ids}

    def get_task_status(self, identity: dict[str, object], task_id: str) -> dict[str, Any]:
        if not _clean(task_id):
            raise ValueError("task_id is required")
        with self._lock:
            changed = self._cleanup_locked()
            key, task = self._find_task_locked(identity, task_id)
            if task is None:
                raise ValueError("task not found")
            changed = self._ensure_status_logs_locked(task) or changed
            if changed:
                self._save_locked()
            return _public_task(task, include_logs=True)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            if self._cleanup_locked():
                self._save_locked()
            tasks = [_public_task(task) for task in self._tasks.values()]
        tasks.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        by_status = {
            TASK_STATUS_QUEUED: 0,
            TASK_STATUS_RUNNING: 0,
            TASK_STATUS_SUCCESS: 0,
            TASK_STATUS_ERROR: 0,
        }
        by_mode = {"generate": 0, "edit": 0}
        for task in tasks:
            status = _clean(task.get("status"))
            mode = _clean(task.get("mode"))
            if status in by_status:
                by_status[status] += 1
            if mode in by_mode:
                by_mode[mode] += 1
        return {
            "total": len(tasks),
            "by_status": by_status,
            "by_mode": by_mode,
            "recent": tasks[:8],
        }

    def begin_sync_task(
        self,
        identity: dict[str, object],
        *,
        mode: str,
        model: str,
        size: str | None = None,
        quality: str = "auto",
        request_preview: str = "",
        request_params: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        owner = _owner_id(identity)
        mode_value = "edit" if mode == "edit" else "generate"
        model_value = _clean(model, "gpt-image-2")
        now_ts = time.time()
        now = _now_iso()
        with self._sync_condition:
            if self._cleanup_locked():
                self._save_locked()
            task_id = f"sync-{int(now_ts * 1000)}-{threading.get_ident()}"
            key = _task_key(owner, task_id)
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": TASK_STATUS_RUNNING,
                "mode": mode_value,
                "model": model_value,
                "size": _clean(size),
                "quality": _clean(quality, "auto"),
                "created_at": now,
                "updated_at": now,
                "created_ts": now_ts,
                "updated_ts": now_ts,
                "started_ts": now_ts,
                "run_started_ts": now_ts,
                "run_count": 1,
                "client_retry_count": 0,
                "quota_consumed": False,
                "request_preview": request_preview,
                "request_params": request_params or {},
                "image_route_attempts": [],
                "progress": "sync_request_started",
                "status_logs": [
                    _status_log(
                        "同步请求已提交，开始处理",
                        level="processing",
                        event="created",
                        details={
                            "mode": mode_value,
                            "model": model_value,
                            "size": _clean(size),
                            "quality": _clean(quality, "auto"),
                        },
                        time_text=now,
                    )
                ],
            }
            task["log_id"] = self._log_task_submit(
                identity,
                task["mode"],
                task["model"],
                float(task["created_ts"]),
                request_preview=request_preview,
                request_params=request_params,
            )
            self._tasks[key] = task
            self._save_locked()
            self._sync_condition.notify_all()
        return key, _public_task(task), "start"

    def update_sync_task_progress(self, key: str, progress: object) -> None:
        if isinstance(progress, dict):
            progress_value = _clean(progress.get("progress") or progress.get("step") or progress.get("event"))
            updates: dict[str, Any] = {}
            if progress_value:
                updates["progress"] = progress_value
            conversation_id = _clean(progress.get("conversation_id"))
            if conversation_id:
                updates["conversation_id"] = conversation_id
            attempts = progress.get("image_route_attempts")
            if isinstance(attempts, list):
                updates["image_route_attempts"] = self._merge_task_route_attempts(
                    key,
                    [dict(item) for item in attempts if isinstance(item, dict)],
                )
            if updates:
                self._update_task(key, **updates)
            message = _clean(progress.get("message"))
            account_email = _clean(progress.get("account_email"))
            if message or account_email:
                with self._sync_condition:
                    task = self._tasks.get(key)
                    if task is None or task.get("cancelled"):
                        return
                    self._ensure_status_logs_locked(task)
                    detail_payload: dict[str, Any] = {
                        "account_email": account_email,
                        "attempt": progress.get("attempt"),
                        "used_account_count": progress.get("used_account_count"),
                        "backend_model": progress.get("backend_model"),
                        "image_route": progress.get("image_route"),
                    }
                    extra_details = progress.get("details")
                    if isinstance(extra_details, dict):
                        detail_payload.update({str(k): v for k, v in extra_details.items()})
                    self._append_status_log_locked(
                        task,
                        message or f"使用账号：{account_email}",
                        level="processing",
                        event=_clean(progress.get("event"), "account_selected"),
                        details=detail_payload,
                    )
                    task["updated_at"] = _now_iso()
                    task["updated_ts"] = time.time()
                    self._save_locked()
                    self._sync_condition.notify_all()
            return
        self._update_task(key, progress=_clean(progress))

    def mark_sync_task_quota_consumed(self, key: str) -> None:
        self._update_task(key, quota_consumed=True)

    def is_sync_task_quota_consumed(self, key: str) -> bool:
        with self._lock:
            return bool((self._tasks.get(key) or {}).get("quota_consumed"))

    def finish_sync_task(
        self,
        key: str,
        identity: dict[str, object],
        *,
        mode: str,
        model: str,
        started: float,
        request_preview: str = "",
        request_params: dict[str, Any] | None = None,
        result_data: object = None,
        error: str = "",
        account_email: str = "",
        conversation_id: str = "",
        image_route: dict[str, Any] | None = None,
        image_route_attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        duration_ms = int((time.time() - started) * 1000)
        merged_attempts = self._merge_task_route_attempts(key, image_route_attempts)
        if error:
            self._update_task(
                key,
                status=TASK_STATUS_ERROR,
                error=error,
                data=[],
                duration_ms=duration_ms,
                image_route_attempts=merged_attempts,
                **({"conversation_id": conversation_id} if conversation_id else {}),
            )
            self._log_call(
                key,
                identity,
                mode,
                model,
                started,
                "调用失败",
                request_preview=request_preview,
                request_params=request_params,
                status="failed",
                error=error,
                account_email=account_email,
                image_route=image_route,
                image_route_attempts=merged_attempts,
            )
            return

        result = result_data if isinstance(result_data, dict) else {}
        data = result.get("data")
        usage = result.get("usage")
        urls = _collect_image_urls(data) if isinstance(data, list) else []
        self._update_task(
            key,
            status=TASK_STATUS_SUCCESS,
            data=data if isinstance(data, list) else [],
            usage=usage if isinstance(usage, dict) else None,
            error="",
            duration_ms=duration_ms,
            image_route_attempts=merged_attempts,
            **({"conversation_id": conversation_id} if conversation_id else {}),
        )
        self._log_call(
            key,
            identity,
            mode,
            model,
            started,
            "调用完成",
            request_preview=request_preview,
            request_params=request_params,
            urls=urls,
            account_email=account_email,
            result_data=data,
            image_route=image_route,
            image_route_attempts=merged_attempts,
        )

    def _submit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        mode: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _clean(client_task_id)
        if not task_id:
            raise ValueError("client_task_id is required")
        owner = _owner_id(identity)
        key = _task_key(owner, task_id)
        now = _now_iso()
        should_start = False
        with self._lock:
            if self._cleanup_locked():
                self._save_locked()
            task = self._tasks.get(key)
            if task is not None:
                raise ValueError("task_id already exists")
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": TASK_STATUS_QUEUED,
                "mode": mode,
                "model": _clean(payload.get("model"), "gpt-image-2"),
                "size": _clean(payload.get("size")),
                "quality": _clean(payload.get("quality"), "auto"),
                "created_at": now,
                "updated_at": now,
                "created_ts": time.time(),
                "status_logs": [
                    _status_log(
                        "任务已进入队列",
                        event="queued",
                        details={
                            "mode": mode,
                            "model": _clean(payload.get("model"), "gpt-image-2"),
                            "size": _clean(payload.get("size")),
                            "quality": _clean(payload.get("quality"), "auto"),
                        },
                        time_text=now,
                    )
                ],
            }
            task["log_id"] = self._log_task_submit(
                identity,
                mode,
                task["model"],
                float(task["created_ts"]),
                request_text(payload.get("prompt")),
                request_params=_request_params_from_payload(payload),
            )
            self._tasks[key] = task
            self._save_locked()
            should_start = True

        if should_start:
            thread = threading.Thread(
                target=self._run_task,
                args=(key, mode, payload, dict(identity), _clean(payload.get("model"), "gpt-image-2")),
                name=f"image-task-{task_id[:16]}",
                daemon=True,
            )
            thread.start()
        return _public_task(task)

    def _run_task(
        self,
        key: str,
        mode: str,
        payload: dict[str, Any],
        identity: dict[str, object],
        model: str,
    ) -> None:
        started = time.time()
        self._update_task(key, status=TASK_STATUS_RUNNING, error="")
        # 创建进度回调，每个步骤完成后更新任务状态
        def progress_callback(step: object) -> None:
            step_name = _clean(step.get("progress") or step.get("step") or step.get("event")) if isinstance(step, dict) else _clean(step)
            if step_name == "image_stream_resolve_start":
                self._update_task(key, started_ts=time.time())
            self.update_sync_task_progress(key, step)
        # 将进度回调添加到 payload 中（handler 会提取并传递给 ConversationRequest）
        payload_with_progress = {**payload, "progress_callback": progress_callback}
        try:
            handler = self.edit_handler if mode == "edit" else self.generation_handler
            result = handler(payload_with_progress)
            if not isinstance(result, dict):
                raise RuntimeError("image task returned streaming result unexpectedly")
            data = result.get("data")
            account_email = _clean(result.get("_account_email") or result.get("account_email"))
            if not isinstance(data, list) or not data:
                upstream = _clean(result.get("message"))
                if upstream:
                    message = upstream
                else:
                    message = "号池中没有可用账号或所有账号均被限流，请检查号池状态（账号额度、是否被封禁、是否到达生图上限）"
                error = RuntimeError(message)
                if account_email:
                    setattr(error, "account_email", account_email)
                route_meta = _image_route_from_result(result)
                route_attempts = _image_route_attempts_from_result(result)
                if route_meta:
                    setattr(error, "image_route", route_meta)
                if route_attempts:
                    setattr(error, "image_route_attempts", route_attempts)
                raise error
            usage = result.get("usage")
            duration_ms = int((time.time() - started) * 1000)
            route_attempts = self._merge_task_route_attempts(key, _image_route_attempts_from_result(result))
            self._update_task(
                key,
                status=TASK_STATUS_SUCCESS,
                data=data,
                usage=usage,
                error="",
                duration_ms=duration_ms,
                image_route_attempts=route_attempts,
            )
            self._log_call(
                key,
                identity,
                mode,
                model,
                started,
                "调用完成",
                request_preview=request_text(payload.get("prompt")),
                request_params=_request_params_from_payload(payload),
                urls=_collect_image_urls(data),
                account_email=account_email,
                result_data=data,
                image_route=_image_route_from_result(result),
                image_route_attempts=route_attempts,
            )
        except Exception as exc:
            error_message = str(exc) or "image task failed"
            account_email = _clean(getattr(exc, "account_email", ""))
            conversation_id = _clean(getattr(exc, "conversation_id", ""))
            duration_ms = int((time.time() - started) * 1000)
            route_attempts = self._merge_task_route_attempts(key, _image_route_attempts_from_exception(exc))
            self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[],
                              duration_ms=duration_ms,
                              image_route_attempts=route_attempts,
                              **({"conversation_id": conversation_id} if conversation_id else {}))
            self._log_call(
                key,
                identity,
                mode,
                model,
                started,
                "调用失败",
                request_preview=request_text(payload.get("prompt")),
                request_params=_request_params_from_payload(payload),
                status="failed",
                error=error_message,
                account_email=account_email,
                image_route=_image_route_from_exception(exc),
                image_route_attempts=route_attempts,
            )

    def _log_call(
        self,
        key: str,
        identity: dict[str, object],
        mode: str,
        model: str,
        started: float,
        suffix: str,
        *,
        request_preview: str = "",
        status: str = "success",
        error: str = "",
        urls: list[str] | None = None,
        account_email: str = "",
        request_params: dict[str, Any] | None = None,
        result_data: object = None,
        image_route: dict[str, Any] | None = None,
        image_route_attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        endpoint = "/v1/images/edits" if mode == "edit" else "/v1/images/generations"
        summary_prefix = "图生图" if mode == "edit" else "文生图"
        detail = _build_log_detail(
            identity,
            endpoint=endpoint,
            model=model,
            started=started,
            request_preview=request_preview,
            status=status,
            error=error,
            urls=urls,
            account_email=account_email,
            request_params=request_params,
            image_route=image_route,
            image_route_attempts=image_route_attempts,
        )
        detail.update(_image_result_meta(result_data))
        try:
            with self._lock:
                task_snapshot = dict(self._tasks.get(key) or {})
                log_id = _clean(task_snapshot.get("log_id"))
            if task_snapshot.get("id"):
                detail["task_id"] = task_snapshot.get("id")
            if task_snapshot.get("client_retry_count"):
                detail["client_retry_count"] = int(task_snapshot.get("client_retry_count") or 0)
            if task_snapshot.get("run_count"):
                detail["run_count"] = int(task_snapshot.get("run_count") or 0)
            summary = f"{summary_prefix}{suffix}"
            if log_id and log_service.update(log_id, summary, detail):
                return
            log_service.add(LOG_TYPE_CALL, summary, detail)
        except Exception:
            pass

    def _log_task_submit(
        self,
        identity: dict[str, object],
        mode: str,
        model: str,
        started: float,
        request_preview: str = "",
        request_params: dict[str, Any] | None = None,
    ) -> str:
        endpoint = "/v1/images/edits" if mode == "edit" else "/v1/images/generations"
        summary_prefix = "图生图" if mode == "edit" else "文生图"
        detail = _build_log_detail(
            identity,
            endpoint=endpoint,
            model=model,
            started=started,
            request_preview=request_preview,
            request_params=request_params,
            status="running",
            finished=False,
        )
        try:
            return log_service.add(LOG_TYPE_CALL, f"{summary_prefix}已提交", detail)
        except Exception:
            return ""

    def _update_task(self, key: str, **updates: Any) -> None:
        with self._sync_condition:
            task = self._tasks.get(key)
            if task is None:
                return
            if task.get("cancelled"):
                return
            self._ensure_status_logs_locked(task)
            previous_status = _clean(task.get("status"))
            previous_progress = _clean(task.get("progress"))
            previous_conversation_id = _clean(task.get("conversation_id"))
            previous_attempts = task.get("image_route_attempts")
            previous_attempt_count = len(previous_attempts) if isinstance(previous_attempts, list) else 0
            task.update(updates)
            self._append_update_logs_locked(
                task,
                updates,
                previous_status=previous_status,
                previous_progress=previous_progress,
                previous_conversation_id=previous_conversation_id,
                previous_attempt_count=previous_attempt_count,
            )
            task["updated_at"] = _now_iso()
            task["updated_ts"] = time.time()
            self._save_locked()
            self._sync_condition.notify_all()

    def _merge_task_route_attempts(
        self,
        key: str,
        attempts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            existing = self._tasks.get(key, {}).get("image_route_attempts")
        existing_items = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
        new_items = [dict(item) for item in attempts if isinstance(item, dict)] if isinstance(attempts, list) else []
        return _dedupe_image_route_attempts([*existing_items, *new_items])

    def wait_sync_task(self, key: str, timeout_secs: float = 180.0) -> dict[str, Any]:
        deadline = time.time() + max(0.0, float(timeout_secs or 0.0))
        with self._sync_condition:
            while True:
                task = self._tasks.get(key)
                if task is None:
                    return {}
                if task.get("status") in TERMINAL_STATUSES:
                    return dict(task)
                remaining = deadline - time.time()
                if remaining <= 0:
                    return dict(task)
                self._sync_condition.wait(timeout=min(1.0, remaining))

    def _find_task_locked(self, identity: dict[str, object], task_id: str) -> tuple[str, dict[str, Any] | None]:
        normalized_id = _clean(task_id)
        if not normalized_id:
            return "", None
        own_key = _task_key(_owner_id(identity), normalized_id)
        task = self._tasks.get(own_key)
        if task is not None:
            return own_key, task
        if not _is_admin(identity):
            return "", None
        matches = [
            (key, item)
            for key, item in self._tasks.items()
            if _clean(item.get("id")) == normalized_id
        ]
        if not matches:
            return "", None
        matches.sort(key=lambda entry: str((entry[1] or {}).get("updated_at") or ""), reverse=True)
        return matches[0]

    def cancel_task(self, identity: dict[str, object], task_id: str) -> dict[str, Any]:
        if not _clean(task_id):
            raise ValueError("task_id is required")
        with self._lock:
            key, task = self._find_task_locked(identity, task_id)
            if task is None:
                raise ValueError("task not found")
            if task.get("status") in TERMINAL_STATUSES:
                raise ValueError("task is already finished")
            self._ensure_status_logs_locked(task)
            task["cancelled"] = True
            task["status"] = TASK_STATUS_ERROR
            task["error"] = "任务已取消"
            self._append_status_log_locked(task, "任务已取消", level="warning", event="cancelled")
            task["updated_at"] = _now_iso()
            task["updated_ts"] = time.time()
            self._save_locked()
            return _public_task(task)

    def _load_locked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        raw_items = raw.get("tasks") if isinstance(raw, dict) else raw
        if not isinstance(raw_items, list):
            return {}
        tasks: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            task_id = _clean(item.get("id"))
            owner = _clean(item.get("owner_id"))
            if not task_id or not owner:
                continue
            status = _clean(item.get("status"))
            if status not in {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING, TASK_STATUS_SUCCESS, TASK_STATUS_ERROR}:
                status = TASK_STATUS_ERROR
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": status,
                "mode": "edit" if item.get("mode") == "edit" else "generate",
                "model": _clean(item.get("model"), "gpt-image-2"),
                "size": _clean(item.get("size")),
                "quality": _clean(item.get("quality"), "auto"),
                "created_at": _clean(item.get("created_at"), _now_iso()),
                "updated_at": _clean(item.get("updated_at"), _clean(item.get("created_at"), _now_iso())),
                "created_ts": item.get("created_ts"),
                "updated_ts": item.get("updated_ts"),
                "started_ts": item.get("started_ts"),
                "run_started_ts": item.get("run_started_ts"),
                "run_count": item.get("run_count"),
                "client_retry_count": item.get("client_retry_count"),
                "quota_consumed": bool(item.get("quota_consumed")),
                "duration_ms": item.get("duration_ms"),
                "log_id": _clean(item.get("log_id")),
                "request_preview": _clean(item.get("request_preview")),
            }
            request_params = item.get("request_params")
            if isinstance(request_params, dict):
                task["request_params"] = request_params
            status_logs = item.get("status_logs")
            if isinstance(status_logs, list):
                task["status_logs"] = [
                    dict(entry)
                    for entry in status_logs[-MAX_TASK_STATUS_LOGS:]
                    if isinstance(entry, dict) and _clean(entry.get("message"))
                ]
            attempts = item.get("image_route_attempts")
            if isinstance(attempts, list):
                task["image_route_attempts"] = [
                    dict(attempt)
                    for attempt in attempts
                    if isinstance(attempt, dict)
                ]
            if item.get("cancelled"):
                task["cancelled"] = True
            data = item.get("data")
            if isinstance(data, list):
                task["data"] = data
            usage = item.get("usage")
            if isinstance(usage, dict):
                task["usage"] = usage
            error = _clean(item.get("error"))
            if error:
                task["error"] = error
            progress = _clean(item.get("progress"))
            if progress:
                task["progress"] = progress
            tasks[_task_key(owner, task_id)] = task
        return tasks

    def _save_locked(self) -> None:
        items = sorted(self._tasks.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"tasks": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def _recover_unfinished_locked(self) -> bool:
        changed = False
        for task in self._tasks.values():
            if task.get("status") in UNFINISHED_STATUSES:
                self._ensure_status_logs_locked(task)
                task["status"] = TASK_STATUS_ERROR
                task["error"] = "服务已重启，未完成的图片任务已中断"
                self._append_status_log_locked(
                    task,
                    "服务已重启，未完成的图片任务已中断",
                    level="error",
                    event="recovered_interrupted",
                )
                task["updated_at"] = _now_iso()
                task["updated_ts"] = time.time()
                changed = True
        return changed

    def _cleanup_locked(self) -> bool:
        changed = False
        stale_cutoff = time.time() - _stale_task_seconds()
        for task in self._tasks.values():
            if task.get("status") in UNFINISHED_STATUSES and _task_activity_ts(task) < stale_cutoff:
                self._ensure_status_logs_locked(task)
                task["status"] = TASK_STATUS_ERROR
                task["error"] = "图片任务长时间未更新，已自动标记为中断"
                self._append_status_log_locked(
                    task,
                    "图片任务长时间未更新，已自动标记为中断",
                    level="error",
                    event="stale_interrupted",
                )
                task["updated_at"] = _now_iso()
                task["updated_ts"] = time.time()
                changed = True

        try:
            retention_days = max(1, int(self.retention_days_getter()))
        except Exception:
            retention_days = 30
        cutoff = time.time() - retention_days * 86400
        removed_keys = [
            key
            for key, task in self._tasks.items()
            if task.get("status") in TERMINAL_STATUSES and _timestamp(task.get("updated_at")) < cutoff
        ]
        for key in removed_keys:
            self._tasks.pop(key, None)
            changed = True
        return changed

    def resume_poll(
        self,
        identity: dict[str, object],
        task_id: str,
        extra_timeout_secs: float = 30.0,
    ) -> dict[str, Any]:
        """恢复对已超时任务的轮询，额外等待 extra_timeout_secs 秒。"""
        with self._lock:
            key, task = self._find_task_locked(identity, task_id)
            if task is None:
                raise ValueError("task not found")
            if task.get("status") != TASK_STATUS_ERROR:
                raise ValueError("task is not in error state")
            error_msg = _clean(task.get("error"))
            if "超时" not in error_msg:
                raise ValueError("task error is not a timeout error")
            conversation_id = _clean(task.get("conversation_id"))
            if not conversation_id:
                raise ValueError("task has no conversation_id")
            mode = task.get("mode", "generate")
            model = task.get("model", "gpt-image-2")
            # 将任务状态重置为 running
            self._update_task(key, status=TASK_STATUS_RUNNING, error="", progress="image_stream_resolve_start")
            with self._lock:
                current = self._tasks.get(key)
                if current is not None:
                    self._append_status_log_locked(
                        current,
                        f"开始续轮询，额外等待 {extra_timeout_secs:g} 秒",
                        level="processing",
                        event="resume_poll",
                        details={"extra_timeout_secs": extra_timeout_secs, "conversation_id": conversation_id},
                    )
                    self._save_locked()

        # 启动新线程继续轮询
        thread = threading.Thread(
            target=self._run_resume_poll,
            args=(key, conversation_id, extra_timeout_secs, dict(identity), mode, model),
            name=f"image-resume-{_clean(task_id)[:16]}",
            daemon=True,
        )
        thread.start()
        return _public_task(task)

    def _run_resume_poll(
        self,
        key: str,
        conversation_id: str,
        extra_timeout_secs: float,
        identity: dict[str, object],
        mode: str,
        model: str,
    ) -> None:
        """后台线程：继续轮询已有 conversation_id 的图片结果。"""
        started = time.time()
        try:
            from services.openai_backend_api import OpenAIBackendAPI
            from services.protocol.conversation import format_image_result

            self._update_task(key, progress="image_stream_resolve_start")
            backend = OpenAIBackendAPI(proxy_url=config.proxy_url or None)
            file_ids, sediment_ids = backend._poll_image_results(
                conversation_id,
                extra_timeout_secs,
            )
            if not file_ids and not sediment_ids:
                raise RuntimeError(
                    f"继续等待 {extra_timeout_secs} 秒后仍未找到图片结果。"
                )

            image_urls = backend.resolve_conversation_image_urls(
                conversation_id, file_ids, sediment_ids, poll=False,
            )
            if not image_urls:
                raise RuntimeError("图片 URL 解析失败")

            self._update_task(key, progress="receiving_image")
            image_items = [
                {"b64_json": __import__("base64").b64encode(image_data).decode("ascii")}
                for image_data in backend.download_image_bytes(image_urls)
            ]
            # 获取 task 的原始 prompt（从 _public_task 的 mode 判断）
            with self._lock:
                task = self._tasks.get(key)
            data = format_image_result(
                image_items,
                "",  # prompt 已不重要，结果已经拿到了
                "b64_json",
                "",
                int(time.time()),
            )["data"]
            self._update_task(key, status=TASK_STATUS_SUCCESS, data=data, error="", duration_ms=int((time.time() - started) * 1000))
            self._log_call(
                key,
                identity,
                mode,
                model,
                started,
                "调用完成（续轮询）",
                status="success",
                urls=_collect_image_urls(data),
                request_params=_request_params_from_payload(task or {}),
                result_data=data,
            )
        except Exception as exc:
            error_message = str(exc) or "resume poll failed"
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[], duration_ms=duration_ms)
            self._log_call(
                key,
                identity,
                mode,
                model,
                started,
                "调用失败（续轮询）",
                status="failed",
                error=error_message,
            )


image_task_service = ImageTaskService(DATA_DIR / "image_tasks.json")
