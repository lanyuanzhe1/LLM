import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.clients.iflytek_chatdoc import IflytekChatDocClient
from app.core.errors import ProviderUnavailable


def _response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_auth_headers_use_chatdoc_md5_hmac_sha1_scheme():
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: _response({}))),
    )

    headers = client.auth_headers(datetime(2026, 8, 27, tzinfo=timezone.utc))

    timestamp = str(int(datetime(2026, 8, 27, tzinfo=timezone.utc).timestamp()))
    auth = hashlib.md5(("app-id" + timestamp).encode()).hexdigest()
    expected = base64.b64encode(
        hmac.new(b"secret", auth.encode(), hashlib.sha1).digest()
    ).decode()
    assert headers == {
        "appId": "app-id",
        "timeStamp": timestamp,
        "signature": expected,
    }


@pytest.mark.asyncio
async def test_search_enables_hybrid_retrieval_and_validates_hits():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return _response(
            {
                "code": 0,
                "data": [
                    {
                        "content": "低温能够抑制粮食呼吸。",
                        "score": 83.5,
                        "fileId": "file-1",
                        "index": 7,
                        "type": "vector",
                    }
                ],
            }
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    hits = await client.search(repo_id="repo-1", query="低温储粮", top_n=8)

    assert captured["path"] == "/openapi/v1/vector/search"
    assert captured["payload"] == {
        "repoIds": ["repo-1"],
        "topN": 8,
        "esTopN": 8,
        "content": "低温储粮",
        "es": True,
        "embedding": True,
        "reRank": True,
        "chatExtends": {"retrievalFilterPolicy": "REGULAR"},
    }
    assert hits[0].file_id == "file-1"
    assert hits[0].content == "低温能够抑制粮食呼吸。"
    assert hits[0].score == 83.5
    assert hits[0].index == 7
    await http.aclose()


@pytest.mark.asyncio
async def test_upload_status_repo_and_batch_add_follow_official_endpoints(tmp_path):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.method))
        if request.url.path.endswith("/repo/create"):
            return _response({"code": 0, "data": "repo-1"})
        if request.url.path.endswith("/file/upload"):
            return _response({"code": 0, "data": {"fileId": "file-1"}})
        if request.url.path.endswith("/file/status"):
            return _response(
                {"code": 0, "data": [{"fileId": "file-1", "fileStatus": "vectored"}]}
            )
        if request.url.path.endswith("/repo/file/add"):
            return _response({"code": 0, "data": None})
        raise AssertionError(request.url.path)

    document = tmp_path / "sample.pdf"
    document.write_bytes(b"%PDF-test")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    repo_id = await client.create_repo("repo", "desc")
    file_id = await client.upload_file(document, upload_name="source.pdf")
    statuses = await client.file_statuses([file_id])
    await client.add_files(repo_id, [file_id])

    assert repo_id == "repo-1"
    assert statuses == {"file-1": "vectored"}
    assert calls == [
        ("/openapi/v1/repo/create", "POST"),
        ("/openapi/v1/file/upload", "POST"),
        ("/openapi/v1/file/status", "POST"),
        ("/openapi/v1/repo/file/add", "POST"),
    ]
    await http.aclose()


@pytest.mark.asyncio
async def test_business_error_is_redacted_as_provider_unavailable():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _response({"code": 10013, "desc": "secret upstream detail"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
        max_retries=1,
    )

    with pytest.raises(ProviderUnavailable) as exc_info:
        await client.search(repo_id="repo", query="query", top_n=5)

    assert exc_info.value.code == "CHATDOC_UNAVAILABLE_10013"
    assert "secret upstream detail" not in str(exc_info.value)
    await http.aclose()


@pytest.mark.asyncio
async def test_repo_file_list_hits_endpoint_and_unwraps_rows():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return _response(
            {
                "code": 0,
                "data": {
                    "total": 1,
                    "rows": [
                        {
                            "fileId": "file-1",
                            "fileName": "低温储粮.pdf",
                            "fileStatus": "vectored",
                            "quantity": 24,
                        }
                    ],
                },
            }
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    rows = await client.repo_file_list(repo_id="repo-1")

    assert captured["path"] == "/openapi/v1/repo/file/list"
    assert captured["payload"] == {
        "repoId": "repo-1",
        "currentPage": 1,
        "pageSize": 500,
    }
    assert rows == [
        {
            "fileId": "file-1",
            "fileName": "低温储粮.pdf",
            "fileStatus": "vectored",
            "quantity": 24,
        }
    ]
    await http.aclose()


@pytest.mark.asyncio
async def test_repo_file_list_accepts_plain_array_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "code": 0,
                "data": [
                    {"fileId": "file-1", "fileName": "低温储粮.pdf", "fileStatus": "vectored"}
                ],
            }
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    rows = await client.repo_file_list(repo_id="repo-1")

    assert rows == [{"fileId": "file-1", "fileName": "低温储粮.pdf", "fileStatus": "vectored"}]
    await http.aclose()


@pytest.mark.asyncio
async def test_repo_file_list_rejects_malformed_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _response({"code": 0, "data": {"rows": "not-a-list"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    with pytest.raises(ProviderUnavailable) as exc_info:
        await client.repo_file_list(repo_id="repo-1")

    assert exc_info.value.code == "CHATDOC_PROTOCOL_ERROR"
    await http.aclose()


@pytest.mark.asyncio
async def test_file_chunks_hits_endpoint_with_form_data_and_returns_typed_chunks():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["form"] = request.content.decode()
        return _response(
            {
                "code": 0,
                "data": [
                    {"dataType": "wiki", "dataIndex": 1, "content": "低温抑制呼吸。"},
                    {"dataType": "wiki", "dataIndex": 0, "content": "仓储管理基础。"},
                ],
            }
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    chunks = await client.file_chunks(file_id="file-1")

    assert captured["path"] == "/openapi/v1/file/chunks"
    assert "fileId=file-1" in captured["form"]
    assert [(c.index, c.content) for c in chunks] == [
        (1, "低温抑制呼吸。"),
        (0, "仓储管理基础。"),
    ]
    await http.aclose()


@pytest.mark.asyncio
async def test_file_chunks_strips_surrounding_whitespace():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "code": 0,
                "data": [
                    {"dataType": "wiki", "dataIndex": 0, "content": "  低温抑制呼吸。\r\n"}
                ],
            }
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    chunks = await client.file_chunks(file_id="file-1")

    assert chunks[0].content == "低温抑制呼吸。"
    await http.aclose()


@pytest.mark.asyncio
async def test_file_chunks_rejects_item_without_content():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "code": 0,
                "data": [{"dataType": "wiki", "dataIndex": 0, "content": ""}],
            }
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekChatDocClient(
        app_id="app-id",
        api_secret="secret",
        base_url="https://chatdoc.example",
        timeout_seconds=10,
        http=http,
    )

    with pytest.raises(ProviderUnavailable) as exc_info:
        await client.file_chunks(file_id="file-1")

    assert exc_info.value.code == "CHATDOC_PROTOCOL_ERROR"
    await http.aclose()
