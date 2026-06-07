from __future__ import annotations

import threading
import time
from threading import Event, Thread

from services.account_service import account_service
from services.config import config
from services.log_service import LOG_TYPE_ACCOUNT, log_service
from services.register_service import register_service


REASON_TEXT = {
    "watcher_started": "自动补池守护线程已启动",
    "checking": "正在检查号池",
    "disabled": "自动补池未启用",
    "threshold_not_reached": "号池充足，未触发补池",
    "register_running": "注册机已在运行",
    "refill_started": "已启动注册机补池",
    "already_checking": "上一次补池检查仍在运行",
    "error": "补池检查异常",
}


def _is_available_account(account: dict) -> bool:
    return account_service._is_image_account_available(account)


def _refresh_candidate_tokens(accounts: list[dict]) -> list[str]:
    return [
        str(account.get("access_token") or "").strip()
        for account in accounts
        if str(account.get("status") or "") not in {"禁用", "异常"}
           and str(account.get("access_token") or "").strip()
    ]


class AccountRefillService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_run_at = 0.0

    def _stats(self, accounts: list[dict] | None = None) -> dict[str, object]:
        accounts = accounts if accounts is not None else account_service.list_accounts()
        total = len(accounts)
        available = sum(1 for account in accounts if _is_available_account(account))
        available_percent = round((available / total * 100.0) if total else 0.0, 2)
        threshold = config.auto_refill_threshold_percent
        target = config.auto_refill_target_available
        return {
            "total": total,
            "available": available,
            "available_percent": available_percent,
            "threshold_percent": threshold,
            "target_available": target,
        }

    def _refresh_pool(self) -> dict[str, object]:
        accounts = account_service.list_accounts()
        tokens = _refresh_candidate_tokens(accounts)
        if not tokens:
            return {
                "attempted": 0,
                "refreshed": 0,
                "errors": 0,
                "relogined": 0,
            }
        result = account_service.refresh_accounts(tokens)
        return {
            "attempted": len(tokens),
            "refreshed": int(result.get("refreshed") or 0),
            "errors": len(result.get("errors") or []),
            "relogined": int(result.get("relogined") or 0),
        }

    def _detail(self, reason: str, source: str, stats: dict[str, object] | None = None, **extra: object) -> dict[str, object]:
        return {
            "event": "auto_refill_check",
            "source": source,
            "enabled": config.auto_refill_enabled,
            "reason": reason,
            "reason_text": REASON_TEXT.get(reason, reason),
            "interval_minutes": config.auto_refill_interval_minutes,
            **(stats or {}),
            **extra,
        }

    def _log(self, summary: str, detail: dict[str, object]) -> None:
        log_service.add(LOG_TYPE_ACCOUNT, summary, detail)

    def run_once(self, source: str = "auto") -> dict[str, object]:
        if not self._lock.acquire(blocking=False):
            detail = self._detail("already_checking", source)
            self._log("自动补池跳过：上次检查未结束", detail)
            return {"started": False, **detail}
        try:
            stats = self._stats()
            if not config.auto_refill_enabled:
                detail = self._detail("disabled", source, stats)
                return {"started": False, **detail}

            refresh = self._refresh_pool()
            stats = self._stats()
            check_detail = self._detail("checking", source, stats, refresh=refresh)
            self._log("自动补池检查号池", check_detail)

            total = int(stats["total"])
            available = int(stats["available"])
            available_percent = float(stats["available_percent"])
            threshold = int(stats["threshold_percent"])
            target = int(stats["target_available"])
            below_target = available < target
            below_ratio = total > 0 and available_percent < threshold
            if not below_target and not below_ratio:
                detail = self._detail(
                    "threshold_not_reached",
                    source,
                    stats,
                    refresh=refresh,
                    below_target=below_target,
                    below_ratio=below_ratio,
                )
                self._log("自动补池未触发：号池充足", detail)
                return {"started": False, **detail}

            register_state = register_service.get()
            if register_state.get("enabled"):
                detail = self._detail(
                    "register_running",
                    source,
                    stats,
                    refresh=refresh,
                    below_target=below_target,
                    below_ratio=below_ratio,
                    register_mode=register_state.get("mode"),
                    register_target_available=register_state.get("target_available"),
                )
                self._log("自动补池跳过：注册机已在运行", detail)
                return {"started": False, **detail}

            register_service.update({
                "mode": "available",
                "target_available": target,
            })
            register_service.start()
            detail = self._detail(
                "refill_started",
                source,
                stats,
                refresh=refresh,
                below_target=below_target,
                below_ratio=below_ratio,
                register_mode="available",
            )
            self._log("自动补池已启动注册机", detail)
            return {"started": True, **detail}
        except Exception as exc:
            detail = self._detail("error", source, error=str(exc))
            self._log("自动补池检查失败", detail)
            return {"started": False, **detail}
        finally:
            self._last_run_at = time.time()
            self._lock.release()

    def start(self, stop_event: Event) -> Thread:
        def worker() -> None:
            self._log(
                "自动补池守护线程启动",
                self._detail(
                    "watcher_started",
                    "startup",
                    enabled=config.auto_refill_enabled,
                    next_check_seconds=10 if not config.auto_refill_enabled else max(60, config.auto_refill_interval_minutes * 60),
                ),
            )
            while not stop_event.is_set():
                if config.auto_refill_enabled:
                    self.run_once("watcher")
                    wait_seconds = max(60, config.auto_refill_interval_minutes * 60)
                else:
                    wait_seconds = 10
                stop_event.wait(wait_seconds)

        thread = Thread(target=worker, name="account-refill-watcher", daemon=True)
        thread.start()
        return thread


account_refill_service = AccountRefillService()
