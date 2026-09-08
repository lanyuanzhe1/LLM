"""Webui read-only knowledge proxy tests.

Both routes are login-gated and forward the app service key; upstream
404/503 status and body pass through unchanged.
"""

import httpx

from webui.utils import upstream


def _signed_in(client) -> str:
    client.post(
        "/api/v1/auths/signup",
        json={"name": "甲", "email": "a@example.com", "password": "secret-123"},
    )
    signin = client.post(
        "/api/v1/auths/signin",
        json={"email": "a@example.com", "password": "secret-123"},
    )
    return signin.json()["token"]


def test_knowledge_files_requires_login(client):
    assert client.get("/api/v1/knowledge/files").status_code == 401


def test_knowledge_chunks_requires_login(client):
    assert client.get("/api/v1/knowledge/files/file-1/chunks").status_code == 401


def test_knowledge_files_proxy_passthrough(client, monkeypatch):
    token = _signed_in(client)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/knowledge/files"
        assert request.headers["authorization"] == "Bearer test-compat-key"
        return httpx.Response(
            200,
            json={
                "files": [
                    {
                        "file_id": "file-1",
                        "name": "低温储粮.pdf",
                        "status": "vectored",
                        "chunk_count": None,
                        "size_bytes": None,
                        "source_path": "知识库/低温储粮.pdf",
                    }
                ]
            },
        )

    monkeypatch.setattr(
        upstream,
        "build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://testserver"
        ),
    )

    response = client.get(
        "/api/v1/knowledge/files", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["files"][0]["file_id"] == "file-1"


def test_knowledge_chunks_proxy_passthrough(client, monkeypatch):
    token = _signed_in(client)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/knowledge/files/file-1/chunks"
        return httpx.Response(
            200,
            json={
                "file_id": "file-1",
                "name": "低温储粮.pdf",
                "chunks": [{"index": 0, "text": "仓储管理基础。"}],
            },
        )

    monkeypatch.setattr(
        upstream,
        "build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://testserver"
        ),
    )

    response = client.get(
        "/api/v1/knowledge/files/file-1/chunks",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["chunks"][0]["text"] == "仓储管理基础。"


def test_knowledge_files_passes_through_503(client, monkeypatch):
    token = _signed_in(client)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "KNOWLEDGE_UNAVAILABLE"})

    monkeypatch.setattr(
        upstream,
        "build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://testserver"
        ),
    )

    response = client.get(
        "/api/v1/knowledge/files", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "KNOWLEDGE_UNAVAILABLE"}


def test_knowledge_chunks_passes_through_404(client, monkeypatch):
    token = _signed_in(client)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "DOCUMENT_NOT_FOUND"})

    monkeypatch.setattr(
        upstream,
        "build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://testserver"
        ),
    )

    response = client.get(
        "/api/v1/knowledge/files/file-missing/chunks",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "DOCUMENT_NOT_FOUND"}
