from __future__ import annotations

import copy
import io
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from curl_cffi import requests
from PIL import Image

from services.config import BASE_DIR, config
from services.log_service import LOG_TYPE_CALL, log_service
from utils.log import logger


class ComfyUIWorkflowError(RuntimeError):
    pass


def _clean(value: object) -> str:
    return str(value or "").strip()


def _write_log(summary: str, detail: dict[str, object]) -> None:
    try:
        log_service.add(LOG_TYPE_CALL, summary, detail)
    except Exception:
        pass


def _resolve_workflow_path(value: object) -> Path:
    raw = _clean(value)
    if not raw:
        raise ComfyUIWorkflowError("ComfyUI workflow path is empty")
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    if not path.exists():
        raise ComfyUIWorkflowError(f"ComfyUI workflow not found: {path}")
    return path


def _load_workflow(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ComfyUIWorkflowError(f"ComfyUI workflow JSON invalid: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("prompt"), dict):
        data = data["prompt"]
    if not isinstance(data, dict):
        raise ComfyUIWorkflowError("ComfyUI workflow must be an API-format prompt object")
    return copy.deepcopy(data)


def _node_inputs(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = workflow.get(str(node_id))
    if not isinstance(node, dict):
        raise ComfyUIWorkflowError(f"ComfyUI workflow node not found: {node_id}")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}
        node["inputs"] = inputs
    return inputs


def _image_dimensions(image_data: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(image_data)) as image:
            return image.size
    except Exception:
        return 0, 0


def _target_dimensions(size: object, fallback: tuple[int, int]) -> tuple[int, int]:
    text = _clean(size).lower()
    numbers = [int(item) for item in __import__("re").findall(r"\d+", text)]
    if len(numbers) >= 2:
        return max(1, numbers[0]), max(1, numbers[1])
    return fallback


class ComfyUITextUpscaleService:
    def _settings(self) -> dict[str, object]:
        return config.get_comfyui_text_upscale_settings()

    def enabled(self) -> bool:
        settings = self._settings()
        return bool(settings.get("enabled"))

    def _session(self) -> requests.Session:
        return requests.Session()

    def _upload_image(self, session: requests.Session, base_url: str, image_data: bytes) -> str:
        filename = f"chatgpt2api_{int(time.time() * 1000)}.png"
        response = session.post(
            f"{base_url}/upload/image",
            files={"image": (filename, image_data, "image/png")},
            data={"overwrite": "true"},
            timeout=60,
        )
        if response.status_code >= 400:
            raise ComfyUIWorkflowError(f"ComfyUI upload failed: HTTP {response.status_code} {response.text[:200]}")
        payload = response.json()
        name = _clean(payload.get("name")) if isinstance(payload, dict) else ""
        if not name:
            raise ComfyUIWorkflowError("ComfyUI upload response missing image name")
        return name

    def _queue_prompt(self, session: requests.Session, base_url: str, workflow: dict[str, Any]) -> str:
        response = session.post(f"{base_url}/prompt", json={"prompt": workflow}, timeout=60)
        if response.status_code >= 400:
            raise ComfyUIWorkflowError(f"ComfyUI prompt failed: HTTP {response.status_code} {response.text[:300]}")
        payload = response.json()
        prompt_id = _clean(payload.get("prompt_id")) if isinstance(payload, dict) else ""
        if not prompt_id:
            raise ComfyUIWorkflowError("ComfyUI prompt response missing prompt_id")
        return prompt_id

    def _history(self, session: requests.Session, base_url: str, prompt_id: str) -> dict[str, Any] | None:
        response = session.get(f"{base_url}/history/{prompt_id}", timeout=30)
        if response.status_code >= 400:
            raise ComfyUIWorkflowError(f"ComfyUI history failed: HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        item = payload.get(prompt_id)
        return item if isinstance(item, dict) else None

    def _output_images(self, history: dict[str, Any], output_node: str) -> list[dict[str, Any]]:
        outputs = history.get("outputs")
        if not isinstance(outputs, dict):
            return []
        nodes = [output_node] if output_node else list(outputs.keys())
        images: list[dict[str, Any]] = []
        for node_id in nodes:
            node_output = outputs.get(str(node_id))
            if not isinstance(node_output, dict):
                continue
            node_images = node_output.get("images")
            if isinstance(node_images, list):
                images.extend(item for item in node_images if isinstance(item, dict))
        return images

    def _download_image(self, session: requests.Session, base_url: str, image: dict[str, Any]) -> bytes:
        params = {
            "filename": _clean(image.get("filename")),
            "subfolder": _clean(image.get("subfolder")),
            "type": _clean(image.get("type")) or "output",
        }
        if not params["filename"]:
            raise ComfyUIWorkflowError("ComfyUI output image missing filename")
        response = session.get(f"{base_url}/view?{urlencode(params)}", timeout=120)
        if response.status_code >= 400:
            raise ComfyUIWorkflowError(f"ComfyUI image download failed: HTTP {response.status_code}")
        return bytes(response.content)

    def enhance_text_image(self, image_data: bytes, *, prompt: str, size: object = None) -> bytes:
        settings = self._settings()
        if not settings.get("enabled"):
            raise ComfyUIWorkflowError("ComfyUI text upscale is disabled")
        base_url = _clean(settings.get("base_url")).rstrip("/")
        workflow_path = _resolve_workflow_path(settings.get("workflow_path"))
        workflow = _load_workflow(workflow_path)
        session = self._session()
        timeout_secs = int(settings.get("timeout_secs") or 300)
        poll_interval_secs = int(settings.get("poll_interval_secs") or 2)

        uploaded_name = self._upload_image(session, base_url, image_data)
        _node_inputs(workflow, _clean(settings.get("input_image_node")))[_clean(settings.get("input_image_field")) or "image"] = uploaded_name
        _node_inputs(workflow, _clean(settings.get("positive_prompt_node")))[_clean(settings.get("positive_prompt_field")) or "text"] = prompt

        size_node = _clean(settings.get("size_node"))
        if size_node:
            width, height = _target_dimensions(size, _image_dimensions(image_data))
            size_inputs = _node_inputs(workflow, size_node)
            size_inputs[_clean(settings.get("width_field")) or "width"] = width
            size_inputs[_clean(settings.get("height_field")) or "height"] = height

        detail = {
            "event": "comfyui_text_upscale_submit",
            "base_url": base_url,
            "workflow_path": str(workflow_path),
            "uploaded_image": uploaded_name,
            "requested_size": _clean(size),
        }
        logger.info(detail)
        _write_log("ComfyUI文字增强提交", detail)

        prompt_id = self._queue_prompt(session, base_url, workflow)
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            history = self._history(session, base_url, prompt_id)
            if history:
                images = self._output_images(history, _clean(settings.get("output_node")))
                if images:
                    payload = self._download_image(session, base_url, images[0])
                    done_detail = {
                        "event": "comfyui_text_upscale_done",
                        "prompt_id": prompt_id,
                        "output_bytes": len(payload),
                    }
                    logger.info(done_detail)
                    _write_log("ComfyUI文字增强完成", done_detail)
                    return payload
                status = history.get("status")
                if isinstance(status, dict) and status.get("status_str") == "error":
                    raise ComfyUIWorkflowError(f"ComfyUI workflow failed: {status}")
            time.sleep(poll_interval_secs)
        raise ComfyUIWorkflowError(f"ComfyUI workflow timed out after {timeout_secs}s")


comfyui_text_upscale_service = ComfyUITextUpscaleService()
