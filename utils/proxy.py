from __future__ import annotations

import httpx
from typing import Optional

PROXY_URL = "http://192.168.0.1:8090"

_PROXY_CONFIG: dict[str, str] = {
    "http://": PROXY_URL,
    "https://": PROXY_URL,
}


def get_proxy_dict() -> dict[str, str]:
    return dict(_PROXY_CONFIG)


def create_async_client(
    timeout: float = 30.0,
    proxy_enabled: bool = True,
    **kwargs,
) -> httpx.AsyncClient:
    proxy = PROXY_URL if proxy_enabled else None
    try:
        return httpx.AsyncClient(
            proxy=proxy,
            timeout=httpx.Timeout(timeout),
            **kwargs,
        )
    except TypeError:
        return httpx.AsyncClient(
            proxies=_PROXY_CONFIG if proxy_enabled else None,
            timeout=httpx.Timeout(timeout),
            **kwargs,
        )


def create_sync_client(
    timeout: float = 30.0,
    proxy_enabled: bool = True,
    **kwargs,
) -> httpx.Client:
    proxy = PROXY_URL if proxy_enabled else None
    try:
        return httpx.Client(
            proxy=proxy,
            timeout=httpx.Timeout(timeout),
            **kwargs,
        )
    except TypeError:
        return httpx.Client(
            proxies=_PROXY_CONFIG if proxy_enabled else None,
            timeout=httpx.Timeout(timeout),
            **kwargs,
        )
