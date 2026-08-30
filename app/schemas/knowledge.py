"""Public read-only schemas for the knowledge catalog (/v1/knowledge/*)."""

from __future__ import annotations

from pydantic import BaseModel


class KnowledgeFile(BaseModel):
    file_id: str
    name: str
    status: str
    chunk_count: int | None = None
    size_bytes: int | None = None
    source_path: str | None = None


class KnowledgeFileList(BaseModel):
    files: list[KnowledgeFile]


class KnowledgeChunk(BaseModel):
    index: int
    text: str


class KnowledgeFileChunks(BaseModel):
    file_id: str
    name: str
    chunks: list[KnowledgeChunk]
