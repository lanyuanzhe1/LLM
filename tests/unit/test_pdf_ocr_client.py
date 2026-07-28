"""Tests for app.clients.iflytek_pdf_ocr — iFlytek PDF OCR client."""

import base64
import hashlib
import hmac
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from app.clients.iflytek_pdf_ocr import (
    IflytekPdfOcrClient,
    PdfOcrDownloadError,
    PdfOcrTaskError,
    PdfOcrTimeoutError,
    PdfOcrUploadError,
    clean_markdown,
    make_signature,
)

_REQUESTS = "app.clients.iflytek_pdf_ocr.requests"


def _client(**overrides) -> IflytekPdfOcrClient:
    kwargs = dict(
        app_id="test-app",
        api_secret="test-secret",
        poll_interval_seconds=0,
        sleep=lambda _: None,
    )
    kwargs.update(overrides)
    return IflytekPdfOcrClient(**kwargs)


class _Resp:
    def __init__(self, payload=None, content: bytes = b""):
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestSignature:
    def test_matches_reference_algorithm(self):
        app_id, ts, secret = "myapp", "1700000000", "mysecret"
        md5_hash = hashlib.md5((app_id + ts).encode()).hexdigest()
        expected = base64.b64encode(
            hmac.new(secret.encode(), md5_hash.encode(), hashlib.sha1).digest()
        ).decode()
        assert make_signature(app_id, ts, secret) == expected


class TestStartTask:
    def test_returns_task_no_and_sends_markdown_format(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        client = _client()
        resp = _Resp({"flag": True, "data": {"taskNo": "T123", "status": "CREATE"}})
        with patch(f"{_REQUESTS}.post", return_value=resp) as mock_post:
            task_no = client._start_task(pdf)
        assert task_no == "T123"
        _, kwargs = mock_post.call_args
        assert kwargs["data"] == {"exportFormat": "markdown"}
        assert set(kwargs["headers"]) == {"appId", "timestamp", "signature"}

    def test_flag_false_raises_upload_error(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        client = _client()
        resp = _Resp({"flag": False, "desc": "invalid signature"})
        with patch(f"{_REQUESTS}.post", return_value=resp):
            with pytest.raises(PdfOcrUploadError, match="invalid signature"):
                client._start_task(pdf)

    def test_network_error_raises_upload_error(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        client = _client()
        with patch(
            f"{_REQUESTS}.post",
            side_effect=requests.RequestException("conn refused"),
        ):
            with pytest.raises(PdfOcrUploadError, match="conn refused"):
                client._start_task(pdf)


class TestPoll:
    def test_waits_through_intermediate_states(self):
        client = _client(max_polls=5)
        responses = [
            _Resp({"flag": True, "data": {"status": "CREATE"}}),
            _Resp({"flag": True, "data": {"status": "DOING"}}),
            _Resp({"flag": True, "data": {"status": "FINISH", "downUrl": "http://x/r.md"}}),
        ]
        with patch(f"{_REQUESTS}.get", side_effect=responses) as mock_get:
            data = client._poll("task-1")
        assert data["status"] == "FINISH"
        assert mock_get.call_count == 3

    def test_failed_status_raises_task_error(self):
        client = _client()
        resp = _Resp({"flag": True, "data": {"status": "FAILED"}})
        with patch(f"{_REQUESTS}.get", return_value=resp):
            with pytest.raises(PdfOcrTaskError, match="FAILED"):
                client._poll("task-1")

    def test_stop_status_raises_task_error(self):
        client = _client()
        resp = _Resp({"flag": True, "data": {"status": "STOP"}})
        with patch(f"{_REQUESTS}.get", return_value=resp):
            with pytest.raises(PdfOcrTaskError, match="STOP"):
                client._poll("task-1")

    def test_flag_false_raises_task_error(self):
        client = _client()
        resp = _Resp({"flag": False, "desc": "bad taskNo"})
        with patch(f"{_REQUESTS}.get", return_value=resp):
            with pytest.raises(PdfOcrTaskError, match="bad taskNo"):
                client._poll("task-1")

    def test_exhausting_max_polls_raises_timeout(self):
        client = _client(max_polls=3)
        resp = _Resp({"flag": True, "data": {"status": "DOING"}})
        with patch(f"{_REQUESTS}.get", return_value=resp):
            with pytest.raises(PdfOcrTimeoutError):
                client._poll("task-1")

    def test_transient_network_error_is_retried(self):
        client = _client(max_polls=3)
        responses = [
            requests.RequestException("flaky"),
            _Resp({"flag": True, "data": {"status": "FINISH", "downUrl": "http://x/r.md"}}),
        ]
        with patch(f"{_REQUESTS}.get", side_effect=responses):
            data = client._poll("task-1")
        assert data["status"] == "FINISH"


class TestDownload:
    def test_fixes_double_utf8_encoding(self):
        client = _client()
        original = "低温储粮技术"
        mangled = original.encode("utf-8").decode("latin-1").encode("utf-8")
        with patch(f"{_REQUESTS}.get", return_value=_Resp(content=mangled)):
            text = client._download({"downUrl": "http://x/r.md"})
        assert "低温储粮技术" in text

    def test_plain_utf8_passes_through(self):
        client = _client()
        content = "# 标题\n\n正文内容".encode("utf-8")
        with patch(f"{_REQUESTS}.get", return_value=_Resp(content=content)):
            text = client._download({"downUrl": "http://x/r.md"})
        assert "正文内容" in text

    def test_missing_down_url_raises(self):
        client = _client()
        with pytest.raises(PdfOcrDownloadError, match="downUrl"):
            client._download({"status": "FINISH"})

    def test_http_error_raises_download_error(self):
        client = _client()

        class _Boom(_Resp):
            def raise_for_status(self):
                raise requests.HTTPError("404")

        with patch(f"{_REQUESTS}.get", return_value=_Boom()):
            with pytest.raises(PdfOcrDownloadError):
                client._download({"downUrl": "http://x/r.md"})


class TestCleanMarkdown:
    def test_strips_base64_images(self):
        text = "前文\n![img](data:image/png;base64,iVBORw0KGgo=)\n后文"
        assert clean_markdown(text) == "前文\n\n后文"

    def test_strips_long_base64_runs(self):
        text = "前文" + "A" * 250 + "后文"
        assert clean_markdown(text) == "前文后文"

    def test_compresses_blank_lines(self):
        assert clean_markdown("a\n\n\n\n\nb") == "a\n\n\nb"

    def test_keeps_normal_text(self):
        assert clean_markdown("正常文本\n\n第二段") == "正常文本\n\n第二段"


class TestOcrPdf:
    def test_full_cycle(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF fake")
        client = _client()
        post_resp = _Resp({"flag": True, "data": {"taskNo": "T9"}})
        status_resp = _Resp(
            {"flag": True, "data": {"status": "FINISH", "downUrl": "http://x/r.md"}}
        )
        content = "# 课件\n\n粮油储藏基础".encode("utf-8")
        with patch(f"{_REQUESTS}.post", return_value=post_resp), patch(
            f"{_REQUESTS}.get", side_effect=[status_resp, _Resp(content=content)]
        ):
            text = client.ocr_pdf(pdf)
        assert "粮油储藏基础" in text
