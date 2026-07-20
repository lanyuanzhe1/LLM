import base64
import json
import traceback

import httpx
import numpy as np
import pytest

from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.core.errors import ProviderUnavailable


@pytest.mark.asyncio
async def test_embedding_request_has_digest_prefix_and_decodes_float32():
    seen: dict[str, str] = {}
    vector = np.array([0.25, 0.75], dtype="<f4")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["digest"] = request.headers["Digest"]
        seen["authorization"] = request.headers["Authorization"]
        body = json.loads(request.content)
        assert body["parameter"]["emb"]["domain"] == "query"
        return httpx.Response(
            200,
            json={
                "header": {"code": 0, "message": "success"},
                "payload": {
                    "feature": {
                        "text": base64.b64encode(vector.tobytes()).decode()
                    }
                },
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://emb-cn-huabei-1.xf-yun.com/",
        timeout_seconds=1,
        http=http,
    )

    result = await client.embed("测试", domain="query")

    assert seen["digest"].startswith("SHA-256=")
    assert 'algorithm="hmac-sha256"' in seen["authorization"]
    np.testing.assert_allclose(result, vector)
    await http.aclose()


@pytest.mark.asyncio
async def test_embedding_retries_transient_503():
    attempts = 0
    vector = np.array([1.0, 0.0], dtype="<f4")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporary")
        return httpx.Response(
            200,
            json={
                "header": {"code": 0, "message": "success"},
                "payload": {
                    "feature": {
                        "text": base64.b64encode(vector.tobytes()).decode()
                    }
                },
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=2,
    )

    result = await client.embed("测试", domain="query")

    assert attempts == 2
    np.testing.assert_allclose(result, vector)
    await http.aclose()


@pytest.mark.asyncio
async def test_embedding_maps_provider_code_to_stable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"header": {"code": 10001, "message": "bad request"}}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=1,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.embed("测试", domain="query")

    assert exc.value.code == "EMBEDDING_UNAVAILABLE"
    await http.aclose()


@pytest.mark.asyncio
async def test_embedding_retries_remote_protocol_error():
    attempts = 0
    vector = np.array([0.5, 0.5], dtype="<f4")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("connection closed", request=request)
        return httpx.Response(
            200,
            json={
                "header": {"code": 0, "message": "success"},
                "payload": {
                    "feature": {
                        "text": base64.b64encode(vector.tobytes()).decode()
                    }
                },
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=2,
    )

    result = await client.embed("测试", domain="query")

    assert attempts == 2
    np.testing.assert_allclose(result, vector)
    await http.aclose()


@pytest.mark.asyncio
async def test_embedding_maps_exhausted_remote_protocol_error():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.RemoteProtocolError("connection closed", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=2,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.embed("测试", domain="query")

    assert attempts == 2
    assert exc.value.code == "EMBEDDING_UNAVAILABLE"
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_body",
    [
        {"header": []},
        {"header": {"code": 0}, "payload": None},
    ],
)
async def test_embedding_maps_malformed_response_shape(response_body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=1,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.embed("测试", domain="query")

    assert exc.value.code == "EMBEDDING_UNAVAILABLE"
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_kind",
    ["provider_message", "http_body", "exception"],
)
async def test_embedding_failure_never_exposes_provider_sentinels(
    failure_kind,
):
    sentinel = f"RAW_EMBEDDING_{failure_kind.upper()}_SECRET"

    def handler(request: httpx.Request) -> httpx.Response:
        if failure_kind == "provider_message":
            return httpx.Response(
                200,
                json={
                    "header": {
                        "code": 10001,
                        "message": sentinel,
                    }
                },
            )
        if failure_kind == "http_body":
            return httpx.Response(418, text=sentinel)
        raise ValueError(sentinel)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=1,
    )

    with pytest.raises(ProviderUnavailable) as caught:
        await client.embed("测试", domain="query")

    error = caught.value
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    assert error.code == "EMBEDDING_UNAVAILABLE"
    assert error.message == "向量化服务暂时不可用"
    assert error.details == {}
    assert error.__cause__ is None
    assert error.__context__ is None
    assert sentinel not in str(error)
    assert sentinel not in rendered
    await http.aclose()
