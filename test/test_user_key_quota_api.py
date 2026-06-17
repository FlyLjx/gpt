from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "chatgpt2api")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.ai as ai_module
import api.support as support_module
from services.auth_service import AuthService
from services.storage.json_storage import JSONStorageBackend


class UserKeyQuotaApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.auth_service = AuthService(
            JSONStorageBackend(Path(self.tmp_dir.name) / "accounts.json", Path(self.tmp_dir.name) / "auth_keys.json")
        )
        self.item, self.raw_key = self.auth_service.create_key(role="user", name="quota-user")
        self.support_patcher = mock.patch.object(support_module, "auth_service", self.auth_service)
        self.handle_patcher = mock.patch.object(
            ai_module.openai_v1_image_generations,
            "handle",
            lambda payload: {"created": 1, "data": [{"url": "http://testserver/images/out.png"}]},
        )
        self.support_patcher.start()
        self.handle_patcher.start()
        self.addCleanup(self.support_patcher.stop)
        self.addCleanup(self.handle_patcher.stop)
        app = FastAPI()
        app.include_router(ai_module.create_router())
        self.client = TestClient(app)

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.raw_key}"}

    def test_user_key_image_quota_blocks_api_request(self) -> None:
        self.auth_service.update_key(self.item["id"], {"limits": {"daily_images": 1}}, role="user")

        first = self.client.post(
            "/v1/images/generations",
            headers=self.auth_headers(),
            json={"prompt": "cat", "model": "gpt-image-2", "n": 1},
        )
        second = self.client.post(
            "/v1/images/generations",
            headers=self.auth_headers(),
            json={"prompt": "cat", "model": "gpt-image-2", "n": 1},
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 429, second.text)
        self.assertIn("今日图片额度已用完", second.text)

    def test_user_key_model_allow_list_blocks_api_request(self) -> None:
        self.auth_service.update_key(
            self.item["id"],
            {"limits": {"allowed_models": ["gpt-image-2"]}},
            role="user",
        )

        response = self.client.post(
            "/v1/images/generations",
            headers=self.auth_headers(),
            json={"prompt": "cat", "model": "codex-gpt-image-2", "n": 1},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("没有使用该模型", response.text)


if __name__ == "__main__":
    unittest.main()
