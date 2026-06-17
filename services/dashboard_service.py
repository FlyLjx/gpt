from __future__ import annotations

from typing import Any

from services.account_service import account_service
from services.auth_service import auth_service
from services.config import config, local_time_text
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


def _call_logs_summary() -> dict[str, Any]:
    today = local_time_text(fmt="%Y-%m-%d")
    items = log_service.list(type=LOG_TYPE_CALL, start_date=today, end_date=today, limit=1000)
    by_endpoint: dict[str, int] = {}
    by_model: dict[str, int] = {}
    by_status = {"success": 0, "failed": 0, "running": 0, "other": 0}
    recent_failed: list[dict[str, Any]] = []

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
