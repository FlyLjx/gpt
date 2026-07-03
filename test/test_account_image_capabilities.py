from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "chatgpt2api")

from services.account_service import AccountService
from services.auth_service import AuthQuotaError, AuthService
from services.openai_backend_api import InvalidAccessTokenError, OpenAIBackendAPI
from services.storage.json_storage import JSONStorageBackend
from utils.helper import anonymize_token, split_image_model


class AccountCapabilityTests(unittest.TestCase):
    def test_unknown_quota_accounts_are_available_only_when_not_throttled(self) -> None:
        self.assertFalse(
            AccountService._is_image_account_available(
                {"status": "限流", "image_quota_unknown": True, "quota": 0}
            )
        )
        self.assertTrue(
            AccountService._is_image_account_available(
                {"status": "正常", "image_quota_unknown": True, "quota": 0}
            )
        )

    def test_refresh_keeps_free_account_available_when_image_quota_is_missing(self) -> None:
        with (
            mock.patch.object(OpenAIBackendAPI, "_get_me", return_value={"email": "free@example.test", "id": "user-1"}),
            mock.patch.object(
                OpenAIBackendAPI,
                "_get_conversation_init",
                return_value={"default_model_slug": "auto", "limits_progress": []},
            ),
            mock.patch.object(OpenAIBackendAPI, "_get_default_account", return_value={"plan_type": "free"}),
        ):
            info = OpenAIBackendAPI("token-free").get_user_info()

        self.assertEqual(info["type"], "free")
        self.assertEqual(info["quota"], 0)
        self.assertTrue(info["image_quota_unknown"])
        self.assertEqual(info["status"], "正常")

    def test_refresh_marks_known_zero_image_quota_as_limited(self) -> None:
        with (
            mock.patch.object(OpenAIBackendAPI, "_get_me", return_value={"email": "free@example.test", "id": "user-1"}),
            mock.patch.object(
                OpenAIBackendAPI,
                "_get_conversation_init",
                return_value={
                    "default_model_slug": "auto",
                    "limits_progress": [{"feature_name": "image_gen", "remaining": 0, "reset_after": "2026-06-08T00:00:00Z"}],
                },
            ),
            mock.patch.object(OpenAIBackendAPI, "_get_default_account", return_value={"plan_type": "free"}),
        ):
            info = OpenAIBackendAPI("token-free").get_user_info()

        self.assertFalse(info["image_quota_unknown"])
        self.assertEqual(info["quota"], 0)
        self.assertEqual(info["status"], "限流")

    def test_prolite_variants_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            self.assertEqual(service._normalize_account_type("prolite"), "ProLite")
            self.assertEqual(service._normalize_account_type("pro_lite"), "ProLite")

    def test_search_account_type_ignores_unrelated_scalar_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            self.assertIsNone(
                service._search_account_type(
                    {
                        "amr": ["pwd", "otp", "mfa"],
                        "chatgpt_compute_residency": "no_constraint",
                        "chatgpt_data_residency": "no_constraint",
                        "user_id": "user-I52GFfLGFM0dokFk2dBiKEBn",
                    }
                )
            )

    def test_mark_image_result_does_not_consume_unknown_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_accounts(["token-1"])
            service.update_account(
                "token-1",
                {
                    "status": "正常",
                    "quota": 0,
                    "image_quota_unknown": True,
                },
            )

            updated = service.mark_image_result("token-1", success=True)

            self.assertIsNotNone(updated)
            self.assertEqual(updated["quota"], 0)
            self.assertEqual(updated["status"], "正常")
            self.assertTrue(updated["image_quota_unknown"])

    def test_invalid_access_token_with_failed_refresh_is_marked_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-dead", "status": "正常", "quota": 25},
            ])

            def mark_invalid(access_token: str, event: str, quiet: bool = False) -> bool:
                service.update_account(access_token, {"status": "异常", "quota": 0}, quiet=True)
                return False

            with (
                mock.patch.object(service, "refresh_access_token", return_value="token-dead"),
                mock.patch.object(service, "remove_invalid_token", side_effect=mark_invalid) as removed,
                mock.patch.object(
                    OpenAIBackendAPI,
                    "get_user_info",
                    side_effect=InvalidAccessTokenError("token invalidated (/backend-api/me)"),
                ),
            ):
                with self.assertRaises(InvalidAccessTokenError):
                    service.fetch_remote_info("token-dead", "refresh_accounts")

            account = service.get_account("token-dead")
            removed.assert_called_once_with("token-dead", "refresh_accounts")
            self.assertEqual(account["status"], "异常")
            self.assertEqual(account["quota"], 0)

    def test_account_healthcheck_tokens_include_stale_available_accounts(self) -> None:
        now = datetime.now(timezone.utc)
        stale = (now - timedelta(hours=2)).isoformat()
        recent = now.isoformat()
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-stale", "status": "正常", "created_at": stale},
                {"access_token": "token-recent", "status": "正常", "last_account_refresh_at": recent},
                {"access_token": "token-disabled", "status": "禁用", "created_at": stale},
                {"access_token": "token-abnormal", "status": "异常", "created_at": stale},
            ])

            with mock.patch("services.account_service.config", mock.Mock(refresh_account_interval_minute=60)):
                tokens = service.list_account_healthcheck_tokens()

        self.assertEqual(tokens, ["token-stale"])

    def test_image_precheck_due_respects_last_account_refresh_time(self) -> None:
        now = datetime.now(timezone.utc)
        stale = (now - timedelta(minutes=30)).isoformat()
        recent = now.isoformat()
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-stale", "status": "正常", "quota": 3, "last_account_refresh_at": stale},
                {"access_token": "token-recent", "status": "正常", "quota": 3, "last_account_refresh_at": recent},
            ])

            with mock.patch("services.account_service.config", mock.Mock(image_account_precheck_interval_minutes=10)):
                self.assertTrue(service._image_precheck_due(service.get_account("token-stale"), "token-stale"))
                self.assertFalse(service._image_precheck_due(service.get_account("token-recent"), "token-recent"))
                self.assertTrue(service._image_precheck_due(None, "token-missing"))

    def test_get_available_access_token_skips_remote_precheck_for_fresh_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {
                    "access_token": "token-fresh",
                    "status": "正常",
                    "quota": 3,
                    "last_account_refresh_at": datetime.now(timezone.utc).isoformat(),
                },
            ])
            service.fetch_remote_info = mock.Mock(side_effect=AssertionError("fresh account should not precheck"))

            with mock.patch("services.account_service.config", mock.Mock(
                image_account_concurrency=3,
                image_account_precheck_interval_minutes=10,
            )):
                token = service.get_available_access_token()

            service.release_image_slot(token)
            self.assertEqual(token, "token-fresh")
            service.fetch_remote_info.assert_not_called()

    def test_get_available_access_token_prechecks_stale_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {
                    "access_token": "token-stale",
                    "status": "正常",
                    "quota": 3,
                    "last_account_refresh_at": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
                },
            ])
            service.fetch_remote_info = mock.Mock(side_effect=lambda access_token, event="": service.get_account(access_token))

            with mock.patch("services.account_service.config", mock.Mock(
                image_account_concurrency=3,
                image_account_precheck_interval_minutes=10,
            )):
                token = service.get_available_access_token()

            service.release_image_slot(token)
            self.assertEqual(token, "token-stale")
            service.fetch_remote_info.assert_called_once_with("token-stale", "get_available_access_token")

    def test_split_image_model_supports_plan_type_prefix(self) -> None:
        self.assertEqual(split_image_model("gpt-image-2"), (None, "gpt-image-2"))
        self.assertEqual(split_image_model("plus-codex-gpt-image-2"), ("plus", "codex-gpt-image-2"))
        self.assertEqual(split_image_model("team-codex-gpt-image-2"), ("team", "codex-gpt-image-2"))
        self.assertEqual(split_image_model("pro-codex-gpt-image-2"), ("pro", "codex-gpt-image-2"))
        self.assertEqual(split_image_model("plus-gpt-image-2"), (None, None))
        self.assertEqual(split_image_model("unknown-image-model"), (None, None))

    def test_get_available_access_token_filters_by_plan_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items(
                [
                    {"access_token": "token-plus", "type": "Plus", "status": "正常", "quota": 3},
                    {"access_token": "token-pro", "type": "Pro", "status": "正常", "quota": 3},
                ]
            )

            service.fetch_remote_info = lambda access_token, event="fetch_remote_info": service.get_account(access_token)

            plus_token = service.get_available_access_token(plan_type="plus")
            pro_token = service.get_available_access_token(plan_type="pro")
            service.release_image_slot(plus_token)
            service.release_image_slot(pro_token)

            self.assertEqual(plus_token, "token-plus")
            self.assertEqual(pro_token, "token-pro")

    def test_get_available_access_token_skips_cooling_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            fresh = datetime.now(timezone.utc).isoformat()
            service.add_account_items([
                {
                    "access_token": "token-cooling",
                    "status": "正常",
                    "quota": 5,
                    "last_account_refresh_at": fresh,
                    "cooldown_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                },
                {"access_token": "token-ready", "status": "正常", "quota": 1, "last_account_refresh_at": fresh},
            ])
            service.fetch_remote_info = mock.Mock(side_effect=AssertionError("fresh account should not precheck"))

            with mock.patch("services.account_service.config", mock.Mock(
                image_account_concurrency=3,
                image_account_precheck_interval_minutes=10,
            )):
                token = service.get_available_access_token()

            service.release_image_slot(token)
            self.assertEqual(token, "token-ready")

    def test_get_available_access_token_skips_proxy_cooling_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            fresh = datetime.now(timezone.utc).isoformat()
            service.add_account_items([
                {
                    "access_token": "token-proxy-cooling",
                    "status": "正常",
                    "quota": 5,
                    "proxy": "http://127.0.0.1:7890",
                    "last_account_refresh_at": fresh,
                    "proxy_stats": {
                        "fail": 3,
                        "last_error_type": "cloudflare",
                        "cooldown_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    },
                },
                {"access_token": "token-ready", "status": "正常", "quota": 1, "last_account_refresh_at": fresh},
            ])
            service.fetch_remote_info = mock.Mock(side_effect=AssertionError("fresh account should not precheck"))

            with mock.patch("services.account_service.config", mock.Mock(
                image_account_concurrency=3,
                image_account_precheck_interval_minutes=10,
            )):
                token = service.get_available_access_token()

            service.release_image_slot(token)
            self.assertEqual(token, "token-ready")

    def test_get_available_access_token_prefers_higher_scored_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            fresh = datetime.now(timezone.utc).isoformat()
            service.add_account_items([
                {
                    "access_token": "token-low",
                    "status": "正常",
                    "quota": 1,
                    "success": 1,
                    "fail": 6,
                    "consecutive_failures": 2,
                    "last_account_refresh_at": fresh,
                },
                {
                    "access_token": "token-high",
                    "status": "正常",
                    "quota": 8,
                    "success": 8,
                    "fail": 1,
                    "last_account_refresh_at": fresh,
                },
            ])
            service.fetch_remote_info = mock.Mock(side_effect=AssertionError("fresh account should not precheck"))

            with mock.patch("services.account_service.config", mock.Mock(
                image_account_concurrency=3,
                image_account_precheck_interval_minutes=10,
            )):
                token = service.get_available_access_token()

            service.release_image_slot(token)
            self.assertEqual(token, "token-high")

    def test_content_policy_failure_does_not_penalize_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-policy", "status": "正常", "quota": 5, "fail": 0},
            ])

            updated = service.mark_image_result("token-policy", success=False, error="content_policy_violation")

            self.assertIsNotNone(updated)
            self.assertEqual(updated["fail"], 0)
            self.assertEqual(updated["consecutive_failures"], 0)
            self.assertIsNone(updated["cooldown_until"])
            self.assertEqual(updated["last_error_type"], "content_policy")
            self.assertEqual(updated["recent_results"], [])

    def test_cloudflare_failure_records_recent_history_and_proxy_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {
                    "access_token": "token-cloudflare",
                    "status": "正常",
                    "quota": 5,
                    "proxy": "http://127.0.0.1:7890",
                },
            ])

            updated = service.mark_image_result(
                "token-cloudflare",
                success=False,
                error="被 Cloudflare 拦截，请配置/检查 FlareSolverr 或更换 IP 重试",
            )

            self.assertIsNotNone(updated)
            self.assertEqual(updated["last_error_type"], "cloudflare")
            self.assertEqual(updated["recent_results"][-1]["error_type"], "cloudflare")
            self.assertEqual(updated["proxy_stats"]["fail"], 1)
            self.assertEqual(updated["proxy_stats"]["last_error_type"], "cloudflare")
            self.assertTrue(updated["proxy_stats"]["cooldown_until"])

    def test_list_accounts_exports_dispatch_observability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-ok", "status": "正常", "quota": 5, "success": 1},
            ])
            service.mark_account_success("token-ok")

            item = service.list_accounts()[0]

            self.assertIn("dispatch_score", item)
            self.assertEqual(item["recent_total"], 1)
            self.assertEqual(item["recent_success_rate"], 100.0)

    def test_codex_route_allows_premium_account_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-plus", "type": "Plus", "source_type": "web", "quota": 3},
                {"access_token": "token-free", "type": "free", "source_type": "codex", "quota": 3},
            ])

            with mock.patch("services.openai_backend_api.account_service", service):
                OpenAIBackendAPI("token-plus")._ensure_codex_capable_account()
                with self.assertRaisesRegex(RuntimeError, "plus/team/pro"):
                    OpenAIBackendAPI("token-free")._ensure_codex_capable_account()


