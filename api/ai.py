from __future__ import annotations

import json

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from api.image_inputs import parse_image_edit_request, read_image_sources
from api.support import consume_identity_quota, require_identity, resolve_api_authorization, resolve_image_base_url
from services.content_filter import check_request, request_shape, request_text
from services.editable_file_task_service import editable_file_task_service
from services.image_task_service import image_task_service
from services.log_service import LoggedCall, image_request_params
from services.protocol import (
    anthropic_v1_messages,
    openai_v1_chat_complete,
    openai_v1_image_edit,
    openai_v1_image_generations,
    openai_v1_models,
    openai_v1_response,
    openai_search,
)
from utils.helper import extract_response_prompt, has_response_image_generation_tool, is_image_chat_request


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    quality: str = "auto"
    response_format: str = "url"
    history_disabled: bool = True
    stream: bool | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    prompt: str | None = None
    n: int | None = None
    stream: bool | None = None
    modalities: list[str] | None = None
    messages: list[dict[str, object]] | None = None


class ResponseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    input: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None


class AnthropicMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict[str, object]] | None = None
    system: object | None = None
    stream: bool | None = None


class SearchRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class EditableFileTaskRequest(BaseModel):
    prompt: str = ""
    base64_images: list[str] = Field(default_factory=list)
    client_task_id: str | None = None


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("调用失败", status="failed", error=str(exc.detail))
        raise


def _response_error_text(result: object) -> str:
    if not isinstance(result, Response):
        return ""
    status_code = int(getattr(result, "status_code", 200) or 200)
    if status_code < 400:
        return ""
    body = getattr(result, "body", b"")
    if isinstance(body, bytes) and body:
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail")
            error = payload.get("error")
            for item in (detail, error, payload):
                if isinstance(item, str) and item:
                    return item
                if isinstance(item, dict):
                    message = item.get("message") or item.get("error")
                    if isinstance(message, str) and message:
                        return message
        text = body.decode("utf-8", errors="replace").strip()
        if text:
            return text[:500]
    return f"HTTP {status_code}"


def _finish_sync_image_task(
    task_key: str,
    identity: dict[str, object],
    *,
    mode: str,
    model: str,
    started: float,
    request_preview: str = "",
    request_params: dict[str, object] | None = None,
    result: object = None,
    error: str = "",
) -> None:
    if not task_key:
        return
    error_text = error or _response_error_text(result)
    if error_text:
        image_task_service.finish_sync_task(
            task_key,
            identity,
            mode=mode,
            model=model,
            started=started,
            request_preview=request_preview,
            request_params=request_params,
            error=error_text,
            account_email=str(getattr(result, "account_email", "") or ""),
            conversation_id=str(getattr(result, "conversation_id", "") or ""),
        )
        return
    if isinstance(result, dict):
        image_task_service.finish_sync_task(
            task_key,
            identity,
            mode=mode,
            model=model,
            started=started,
            request_preview=request_preview,
            request_params=request_params,
            result_data=result,
            account_email=str(result.get("_account_email") or result.get("account_email") or ""),
            conversation_id=str(result.get("_conversation_id") or result.get("conversation_id") or ""),
        )
        return
    image_task_service.finish_sync_task(
        task_key,
        identity,
        mode=mode,
        model=model,
        started=started,
        request_preview=request_preview,
        request_params=request_params,
        result_data={},
    )


