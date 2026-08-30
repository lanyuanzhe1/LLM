"""Unit tests for the knowledge catalog service (ChatDoc → normalized contract)."""

from __future__ import annotations

import pytest

from app.clients.iflytek_chatdoc import ChatDocChunk
from app.core.errors import ProviderUnavailable
from app.rag.chatdoc_retriever import ChatDocFile, ChatDocManifest
from app.services.knowledge_catalog import KnowledgeCatalog


def _manifest(files: dict[str, ChatDocFile]) -> ChatDocManifest:
    return ChatDocManifest(
        repo_id="repo-1",
        files=files,
        source_count=len(files),
    )


def _file(file_id: str, source: str) -> ChatDocFile:
    return ChatDocFile(
        file_id=file_id,
        source=source,
        checksum="a" * 64,
        source_type="其他论文",
    )


class _FakeClient:
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


def _catalog(client) -> KnowledgeCatalog:
    manifest = _manifest(
        {
            "file-1": _file("file-1", "知识库/低温储粮.pdf"),
            "file-2": _file("file-2", "知识库/虫害防治.pdf"),
        }
    )
    return KnowledgeCatalog(client=client, manifest=manifest)


@pytest.mark.asyncio
async def test_list_files_normalizes_chatdoc_rows_and_maps_manifest_source():
    client = _FakeClient(
        rows=[
            {
                "fileId": "file-1",
                "fileName": "低温储粮.pdf",
                "fileStatus": "vectored",
                "quantity": 24,
            }
        ]
    )
    catalog = _catalog(client)

    files = await catalog.list_files()

    assert len(files) == 1
    file = files[0]
    assert file.file_id == "file-1"
    assert file.name == "低温储粮.pdf"
    assert file.status == "vectored"
    assert file.source_path == "知识库/低温储粮.pdf"
    # quantity 是计量数而非 chunk 数，chunk_count 保持缺失
    assert file.chunk_count is None
    assert file.size_bytes is None


@pytest.mark.asyncio
async def test_list_files_omits_source_path_for_unmapped_file():
    client = _FakeClient(
        rows=[
            {
                "fileId": "file-unknown",
                "fileName": "未入库.pdf",
                "fileStatus": "uploaded",
            }
        ]
    )
    catalog = _catalog(client)

    files = await catalog.list_files()

    assert files[0].file_id == "file-unknown"
    assert files[0].status == "uploaded"
    assert files[0].source_path is None


@pytest.mark.asyncio
async def test_list_files_sorts_by_name():
    client = _FakeClient(
        rows=[
            {"fileId": "file-2", "fileName": "beta.pdf", "fileStatus": "vectored"},
            {"fileId": "file-1", "fileName": "alpha.pdf", "fileStatus": "vectored"},
        ]
    )
    catalog = _catalog(client)

    files = await catalog.list_files()

    assert [f.file_id for f in files] == ["file-1", "file-2"]


@pytest.mark.asyncio
async def test_file_chunks_returns_none_for_file_not_in_manifest():
    catalog = _catalog(_FakeClient())

    result = await catalog.file_chunks("file-missing")

    assert result is None


@pytest.mark.asyncio
async def test_file_chunks_orders_by_data_index_and_uses_manifest_basename():
    client = _FakeClient(
        chunks=[
            ChatDocChunk(index=1, content="低温抑制呼吸。"),
            ChatDocChunk(index=0, content="仓储管理基础。"),
        ]
    )
    catalog = _catalog(client)

    result = await catalog.file_chunks("file-1")

    assert result is not None
    assert result.file_id == "file-1"
    assert result.name == "低温储粮.pdf"  # manifest source 的 basename
    assert [(c.index, c.text) for c in result.chunks] == [
        (0, "仓储管理基础。"),
        (1, "低温抑制呼吸。"),
    ]
