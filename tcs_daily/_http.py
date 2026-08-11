"""Minimal HTTP helpers with TLS and user-agent handling."""

from __future__ import annotations

import os
import ssl
import time
from http.client import IncompleteRead
from urllib.error import URLError
from urllib.request import Request, urlopen

import certifi

UA = "tcs-daily/0.2 (+https://bzy.moe/tcs-daily)"


def _ssl_ctx() -> ssl.SSLContext:
    if os.environ.get("TCS_DAILY_INSECURE_SSL") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context(cafile=certifi.where())


def get(url: str, *, timeout: int = 30, retries: int = 3) -> bytes:
    """HTTP GET with retries and exponential backoff."""
    last_exc: Exception | None = None
    partial = b""
    for attempt in range(retries):
        try:
            headers = {"User-Agent": UA}
            if partial:
                headers["Range"] = f"bytes={len(partial)}-"
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
                prefix = partial if partial and getattr(resp, "status", None) == 206 else b""
                partial = prefix
                try:
                    return prefix + resp.read()
                except IncompleteRead as exc:
                    partial = prefix + exc.partial
                    last_exc = exc
        except IncompleteRead as exc:
            partial += exc.partial
            last_exc = exc
        except (URLError, OSError, TimeoutError) as exc:
            last_exc = exc
        if attempt < retries - 1:
            wait = 2 ** attempt  # 1s, 2s, 4s …
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def get_text(url: str, *, timeout: int = 30) -> str:
    return get(url, timeout=timeout).decode("utf-8", "ignore")