async def _run_with_sync_image_task(
    call: LoggedCall,
    handler,
    payload: dict[str, object],
    identity: dict[str, object],
    *,
    mode: str,
    model: str,
    request_preview: str,
    request_params: dict[str, object] | None,
    size: object = None,
    quality: object = "auto",
    stream: bool = False,
):
    task_started = __import__("time").time()
    task_key = ""
    if not stream:
        task_key, _ = image_task_service.begin_sync_task(
            identity,
            mode=mode,
            model=model,
            size=str(size or "").strip() or None,
            quality=str(quality or "auto"),
            request_preview=request_preview,
            request_params=request_params,
        )
        payload["progress_callback"] = lambda step: image_task_service.update_sync_task_progress(task_key, step)
    try:
        result = await call.run(handler, payload)
    except Exception as exc:
        _finish_sync_image_task(
            task_key,
            identity,
            mode=mode,
            model=model,
            started=task_started,
            request_preview=request_preview,
            request_params=request_params,
            error=str(exc),
        )
        raise
    if not isinstance(result, StreamingResponse):
        _finish_sync_image_task(
            task_key,
            identity,
            mode=mode,
            model=model,
            started=task_started,
            request_preview=request_preview,
            request_params=request_params,
            result=result,
        )
    return result


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models(
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        try:
            return await run_in_threadpool(openai_v1_models.list_models)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        payload = body.model_dump(mode="python")
        consume_identity_quota(
            identity,
            endpoint="/v1/images/generations",
            model=body.model,
            image_units=body.n,
        )
        payload["base_url"] = resolve_image_base_url(request)
        request_preview = body.prompt
        request_params = image_request_params(payload)
        call = LoggedCall(
            identity,
            "/v1/images/generations",
            body.model,
            "文生图",
            request_text=request_preview,
            request_params=request_params,
        )
        return await _run_with_sync_image_task(
            call,
            openai_v1_image_generations.handle,
            payload,
            identity,
            mode="generate",
            model=body.model,
            request_preview=request_preview,
            request_params=request_params,
            size=body.size,
            quality=body.quality,
            stream=bool(body.stream),
        )

    @router.post("/v1/images/edits")
    async def edit_images(
            request: Request,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        payload, image_sources, mask_sources = await parse_image_edit_request(request)
        prompt = str(payload["prompt"])
        model = str(payload["model"])
        consume_identity_quota(
            identity,
            endpoint="/v1/images/edits",
            model=model,
            image_units=int(payload.get("n") or 1),
        )
        call = LoggedCall(
            identity,
            "/v1/images/edits",
            model,
            "图生图",
            request_text=prompt,
            request_params=image_request_params(payload),
        )
        payload["images"] = await read_image_sources(image_sources)
        if mask_sources:
            payload["mask"] = await read_image_sources(mask_sources)
        payload["base_url"] = resolve_image_base_url(request)
        request_params = image_request_params(payload)
        return await _run_with_sync_image_task(
            call,
            openai_v1_image_edit.handle,
            payload,
            identity,
            mode="edit",
            model=model,
            request_preview=prompt,
            request_params=request_params,
            size=payload.get("size"),
            quality=payload.get("quality"),
            stream=bool(payload.get("stream")),
        )

    @router.post("/v1/chat/completions")
    async def create_chat_completion(
            body: ChatCompletionRequest,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        consume_identity_quota(identity, endpoint="/v1/chat/completions", model=model)
        request_preview = request_text(payload.get("prompt"), payload.get("messages"))
        call = LoggedCall(
            identity,
            "/v1/chat/completions",
            model,
            "文本生成",
            request_text=request_preview,
            request_shape=request_shape(payload.get("messages")),
        )
        await filter_or_log(call, request_preview)
        if is_image_chat_request(payload):
            return await _run_with_sync_image_task(
                call,
                openai_v1_chat_complete.handle,
                payload,
                identity,
                mode="edit" if any(openai_v1_chat_complete.chat_image_args(payload)[3]) else "generate",
                model=model,
                request_preview=request_preview,
                request_params=image_request_params(payload),
                size=payload.get("size"),
                quality=payload.get("quality"),
                stream=bool(payload.get("stream")),
            )
        return await call.run(openai_v1_chat_complete.handle, payload)

    @router.post("/v1/responses")
    async def create_response(
            body: ResponseCreateRequest,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        consume_identity_quota(identity, endpoint="/v1/responses", model=model)
        request_preview = request_text(payload.get("input"), payload.get("instructions"))
        call = LoggedCall(
            identity,
            "/v1/responses",
            model,
            "Responses",
            request_text=request_preview,
            request_shape=request_shape(payload.get("input")),
        )
        await filter_or_log(call, request_preview)
        if has_response_image_generation_tool(payload):
            tool = openai_v1_response.response_image_tool(payload)
            return await _run_with_sync_image_task(
                call,
                openai_v1_response.handle,
                payload,
                identity,
                mode="edit" if openai_v1_response.extract_response_image(payload.get("input")) else "generate",
                model=model,
                request_preview=request_preview or extract_response_prompt(payload.get("input")),
                request_params=image_request_params({"size": tool.get("size"), "quality": tool.get("quality"), "stream": payload.get("stream")}),
                size=tool.get("size"),
                quality=tool.get("quality"),
                stream=bool(payload.get("stream")),
            )
        return await call.run(openai_v1_response.handle, payload)

    @router.post("/v1/messages")
    async def create_message(
            body: AnthropicMessageRequest,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
            anthropic_version: str | None = Header(default=None, alias="anthropic-version"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        consume_identity_quota(identity, endpoint="/v1/messages", model=model)
        request_preview = request_text(payload.get("system"), payload.get("messages"), payload.get("tools"))
        call = LoggedCall(identity, "/v1/messages", model, "Messages", request_text=request_preview)
        await filter_or_log(call, request_preview)
        return await call.run(anthropic_v1_messages.handle, payload, sse="anthropic")

    @router.post("/v1/search")
    async def search(
            body: SearchRequest,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        consume_identity_quota(identity, endpoint="/v1/search", model=openai_search.MODEL)
        call = LoggedCall(identity, "/v1/search", openai_search.MODEL, "搜索", request_text=body.prompt)
        await filter_or_log(call, body.prompt)
        return await call.run(openai_search.handle, body.model_dump(mode="python"))

    @router.get("/v1/editable-file-tasks")
    async def list_editable_file_tasks(
            ids: str = "",
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        consume_identity_quota(identity, endpoint="/v1/editable-file-tasks")
        task_ids = [item.strip() for item in ids.split(",") if item.strip()]
        return await run_in_threadpool(editable_file_task_service.list_tasks, identity, task_ids)

    @router.get("/files/{file_path:path}")
    async def download_editable_file(file_path: str):
        try:
            path = await run_in_threadpool(editable_file_task_service.public_file_path, file_path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail={"error": "file not found"}) from exc
        return FileResponse(path, filename=path.name)

    @router.post("/v1/ppt/generations")
    async def create_ppt_task(
            body: EditableFileTaskRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        consume_identity_quota(identity, endpoint="/v1/ppt/generations", model="gpt-5-5-thinking")
        await filter_or_log(LoggedCall(identity, "/v1/ppt/generations", "gpt-5-5-thinking", "PPT生成任务", request_text=body.prompt), body.prompt)
        return await run_in_threadpool(
            editable_file_task_service.submit_ppt,
            identity,
            client_task_id=body.client_task_id or "",
            prompt=body.prompt,
            base64_images=body.base64_images,
            base_url=resolve_image_base_url(request),
        )

    @router.post("/v1/psd/generations")
    async def create_psd_task(
            body: EditableFileTaskRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            api_key: str | None = Header(default=None, alias="api-key"),
    ):
        identity = require_identity(resolve_api_authorization(authorization, x_api_key, api_key))
        consume_identity_quota(identity, endpoint="/v1/psd/generations", model="gpt-5-5-thinking")
        await filter_or_log(LoggedCall(identity, "/v1/psd/generations", "gpt-5-5-thinking", "PSD生成任务", request_text=body.prompt), body.prompt)
        return await run_in_threadpool(
            editable_file_task_service.submit_psd,
            identity,
            client_task_id=body.client_task_id or "",
            prompt=body.prompt,
            base64_images=body.base64_images,
            base_url=resolve_image_base_url(request),
        )

    return router
