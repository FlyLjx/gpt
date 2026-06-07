from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_refill_service import AccountRefillService, _refresh_candidate_tokens


class AccountRefillServiceTests(unittest.TestCase):
    def test_available_account_requires_image_quota(self) -> None:
        service = AccountRefillService()

        stats = service._stats([
            {"status": "正常", "quota": 0, "image_quota_unknown": False},
            {"status": "正常", "quota": 2, "image_quota_unknown": False},
            {"status": "限流", "quota": 5, "image_quota_unknown": False},
            {"status": "正常", "quota": 0, "image_quota_unknown": True},
        ])

        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["available"], 2)

    def test_refresh_candidates_skip_disabled_and_abnormal_accounts(self) -> None:
        tokens = _refresh_candidate_tokens([
            {"access_token": "token-normal", "status": "正常"},
            {"access_token": "token-limited", "status": "限流"},
            {"access_token": "token-disabled", "status": "禁用"},
            {"access_token": "token-abnormal", "status": "异常"},
            {"access_token": "", "status": "正常"},
        ])

        self.assertEqual(tokens, ["token-normal", "token-limited"])

    def test_refresh_pool_refreshes_candidate_accounts(self) -> None:
        service = AccountRefillService()

        with patch("services.account_refill_service.account_service") as mocked_account_service:
            mocked_account_service.list_accounts.return_value = [
                {"access_token": "token-normal", "status": "正常"},
                {"access_token": "token-disabled", "status": "禁用"},
            ]
            mocked_account_service.refresh_accounts.return_value = {
                "refreshed": 1,
                "errors": [],
                "relogined": 0,
            }

            refresh = service._refresh_pool()

        mocked_account_service.refresh_accounts.assert_called_once_with(["token-normal"])
        self.assertEqual(refresh["attempted"], 1)
        self.assertEqual(refresh["refreshed"], 1)


if __name__ == "__main__":
    unittest.main()
