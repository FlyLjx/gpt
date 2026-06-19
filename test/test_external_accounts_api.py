from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "chatgpt2api")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.external_accounts as external_accounts_module


class ExternalAccountsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account_service = mock.Mock()
        self.account_service.account_health.return_value = {
            "active": 3,
            "healthy": True,
            "status": "ok",
            "total": 5,
        }
        self.account_service.list_accounts.return_value = [{"access_token": "token-1"}]
        self.account_service.add_account_items.return_value = {
            "added": 1,
            "skipped": 0,
            "items": [{"access_token": "token-1"}],
        }
        self.account_service.add_accounts.return_value = {
            "added": 1,
            "skipped": 0,
            "items": [{"access_token": "token-2"}],
        }
        self.account_service.refresh_accounts.return_value = {
            "refreshed": 2,
            "errors": [],
            "items": [{"access_token": "token-1"}, {"access_token": "token-2"}],
        }

        self.account_patcher = mock.patch.object(external_accounts_module, "account_service", self.account_service)
        self.account_patcher.start()
        self.addCleanup(self.account_patcher.stop)

        app = FastAPI()
        app.include_router(external_accounts_module.create_router())
        self.client = TestClient(app)

    def test_summary_accepts_authorization_bearer(self) -> None:
        response = self.client.get(
            "/api/external/accounts/summary",
            headers={"Authorization": "Bearer chatgpt2api"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["valid_account_count"], 3)

    def test_summary_accepts_x_api_key_header(self) -> None:
        response = self.client.get(
            "/api/external/accounts/summary",
            headers={"x-api-key": "chatgpt2api"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["healthy"])

    def test_import_accepts_api_key_query_and_refreshes(self) -> None:
        response = self.client.post(
            "/api/external/accounts/import?api_key=chatgpt2api",
            json={
                "tokens": ["token-1", "token-2"],
                "accounts": [{"access_token": "token-1", "type": "plus"}],
                "refresh": True,
                "source_type": "integration",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.account_service.add_account_items.assert_called_once()
        self.account_service.add_accounts.assert_called_once_with(["token-2"], source_type="integration")
        self.account_service.refresh_accounts.assert_called_once_with(["token-1", "token-2"])
        payload = response.json()
        self.assertEqual(payload["added"], 2)
        self.assertEqual(payload["refreshed"], 2)

    def test_import_can_skip_refresh(self) -> None:
        response = self.client.post(
            "/api/external/accounts/import",
            headers={"Authorization": "Bearer chatgpt2api"},
            json={
                "tokens": ["token-3"],
                "refresh": False,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.account_service.add_accounts.assert_called_once_with(["token-3"], source_type="external_api")
        self.account_service.refresh_accounts.assert_not_called()
        self.assertEqual(response.json()["refreshed"], 0)


if __name__ == "__main__":
    unittest.main()
