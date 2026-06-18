from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PREVIOUS_AUTH_KEY = os.environ.get("CHATGPT2API_AUTH_KEY")
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register_service import RegisterService, _normalize
from services.register import mail_provider


class RegisterServiceTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        if _PREVIOUS_AUTH_KEY is None:
            os.environ.pop("CHATGPT2API_AUTH_KEY", None)
        else:
            os.environ["CHATGPT2API_AUTH_KEY"] = _PREVIOUS_AUTH_KEY

    def test_normalize_adds_low_success_pause_defaults(self) -> None:
        cfg = _normalize({})

        self.assertTrue(cfg["low_success_pause_enabled"])
        self.assertEqual(cfg["low_success_min_done"], 5)
        self.assertEqual(cfg["low_success_threshold_percent"], 20)
        self.assertEqual(cfg["low_success_pause_seconds"], 60)
        self.assertTrue(cfg["flaresolverr"]["enabled"])
        self.assertTrue(cfg["flaresolverr"]["preload"])

    def test_normalize_drops_legacy_warp_flag_and_keeps_flaresolverr_defaults(self) -> None:
        cfg = _normalize({"use_warp_proxy": True, "flaresolverr": {"url": "http://flaresolverr:8191"}})

        self.assertNotIn("use_warp_proxy", cfg)
        self.assertTrue(cfg["flaresolverr"]["enabled"])
        self.assertEqual(cfg["flaresolverr"]["url"], "http://flaresolverr:8191")

    def test_low_success_pause_is_rate_limited_by_done_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RegisterService(Path(tmp_dir) / "register.json")
            cfg = {
                "low_success_pause_enabled": True,
                "low_success_min_done": 3,
                "low_success_threshold_percent": 50,
                "low_success_pause_seconds": 10,
            }

            with mock.patch("services.register_service.time.time", return_value=100.0):
                self.assertTrue(service._should_pause_for_low_success(cfg, done=3, success=0, fail=3))
                self.assertTrue(service._should_pause_for_low_success(cfg, done=3, success=0, fail=3))

            with mock.patch("services.register_service.time.time", return_value=111.0):
                self.assertFalse(service._should_pause_for_low_success(cfg, done=3, success=0, fail=3))

            with mock.patch("services.register_service.time.time", return_value=112.0):
                self.assertTrue(service._should_pause_for_low_success(cfg, done=4, success=0, fail=4))

    def test_outlook_pool_is_merged_and_redacted_from_public_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / "outlook_token_used.json"
            service = RegisterService(Path(tmp_dir) / "register.json")
            provider = {
                "type": "outlook_token",
                "enable": True,
                "mode": "graph",
                "mailboxes": "user1@hotmail.com----pass1----client1----refresh-secret-1",
            }

            with mock.patch.object(mail_provider, "OUTLOOK_TOKEN_USED_FILE", state_file):
                public_config = service.update({"mail": {"providers": [provider]}})

                self.assertEqual(public_config["mail"]["providers"][0]["mailboxes"], "")
                self.assertEqual(public_config["mail"]["providers"][0]["mailboxes_count"], 1)
                self.assertNotIn("refresh-secret-1", json.dumps(public_config))

                raw_saved = json.loads((Path(tmp_dir) / "register.json").read_text(encoding="utf-8"))
                self.assertIn("refresh-secret-1", raw_saved["mail"]["providers"][0]["mailboxes"])

                public_config = service.update(
                    {
                        "mail": {
                            "providers": [
                                {
                                    **provider,
                                    "mailboxes": "user1@hotmail.com----pass2----client2----refresh-secret-2\n"
                                    "user2@hotmail.com----pass3----client3----refresh-secret-3",
                                }
                            ]
                        }
                    }
                )

                raw_saved = json.loads((Path(tmp_dir) / "register.json").read_text(encoding="utf-8"))
                saved_pool = raw_saved["mail"]["providers"][0]["mailboxes"]
                self.assertIn("refresh-secret-2", saved_pool)
                self.assertIn("refresh-secret-3", saved_pool)
                self.assertNotIn("refresh-secret-1", saved_pool)
                self.assertEqual(public_config["mail"]["providers"][0]["mailboxes_count"], 2)

    def test_outlook_provider_marks_state_and_reset_failed_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / "outlook_token_used.json"
            mail_config = {
                "request_timeout": 1,
                "wait_timeout": 1,
                "wait_interval": 0.2,
                "providers": [
                    {
                        "type": "outlook_token",
                        "enable": True,
                        "mailboxes": "user1@hotmail.com----pass1----client1----refresh1\n"
                        "user2@hotmail.com----pass2----client2----refresh2",
                    }
                ],
            }

            with mock.patch.object(mail_provider, "OUTLOOK_TOKEN_USED_FILE", state_file):
                mailbox = mail_provider.create_mailbox(mail_config)
                self.assertEqual(mailbox["address"], "user1@hotmail.com")

                state = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(state["user1@hotmail.com"]["state"], "in_use")

                mail_provider.mark_mailbox_result(mailbox, success=False, error=RuntimeError("boom"))
                state = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(state["user1@hotmail.com"]["state"], "failed")

                mailbox2 = mail_provider.create_mailbox(mail_config)
                self.assertEqual(mailbox2["address"], "user2@hotmail.com")
                mail_provider.mark_mailbox_result(mailbox2, success=True)

                cleared = mail_provider.reset_outlook_token_pool_state("failed")
                state = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(cleared, 1)
                self.assertNotIn("user1@hotmail.com", state)
                self.assertEqual(state["user2@hotmail.com"]["state"], "used")


if __name__ == "__main__":
    unittest.main()
