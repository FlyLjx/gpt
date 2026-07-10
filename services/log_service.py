from __future__ import annotations

import hashlib
import json
import itertools
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from services.config import DATA_DIR, local_time_text
from services.protocol.error_response import anthropic_error_response, openai_error_response
from utils.helper import anthropic_sse_stream, sse_json_stream

LOG_TYPE_CALL = "call"
LOG_TYPE_ACCOUNT = "account"
INTERNAL_RESPONSE_KEYS = {"_account_email", "_conversation_id", "_b64_json", "_image_route", "_image_route_attempts"}
IMAGE_REQUEST_PARAM_KEYS = ("n", "size", "quality", "response_format", "stream")
IMAGE_ROUTE_DETAIL_KEYS = (
    "account_type",
    "account_source_type",
    "account_default_model_slug",
    "requested_model",
    "backend_model",
    "image_channel",
    "image_channel_label",
    "image_route",
    "image_route_label",
)
IMAGE_FINAL_RESULT_LABELS = {
    "success": "成功",
    "failed": "失败",
    "running": "处理中",
}


class LogService:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def _legacy_id(raw_line: str, line_number: int) -> str:
        payload = f"{line_number}:{raw_line}".encode("utf-8", errors="ignore")
        return hashlib.sha1(payload).hexdigest()[:24]

    def _parse_line(self, raw_line: str, line_number: int) -> dict[str, Any] | None:
        try:
            item = json.loads(raw_line)
        except Exception:
            return None
        if not isinstance(item, dict):
            return None
        parsed = dict(item)
        parsed["id"] = str(parsed.get("id") or self._legacy_id(raw_line, line_number))
        return parsed

    @staticmethod
    def _serialize_item(item: dict[str, Any]) -> str:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _matches_filters(item: dict[str, Any], *, type: str = "", start_date: str = "", end_date: str = "") -> bool:
        t = str(item.get("time") or "")
        day = t[:10]
        if type and item.get("type") != type:
            return False
        if start_date and day < start_date:
            return False
        if end_date and day > end_date:
            return False
        return True

    def add(self, type: str, summary: str = "", detail: dict[str, Any] | None = None, **data: Any) -> str:
        item_id = uuid4().hex
        item_detail = detail or data
        item = {
            "id": item_id,
            "time": local_time_text(),
            "type": type,
            "summary": summary,
            "detail": item_detail,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(self._serialize_item(item) + "\n")
        self._notify_if_needed(item)
        return item_id

    def update(self, item_id: str, summary: str = "", detail: dict[str, Any] | None = None, **data: Any) -> bool:
        target_id = str(item_id or "").strip()
        if not target_id or not self.path.exists():
            return False
        updated_item: dict[str, Any] | None = None
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            changed = False
            next_lines: list[str] = []
            for line_number, raw_line in enumerate(lines):
                item = self._parse_line(raw_line, line_number)
                if item is None or str(item.get("id") or "") != target_id:
                    next_lines.append(raw_line)
                    continue
                updated = {
                    **item,
                    "id": target_id,
                    "summary": summary or str(item.get("summary") or ""),
                    "detail": detail or data,
                }
                updated_item = updated
                next_lines.append(self._serialize_item(updated))
                changed = True
            if not changed:
                return False
            content = "\n".join(next_lines)
            if content:
                content += "\n"
            self.path.write_text(content, encoding="utf-8")
        if updated_item is not None:
            self._notify_if_needed(updated_item)
        return True

    @staticmethod
    def _notify_if_needed(item: dict[str, Any]) -> None:
        try:
            if item.get("type") != LOG_TYPE_CALL:
                return
            detail = item.get("detail")
            if not isinstance(detail, dict) or str(detail.get("status") or "") != "failed":
                return
            from services.notification_service import notification_service

            notification_service.notify_failed_log(
                str(item.get("id") or ""),
                str(item.get("summary") or ""),
                detail,
            )
        except Exception:
            return

    def list(self, type: str = "", start_date: str = "", end_date: str = "", limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line_number in range(len(lines) - 1, -1, -1):
            item = self._parse_line(lines[line_number], line_number)
            if item is None:
                continue
            if not self._matches_filters(item, type=type, start_date=start_date, end_date=end_date):
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def delete(self, ids: list[str]) -> dict[str, int]:
        target_ids = {str(item or "").strip() for item in ids if str(item or "").strip()}
        if not self.path.exists() or not target_ids:
            return {"removed": 0}
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            kept_lines: list[str] = []
            removed = 0
            for line_number, raw_line in enumerate(lines):
                item = self._parse_line(raw_line, line_number)
                if item is None:
                    kept_lines.append(raw_line)
                    continue
                if str(item.get("id") or "") in target_ids:
                    removed += 1
                    continue
                kept_lines.append(self._serialize_item(item))
            content = "\n".join(kept_lines)
            if content:
                content += "\n"
            self.path.write_text(content, encoding="utf-8")
        return {"removed": removed}


log_service = LogService(DATA_DIR / "logs.jsonl")


def _collect_urls(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str):
                urls.append(item)
            elif key == "urls" and isinstance(item, list):
                urls.extend(str(url) for url in item if isinstance(url, str))
            else:
                urls.extend(_collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_collect_urls(item))
    return urls


def _collect_account_emails(value: object) -> list[str]:
    emails: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"_account_email", "account_email"} and isinstance(item, str) and item.strip():
                emails.append(item.strip())
            else:
                emails.extend(_collect_account_emails(item))
    elif isinstance(value, list):
        for item in value:
            emails.extend(_collect_account_emails(item))
    return emails


def _collect_conversation_ids(value: object) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "_conversation_id" and isinstance(item, str) and item.strip():
                ids.append(item.strip())
            else:
                ids.extend(_collect_conversation_ids(item))
    elif isinstance(value, list):
        for item in value:
            ids.extend(_collect_conversation_ids(item))
    return ids


def _collect_image_routes(value: object) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "_image_route" and isinstance(item, dict):
                route = {str(route_key): route_value for route_key, route_value in item.items()}
                if route:
                    routes.append(route)
            else:
                routes.extend(_collect_image_routes(item))
    elif isinstance(value, list):
        for item in value:
            routes.extend(_collect_image_routes(item))
    return routes


def _collect_image_route_attempts(value: object) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "_image_route_attempts" and isinstance(item, list):
                attempts.extend(
                    {str(route_key): route_value for route_key, route_value in route.items()}
                    for route in item
                    if isinstance(route, dict) and route
                )
            else:
                attempts.extend(_collect_image_route_attempts(item))
    elif isinstance(value, list):
        for item in value:
            attempts.extend(_collect_image_route_attempts(item))
    return attempts


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


def _image_route_from_exception(exc: Exception) -> dict[str, Any]:
    route = getattr(exc, "image_route", None)
    return dict(route) if isinstance(route, dict) else {}


def _image_route_attempts_from_exception(exc: Exception) -> list[dict[str, Any]]:
    attempts = getattr(exc, "image_route_attempts", None)
    if not isinstance(attempts, list):
        return []
    return _dedupe_image_route_attempts([dict(item) for item in attempts if isinstance(item, dict)])


def _clean_detail_text(value: object) -> str:
    return str(value or "").strip()


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _request_count_from_detail(detail: dict[str, Any], attempts: list[dict[str, Any]]) -> int:
    request_params = detail.get("request_params")
    n = _safe_int(request_params.get("n") if isinstance(request_params, dict) else None)
    if n > 0:
        return n
    totals = [_safe_int(item.get("total")) for item in attempts]
    return max([item for item in totals if item > 0], default=1)


def _attempt_status(item: dict[str, Any]) -> str:
    return _clean_detail_text(item.get("status")).lower()


def _attempt_is_success(item: dict[str, Any]) -> bool:
    return _attempt_status(item) == "success"


def _attempt_is_failed(item: dict[str, Any]) -> bool:
    status = _attempt_status(item)
    return status in {"failed", "error"} or bool(_clean_detail_text(item.get("error")))


def _account_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    mapping = {
        "email": "account_email",
        "token": "account_token",
        "type": "account_type",
        "source_type": "account_source_type",
        "backend_model": "backend_model",
        "channel": "image_channel",
        "channel_label": "image_channel_label",
        "route": "image_route",
        "route_label": "image_route_label",
        "index": "index",
        "attempt": "attempt",
        "status": "status",
    }
    for out_key, in_key in mapping.items():
        value = item.get(in_key)
        if value is not None and value != "":
            summary[out_key] = value
    error = _clean_detail_text(item.get("error"))
    if error:
        summary["error"] = error[:300]
    return summary


def _unique_texts(values: list[object]) -> list[str]:
    return list(dict.fromkeys(_clean_detail_text(value) for value in values if _clean_detail_text(value)))


def _detail_request_size(detail: dict[str, Any]) -> str:
    request_params = detail.get("request_params")
    if isinstance(request_params, dict):
        return _clean_detail_text(request_params.get("size"))
    return ""


def _has_image_log_detail(
    endpoint: str,
    image_route: dict[str, Any] | None = None,
    image_route_attempts: list[dict[str, Any]] | None = None,
    result: object = None,
) -> bool:
    if endpoint.startswith(("/v1/images", "/api/image-tasks")):
        return True
    if image_route or image_route_attempts:
        return True
    return bool(_collect_image_routes(result) or _collect_image_route_attempts(result))


def apply_image_log_detail(
    detail: dict[str, Any],
    image_route: dict[str, Any] | None = None,
    image_route_attempts: list[dict[str, Any]] | None = None,
    result: object = None,
) -> None:
    route_meta = dict(image_route or {})
    if not route_meta:
        routes = _collect_image_routes(result)
        route_meta = routes[0] if routes else {}
    attempts = _dedupe_image_route_attempts([
        *(image_route_attempts or []),
        *_collect_image_route_attempts(result),
    ])
    successful_attempts = [item for item in attempts if _attempt_is_success(item)]
    failed_attempts = [item for item in attempts if _attempt_is_failed(item)]
    if successful_attempts:
        route_meta = dict(successful_attempts[-1])
    elif not route_meta and attempts:
        route_meta = dict(attempts[-1])

    for key in IMAGE_ROUTE_DETAIL_KEYS:
        value = route_meta.get(key)
        if value is not None and value != "":
            detail[key] = value
    if route_meta.get("account_email") and not detail.get("account_email"):
        detail["account_email"] = route_meta["account_email"]

    resolution = _detail_request_size(detail)
    if resolution:
        detail["resolution"] = resolution
    if attempts:
        request_count = _request_count_from_detail(detail, attempts)
        retry_count = max(0, len(attempts) - request_count)
        final_accounts = [_account_summary(item) for item in successful_attempts]
        failed_account_details = [_account_summary(item) for item in failed_attempts]
        failed_accounts = _unique_texts([
            item.get("account_email") or item.get("account_token") or item.get("token")
            for item in failed_attempts
        ])
        used_accounts = _unique_texts([
            item.get("account_email") or item.get("account_token") or item.get("token")
            for item in attempts
        ])
        detail["image_route_attempts"] = attempts
        detail["image_route_attempt_count"] = len(attempts)
        detail["retry_count"] = retry_count
        detail["used_accounts"] = used_accounts
        detail["used_account_count"] = len(used_accounts)
        if final_accounts:
            detail["final_accounts"] = final_accounts
            detail["final_account_count"] = len(final_accounts)
            detail["final_account_emails"] = _unique_texts([
                item.get("account_email") or item.get("account_token") or item.get("token")
                for item in successful_attempts
            ])
        if failed_account_details:
            detail["failed_account_details"] = failed_account_details
        if failed_accounts:
            detail["failed_accounts"] = failed_accounts
            detail["failed_account_count"] = len(failed_accounts)
    final_result = _clean_detail_text(detail.get("status")) or "success"
    detail["final_result"] = final_result
    detail["final_result_label"] = IMAGE_FINAL_RESULT_LABELS.get(final_result, final_result)


def image_request_params(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    params = {key: payload.get(key) for key in IMAGE_REQUEST_PARAM_KEYS if key in payload}
    images = payload.get("images")
    if isinstance(images, list):
        params["image_count"] = len(images)
    masks = payload.get("mask")
    if isinstance(masks, list):
        params["mask_count"] = len(masks)
    return params


def _collect_image_result_meta(value: object) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, dict)]
    if not items:
        return meta
    return meta


