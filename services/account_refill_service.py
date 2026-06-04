from __future__ import annotations

import threading
import time
from threading import Event, Thread

from services.account_service import account_service
from services.config import config
from services.log_service import LOG_TYPE_ACCOUNT, log_service
from services.register_service import register_service


def _is_available_account(account: dict) -> bool:
    return str(account.get("status") or "") == "正常"


class AccountRefillService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_run_at = 0.0

    def _stats(self) -> dict[str, object]:
        accounts = account_service.list_accounts()
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

    def run_once(self, source: str = "auto") -> dict[str, object]:
        if not self._lock.acquire(blocking=False):
            return {"started": False, "reason": "already_checking"}
        try:
            stats = self._stats()
            result: dict[str, object] = {
                "event": "auto_refill_check",
                "source": source,
                "enabled": config.auto_refill_enabled,
                **stats,
            }
            if not config.auto_refill_enabled:
                return {"started": False, "reason": "disabled", **result}

            total = int(stats["total"])
            available = int(stats["available"])
            available_percent = float(stats["available_percent"])
            threshold = int(stats["threshold_percent"])
            target = int(stats["target_available"])
            below_target = available < target
            below_ratio = total > 0 and available_percent < threshold
            if not below_target and not below_ratio:
                return {"started": False, "reason": "threshold_not_reached", **result}

            register_state = register_service.get()
            if register_state.get("enabled"):
                log_service.add(
                    LOG_TYPE_ACCOUNT,
                    "自动补池跳过：注册机已在运行",
                    {**result, "reason": "register_running"},
                )
                return {"started": False, "reason": "register_running", **result}

            register_service.update({
                "mode": "available",
                "target_available": target,
            })
            register_service.start()
            started_result = {
                "started": True,
                "reason": "refill_started",
                "register_mode": "available",
                **result,
            }
            log_service.add(LOG_TYPE_ACCOUNT, "自动补池已启动注册机", started_result)
            return started_result
        except Exception as exc:
            error_result = {
                "started": False,
                "reason": "error",
                "error": str(exc),
                "source": source,
            }
            log_service.add(LOG_TYPE_ACCOUNT, "自动补池检查失败", error_result)
            return error_result
        finally:
            self._last_run_at = time.time()
            self._lock.release()

    def start(self, stop_event: Event) -> Thread:
        def worker() -> None:
            while not stop_event.is_set():
                if config.auto_refill_enabled:
                    self.run_once("watcher")
                stop_event.wait(max(60, config.auto_refill_interval_minutes * 60))

        thread = Thread(target=worker, name="account-refill-watcher", daemon=True)
        thread.start()
        return thread


account_refill_service = AccountRefillService()
