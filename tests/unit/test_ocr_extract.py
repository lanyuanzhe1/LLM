# tests/unit/test_ocr_extract.py
"""Tests for app.ingest.ocr_extract — cached OCR text extraction."""

from pathlib import Path

import pytest

from app.clients.iflytek_pdf_ocr import PdfOcrTaskError
from app.ingest.converter import ConversionError
from app.ingest.ocr_extract import OcrExtractionError, OcrTextExtractor


class _FakeClient:
    def __init__(self, text: str = "OCR 结果文本", error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls: list[Path] = []

    def ocr_pdf(self, pdf_path: Path) -> str:
        self.calls.append(Path(pdf_path))
        if self.error is not None:
            raise self.error
        return self.text


def _source(tmp_path: Path, name: str = "doc.pdf", content: bytes = b"%PDF fake") -> Path:
    src = tmp_path / name
    src.write_bytes(content)
    return src


def test_extract_success_writes_cache(tmp_path):
    src = _source(tmp_path)
    client = _FakeClient()
    extractor = OcrTextExtractor(client=client, cache_dir=tmp_path / "cache")
    text = extractor.extract(src)
    assert text == "OCR 结果文本"
    assert len(client.calls) == 1
    cached = list((tmp_path / "cache").glob("*.md"))
    assert len(cached) == 1
    assert cached[0].read_text(encoding="utf-8") == "OCR 结果文本"


def test_cache_hit_skips_client(tmp_path):
    src = _source(tmp_path)
    client = _FakeClient()
    extractor = OcrTextExtractor(client=client, cache_dir=tmp_path / "cache")
    extractor.extract(src)
    again = extractor.extract(src)
    assert again == "OCR 结果文本"
    assert len(client.calls) == 1


def test_client_failure_raises_and_caches_nothing(tmp_path):
    src = _source(tmp_path)
    client = _FakeClient(error=PdfOcrTaskError("task ended with status FAILED"))
    extractor = OcrTextExtractor(client=client, cache_dir=tmp_path / "cache")
    with pytest.raises(OcrExtractionError, match="FAILED"):
        extractor.extract(src)
    assert not (tmp_path / "cache").exists()


def test_conversion_failure_raises_and_caches_nothing(tmp_path, monkeypatch):
    src = _source(tmp_path, name="slides.pptx", content=b"fake pptx")

    def boom(path, work_dir):
        raise ConversionError("soffice not found")

    monkeypatch.setattr("app.ingest.ocr_extract.to_pdf", boom)
    extractor = OcrTextExtractor(client=_FakeClient(), cache_dir=tmp_path / "cache")
    with pytest.raises(OcrExtractionError, match="soffice not found"):
        extractor.extract(src)
    assert not (tmp_path / "cache").exists()


def test_empty_ocr_result_raises(tmp_path):
    src = _source(tmp_path)
    client = _FakeClient(text="   \n  ")
    extractor = OcrTextExtractor(client=client, cache_dir=tmp_path / "cache")
    with pytest.raises(OcrExtractionError, match="empty"):
        extractor.extract(src)
    assert not (tmp_path / "cache").exists()


def test_unreadable_source_raises(tmp_path):
    extractor = OcrTextExtractor(client=_FakeClient(), cache_dir=tmp_path / "cache")
    with pytest.raises(OcrExtractionError, match="cannot read"):
        extractor.extract(tmp_path / "missing.pdf")
