"""Format-routing text extraction module for RAG knowledge ingestion.

Primary path (when an OcrTextExtractor is supplied): every supported file
is converted to PDF and recognized by the iFlytek PDF OCR service. The
local parsers below remain as the failure fallback, and as the default
for callers that pass no extractor.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.ingest.ocr_extract import OcrExtractionError, OcrTextExtractor

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".ppt", ".pptx"})


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return ""


def _read_pdf(path: Path) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except Exception:
        return ""


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return ""
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ""


_READERS = {
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".txt": _read_text_file,
    ".md": _read_text_file,
}


def read_file(file_path: Path, *, ocr: OcrTextExtractor | None = None) -> str:
    """Extract text from a document. Returns "" on any failure.

    With *ocr* given, the file goes through convert-to-PDF + OCR first;
    OcrExtractionError falls back to local extraction with a warning.
    Without *ocr*, only local extraction runs (PPT/PPTX have no local
    parser and yield "").
    """
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return ""
    if ocr is not None:
        try:
            return ocr.extract(file_path)
        except OcrExtractionError as exc:
            logger.warning(
                "OCR failed for %s, falling back to local extraction: %s",
                file_path,
                exc,
            )
    reader = _READERS.get(ext)
    if reader is None:
        return ""
    return reader(file_path)
