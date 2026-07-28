"""Build a Bailian vector store from existing OCR text cache files."""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from app.core.errors import ProviderUnavailable
from app.ingest.builder import build_index_from_chunks, publish_store, save_artifacts
from app.ingest.manifest import DocumentEntry, Manifest, save_manifest
from app.ingest.scanner import scan_base
from ingest_knowledge import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DOC_DIR,
    PARSER_VERSION,
    chunk_text,
    clean_text,
)

OUTPUT_BASE_DIR = Path(os.environ.get("VECTOR_STORE_DIR", "./vector_store"))
OCR_CACHE_DIR = Path(os.environ.get("OCR_CACHE_DIR", "./ocr_cache"))


class BailianEmbeddingClient:
    """Minimal client for Bailian's OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.endpoint = f"{base_url.rstrip('/')}/embeddings"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._http = httpx.AsyncClient()

    async def embed(self, text: str) -> np.ndarray:
        payload = {"model": self.model, "input": text}
        for attempt in range(self.max_retries):
            try:
                response = await self._http.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < self.max_retries:
                        await asyncio.sleep(0.2 * (attempt + 1))
                        continue
                response.raise_for_status()
                vector = np.asarray(
                    response.json()["data"][0]["embedding"], dtype=np.float32
                )
                if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
                    raise ValueError("invalid embedding vector")
                return vector
            except httpx.TransportError:
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
            except (
                httpx.HTTPStatusError,
                KeyError,
                TypeError,
                ValueError,
                IndexError,
            ):
                break
        raise ProviderUnavailable(
            "EMBEDDING_UNAVAILABLE",
            "向量化服务暂时不可用",
        ) from None

    async def close(self) -> None:
        await self._http.aclose()


@dataclass(frozen=True)
class BuildSettings:
    api_key: str
    base_url: str
    model: str
    dimension: int
    output_dir: Path


def load_settings() -> BuildSettings:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    base_url = os.environ.get("BAILIAN_BASE_URL", "").strip().rstrip("/")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is required")
    if not base_url:
        raise RuntimeError("BAILIAN_BASE_URL is required")
    return BuildSettings(
        api_key=api_key,
        base_url=base_url,
        model="text-embedding-v4",
        dimension=1024,
        output_dir=OUTPUT_BASE_DIR / "bailian-base",
    )


async def _embed_chunks(
    chunks: list[dict], settings: BuildSettings
) -> list[dict]:
    client = BailianEmbeddingClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        timeout_seconds=30.0,
    )
    try:
        for chunk in chunks:
            vector = await client.embed(chunk["text"])
            if vector.shape != (settings.dimension,):
                raise ValueError(
                    f"{settings.model} returned {vector.size} dimensions; "
                    f"expected {settings.dimension}"
                )
            chunk["embedding"] = vector
    finally:
        await client.close()
    return chunks


def run_build() -> Path:
    """Embed cached OCR text and publish Bailian-only artifacts.

    The source document is scanned only to map its SHA-256 to the matching
    ``ocr_cache/<sha256>.md`` file. No OCR, document conversion, or local
    text extraction is performed by this script.
    """
    settings = load_settings()
    documents = list(scan_base(DOC_DIR))
    if not documents:
        raise RuntimeError(f"no supported documents found in {DOC_DIR}")
    if not OCR_CACHE_DIR.is_dir():
        raise RuntimeError(f"OCR cache directory not found: {OCR_CACHE_DIR}")

    chunks: list[dict] = []
    indexed_documents: list[tuple[object, int]] = []
    for document in documents:
        cache_path = OCR_CACHE_DIR / f"{document.sha256}.md"
        if not cache_path.is_file():
            continue
        try:
            text = cache_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        cleaned = clean_text(text)
        if not cleaned:
            continue
        document_chunks = chunk_text(
            cleaned,
            document.path,
            CHUNK_SIZE,
            CHUNK_OVERLAP,
            document_checksum=document.sha256,
            source_type=document.source_type,
            scope="base",
        )
        chunks.extend(document_chunks)
        indexed_documents.append((document, len(document_chunks)))

    if not chunks:
        raise RuntimeError("no non-empty OCR cache entries matched knowledge files")

    embedded = asyncio.run(_embed_chunks(chunks, settings))
    index = build_index_from_chunks(embedded)
    staging = settings.output_dir.parent / f".{settings.output_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        save_artifacts(index, embedded, staging)
        save_manifest(
            Manifest(
                scope="base",
                source_root=str(DOC_DIR),
                embedding_dimension=settings.dimension,
                embedding_provider="bailian",
                embedding_url=settings.base_url,
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                parser_version=PARSER_VERSION,
                documents={
                    document.path: DocumentEntry(
                        sha256=document.sha256,
                        mtime_ns=document.mtime_ns,
                        size_bytes=document.size_bytes,
                        chunk_count=chunk_count,
                    )
                    for document, chunk_count in indexed_documents
                },
            ),
            staging,
        )
        publish_store(staging, settings.output_dir)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return settings.output_dir


def main() -> None:
    output_dir = run_build()
    print(f"Published Bailian vector store: {output_dir}")


if __name__ == "__main__":
    main()
