"""Tests for app.ingest.converter — LibreOffice headless ->PDF conversion."""

import subprocess
from pathlib import Path

import pytest

from app.ingest.converter import ConversionError, to_pdf


class _Proc:
    def __init__(self, returncode: int = 0, stderr: bytes = b""):
        self.returncode = returncode
        self.stderr = stderr


def test_pdf_passthrough(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    assert to_pdf(pdf, tmp_path / "out") == pdf


def test_converts_via_soffice(tmp_path, monkeypatch):
    src = tmp_path / "slides.pptx"
    src.write_bytes(b"fake pptx")
    work = tmp_path / "work"
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        (work / "slides.pdf").write_bytes(b"%PDF converted")
        return _Proc()

    monkeypatch.setattr("app.ingest.converter.subprocess.run", fake_run)
    out = to_pdf(src, work)
    assert out == work / "slides.pdf"
    cmd = calls["cmd"]
    assert cmd[0] == "soffice"
    assert "--headless" in cmd
    assert "--convert-to" in cmd
    assert "pdf" in cmd
    assert str(src) in cmd
    assert calls["kwargs"]["timeout"] == 120.0


def test_missing_soffice_raises(tmp_path, monkeypatch):
    src = tmp_path / "a.docx"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("soffice")

    monkeypatch.setattr("app.ingest.converter.subprocess.run", fake_run)
    with pytest.raises(ConversionError, match="soffice not found"):
        to_pdf(src, tmp_path / "work")


def test_timeout_raises(tmp_path, monkeypatch):
    src = tmp_path / "a.docx"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="soffice", timeout=120)

    monkeypatch.setattr("app.ingest.converter.subprocess.run", fake_run)
    with pytest.raises(ConversionError, match="timed out"):
        to_pdf(src, tmp_path / "work")


def test_nonzero_exit_raises_with_stderr(tmp_path, monkeypatch):
    src = tmp_path / "a.docx"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        return _Proc(returncode=1, stderr=b"unsupported format")

    monkeypatch.setattr("app.ingest.converter.subprocess.run", fake_run)
    with pytest.raises(ConversionError, match="unsupported format"):
        to_pdf(src, tmp_path / "work")


def test_missing_output_raises(tmp_path, monkeypatch):
    src = tmp_path / "a.docx"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        return _Proc()

    monkeypatch.setattr("app.ingest.converter.subprocess.run", fake_run)
    with pytest.raises(ConversionError, match="no output"):
        to_pdf(src, tmp_path / "work")
