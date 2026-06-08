from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size: int = -1) -> bytes:
        return b'{"code":200,"message":"success"}'


class NotificationServiceTests(unittest.TestCase):
    def _store(self):
        from services.config import ConfigStore

        tmp_dir = tempfile.TemporaryDirectory()
        config_file = Path(tmp_dir.name) / "config.json"
        config_file.write_text(json.dumps({
            "auth-key": "test-auth",
            "notifications": {
                "bark": {
                    "enabled": True,
                    "server_url": "https://bark.example.com",
                    "device_key": "test-device-key",
                    "title_prefix": "unit",
                    "group": "unit",
                    "min_interval_seconds": 0,
                }
            },
        }), encoding="utf-8")
        return tmp_dir, ConfigStore(config_file)

    def test_bark_test_posts_push_payload(self) -> None:
        from services import notification_service as notification_module

        tmp_dir, store = self._store()
        captured: dict[str, object] = {}

        def fake_urlopen(request: urllib.request.Request, timeout: float = 0):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(bytes(request.data or b"{}").decode("utf-8"))
            return FakeResponse()

        try:
            with patch.object(notification_module, "config", store), patch("urllib.request.urlopen", fake_urlopen):
                result = notification_module.NotificationService().test_bark("hello")
        finally:
            tmp_dir.cleanup()

        self.assertTrue(result["ok"])
        self.assertEqual(captured["url"], "https://bark.example.com/push")
        payload = captured["payload"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["device_key"], "test-device-key")
        self.assertEqual(payload["title"], "unit - Bark 测试")
        self.assertEqual(payload["body"], "hello")

    def test_register_log_filters_noisy_steps(self) -> None:
        from services import notification_service as notification_module

        tmp_dir, store = self._store()
        service = notification_module.NotificationService()
        sent: list[tuple[str, str]] = []

        def fake_send(title: str, body: str, **_kwargs):
            sent.append((title, body))

        try:
            with patch.object(notification_module, "config", store), patch.object(service, "_send_async", fake_send):
                service.notify_register_log("[任务1] 开始提交注册密码", "info")
                service.notify_register_log("任务1 注册失败，本次耗时0.4s，原因: error", "red")
                service.notify_register_log("注册任务结束，成功0，失败1", "yellow")
                service.notify_register_log("注册任务结束，成功1，失败0", "yellow")
        finally:
            tmp_dir.cleanup()

        self.assertEqual([title for title, _body in sent], ["注册机异常", "注册机异常", "注册机通知"])

    def test_failed_log_triggers_notification(self) -> None:
        from services.log_service import LOG_TYPE_CALL, LogService

        with tempfile.TemporaryDirectory() as tmp_dir:
            log_service = LogService(Path(tmp_dir) / "logs.jsonl")
            captured: dict[str, object] = {}

            class FakeNotification:
                def notify_failed_log(self, log_id: str, summary: str, detail: dict):
                    captured["log_id"] = log_id
                    captured["summary"] = summary
                    captured["detail"] = detail

            with patch.dict("sys.modules", {"services.notification_service": type("M", (), {"notification_service": FakeNotification()})}):
                log_id = log_service.add(LOG_TYPE_CALL, "调用失败", {"status": "failed", "error": "boom"})

            self.assertEqual(captured["log_id"], log_id)
            self.assertEqual(captured["summary"], "调用失败")
            self.assertEqual(captured["detail"]["error"], "boom")


if __name__ == "__main__":
    unittest.main()
