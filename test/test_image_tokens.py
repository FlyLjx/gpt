from __future__ import annotations

import unittest

from services.protocol import conversation

from utils.image_tokens import (
    count_image_content_tokens,
    count_image_input_tokens,
    count_image_inputs_tokens,
    count_image_output_items_tokens,
    count_image_output_tokens,
    image_usage,
    token_usage,
)


class ImageTokenTests(unittest.TestCase):
    def test_image_token_count_is_disabled(self):
        self.assertEqual(count_image_input_tokens(1024, 1024, "gpt-4.1-mini", "high"), 0)
        self.assertEqual(count_image_content_tokens([{"type": "image_url", "width": 1024, "height": 1024}], "gpt-image-2"), 0)
        self.assertEqual(count_image_inputs_tokens([(b"not-an-image", "image/png")], "gpt-image-2"), 0)
        self.assertEqual(count_image_output_tokens("1024x1024", "auto", 2), 0)
        self.assertEqual(count_image_output_items_tokens([{"b64_json": "invalid"}], "1024x1024", "auto"), 0)

    def test_text_token_count_is_disabled(self):
        self.assertEqual(conversation.count_text_tokens("hello", "gpt-image-2"), 0)
        self.assertEqual(
            conversation.count_message_text_tokens([{"role": "user", "content": "hello"}], "gpt-image-2"),
            0,
        )
        self.assertEqual(
            conversation.count_message_image_tokens([{"role": "user", "content": []}], "gpt-image-2"),
            0,
        )

    def test_usage_shape_is_preserved_with_zero_tokens(self):
        usage = token_usage(
            input_text_tokens=10,
            input_image_tokens=20,
            output_text_tokens=30,
            output_image_tokens=40,
        )
        self.assertEqual(usage["input_tokens"], 0)
        self.assertEqual(usage["output_tokens"], 0)
        self.assertEqual(usage["total_tokens"], 0)
        self.assertEqual(usage["input_tokens_details"]["image_tokens"], 0)
        self.assertEqual(usage["output_tokens_details"]["image_tokens"], 0)
        self.assertEqual(image_usage(output_tokens=100)["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
