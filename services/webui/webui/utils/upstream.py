"""HTTP client toward the grain domain service (app)."""

from collections.abc import AsyncIterator

import httpx

from webui.settings import APP_UPSTREAM_BASE_URL, OPENAI_COMPAT_API_KEY


def service_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {OPENAI_COMPAT_API_KEY}"}
    if extra:
        headers.update(extra)
    return headers


def build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=APP_UPSTREAM_BASE_URL,
        timeout=httpx.Timeout(120.0, connect=10.0),
    )


async def get_json(path: str) -> httpx.Response:
    async with build_client() as client:
        response = await client.get(path, headers=service_headers())
        return response


async def stream_post(
    path: str, *, json_body: dict, headers: dict[str, str]
) -> AsyncIterator[bytes]:
    """Yield raw upstream bytes; caller owns framing. Test hook: 替换 build_client。"""
    async with build_client() as client:
        async with client.stream(
            "POST", path, json=json_body, headers=headers
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk
