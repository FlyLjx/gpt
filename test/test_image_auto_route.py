from __future__ import annotations

import unittest
from unittest import mock

from services.log_service import _strip_internal_response_fields, _collect_image_routes
from services.protocol import conversation
from services.protocol.conversation import ConversationRequest


class ImageAutoRouteTests(unittest.TestCase):
    def test_default_image_model_non_4k_uses_free_route(self) -> None:
        calls = []

        def get_available_access_token(**kwargs):
            calls.append(kwargs)
            return "token-free"

        request = ConversationRequest(model="gpt-image-2", size="1024x1024")

        with mock.patch.object(conversation.account_service, "get_available_access_token", get_available_access_token):
            token, routed, route = conversation._select_image_request_route(request)

        self.assertEqual(token, "token-free")
        self.assertIs(routed, request)
        self.assertEqual(route["requested_model"], "gpt-image-2")
        self.assertEqual(route["backend_model"], "gpt-image-2")
        self.assertEqual(route["image_channel"], "image-2")
        self.assertEqual(route["image_route"], "free_image2_fallback")
        self.assertEqual(calls, [{"plan_type": "free"}])

    def test_default_image_model_4k_prefers_codex_plus_team_pro_accounts(self) -> None:
        calls = []

        def get_available_access_token(**kwargs):
            calls.append(kwargs)
            return "token-codex-team"

        with mock.patch.object(conversation.account_service, "get_available_access_token", get_available_access_token):
            token, routed, route = conversation._select_image_request_route(
                ConversationRequest(model="gpt-image-2", size="3840x2160")
            )

        self.assertEqual(token, "token-codex-team")
        self.assertEqual(routed.model, "codex-gpt-image-2")
        self.assertEqual(route["requested_model"], "gpt-image-2")
        self.assertEqual(route["backend_model"], "codex-gpt-image-2")
        self.assertEqual(route["image_channel"], "codex")
        self.assertEqual(route["image_route"], "auto_premium_codex")
        self.assertEqual(calls, [{"plan_types": ("plus", "team", "pro")}])

    def test_default_image_model_4k_falls_back_to_free_when_codex_unavailable(self) -> None:
        calls = []

        def get_available_access_token(**kwargs):
            calls.append(kwargs)
            if kwargs.get("plan_types") == ("plus", "team", "pro"):
                raise RuntimeError("no available codex image quota")
            return "token-free"

        request = ConversationRequest(model="gpt-image-2", size="4096x4096")

        with mock.patch.object(conversation.account_service, "get_available_access_token", get_available_access_token):
            token, routed, route = conversation._select_image_request_route(request)

        self.assertEqual(token, "token-free")
        self.assertIs(routed, request)
        self.assertEqual(route["backend_model"], "gpt-image-2")
        self.assertEqual(route["image_channel"], "image-2")
        self.assertEqual(route["image_route"], "free_image2_fallback")
        self.assertEqual(calls, [
            {"plan_types": ("plus", "team", "pro")},
            {"plan_type": "free"},
        ])

    def test_4k_route_detection_accepts_common_4k_sizes(self) -> None:
        self.assertTrue(conversation._requests_4k_image("3840x2160"))
        self.assertTrue(conversation._requests_4k_image("2160x3840"))
        self.assertTrue(conversation._requests_4k_image("4096x4096"))
        self.assertTrue(conversation._requests_4k_image("4k"))
        self.assertFalse(conversation._requests_4k_image("1536x1024"))
        self.assertFalse(conversation._requests_4k_image("1024x1024"))

    def test_explicit_codex_model_keeps_codex_route(self) -> None:
        calls = []

        def get_available_access_token(**kwargs):
            calls.append(kwargs)
            return "token-codex-plus"

        request = ConversationRequest(model="plus-codex-gpt-image-2")

        with mock.patch.object(conversation.account_service, "get_available_access_token", get_available_access_token):
            token, routed, route = conversation._select_image_request_route(request)

        self.assertEqual(token, "token-codex-plus")
        self.assertIs(routed, request)
        self.assertEqual(route["backend_model"], "plus-codex-gpt-image-2")
        self.assertEqual(route["image_channel"], "codex")
        self.assertEqual(route["image_route"], "explicit_codex")
        self.assertEqual(calls, [{"plan_type": "plus", "plan_types": None}])

    def test_output_chunks_include_internal_route_meta_for_logs(self) -> None:
        output = conversation.ImageOutput(
            kind="result",
            model="codex-gpt-image-2",
            index=1,
            total=1,
            data=[{"url": "https://example.test/image.png"}],
            account_email="plus@example.test",
            route_meta={
                "requested_model": "gpt-image-2",
                "backend_model": "codex-gpt-image-2",
                "image_channel": "codex",
                "image_channel_label": "Codex线路",
                "image_route": "auto_premium_codex",
            },
        )

        chunk = output.to_chunk()
        collected = conversation.collect_image_outputs([output])

        self.assertEqual(chunk["_image_route"]["backend_model"], "codex-gpt-image-2")
        self.assertEqual(collected["_image_route"]["image_channel"], "codex")
        self.assertEqual(collected["_account_email"], "plus@example.test")

    def test_log_helpers_collect_and_strip_image_route(self) -> None:
        payload = {
            "data": [{"url": "https://example.test/image.png"}],
            "_image_route": {
                "account_email": "plus@example.test",
                "account_type": "Plus",
                "requested_model": "gpt-image-2",
                "backend_model": "codex-gpt-image-2",
                "image_channel": "codex",
            },
        }

        routes = _collect_image_routes(payload)
        stripped = _strip_internal_response_fields(payload)

        self.assertEqual(routes[0]["account_type"], "Plus")
        self.assertNotIn("_image_route", stripped)


if __name__ == "__main__":
    unittest.main()
