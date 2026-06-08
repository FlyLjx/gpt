from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from threading import Lock, Thread
from typing import Any

from services.config import config
from utils.log import logger


REGISTER_ERROR_KEYWORDS = ("失败", "异常", "错误", "error", "failed", "invalid", "timeout", "超时")
REGISTER_INFO_KEYWORDS = ("注册任务启动", "注册任务结束", "已请求停止注册任务")
AUTO_REFILL_NOTIFY_REASONS = {"refill_started", "error", "register_running"}
REGISTER_END_RE = re.compile(r"注册任务结束，成功(?P<success>\d+)，失败(?P<fail>\d+)")


def _clean(value: object) -> str:
    return str(value or "").strip()


def _truncate(value: object, limit: int = 1200) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def _status_code_from_response(response: object) -> int:
    return int(getattr(response, "status", 0) or getattr(response, "code", 0) or 0)


def _is_register_error(content: str, level: str) -> bool:
    if level == "red":
        return True
    end_match = REGISTER_END_RE.search(content)
    if end_match:
        return int(end_match.group("fail") or 0) > 0
    return any(keyword.lower() in content.lower() for keyword in REGISTER_ERROR_KEYWORDS)


class NotificationService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._last_sent_at: dict[str, float] = {}

    def _settings(self) -> dict[str, object]:
        return config.get_notification_settings()

    def _bark_settings(self) -> dict[str, object]:
        settings = self._settings()
        bark = settings.get("bark") if isinstance(settings, dict) else {}
        return bark if isinstance(bark, dict) else {}

    def _bark_enabled(self, settings: dict[str, object] | None = None) -> bool:
        bark = settings if settings is not None else self._bark_settings()
        return bool(bark.get("enabled")) and bool(_clean(bark.get("device_key")))

    def _title(self, title: str, settings: dict[str, object]) -> str:
        prefix = _clean(settings.get("title_prefix"))
        title = _clean(title)
        return f"{prefix} - {title}" if prefix else title

    def _should_send(self, key: str, settings: dict[str, object]) -> bool:
        cooldown = int(settings.get("min_interval_seconds") or 0)
        if cooldown <= 0:
            return True
        now = time.time()
        with self._lock:
            last = self._last_sent_at.get(key)
            if last is not None and now - last < cooldown:
                return False
            self._last_sent_at[key] = now
        return True

    def _send_bark(self, title: str, body: str, *, group: str = "", level: str = "", url: str = "") -> dict[str, object]:
        settings = self._bark_settings()
        if not self._bark_enabled(settings):
            return {"ok": False, "status": 0, "error": "Bark push is disabled or missing device_key"}

        server_url = _clean(settings.get("server_url")).rstrip("/")
        device_key = _clean(settings.get("device_key"))
        endpoint = f"{server_url}/push"
        payload = {
            "device_key": device_key,
            "title": self._title(title, settings),
            "body": _truncate(body, 3500),
            "group": _clean(group or settings.get("group")),
            "level": _clean(level or settings.get("level")) or "active",
        }
        target_url = _clean(url)
        if target_url:
            payload["url"] = target_url

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"content-type": "application/json; charset=utf-8", "user-agent": "chatgpt2api-bark/1.0"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=float(settings.get("timeout_secs") or 10)) as response:
                raw = response.read(4096).decode("utf-8", errors="replace")
                status = _status_code_from_response(response)
                ok = 200 <= status < 300
                try:
                    data = json.loads(raw) if raw else {}
                except Exception:
                    data = {}
                if isinstance(data, dict) and int(data.get("code") or 200) >= 400:
                    ok = False
                return {
                    "ok": ok,
                    "status": status,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "error": "" if ok else _truncate(data.get("message") if isinstance(data, dict) else raw, 300),
                }
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096).decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            return {
                "ok": False,
                "status": int(exc.code or 0),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": _truncate(raw or str(exc), 300),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": 0,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc) or exc.__class__.__name__,
            }

    def _send_async(
        self,
        title: str,
        body: str,
        *,
        key: str,
        group: str = "",
        level: str = "",
        url: str = "",
    ) -> None:
        settings = self._bark_settings()
        if not self._bark_enabled(settings) or not self._should_send(key, settings):
            return

        def worker() -> None:
            result = self._send_bark(title, body, group=group, level=level, url=url)
            if not result.get("ok"):
                logger.warning({"event": "bark_push_failed", "status": result.get("status"), "error": result.get("error")})

        Thread(target=worker, name="bark-notification", daemon=True).start()

    def test_bark(self, body: str = "这是一条 chatgpt2api Bark 测试通知") -> dict[str, object]:
        return self._send_bark("Bark 测试", body, group="chatgpt2api", level="active")

    def notify_failed_log(self, log_id: str, summary: str, detail: dict[str, Any]) -> None:
        settings = self._bark_settings()
        if not self._bark_enabled(settings) or not bool(settings.get("notify_failed_calls", True)):
            return
        if _clean(detail.get("status")) != "failed":
            return
        body = "\n".join(
            part for part in [
                f"摘要：{_clean(summary)}",
                f"接口：{_clean(detail.get('endpoint'))}",
                f"模型：{_clean(detail.get('model'))}",
                f"分辨率：{_clean(detail.get('resolution'))}",
                f"账号：{_clean(detail.get('account_email'))}",
                f"账号类型：{_clean(detail.get('account_type'))}",
                f"最终渠道：{_clean(detail.get('image_channel_label') or detail.get('image_route_label'))}",
                f"耗时：{detail.get('duration_ms')} ms" if detail.get("duration_ms") is not None else "",
                f"错误：{_truncate(detail.get('error'), 900)}",
            ] if part and not part.endswith("：")
        )
        self._send_async("异常调用日志", body, key=f"call:{log_id}:failed", group="chatgpt2api-call", level="timeSensitive")

    def notify_register_log(self, text: str, level: str = "") -> None:
        settings = self._bark_settings()
        if not self._bark_enabled(settings) or not bool(settings.get("notify_register", True)):
            return
        content = _clean(text)
        normalized_level = _clean(level).lower()
        is_error = _is_register_error(content, normalized_level)
        is_key_info = any(keyword in content for keyword in REGISTER_INFO_KEYWORDS)
        if bool(settings.get("notify_register_errors_only")) and not is_error:
            return
        if not is_error and not is_key_info:
            return
        title = "注册机异常" if is_error else "注册机通知"
        push_level = "timeSensitive" if is_error else "active"
        self._send_async(title, content, key=f"register:{normalized_level}:{content}", group="chatgpt2api-register", level=push_level)

    def notify_auto_refill(self, summary: str, detail: dict[str, object]) -> None:
        settings = self._bark_settings()
        if not self._bark_enabled(settings) or not bool(settings.get("notify_auto_refill", True)):
            return
        reason = _clean(detail.get("reason"))
        if reason not in AUTO_REFILL_NOTIFY_REASONS:
            return
        is_error = reason == "error"
        body = "\n".join(
            part for part in [
                f"摘要：{_clean(summary)}",
                f"原因：{_clean(detail.get('reason_text') or reason)}",
                f"来源：{_clean(detail.get('source'))}",
                f"号池：{detail.get('available')}/{detail.get('total')}" if detail.get("total") is not None else "",
                f"阈值：{detail.get('threshold_percent')}%" if detail.get("threshold_percent") is not None else "",
                f"目标正常号：{detail.get('target_available')}" if detail.get("target_available") is not None else "",
                f"错误：{_truncate(detail.get('error'), 900)}" if detail.get("error") else "",
            ] if part
        )
        self._send_async(
            "自动补池异常" if is_error else "自动补池通知",
            body,
            key=f"auto-refill:{reason}:{_clean(detail.get('source'))}",
            group="chatgpt2api-register",
            level="timeSensitive" if is_error else "active",
        )


notification_service = NotificationService()
