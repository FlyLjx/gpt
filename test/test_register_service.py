from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register_service import RegisterService, _normalize


class RegisterServiceTests(unittest.TestCase):
    def test_normalize_adds_low_success_pause_defaults(self) -> None:
        cfg = _normalize({})

        self.assertTrue(cfg["low_success_pause_enabled"])
        self.assertEqual(cfg["low_success_min_done"], 5)
        self.assertEqual(cfg["low_success_threshold_percent"], 20)
        self.assertEqual(cfg["low_success_pause_seconds"], 60)

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


if __name__ == "__main__":
    unittest.main()
