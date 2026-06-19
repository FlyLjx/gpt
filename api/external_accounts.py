from __future__ import annotations

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from api.support import require_admin, resolve_api_authorization
from services.account_service import account_service


class ExternalAccountImportRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    accounts: list[dict[str, object]] = Field(default_factory=list)
    refresh: bool = True
    source_type: str = "external_api"


def _account_payload_token(item: dict[str, object]) -> str:
    return str(item.get("access_token") or item.get("accessToken") or "").strip()


def _unique_tokens(tokens: list[str]) -> list[str]:
    return list(dict.fromkeys(str(token or "").strip() for token in tokens if str(token or "").strip()))


def create_router() -> APIRouter:
    router = APIRouter(tags=["external-accounts"])

    @router.get("/api/external/accounts/summary")
    async def get_external_accounts_summary(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None, alias="x-api-key"),
        api_key: str | None = Query(default=None),
    ):
        require_admin(resolve_api_authorization(authorization, x_api_key, api_key))
        summary = account_service.account_health()
        return {
            "ok": True,
            "valid_account_count": int(summary.get("active") or 0),
            "healthy": bool(summary.get("healthy")),
            "status": str(summary.get("status") or ""),
            "summary": summary,
        }

    @router.post("/api/external/accounts/import")
    async def import_external_accounts(
        body: ExternalAccountImportRequest,
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None, alias="x-api-key"),
        api_key: str | None = Query(default=None),
    ):
        require_admin(resolve_api_authorization(authorization, x_api_key, api_key))

        account_payloads = [item for item in body.accounts if isinstance(item, dict)]
        payload_tokens = [_account_payload_token(item) for item in account_payloads]
        tokens = _unique_tokens([*body.tokens, *payload_tokens])

        result = {"added": 0, "skipped": 0, "items": account_service.list_accounts()}
        if account_payloads:
            result = account_service.add_account_items(account_payloads)
            payload_token_set = set(_unique_tokens(payload_tokens))
            extra_tokens = [token for token in tokens if token not in payload_token_set]
            if extra_tokens:
                extra_result = account_service.add_accounts(extra_tokens, source_type=body.source_type)
                result["added"] = int(result.get("added") or 0) + int(extra_result.get("added") or 0)
                result["skipped"] = int(result.get("skipped") or 0) + int(extra_result.get("skipped") or 0)
                result["items"] = extra_result.get("items", result.get("items", []))
        elif tokens:
            result = account_service.add_accounts(tokens, source_type=body.source_type)

        refresh_result = {"refreshed": 0, "errors": [], "items": result.get("items", [])}
        if body.refresh and tokens:
            refresh_result = account_service.refresh_accounts(tokens)

        summary = account_service.account_health()
        return {
            "ok": True,
            "added": int(result.get("added") or 0),
            "skipped": int(result.get("skipped") or 0),
            "refreshed": int(refresh_result.get("refreshed") or 0),
            "errors": refresh_result.get("errors", []),
            "valid_account_count": int(summary.get("active") or 0),
            "healthy": bool(summary.get("healthy")),
            "status": str(summary.get("status") or ""),
            "items": refresh_result.get("items", result.get("items", [])),
        }

    return router
