import base64
import binascii
import json
import logging
import os
import re
import sys
from typing import Any


class Logger:
    _DATA_URL_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")
    _JSON_B64_RE = re.compile(r'("b64_json"\s*:\s*")([A-Za-z0-9+/=]+)(")')
    _RESET = "\033[0m"
    _DIM = "\033[2m"
    _LEVEL_COLORS = {
        "debug": "\033[36m",
        "info": "\033[32m",
        "warning": "\033[33m",
        "error": "\033[31m",
    }
    _FEATURE_COLORS = {
        "账号": "\033[35m",
        "生图": "\033[34m",
        "文件": "\033[36m",
        "搜索": "\033[32m",
        "审核": "\033[33m",
        "存储": "\033[36m",
        "系统": "\033[37m",
    }
    _EVENT_FEATURES = {
        "backend_user_info_account_payload": "账号",
        "backend_conversation_init_quota_payload": "账号",
        "backend_user_info_result": "账号",
        "image_auto_cleanup": "存储",
        "image_auto_cleanup_done": "存储",
        "image_poll_check": "生图",
        "image_poll_hit": "生图",
        "image_poll_hit_no_settle": "生图",
        "image_poll_hit_pending_settle": "生图",
        "image_poll_hit_settle_disabled": "生图",
        "image_poll_wait": "生图",
        "image_poll_timeout": "生图",
        "list_conversations_failed": "系统",
    }

    def __init__(self, name: str = "chatgpt2api") -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self._color_enabled = self._should_enable_color()

    def _should_enable_color(self) -> bool:
        if os.getenv("NO_COLOR"):
            return False
        if os.getenv("FORCE_COLOR"):
            return True
        return sys.stderr.isatty()

    def _enabled(self, level: str) -> bool:
        try:
            from services.config import config
            levels = set(config.log_levels)
        except Exception:
            levels = set()
        return level in (levels or {"info", "warning", "error"})

    def _mask_string(self, value: str, keep: int = 10) -> str:
        if len(value) <= keep:
            return value
        return value[:keep] + "..."

    def _mask_base64(self, value: str) -> str:
        if value.startswith("data:") and ";base64," in value:
            header, _, data = value.partition(",")
            return f"{header},{self._mask_string(data, 24)} (base64 len={len(data)})"
        return f"{self._mask_string(value, 24)} (base64 len={len(value)})"

    def _is_base64_string(self, value: str) -> bool:
        if len(value) < 64 or len(value) % 4 != 0:
            return False
        if not any(char in value for char in "+/="):
            return False
        try:
            base64.b64decode(value, validate=True)
            return True
        except (binascii.Error, ValueError):
            return False

    def _sanitize_string(self, value: str) -> str:
        stripped = value.strip()
        if stripped.startswith("data:") and ";base64," in stripped:
            return self._mask_base64(stripped)
        if self._is_base64_string(stripped):
            return self._mask_base64(stripped)
        sanitized = self._DATA_URL_RE.sub(lambda match: self._mask_base64(match.group(0)), value)
        sanitized = self._JSON_B64_RE.sub(
            lambda match: f'{match.group(1)}{self._mask_base64(match.group(2))}{match.group(3)}',
            sanitized,
        )
        if sanitized != value:
            return sanitized
        return value

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                lowered_key = key.lower()
                if isinstance(item, str) and ("token" in lowered_key or lowered_key == "dx"):
                    sanitized[key] = self._mask_string(item)
                elif isinstance(item, str) and ("base64" in lowered_key or lowered_key == "b64_json"):
                    sanitized[key] = self._mask_base64(item)
                else:
                    sanitized[key] = self._sanitize(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._sanitize(item) for item in value)
        if isinstance(value, str):
            return self._sanitize_string(value)
        return value

    def _message(self, value: Any) -> str:
        sanitized = self._sanitize(value)
        if isinstance(sanitized, str):
            return sanitized
        return json.dumps(sanitized, ensure_ascii=False, default=str)

    def _color(self, value: str, color: str) -> str:
        if not self._color_enabled:
            return value
        return f"{color}{value}{self._RESET}"

    def _feature_for_event(self, event: str) -> str:
        if event in self._EVENT_FEATURES:
            return self._EVENT_FEATURES[event]
        if event.startswith(("backend_", "account_", "oauth_", "relogin_")):
            return "账号"
        if event.startswith(("image_", "codex_", "conversation_")):
            return "生图"
        if event.startswith(("editable_", "file_")):
            return "文件"
        if event.startswith(("content_filter", "ai_review")):
            return "审核"
        if "storage" in event or "backup" in event:
            return "存储"
        return "系统"

    def _format(self, level: str, value: Any) -> str:
        sanitized = self._sanitize(value)
        event = sanitized.get("event") if isinstance(sanitized, dict) else ""
        event = str(event or "").strip()
        feature = self._feature_for_event(event) if event else "系统"
        level_label = self._color(f"[{level.upper():7}]", self._LEVEL_COLORS.get(level, ""))
        feature_color = self._FEATURE_COLORS.get(feature, "")
        feature_label = self._color(f"[{feature}]", feature_color)
        event_label = self._color(f"[{event}]", self._DIM) if event else ""
        message = self._message(sanitized)
        return " ".join(part for part in (level_label, feature_label, event_label, message) if part)

    def debug(self, message: Any) -> None:
        if self._enabled("debug"):
            self._logger.debug(self._format("debug", message))

    def info(self, message: Any) -> None:
        if self._enabled("info"):
            self._logger.info(self._format("info", message))

    def warning(self, message: Any) -> None:
        if self._enabled("warning"):
            self._logger.warning(self._format("warning", message))

    def error(self, message: Any) -> None:
        if self._enabled("error"):
            self._logger.error(self._format("error", message))


logger = Logger()
