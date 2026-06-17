from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from services.config import config
from services.storage.base import StorageBackend

AuthRole = Literal["admin", "user"]


class AuthQuotaError(RuntimeError):
    def __init__(self, message: str, status_code: int = 429):
        super().__init__(message)
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class AuthService:
    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self._lock = Lock()
        self._items = self._load()
        self._last_used_flush_at: dict[str, datetime] = {}

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _default_name(role: object) -> str:
        return "管理员密钥" if str(role or "").strip().lower() == "admin" else "普通用户"

    @staticmethod
    def _normalize_positive_int(value: object) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _normalize_string_list(cls, value: object) -> list[str]:
        if isinstance(value, str):
            candidates = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            candidates = [cls._clean(item) for item in value]
        else:
            candidates = []
        return list(dict.fromkeys(item for item in candidates if item))

    @classmethod
    def _normalize_limits(cls, value: object) -> dict[str, object]:
        raw = value if isinstance(value, dict) else {}
        return {
            "daily_requests": cls._normalize_positive_int(raw.get("daily_requests")),
            "daily_images": cls._normalize_positive_int(raw.get("daily_images")),
            "allowed_models": cls._normalize_string_list(raw.get("allowed_models")),
            "allowed_endpoints": cls._normalize_string_list(raw.get("allowed_endpoints")),
        }

    @classmethod
    def _normalize_usage(cls, value: object) -> dict[str, object]:
        raw = value if isinstance(value, dict) else {}
        date = cls._clean(raw.get("date")) or _today()
        return {
            "date": date,
            "requests": cls._normalize_positive_int(raw.get("requests")),
            "images": cls._normalize_positive_int(raw.get("images")),
        }

    def _normalize_item(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        role = self._clean(raw.get("role")).lower()
        if role not in {"admin", "user"}:
            return None
        key_hash = self._clean(raw.get("key_hash"))
        if not key_hash:
            return None
        item_id = self._clean(raw.get("id")) or uuid.uuid4().hex[:12]
        name = self._clean(raw.get("name")) or self._default_name(role)
        created_at = self._clean(raw.get("created_at")) or _now_iso()
        last_used_at = self._clean(raw.get("last_used_at")) or None
        return {
            "id": item_id,
            "name": name,
            "role": role,
            "key_hash": key_hash,
            "enabled": bool(raw.get("enabled", True)),
            "created_at": created_at,
            "last_used_at": last_used_at,
            "limits": self._normalize_limits(raw.get("limits")),
            "usage": self._normalize_usage(raw.get("usage")),
        }

    def _load(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_auth_keys()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        return [normalized for item in items if (normalized := self._normalize_item(item)) is not None]

    def _save(self) -> None:
        self.storage.save_auth_keys(self._items)

    def _reload_locked(self) -> None:
        self._items = self._load()

    @staticmethod
    def _public_item(item: dict[str, object]) -> dict[str, object]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "role": item.get("role"),
            "enabled": bool(item.get("enabled", True)),
            "created_at": item.get("created_at"),
            "last_used_at": item.get("last_used_at"),
            "limits": AuthService._normalize_limits(item.get("limits")),
            "usage": AuthService._normalize_usage(item.get("usage")),
        }

    def list_keys(self, role: AuthRole | None = None) -> list[dict[str, object]]:
        with self._lock:
            self._reload_locked()
            items = [item for item in self._items if role is None or item.get("role") == role]
            return [self._public_item(item) for item in items]

    def _has_key_hash_locked(self, key_hash: str, *, exclude_id: str = "") -> bool:
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            stored_hash = self._clean(item.get("key_hash"))
            if stored_hash and hmac.compare_digest(stored_hash, key_hash):
                return True
        return False

    def _build_key_hash_locked(self, raw_key: str, *, exclude_id: str = "") -> str:
        candidate = self._clean(raw_key)
        if not candidate:
            raise ValueError("请输入新的专用密钥")
        admin_key = self._clean(config.auth_key)
        if admin_key and hmac.compare_digest(candidate, admin_key):
            raise ValueError("这个密钥和管理员密钥冲突了，请换一个新的密钥")
        key_hash = _hash_key(candidate)
        if self._has_key_hash_locked(key_hash, exclude_id=exclude_id):
            raise ValueError("这个专用密钥已经存在，请换一个新的密钥")
        return key_hash

    def _has_name_locked(self, name: str, *, role: AuthRole | None = None, exclude_id: str = "") -> bool:
        candidate = self._clean(name)
        if not candidate:
            return False
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            if role is not None and item.get("role") != role:
                continue
            if self._clean(item.get("name")) == candidate:
                return True
        return False

    def _build_default_name_locked(self, role: AuthRole, *, exclude_id: str = "") -> str:
        base_name = self._default_name(role)
        if not self._has_name_locked(base_name, role=role, exclude_id=exclude_id):
            return base_name
        suffix = 2
        while True:
            candidate = f"{base_name} {suffix}"
            if not self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
                return candidate
            suffix += 1

    def _build_name_locked(self, name: str, *, role: AuthRole, exclude_id: str = "") -> str:
        candidate = self._clean(name)
        if not candidate:
            return self._build_default_name_locked(role, exclude_id=exclude_id)
        if self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
            raise ValueError("这个名称已经在使用中了，换一个更容易区分的名称吧")
        return candidate

    def create_key(self, *, role: AuthRole, name: str = "") -> tuple[dict[str, object], str]:
        with self._lock:
            self._reload_locked()
            normalized_name = self._build_name_locked(name, role=role)
            while True:
                raw_key = f"sk-{secrets.token_urlsafe(24)}"
                try:
                    key_hash = self._build_key_hash_locked(raw_key)
                    break
                except ValueError:
                    continue
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "role": role,
                "key_hash": key_hash,
                "enabled": True,
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            self._items.append(item)
            self._save()
            return self._public_item(item), raw_key

    def update_key(
        self,
        key_id: str,
        updates: dict[str, object],
        *,
        role: AuthRole | None = None,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                next_item = dict(item)
                next_role = "admin" if str(next_item.get("role") or "").strip().lower() == "admin" else "user"
                if "name" in updates and updates.get("name") is not None:
                    next_item["name"] = self._build_name_locked(
                        str(updates.get("name") or ""),
                        role=next_role,
                        exclude_id=normalized_id,
                    )
                if "enabled" in updates and updates.get("enabled") is not None:
                    next_item["enabled"] = bool(updates.get("enabled"))
                if "key" in updates and updates.get("key") is not None:
                    next_item["key_hash"] = self._build_key_hash_locked(str(updates.get("key") or ""), exclude_id=normalized_id)
                if "limits" in updates and updates.get("limits") is not None:
                    next_item["limits"] = self._normalize_limits(updates.get("limits"))
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        return None

    def delete_key(self, key_id: str, *, role: AuthRole | None = None) -> bool:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return False
        with self._lock:
            self._reload_locked()
            before = len(self._items)
            self._items = [
                item
                for item in self._items
                if not (item.get("id") == normalized_id and (role is None or item.get("role") == role))
            ]
            if len(self._items) == before:
                return False
            self._save()
            return True

    def authenticate(self, raw_key: str) -> dict[str, object] | None:
        candidate = self._clean(raw_key)
        if not candidate:
            return None
        candidate_hash = _hash_key(candidate)
        with self._lock:
            for index, item in enumerate(self._items):
                if not bool(item.get("enabled", True)):
                    continue
                stored_hash = self._clean(item.get("key_hash"))
                if not stored_hash or not hmac.compare_digest(stored_hash, candidate_hash):
                    continue
                next_item = dict(item)
                now = datetime.now(timezone.utc)
                next_item["last_used_at"] = now.isoformat()
                self._items[index] = next_item
                item_id = self._clean(next_item.get("id"))
                last_flush_at = self._last_used_flush_at.get(item_id)
                if last_flush_at is None or (now - last_flush_at).total_seconds() >= 60:
                    try:
                        self._save()
                        self._last_used_flush_at[item_id] = now
                    except Exception:
                        pass
                return self._public_item(next_item)
        return None

    def consume_quota(
        self,
        identity: dict[str, object],
        *,
        endpoint: str,
        model: str = "",
        request_units: int = 1,
        image_units: int = 0,
    ) -> dict[str, object] | None:
        if identity.get("role") != "user":
            return None
        item_id = self._clean(identity.get("id"))
        if not item_id:
            return None
        endpoint = self._clean(endpoint)
        model = self._clean(model)
        request_units = max(0, int(request_units or 0))
        image_units = max(0, int(image_units or 0))
        today = _today()
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != item_id:
                    continue
                if not bool(item.get("enabled", True)):
                    raise AuthQuotaError("用户密钥已禁用", status_code=401)
                limits = self._normalize_limits(item.get("limits"))
                allowed_endpoints = set(limits["allowed_endpoints"])
                allowed_models = set(limits["allowed_models"])
                if allowed_endpoints and endpoint not in allowed_endpoints:
                    raise AuthQuotaError("这个用户密钥没有访问该接口的权限", status_code=403)
                if allowed_models and model and model not in allowed_models:
                    raise AuthQuotaError("这个用户密钥没有使用该模型的权限", status_code=403)

                usage = self._normalize_usage(item.get("usage"))
                if usage.get("date") != today:
                    usage = {"date": today, "requests": 0, "images": 0}
                daily_requests = int(limits.get("daily_requests") or 0)
                daily_images = int(limits.get("daily_images") or 0)
                next_requests = int(usage.get("requests") or 0) + request_units
                next_images = int(usage.get("images") or 0) + image_units
                if daily_requests > 0 and next_requests > daily_requests:
                    raise AuthQuotaError("这个用户密钥今日调用次数已用完", status_code=429)
                if daily_images > 0 and next_images > daily_images:
                    raise AuthQuotaError("这个用户密钥今日图片额度已用完", status_code=429)

                next_item = dict(item)
                next_item["usage"] = {
                    "date": today,
                    "requests": next_requests,
                    "images": next_images,
                }
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        raise AuthQuotaError("用户密钥不存在或已被删除", status_code=401)


auth_service = AuthService(config.get_storage_backend())
