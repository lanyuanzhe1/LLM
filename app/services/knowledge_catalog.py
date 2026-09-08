"""Read-only knowledge catalog: ChatDoc rows → normalized public contract.

The local ChatDoc manifest (``artifacts/chatdoc/base.json``) is used ONLY for
file_id membership checks and source-path display names. All file/chunk data
bodies come from the ChatDoc API — never from the local vector store or the
manifest content fields.
"""

from __future__ import annotations

import os
from typing import Protocol

from app.clients.iflytek_chatdoc import ChatDocChunk
from app.rag.chatdoc_retriever import ChatDocManifest
from app.schemas.knowledge import (
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeFileChunks,
)


class ChatDocCatalogProvider(Protocol):
    async def repo_file_list(self, repo_id: str) -> list[dict]: ...

    async def file_chunks(self, file_id: str) -> list[ChatDocChunk]: ...


class KnowledgeCatalog:
    def __init__(
        self,
        *,
        client: ChatDocCatalogProvider,
        manifest: ChatDocManifest,
    ) -> None:
        self.client = client
        self.manifest = manifest

    async def list_files(self) -> list[KnowledgeFile]:
        rows = await self.client.repo_file_list(self.manifest.repo_id)
        files: list[KnowledgeFile] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            file_id = row.get("fileId")
            if not isinstance(file_id, str) or not file_id.strip():
                continue
            name = row.get("fileName")
            if not isinstance(name, str) or not name.strip():
                name = file_id
            manifest_file = self.manifest.files.get(file_id)
            files.append(
                KnowledgeFile(
                    file_id=file_id,
                    name=name,
                    status=str(row.get("fileStatus") or "unknown"),
                    chunk_count=None,  # quantity 是计量数，非 chunk 数
                    size_bytes=None,
                    source_path=(
                        manifest_file.source if manifest_file is not None else None
                    ),
                )
            )
        files.sort(key=lambda item: item.name.casefold())
        return files

    async def file_chunks(self, file_id: str) -> KnowledgeFileChunks | None:
        manifest_file = self.manifest.files.get(file_id)
        if manifest_file is None:
            return None
        chunks = await self.client.file_chunks(file_id)
        ordered = sorted(chunks, key=lambda chunk: chunk.index)
        return KnowledgeFileChunks(
            file_id=file_id,
            name=os.path.basename(manifest_file.source) or manifest_file.source,
            chunks=[
                KnowledgeChunk(index=chunk.index, text=chunk.content)
                for chunk in ordered
            ],
        )
