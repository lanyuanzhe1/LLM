"""Contract tests for the read-only knowledge catalog API (/v1/knowledge/*).

Auth: Bearer service key (openai_compat middleware covers /v1/knowledge/*).
Errors: ChatDoc failure → 503 KNOWLEDGE_UNAVAILABLE; unknown file → 404
DOCUMENT_NOT_FOUND.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.clients.iflytek_chatdoc import ChatDocChunk
from app.core.errors import ProviderUnavailable
from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.rag.chatdoc_retriever import ChatDocFile, ChatDocManifest
from app.services.knowledge_catalog import KnowledgeCatalog

COMPAT_KEY = "test-compat-key"
AUTH = {"Authorization": f"Bearer {COMPAT_KEY}"}


def _settings(**overrides) -> SimpleNamespace:
    values = {
        "xf_app_id": "app-id",
        "xf_embedding_api_secret": SecretStr("embedding-secret"),
        "xf_maas_api_key": SecretStr("maas-key"),
        "xf_maas_api_secret": SecretStr("maas-secret"),
        "xf_maas_resource_id": "resource-id",
        "xf_maas_service_id": "service-id",
        "xf_workflow_api_key": SecretStr("workflow-key"),
        "xf_workflow_api_secret": SecretStr("workflow-secret"),
        "xf_workflow_flow_id": "flow-id",
        "tools_service_token": SecretStr("tool-token"),
        "openai_compat_api_key": SecretStr(COMPAT_KEY),
        "xf_chatdoc_repo_id": "repo-1",
        "chatdoc_manifest_path": Path("missing-chatdoc-manifest.json"),
        "retrieval_min_score": 0.35,
        "chatdoc_url": "https://chatdoc.invalid/",
        "chatdoc_timeout_seconds": 1,
        "maas_url": "wss://maas.invalid/v1/chat",
        "maas_timeout_seconds": 1,
        "maas_max_frames": 1024,
        "maas_max_payload_bytes": 2_097_152,
        "maas_max_answer_chars": 32_000,
        "workflow_url": "https://workflow.invalid/v1/chat",
        "workflow_timeout_seconds": 1,
        "workflow_max_frames": 1024,
        "workflow_max_payload_bytes": 2_097_152,
        "workflow_max_answer_chars": 32_000,
        "gateway_max_buffer_chars": 32_000,
        "request_context_ttl_seconds": 300,
        "log_level": "INFO",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _FakeChatDoc:
    def __init__(
        self,
        *,
        rows: list[dict] | None = None,
        chunks: list[ChatDocChunk] | None = None,
        fail: bool = False,
    ) -> None:
        self.rows = rows or []
        self.chunks = chunks or []
        self.fail = fail

    async def repo_file_list(self, repo_id: str) -> list[dict]:
        if self.fail:
            raise ProviderUnavailable("CHATDOC_UNAVAILABLE", "暂时不可用")
        return self.rows

    async def file_chunks(self, file_id: str) -> list[ChatDocChunk]:
        if self.fail:
            raise ProviderUnavailable("CHATDOC_UNAVAILABLE", "暂时不可用")
        return self.chunks


def _manifest() -> ChatDocManifest:
    return ChatDocManifest(
        repo_id="repo-1",
        files={
            "file-1": ChatDocFile(
                file_id="file-1",
                source="知识库/低温储粮.pdf",
                checksum="a" * 64,
                source_type="其他论文",
            )
        },
        source_count=1,
    )


def _client(*, knowledge=None, **settings_overrides) -> TestClient:
    from app.main import create_app

    contexts = RequestContextStore(ttl_seconds=300)
    container = ServiceContainer(
        retriever=None,
        generation=None,
        cases=None,
        citations=None,
        contexts=contexts,
        workflow=None,
        knowledge=knowledge,
    )
    return TestClient(
        create_app(
            settings=_settings(**settings_overrides),
            container=container,
        )
    )


def _knowledge_client(fake=None, **settings_overrides) -> TestClient:
    fake = fake or _FakeChatDoc(
        rows=[
            {
                "fileId": "file-1",
                "fileName": "低温储粮.pdf",
                "fileStatus": "vectored",
                "quantity": 24,
            },
            {
                "fileId": "file-2",
                "fileName": "虫害防治.pdf",
                "fileStatus": "uploaded",
            },
        ],
        chunks=[
            ChatDocChunk(index=1, content="低温抑制呼吸。"),
            ChatDocChunk(index=0, content="仓储管理基础。"),
        ],
    )
    return _client(
        knowledge=KnowledgeCatalog(client=fake, manifest=_manifest()),
        **settings_overrides,
    )


def test_knowledge_files_requires_service_key():
    client = _knowledge_client()

    response = client.get("/v1/knowledge/files")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "未授权", "code": "UNAUTHORIZED"}
    }


def test_knowledge_files_returns_normalized_catalog():
    client = _knowledge_client()

    response = client.get("/v1/knowledge/files", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["files"]
    assert body["files"] == [
        {
            "file_id": "file-1",
            "name": "低温储粮.pdf",
            "status": "vectored",
            "chunk_count": None,
            "size_bytes": None,
            "source_path": "知识库/低温储粮.pdf",
        },
        {
            "file_id": "file-2",
            "name": "虫害防治.pdf",
            "status": "uploaded",
            "chunk_count": None,
            "size_bytes": None,
            "source_path": None,
        },
    ]


def test_knowledge_files_returns_503_when_chatdoc_unavailable():
    client = _knowledge_client(fake=_FakeChatDoc(fail=True))

    response = client.get("/v1/knowledge/files", headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"detail": "KNOWLEDGE_UNAVAILABLE"}


def test_knowledge_chunks_requires_service_key():
    client = _knowledge_client()

    response = client.get("/v1/knowledge/files/file-1/chunks")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"message": "未授权", "code": "UNAUTHORIZED"}
    }


def test_knowledge_chunks_returns_ordered_chunks():
    client = _knowledge_client()

    response = client.get("/v1/knowledge/files/file-1/chunks", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["file_id"] == "file-1"
    assert body["name"] == "低温储粮.pdf"
    assert body["chunks"] == [
        {"index": 0, "text": "仓储管理基础。"},
        {"index": 1, "text": "低温抑制呼吸。"},
    ]


def test_knowledge_chunks_returns_404_for_unknown_file():
    client = _knowledge_client()

    response = client.get("/v1/knowledge/files/file-missing/chunks", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"detail": "DOCUMENT_NOT_FOUND"}


def test_knowledge_chunks_returns_503_when_chatdoc_unavailable():
    client = _knowledge_client(fake=_FakeChatDoc(fail=True))

    response = client.get("/v1/knowledge/files/file-1/chunks", headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"detail": "KNOWLEDGE_UNAVAILABLE"}


def test_knowledge_endpoints_503_when_catalog_missing():
    client = _client(knowledge=None)

    files = client.get("/v1/knowledge/files", headers=AUTH)
    chunks = client.get("/v1/knowledge/files/file-1/chunks", headers=AUTH)

    assert files.status_code == 503
    assert chunks.status_code == 503
