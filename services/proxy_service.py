"""Global outbound proxy helpers for upstream ChatGPT and CPA requests."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from curl_cffi.requests import Session

from services.config import config


class ProxySettingsStore:
    def build_session_kwargs(self, account: dict | None = None, proxy: str = "", **session_kwargs) -> dict[str, object]:
        account_proxy = str((account or {}).get("proxy") or "").strip()
        proxy = str(proxy or account_proxy or config.get_proxy_settings()).strip()
        if proxy:
            session_kwargs["proxy"] = proxy
        return session_kwargs


def _clean(value: object) -> str:
    return str(value or "").strip()


def _is_valid_proxy_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https", "socks5", "socks5h"} and bool(parsed.netloc)


def _is_urllib_proxy_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def get_urllib_proxy_error(proxy: str = "", account: dict | None = None) -> str:
    candidate = _clean(proxy or (account or {}).get("proxy") or config.get_proxy_settings())
    if not candidate:
        return ""
    if not _is_urllib_proxy_url(candidate):
        return "Codex urllib path only supports http/https proxy; use http://host:port for Codex image requests"
    return ""


def build_urllib_opener(proxy: str = "", account: dict | None = None) -> urllib.request.OpenerDirector:
    candidate = _clean(proxy or (account or {}).get("proxy") or config.get_proxy_settings())
    if not candidate or get_urllib_proxy_error(candidate):
        return urllib.request.build_opener()
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": candidate, "https": candidate}))


def _lookup_exit_ip(session: Session, *, timeout: float) -> dict[str, str]:
    try:
        response = session.get(
            "https://ipinfo.io/json",
            headers={"user-agent": "Mozilla/5.0 (chatgpt2api proxy geo test)"},
            timeout=timeout,
        )
        if response.status_code >= 400:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            return {}
        return {
            "ip": _clean(data.get("ip")),
            "country": _clean(data.get("country")),
            "region": _clean(data.get("region")),
            "city": _clean(data.get("city")),
            "org": _clean(data.get("org")),
            "timezone": _clean(data.get("timezone")),
        }
    except Exception:
        return {}


def _test_chatgpt_with_curl(url: str, *, timeout: float) -> dict:
    session = Session(impersonate="edge101", verify=True, proxy=url)
    started = time.perf_counter()
    try:
        response = session.get(
            "https://chatgpt.com/api/auth/csrf",
            headers={"user-agent": "Mozilla/5.0 (chatgpt2api proxy test)"},
            timeout=timeout,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": response.status_code < 500,
            "status": int(response.status_code),
            "latency_ms": latency_ms,
            "url": "https://chatgpt.com/api/auth/csrf",
            "error": None if response.status_code < 500 else f"HTTP {response.status_code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "url": "https://chatgpt.com/api/auth/csrf",
            "error": str(exc) or exc.__class__.__name__,
        }
    finally:
        session.close()


def _test_chatgpt_with_urllib(url: str, *, timeout: float) -> dict:
    started = time.perf_counter()
    target = "https://chatgpt.com/api/auth/csrf"
    if not _is_urllib_proxy_url(url):
        return {
            "ok": False,
            "status": 0,
            "latency_ms": 0,
            "url": target,
            "error": get_urllib_proxy_error(url),
        }
    request = urllib.request.Request(target, headers={"user-agent": "Mozilla/5.0 (chatgpt2api urllib proxy test)"})
    opener = build_urllib_opener(url)
    try:
        with opener.open(request, timeout=timeout) as response:
            return {
                "ok": int(getattr(response, "status", 0) or 0) < 500,
                "status": int(getattr(response, "status", 0) or 0),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "url": target,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        status = int(exc.code or 0)
        return {
            "ok": status < 500,
            "status": status,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "url": target,
            "error": None if status < 500 else f"HTTP {status}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "url": target,
            "error": str(exc) or exc.__class__.__name__,
        }


def test_proxy(url: str, *, timeout: float = 15.0) -> dict:
    candidate = _clean(url)
    if not candidate:
        return {"ok": False, "status": 0, "latency_ms": 0, "error": "proxy url is required"}
    if not _is_valid_proxy_url(candidate):
        return {"ok": False, "status": 0, "latency_ms": 0, "error": "invalid proxy url"}
    started = time.perf_counter()
    chatgpt = _test_chatgpt_with_curl(candidate, timeout=timeout)
    urllib_chatgpt = _test_chatgpt_with_urllib(candidate, timeout=timeout)
    exit_session = Session(impersonate="edge101", verify=True, proxy=candidate)
    try:
        exit_ip = _lookup_exit_ip(exit_session, timeout=min(timeout, 8.0))
    finally:
        exit_session.close()
    ok = bool(chatgpt.get("ok")) and bool(urllib_chatgpt.get("ok"))
    error = None
    if not ok:
        failed = urllib_chatgpt if not urllib_chatgpt.get("ok") else chatgpt
        error = str(failed.get("error") or "chatgpt.com connection failed")
    return {
        "ok": ok,
        "status": int(chatgpt.get("status") or urllib_chatgpt.get("status") or 0),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "exit_ip": exit_ip,
        "chatgpt": chatgpt,
        "urllib_chatgpt": urllib_chatgpt,
        "error": error,
    }

proxy_settings = ProxySettingsStore()