class TokenLogTests(unittest.TestCase):
    def test_anonymize_token_hides_raw_value(self) -> None:
        token = "super-secret-token"
        token_ref = anonymize_token(token)

        self.assertTrue(token_ref.startswith("token:"))
        self.assertNotIn(token, token_ref)


class AuthServiceTests(unittest.TestCase):
    def test_create_authenticate_disable_and_delete_user_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))

            item, raw_key = service.create_key(role="user", name="Alice")

            self.assertEqual(item["role"], "user")
            self.assertEqual(item["name"], "Alice")
            self.assertTrue(item["enabled"])
            self.assertTrue(raw_key.startswith("sk-"))

            authed = service.authenticate(raw_key)
            self.assertIsNotNone(authed)
            self.assertEqual(authed["id"], item["id"])
            self.assertEqual(authed["role"], "user")
            self.assertIsNotNone(authed["last_used_at"])

            updated = service.update_key(item["id"], {"enabled": False}, role="user")
            self.assertIsNotNone(updated)
            self.assertFalse(updated["enabled"])
            self.assertIsNone(service.authenticate(raw_key))

            self.assertTrue(service.delete_key(item["id"], role="user"))
            self.assertFalse(service.delete_key(item["id"], role="user"))
            self.assertEqual(service.list_keys(role="user"), [])

    def test_authenticate_ignores_last_used_save_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, raw_key = service.create_key(role="user", name="Alice")

            def fail_save() -> None:
                raise OSError("disk unavailable")

            service._save = fail_save

            authed = service.authenticate(raw_key)

            self.assertIsNotNone(authed)
            self.assertEqual(authed["id"], item["id"])
            self.assertIsNotNone(authed["last_used_at"])

    def test_update_user_key_replaces_raw_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, raw_key = service.create_key(role="user", name="Alice")

            updated = service.update_key(item["id"], {"key": "sk-user-custom-key"}, role="user")

            self.assertIsNotNone(updated)
            self.assertIsNone(service.authenticate(raw_key))

            authed = service.authenticate("sk-user-custom-key")
            self.assertIsNotNone(authed)
            self.assertEqual(authed["id"], item["id"])

    def test_user_key_name_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            first, _ = service.create_key(role="user", name="Alice")
            second, _ = service.create_key(role="user", name="Bob")

            with self.assertRaisesRegex(ValueError, "这个名称已经在使用中了"):
                service.create_key(role="user", name="Alice")

            with self.assertRaisesRegex(ValueError, "这个名称已经在使用中了"):
                service.update_key(second["id"], {"name": "Alice"}, role="user")

            updated = service.update_key(first["id"], {"name": "Alice"}, role="user")
            self.assertIsNotNone(updated)
            self.assertEqual(updated["name"], "Alice")

    def test_user_key_quota_defaults_to_unlimited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, _ = service.create_key(role="user", name="Alice")

            updated = service.consume_quota(item, endpoint="/v1/chat/completions", model="gpt-5")

            self.assertIsNotNone(updated)
            self.assertEqual(updated["usage"]["requests"], 1)
            self.assertEqual(updated["usage"]["images"], 0)

    def test_user_key_daily_request_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, _ = service.create_key(role="user", name="Alice")
            service.update_key(item["id"], {"limits": {"daily_requests": 1}}, role="user")

            identity = service.list_keys(role="user")[0]
            service.consume_quota(identity, endpoint="/v1/chat/completions")

            with self.assertRaisesRegex(AuthQuotaError, "今日调用次数已用完"):
                service.consume_quota(identity, endpoint="/v1/chat/completions")

    def test_user_key_daily_image_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, _ = service.create_key(role="user", name="Alice")
            service.update_key(item["id"], {"limits": {"daily_images": 2}}, role="user")

            identity = service.list_keys(role="user")[0]

            with self.assertRaisesRegex(AuthQuotaError, "今日图片额度已用完"):
                service.consume_quota(identity, endpoint="/v1/images/generations", image_units=3)

    def test_user_key_model_and_endpoint_allow_lists_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))
            item, _ = service.create_key(role="user", name="Alice")
            service.update_key(
                item["id"],
                {
                    "limits": {
                        "allowed_endpoints": ["/v1/images/generations"],
                        "allowed_models": ["gpt-image-2"],
                    }
                },
                role="user",
            )
            identity = service.list_keys(role="user")[0]

            service.consume_quota(identity, endpoint="/v1/images/generations", model="gpt-image-2", image_units=1)
            with self.assertRaisesRegex(AuthQuotaError, "没有访问该接口"):
                service.consume_quota(identity, endpoint="/v1/chat/completions", model="gpt-image-2")
            with self.assertRaisesRegex(AuthQuotaError, "没有使用该模型"):
                service.consume_quota(identity, endpoint="/v1/images/generations", model="codex-gpt-image-2")

    def test_relogin_progress_result_includes_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.init_relogin_progress("progress-1", 1)

            service.update_relogin_progress("progress-1", "token-1", "成功", email="user@example.com")
            progress = service.get_relogin_progress("progress-1")

            self.assertIsNotNone(progress)
            self.assertTrue(progress["done"])
            self.assertEqual(progress["results"][0]["email"], "user@example.com")
            self.assertEqual(progress["results"][0]["status"], "成功")

    def test_public_account_masks_saved_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-1", "email": "user@example.com", "password": "secret-password"},
            ])

            account = service.get_account("token-1")

            self.assertIsNotNone(account)
            self.assertTrue(account["has_password"])
            self.assertNotIn("password", account)

    def test_relogin_uses_internal_saved_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_account_items([
                {"access_token": "token-1", "email": "user@example.com", "password": "secret-password", "status": "异常"},
            ])

            with mock.patch("services.account_service.Thread") as thread_cls:
                result = service.re_login_accounts(["token-1"], "progress-1")

            self.assertEqual(result["relogined"], 1)
            thread_cls.assert_called_once()
            args = thread_cls.call_args.kwargs["args"]
            self.assertEqual(args[:3], ("token-1", "user@example.com", "secret-password"))


if __name__ == "__main__":
    unittest.main()
