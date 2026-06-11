from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from api.support import require_identity
from services.openai_backend_api import OpenAIBackendAPI


class ChatGPTWebDebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = Field(default="GET")
    path: str = Field(..., min_length=1)
    access_token: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    bootstrap: bool = True


def _normalize_debug_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("path is required")
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlsplit(raw)
        if parsed.netloc != "chatgpt.com":
            raise ValueError("only chatgpt.com URLs are allowed")
        raw = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    if not raw.startswith("/"):
        raw = "/" + raw
    if not (raw.startswith("/backend-api/") or raw.startswith("/backend-anon/")):
        raise ValueError("path must start with /backend-api/ or /backend-anon/")
    return raw


def _safe_response_body(response: object) -> Any:
    try:
        return response.json()  # type: ignore[attr-defined]
    except Exception:
        text = str(getattr(response, "text", "") or "")
        return text[:20000]


def _debug_chatgpt_web(body: ChatGPTWebDebugRequest) -> dict[str, Any]:
    method = str(body.method or "GET").strip().upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("method must be GET, POST, PUT, PATCH, or DELETE")
    path = _normalize_debug_path(body.path)
    api = OpenAIBackendAPI(str(body.access_token or "").strip())
    if body.bootstrap:
        api._bootstrap()

    headers = api._headers(path, {str(k): str(v) for k, v in body.headers.items() if str(k).strip()})
    started = time.perf_counter()
    request_kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": int(body.timeout_seconds),
    }
    if method in {"POST", "PUT", "PATCH", "DELETE"} and body.body is not None:
        request_kwargs["json"] = body.body
    response = api.session.request(method, api.base_url + path, **request_kwargs)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    response_headers = {
        str(key): str(value)
        for key, value in getattr(response, "headers", {}).items()
        if str(key).lower() in {"content-type", "date", "server", "cf-ray", "openai-version"}
    }
    return {
        "ok": 200 <= int(response.status_code) < 400,
        "status": int(response.status_code),
        "elapsed_ms": elapsed_ms,
        "method": method,
        "url": api.base_url + path,
        "request_headers": {
            "X-OpenAI-Target-Path": headers.get("X-OpenAI-Target-Path"),
            "X-OpenAI-Target-Route": headers.get("X-OpenAI-Target-Route"),
            "Authorization": "Bearer ***" if headers.get("Authorization") else None,
        },
        "response_headers": response_headers,
        "body": _safe_response_body(response),
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/debug/chatgpt-web")
    async def debug_chatgpt_web(body: ChatGPTWebDebugRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin required")
        try:
            return await run_in_threadpool(_debug_chatgpt_web, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

    return router
