from __future__ import annotations

from typing import Any

DEFAULT_IMAGE_SIZE = (1024, 1024)


def image_size_from_bytes(data: bytes) -> tuple[int, int] | None:
    return None


def image_size_from_data_url(value: str) -> tuple[int, int] | None:
    return None


def parse_image_size(size: object, default: tuple[int, int] = DEFAULT_IMAGE_SIZE) -> tuple[int, int]:
    return default


def count_image_input_tokens(
    width: int,
    height: int,
    model: str,
    detail: str = "auto",
    input_fidelity: str = "low",
) -> int:
    return 0


def count_image_content_tokens(content: object, model: str, default_detail: str = "auto") -> int:
    return 0


def count_image_inputs_tokens(images: object, model: str, default_detail: str = "auto") -> int:
    return 0


def count_generated_image_tokens(width: int, height: int, quality: str = "auto") -> int:
    return 0


def count_image_output_tokens(size: object = None, quality: str = "auto", count: int = 1) -> int:
    return 0


def count_image_output_items_tokens(
    items: object,
    size: object = None,
    quality: str = "auto",
) -> int:
    return 0


def token_usage(
    input_text_tokens: int = 0,
    input_image_tokens: int = 0,
    output_text_tokens: int = 0,
    output_image_tokens: int = 0,
) -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "input_tokens_details": {
            "text_tokens": 0,
            "image_tokens": 0,
            "cached_tokens": 0,
        },
        "output_tokens_details": {
            "text_tokens": 0,
            "image_tokens": 0,
            "reasoning_tokens": 0,
        },
    }


def image_usage(
    input_text_tokens: int = 0,
    input_image_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, Any]:
    return token_usage()


def chat_usage_from_image_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_tokens_details": {
            "text_tokens": 0,
            "image_tokens": 0,
            "cached_tokens": 0,
        },
        "completion_tokens_details": {
            "text_tokens": 0,
            "image_tokens": 0,
            "reasoning_tokens": 0,
        },
    }
