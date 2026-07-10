from __future__ import annotations

from io import BytesIO
from typing import Any, Iterator

from PIL import Image

from services.protocol.conversation import (
    ConversationRequest,
    ImageGenerationError,
    collect_image_outputs,
    count_text_tokens,
    encode_images,
    stream_image_chunks,
    stream_image_outputs_with_pool,
)
from utils.image_tokens import count_image_inputs_tokens, count_image_output_items_tokens, image_usage


def _reference_prompt(prompt: str, images: list[tuple[bytes, str, str]]) -> str:
    """给多参考图请求补充稳定的图片顺序说明，避免上游忽略或混淆图1/图2。"""
    count = len(images)
    if count <= 0:
        return prompt
    labels = "、".join(
        f"图{index}=第{index}张上传图片（{filename or f'image_{index}.png'}）"
        for index, (_, filename, _) in enumerate(images, start=1)
    )
    prefix_lines = [
        "【参考图顺序绑定】",
        f"本次图生图请求实际上传了 {count} 张参考图，默认按上传顺序依次对应：{labels}。",
        "第1张通常来自前端“主参考图”位置，第2张及以后通常来自“补充参考图”位置；但最终要以用户任务语义和图片可见内容共同判断。",
        "当用户提示词出现“图1/图一/第一张/主参考图”时，通常指第1张上传图片；出现“图2/图二/第二张/补充参考图”时，通常指第2张上传图片，后续编号依此类推。",
        "如果用户文字里的编号与图片实际内容明显矛盾，请以图片内容和任务目标为准自动纠正。例如文字说“图1的小女孩”但只有另一张图里有小女孩，则把有小女孩的那张作为目标画布；文字说“第二的红色碗”但红色碗只在另一张产品图里，则把含红色碗的那张作为素材来源。",
        "请优先读取实际上传的图片内容，不要只根据文字想象；如果提示词里出现“参考图数量：0”等与实际上传数量矛盾的文字，请忽略该矛盾文字，以实际上传图片为准。",
    ]
    if count >= 2:
        prefix_lines.extend([
            "如果任务是替换、合成或迁移元素：目标画布/最终场景应是包含“需要被替换区域”的图片（例如人物手里原本端着的碗、原始房间、原始场景）；素材来源应是包含“要替换进去的对象/颜色/材质/风格”的图片（例如产品图里的红色碗）。",
            "保持目标画布中未指定修改的人物、姿势、构图、背景、光照和风格不变；只把用户点名的局部对象替换成素材来源中的对象，替换后必须清晰可见，不能保持原物不变。",
            "不要把素材来源图里的海报文字、包装盒、背景、边框、水印或无关元素带入最终图，除非用户明确要求。",
        ])
    return "\n".join(prefix_lines) + "\n\n【用户原始指令】\n" + prompt


def _composite_mask(
    images: list[tuple[bytes, str, str]],
    masks: list[tuple[bytes, str, str]],
) -> list[tuple[bytes, str, str]]:
    """把 mask 的 alpha/灰度通道合成到图片 alpha 通道中。"""
    if not masks:
        return images
    result: list[tuple[bytes, str, str]] = []
    for index, (data, filename, _mime_type) in enumerate(images):
        mask_data = masks[index][0] if index < len(masks) else masks[-1][0]
        image = Image.open(BytesIO(data)).convert("RGBA")
        mask_image = Image.open(BytesIO(mask_data))
        if mask_image.mode == "RGBA":
            alpha = mask_image.split()[3]
        elif mask_image.mode == "L":
            alpha = mask_image
        else:
            alpha = mask_image.convert("L")
        alpha = alpha.resize(image.size, Image.LANCZOS)
        image.putalpha(alpha)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        result.append((buffer.getvalue(), filename, "image/png"))
    return result


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "")
    images = body.get("images") or []
    masks = body.get("mask") or []
    images = _composite_mask(images, masks)
    effective_prompt = _reference_prompt(prompt, images)
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size")
    quality = str(body.get("quality") or "auto")
    response_format = str(body.get("response_format") or "url")
    base_url = str(body.get("base_url") or "") or None
    progress_callback = body.get("progress_callback")
    encoded_images = encode_images(images)
    if not encoded_images:
        raise ImageGenerationError("image is required")
    outputs = stream_image_outputs_with_pool(ConversationRequest(
        prompt=effective_prompt,
        model=model,
        n=n,
        size=size,
        quality=quality,
        response_format=response_format,
        base_url=base_url,
        images=encoded_images,
        message_as_error=True,
        progress_callback=progress_callback,
    ))
    if body.get("stream"):
        return stream_image_chunks(outputs)
    result = collect_image_outputs(outputs)
    result["usage"] = image_usage(
        input_text_tokens=count_text_tokens(effective_prompt, model),
        input_image_tokens=count_image_inputs_tokens(images, model),
        output_tokens=count_image_output_items_tokens(result.get("data"), size, quality),
    )
    return result