def _strip_internal_response_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _strip_internal_response_fields(item)
            for key, item in value.items()
            if key not in INTERNAL_RESPONSE_KEYS
        }
    if isinstance(value, list):
        return [_strip_internal_response_fields(item) for item in value]
    return value


def _request_excerpt(text: object, limit: int = 1000) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _image_error_response(exc: Exception) -> JSONResponse:
    from services.protocol.conversation import public_image_error_message

    message = public_image_error_message(str(exc))
    lower_message = message.lower()
    if "no available image quota" in lower_message or ("no available" in lower_message and "image quota" in lower_message):
        return openai_error_response(
            {
                "error": {
                    "message": "no available image quota",
                    "type": "insufficient_quota",
                    "param": None,
                    "code": "insufficient_quota",
                }
            },
            429,
        )
    if hasattr(exc, "to_openai_error") and hasattr(exc, "status_code"):
        return JSONResponse(status_code=int(exc.status_code), content=exc.to_openai_error())
    return openai_error_response(message, 502)


def _protocol_error_response(exc: Exception, status_code: int, sse: str) -> JSONResponse:
    message = str(exc)
    if sse == "anthropic":
        return anthropic_error_response(message, status_code)
    return openai_error_response(message, status_code)


def _next_item(items):
    try:
        return True, next(items)
    except StopIteration:
        return False, None


