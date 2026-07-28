# app/ingest/ocr_extract.py
"""OCR-based text extraction with on-disk caching.

Cache key is the SHA-256 of the source file, so rebuilding a vector store
from scratch never re-bills the OCR API for unchanged files. Only
successful OCR results are cached — a fallback-free retry is always
possible after a transient failure.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from app.clients.iflytek_pdf_ocr import IflytekPdfOcrClient, PdfOcrError
from app.ingest.converter import ConversionError, to_pdf


class OcrExtractionError(Exception):
    """Raised when OCR extraction fails at any stage."""


class OcrTextExtractor:
    def __init__(self, *, client: IflytekPdfOcrClient, cache_dir: Path) -> None:
        self._client = client
        self._cache_dir = Path(cache_dir)

    def extract(self, source_path: Path) -> str:
        source_path = Path(source_path)
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise OcrExtractionError(f"cannot read {source_path}: {exc}") from exc
        digest = hashlib.sha256(raw).hexdigest()
        cache_path = self._cache_dir / f"{digest}.md"
        if cache_path.is_file() and cache_path.stat().st_size > 0:
            return cache_path.read_text(encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="pdf_ocr_") as tmp:
                pdf_path = to_pdf(source_path, Path(tmp))
                text = self._client.ocr_pdf(pdf_path)
        except (ConversionError, PdfOcrError) as exc:
            raise OcrExtractionError(str(exc)) from exc
        if not text.strip():
            raise OcrExtractionError(
                f"OCR returned empty text for {source_path.name}"
            )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        return text
