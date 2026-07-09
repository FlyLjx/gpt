from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from services.account_service import account_service
from services.auth_service import auth_service
from services.config import LOCAL_TIME_FORMAT, config, local_datetime, local_time_text
from services.image_task_service import image_task_service
from services.log_service import LOG_TYPE_CALL, log_service


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("detail")
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _call_status(detail: dict[str, Any]) -> str:
    status = _text(detail.get("status"))
    return status or "success"


def _parse_local_log_time(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text[:19], LOCAL_TIME_FORMAT)
    except Exception:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None


def _call_finished_time(item: dict[str, Any], detail: dict[str, Any]) -> datetime | None:
    for key in ("ended_at", "submitted_at", "started_at"):
        parsed = _parse_local_log_time(detail.get(key))
        if parsed is not None:
            return parsed
    return _parse_local_log_time(item.get("time"))


def _minute_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _minute_label(value: datetime) -> str:
    return value.strftime("%H:%M")


def _error_label(detail: dict[str, Any]) -> str:
    for key in ("error_type", "code"):
        value = _text(detail.get(key))
        if value:
            return value[:80]

    error = _text(detail.get("error"))
    lowered = error.lower()
    if not error:
        return "未知错误"
    if "no available image quota" in lowered or "insufficient_quota" in lowered or "quota" in lowered:
        return "额度不足"
    if "rate limit" in lowered or "429" in lowered or "限流" in error:
        return "限流"
    if "timeout" in lowered or "timed out" in lowered or "超时" in error:
        return "超时"
    if "content policy" in lowered or "policy" in lowered or "安全" in error:
        return "内容策略"
    if "invalid_api_key" in lowered or "unauthorized" in lowered or "401" in lowered or "密钥" in error:
        return "认证失败"
    if "upstream" in lowered or "502" in lowered or "503" in lowered:
        return "上游异常"
    return error[:80]


def _runtime_health_summary(items: list[dict[str, Any]], window_minutes: int = 60) -> dict[str, Any]:
    now = local_datetime().replace(second=0, microsecond=0, tzinfo=None)
    start = now - timedelta(minutes=max(1, window_minutes) - 1)
    buckets = {
        _minute_key(start + timedelta(minutes=index)): {
            "time": _minute_key(start + timedelta(minutes=index)),
            "label": _minute_label(start + timedelta(minutes=index)),
            "success": 0,
            "failed": 0,
        }
        for index in range(window_minutes)
    }
    totals = {"success": 0, "failed": 0, "running": 0, "other": 0}
    error_reasons: dict[str, int] = {}

    for item in items:
        detail = _detail(item)
        status = _call_status(detail)
        finished_at = _call_finished_time(item, detail)
        if finished_at is None or finished_at < start or finished_at > now + timedelta(minutes=1):
            continue

        if status in totals:
            totals[status] += 1
        else:
            totals["other"] += 1

        bucket = buckets.get(_minute_key(finished_at))
        if bucket is not None:
            if status == "success":
                bucket["success"] += 1
            elif status == "failed":
                bucket["failed"] += 1

        if status == "failed":
            label = _error_label(detail)
            error_reasons[label] = error_reasons.get(label, 0) + 1

    total_finished = totals["success"] + totals["failed"]
    total_all = total_finished + totals["running"] + totals["other"]
    error_rate = round((totals["failed"] / total_finished) * 100, 1) if total_finished else 0.0
    success_rate = round((totals["success"] / total_finished) * 100, 1) if total_finished else 0.0

    return {
        "window_minutes": window_minutes,
        "start_time": _minute_key(start),
        "end_time": _minute_key(now),
        "series": list(buckets.values()),
        "totals": totals,
        "total": total_all,
        "success_rate": success_rate,
        "error_rate": error_rate,
        "status_pie": [
            {"label": "成功", "value": totals["success"], "status": "success"},
            {"label": "失败", "value": totals["failed"], "status": "failed"},
            {"label": "处理中", "value": totals["running"], "status": "running"},
            {"label": "其他", "value": totals["other"], "status": "other"},
        ],
        "error_reasons": [
            {"label": label, "value": value}
            for label, value in sorted(error_reasons.items(), key=lambda item: item[1], reverse=True)[:6]
        ],
    }


def _call_logs_summary() -> dict[str, Any]:
    today = local_time_text(fmt="%Y-%m-%d")
    items = log_service.list(type=LOG_TYPE_CALL, start_date=today, end_date=today, limit=5000)
    by_endpoint: dict[str, int] = {}
    by_model: dict[str, int] = {}
    by_status = {"success": 0, "failed": 0, "running": 0, "other": 0}
    recent_failed: list[dict[str, Any]] = []
    runtime = _runtime_health_summary(items)

    for item in items:
        detail = _detail(item)
        status = _call_status(detail)
        if status in by_status:
            by_status[status] += 1
        else:
            by_status["other"] += 1

        endpoint = _text(detail.get("endpoint")) or "unknown"
        model = _text(detail.get("model")) or "unknown"
        by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
        by_model[model] = by_model.get(model, 0) + 1

        if status == "failed" and len(recent_failed) < 8:
            recent_failed.append({
                "id": item.get("id"),
                "time": item.get("time"),
                "summary": item.get("summary"),
                "endpoint": endpoint,
                "model": model,
                "error": _text(detail.get("error"))[:300],
                "account_email": _text(detail.get("account_email")),
            })

    return {
        "date": today,
        "total": len(items),
        "by_status": by_status,
        "by_endpoint": by_endpoint,
        "by_model": by_model,
        "recent_failed": recent_failed,
        "runtime": runtime,
    }


def build_dashboard_summary(app_version: str) -> dict[str, Any]:
    storage = config.get_storage_backend()
    user_keys = auth_service.list_keys(role="user")
    accounts = account_service.get_stats()
    storage_health = storage.health_check()
    tasks = image_task_service.get_stats()
    calls = _call_logs_summary()

    return {
        "version": app_version,
        "generated_at": local_time_text(),
        "storage": {
            "backend": storage.get_backend_info(),
            "health": storage_health,
        },
        "accounts": accounts,
        "auth_keys": {
            "users": len(user_keys),
            "enabled_users": sum(1 for item in user_keys if item.get("enabled")),
        },
        "calls": calls,
        "tasks": tasks,
    }