@dataclass
class LoggedCall:
    identity: dict[str, object]
    endpoint: str
    model: str
    summary: str
    started: float = field(default_factory=time.time)
    request_text: str = ""
    request_shape: dict[str, int] | None = None
    request_params: dict[str, Any] | None = None
    log_id: str = ""

    async def run(self, handler, *args, sse: str = "openai"):
        from services.protocol.conversation import ImageGenerationError

        self.begin()
        try:
            result = await run_in_threadpool(handler, *args)
        except ImageGenerationError as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""),
                     conversation_id=getattr(exc, "conversation_id", ""), image_route=_image_route_from_exception(exc),
                     image_route_attempts=_image_route_attempts_from_exception(exc))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("调用失败", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""),
                     image_route=_image_route_from_exception(exc),
                     image_route_attempts=_image_route_attempts_from_exception(exc))
            if self.endpoint.startswith("/v1/images"):
                return _image_error_response(exc)
            return _protocol_error_response(exc, 502, sse)

        if isinstance(result, dict):
            self.log("调用完成", result)
            return _strip_internal_response_fields(result)

        sender = anthropic_sse_stream if sse == "anthropic" else sse_json_stream
        try:
            has_first, first = await run_in_threadpool(_next_item, result)
        except ImageGenerationError as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""),
                     conversation_id=getattr(exc, "conversation_id", ""), image_route=_image_route_from_exception(exc),
                     image_route_attempts=_image_route_attempts_from_exception(exc))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("调用失败", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""),
                     image_route=_image_route_from_exception(exc),
                     image_route_attempts=_image_route_attempts_from_exception(exc))
            if self.endpoint.startswith("/v1/images"):
                return _image_error_response(exc)
            return _protocol_error_response(exc, 502, sse)
        if not has_first:
            self.log("流式调用结束")
            return StreamingResponse(sender(()), media_type="text/event-stream")
        return StreamingResponse(sender(self.stream(itertools.chain([first], result))), media_type="text/event-stream")

    def stream(self, items):
        urls: list[str] = []
        account_emails: list[str] = []
        conversation_ids: list[str] = []
        image_routes: list[dict[str, Any]] = []
        image_route_attempts: list[dict[str, Any]] = []
        failed = False
        try:
            for item in items:
                urls.extend(_collect_urls(item))
                account_emails.extend(_collect_account_emails(item))
                conversation_ids.extend(_collect_conversation_ids(item))
                image_routes.extend(_collect_image_routes(item))
                image_route_attempts.extend(_collect_image_route_attempts(item))
                yield _strip_internal_response_fields(item)
        except Exception as exc:
            failed = True
            self.log(
                "流式调用失败",
                status="failed",
                error=str(exc),
                urls=urls,
                account_email=(account_emails[0] if account_emails else getattr(exc, "account_email", "")),
                conversation_id=(conversation_ids[0] if conversation_ids else getattr(exc, "conversation_id", "")),
                image_route=(image_routes[0] if image_routes else _image_route_from_exception(exc)),
                image_route_attempts=(
                    image_route_attempts if image_route_attempts else _image_route_attempts_from_exception(exc)
                ),
            )
            if self.endpoint.startswith("/v1/images") and not hasattr(exc, "to_openai_error"):
                from services.protocol.conversation import ImageGenerationError, public_image_error_message

                raise ImageGenerationError(public_image_error_message(str(exc))) from exc
            raise
        finally:
            if not failed:
                self.log("流式调用结束", urls=urls, account_email=account_emails[0] if account_emails else "",
                         conversation_id=conversation_ids[0] if conversation_ids else "",
                         image_route=image_routes[0] if image_routes else None,
                         image_route_attempts=image_route_attempts)

    def log(self, suffix: str, result: object = None, status: str = "success", error: str = "",
            urls: list[str] | None = None, account_email: str = "", conversation_id: str = "",
            image_route: dict[str, Any] | None = None,
            image_route_attempts: list[dict[str, Any]] | None = None,
            finished: bool = True) -> None:
        detail = {
            "key_id": self.identity.get("id"),
            "key_name": self.identity.get("name"),
            "role": self.identity.get("role"),
            "endpoint": self.endpoint,
            "model": self.model,
            "started_at": local_time_text(self.started),
            "status": status,
        }
        if finished:
            detail["ended_at"] = local_time_text()
            detail["duration_ms"] = int((time.time() - self.started) * 1000)
        else:
            detail["submitted_at"] = local_time_text()
            detail["duration_ms"] = 0
        request_excerpt = _request_excerpt(self.request_text)
        if request_excerpt:
            detail["request_text"] = request_excerpt
        if self.request_shape:
            detail["request_shape"] = self.request_shape
        if self.request_params:
            detail["request_params"] = self.request_params
        if error:
            detail["error"] = error
        email = str(account_email or "").strip()
        if not email:
            emails = _collect_account_emails(result)
            email = emails[0] if emails else ""
        if email:
            detail["account_email"] = email
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            conv_ids = _collect_conversation_ids(result)
            conv_id = conv_ids[0] if conv_ids else ""
        if conv_id:
            detail["conversation_id"] = conv_id
        collected_urls = [*(urls or []), *_collect_urls(result)]
        if collected_urls and not self.endpoint.startswith("/v1/search"):
            detail["urls"] = list(dict.fromkeys(collected_urls))
        if _has_image_log_detail(self.endpoint, image_route, image_route_attempts, result):
            apply_image_log_detail(detail, image_route, image_route_attempts, result)
            detail.update(_collect_image_result_meta(result))
        summary = f"{self.summary}{suffix}"
        if self.log_id:
            if log_service.update(self.log_id, summary, detail):
                return
        self.log_id = log_service.add(LOG_TYPE_CALL, summary, detail)

    def begin(self) -> None:
        if self.log_id:
            return
        self.log("已提交", status="running", finished=False)
