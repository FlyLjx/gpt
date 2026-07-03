from __future__ import annotations

import base64
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "chatgpt2api")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.ai as ai_module


AUTH_HEADERS = {"Authorization": "Bearer chatgpt2api"}
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")


class SyncImageApiTaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.begin_sync_task = mock.Mock(return_value=("owner:sync-test", {"id": "sync-test"}))
        self.finish_sync_task = mock.Mock()
        self.task_service = mock.Mock(
            begin_sync_task=self.begin_sync_task,
            finish_sync_task=self.finish_sync_task,
            update_sync_task_progress=mock.Mock(),
        )
        self.task_patcher = mock.patch.object(ai_module, "image_task_service", self.task_service, create=True)
        self.task_patcher.start()
        self.addCleanup(self.task_patcher.stop)

        app = FastAPI()
        app.include_router(ai_module.create_router())
        self.client = TestClient(app)

    def test_image_generation_creates_and_finishes_sync_task(self):
        with mock.patch.object(
            ai_module.openai_v1_image_generations,
            "handle",
            return_value={"created": 1, "data": [{"b64_json": "ZmFrZQ=="}]},
        ):
            response = self.client.post(
                "/v1/images/generations",
                headers=AUTH_HEADERS,
                json={
                    "model": "gpt-image-2",
                    "prompt": "cat",
                    "n": 1,
                    "response_format": "b64_json",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.begin_sync_task.assert_called_once()
        self.finish_sync_task.assert_called_once()
        self.assertEqual(self.finish_sync_task.call_args.kwargs["mode"], "generate")
        self.assertFalse(self.finish_sync_task.call_args.kwargs.get("error"))

    def test_streaming_image_generation_does_not_create_sync_task(self):
        with mock.patch.object(
            ai_module.openai_v1_image_generations,
            "handle",
            return_value=iter([{"created": 1, "data": [{"b64_json": "ZmFrZQ=="}]}]),
        ):
            response = self.client.post(
                "/v1/images/generations",
                headers=AUTH_HEADERS,
                json={
                    "model": "gpt-image-2",
                    "prompt": "cat",
                    "n": 1,
                    "stream": True,
                    "response_format": "b64_json",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.begin_sync_task.assert_not_called()
        self.finish_sync_task.assert_not_called()

    def test_image_edit_creates_and_finishes_sync_task(self):
        with mock.patch.object(
            ai_module.openai_v1_image_edit,
            "handle",
            return_value={"created": 1, "data": [{"b64_json": "ZmFrZQ=="}]},
        ):
            response = self.client.post(
                "/v1/images/edits",
                headers=AUTH_HEADERS,
                json={
                    "model": "gpt-image-2",
                    "prompt": "edit",
                    "image": PNG_DATA_URL,
                    "n": 1,
                    "response_format": "b64_json",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.begin_sync_task.assert_called_once()
        self.finish_sync_task.assert_called_once()
        self.assertEqual(self.finish_sync_task.call_args.kwargs["mode"], "edit")
        self.assertFalse(self.finish_sync_task.call_args.kwargs.get("error"))

    def test_image_chat_completion_creates_and_finishes_sync_task(self):
        with mock.patch.object(
            ai_module.openai_v1_chat_complete,
            "handle",
            return_value={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "![image](http://testserver/images/out.png)"}}],
            },
        ):
            response = self.client.post(
                "/v1/chat/completions",
                headers=AUTH_HEADERS,
                json={
                    "model": "gpt-image-2",
                    "messages": [{"role": "user", "content": "画一只猫"}],
                    "n": 1,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.begin_sync_task.assert_called_once()
        self.finish_sync_task.assert_called_once()
        self.assertEqual(self.finish_sync_task.call_args.kwargs["mode"], "generate")
        self.assertFalse(self.finish_sync_task.call_args.kwargs.get("error"))

    def test_image_response_creates_and_finishes_sync_task(self):
        with mock.patch.object(
            ai_module.openai_v1_response,
            "handle",
            return_value={
                "id": "resp-test",
                "object": "response",
                "status": "completed",
                "output": [{"type": "image_generation_call", "status": "completed", "url": "http://testserver/images/out.png"}],
            },
        ):
            response = self.client.post(
                "/v1/responses",
                headers=AUTH_HEADERS,
                json={
                    "model": "gpt-image-2",
                    "input": "画一只猫",
                    "tools": [{"type": "image_generation", "size": "1024x1024"}],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.begin_sync_task.assert_called_once()
        self.finish_sync_task.assert_called_once()
        self.assertEqual(self.finish_sync_task.call_args.kwargs["mode"], "generate")
        self.assertFalse(self.finish_sync_task.call_args.kwargs.get("error"))

    def test_image_generation_error_response_finishes_sync_task_as_error(self):
        with mock.patch.object(
            ai_module.openai_v1_image_generations,
            "handle",
            side_effect=RuntimeError("upstream failed"),
        ):
            response = self.client.post(
                "/v1/images/generations",
                headers=AUTH_HEADERS,
                json={
                    "model": "gpt-image-2",
                    "prompt": "cat",
                    "n": 1,
                    "response_format": "b64_json",
                },
            )

        self.assertEqual(response.status_code, 502, response.text)
        self.begin_sync_task.assert_called_once()
        self.finish_sync_task.assert_called_once()
        self.assertIn("upstream failed", self.finish_sync_task.call_args.kwargs["error"])


if __name__ == "__main__":
    unittest.main()
