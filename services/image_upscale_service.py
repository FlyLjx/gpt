from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from services.config import config
from services.log_service import LOG_TYPE_CALL, log_service
from utils.helper import is_codex_image_model
from utils.log import logger


FOUR_K_PATTERN = re.compile(r"\b(?:4k|4096|3840|2160)\b", re.IGNORECASE)


@dataclass(frozen=True)
class UpscaleResult:
    payload: bytes
    applied: bool
    mime_type: str
    original_size: tuple[int, int] | None = None
    target_size: tuple[int, int] | None = None


def _requested_4k(size: object) -> bool:
    text = str(size or "").strip().lower()
    if not text:
        return False
    if FOUR_K_PATTERN.search(text):
        return True
    numbers = [int(item) for item in re.findall(r"\d+", text)]
    return bool(numbers and max(numbers) >= 2160)


def _explicit_false(value: object) -> bool:
    if isinstance(value, bool):
        return value is False
    if value is None or value == "":
        return False
    return str(value).strip().lower() in {"false", "0", "no", "n", "off"}


def _write_upscale_log(summary: str, detail: dict[str, object]) -> None:
    try:
        log_service.add(LOG_TYPE_CALL, summary, detail)
    except Exception:
        pass


def _output_quality(value: object) -> int:
    text = str(value or "").strip().lower()
    if text in {"high", "hd", "best"}:
        return 95
    if text in {"low", "standard"}:
        return min(config.image_upscale_quality, 82)
    return config.image_upscale_quality


def should_upscale_image(*, model: object, size: object, upscale: object = None) -> bool:
    return bool(
        not _explicit_false(upscale)
        and config.image_upscale_enabled
        and _requested_4k(size)
        and not is_codex_image_model(model)
    )


def upstream_image_size(*, model: object, size: object, upscale: object = None) -> str | None:
    if should_upscale_image(model=model, size=size, upscale=upscale):
        return "1024x1024"
    value = str(size or "").strip()
    return value or None


def _target_dimensions(width: int, height: int) -> tuple[int, int]:
    target_long_edge = config.image_upscale_target_long_edge
    long_edge = max(width, height)
    if long_edge <= 0 or long_edge >= target_long_edge:
        return width, height
    scale = target_long_edge / long_edge
    return max(1, round(width * scale)), max(1, round(height * scale))


def upscale_image_bytes(
    image_data: bytes,
    *,
    model: object,
    size: object,
    quality: object = None,
    upscale: object = None,
) -> UpscaleResult:
    if not should_upscale_image(model=model, size=size, upscale=upscale):
        if _requested_4k(size):
            detail = {
                "event": "image_upscale_skipped",
                "model": str(model or ""),
                "requested_size": str(size or ""),
                "upscale": upscale,
                "enabled": config.image_upscale_enabled,
                "is_codex_model": is_codex_image_model(model),
            }
            logger.info(detail)
            _write_upscale_log("图片超分跳过", detail)
        return UpscaleResult(payload=image_data, applied=False, mime_type="image/png")
    try:
        with Image.open(io.BytesIO(image_data)) as image:
            image = ImageOps.exif_transpose(image)
            original_size = image.size
            target_size = _target_dimensions(*original_size)
            if target_size == original_size:
                return UpscaleResult(
                    payload=image_data,
                    applied=False,
                    mime_type=Image.MIME.get(image.format or "PNG", "image/png"),
                    original_size=original_size,
                    target_size=target_size,
                )
            has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            image = image.resize(target_size, Image.Resampling.LANCZOS)
            image = ImageEnhance.Contrast(image).enhance(1.04)
            image = image.filter(ImageFilter.UnsharpMask(radius=0.8, percent=155, threshold=2))
            output = io.BytesIO()
            output_format = config.image_upscale_format
            output_quality = _output_quality(quality)
            if output_format == "png" or has_alpha:
                image.save(output, format="PNG", optimize=True)
                mime_type = "image/png"
            elif output_format == "webp":
                image.save(output, format="WEBP", quality=output_quality, method=6, lossless=False)
                mime_type = "image/webp"
            else:
                image.convert("RGB").save(
                    output,
                    format="JPEG",
                    quality=output_quality,
                    subsampling=0,
                    optimize=True,
                    progressive=True,
                )
                mime_type = "image/jpeg"
            payload = output.getvalue()
            detail = {
                "event": "image_upscale_applied",
                "model": str(model or ""),
                "requested_size": str(size or ""),
                "original_width": original_size[0],
                "original_height": original_size[1],
                "target_width": target_size[0],
                "target_height": target_size[1],
                "original_bytes": len(image_data),
                "output_bytes": len(payload),
                "mime_type": mime_type,
                "output_quality": output_quality,
            }
            logger.info(detail)
            _write_upscale_log("图片超分完成", detail)
            return UpscaleResult(
                payload=payload,
                applied=True,
                mime_type=mime_type,
                original_size=original_size,
                target_size=target_size,
            )
    except Exception as exc:
        detail = {
            "event": "image_upscale_failed",
            "model": str(model or ""),
            "requested_size": str(size or ""),
            "error": str(exc),
        }
        logger.warning(detail)
        _write_upscale_log("图片超分失败", detail)
        return UpscaleResult(payload=image_data, applied=False, mime_type="image/png")
