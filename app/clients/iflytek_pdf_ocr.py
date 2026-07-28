"""Synchronous client for the iFlytek PDF OCR service.

API reference: docs/官网文档/讯飞_PDF_OCR_API.md
Flow: POST start (multipart) -> poll status every 5s -> download Markdown.
Auth: Base64(HmacSHA1(MD5(appId + timestamp), apiSecret)) in headers —
a scheme distinct from the Embedding API's HMAC-SHA256; do not merge them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from collections.abc import Callable
from pathlib import Path

import requests

START_URL = "https://iocr.xfyun.cn/ocrzdq/v1/pdfOcr/start"
STATUS_URL = "https://iocr.xfyun.cn/ocrzdq/v1/pdfOcr/status"

_TERMINAL_FAILURE_STATUSES = {"FAILED", "ANY_FAILED", "STOP"}


class PdfOcrError(Exception):
    """Base error for PDF OCR failures."""


class PdfOcrUploadError(PdfOcrError):
    """The start request failed or was rejected."""


class PdfOcrTaskError(PdfOcrError):
    """The OCR task ended in a non-FINISH state or the status query was rejected."""


class PdfOcrTimeoutError(PdfOcrError):
    """Polling exceeded max_polls without reaching FINISH."""


class PdfOcrDownloadError(PdfOcrError):
    """Downloading or decoding the result failed."""


def make_signature(app_id: str, timestamp: str, api_secret: str) -> str:
    """Base64(HmacSHA1(MD5(appId + timestamp), apiSecret))."""
    md5_hash = hashlib.md5((app_id + timestamp).encode()).hexdigest()
    digest = hmac.new(api_secret.encode(), md5_hash.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def clean_markdown(text: str) -> str:
    """Strip base64-embedded images and compress excess blank lines."""
    text = re.sub(r"!\[img\]\(data:image/[^)]+\)", "", text)
    text = re.sub(r"[A-Za-z0-9+/=]{200,}", "", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


class IflytekPdfOcrClient:
    def __init__(
        self,
        *,
        app_id: str,
        api_secret: str,
        start_url: str = START_URL,
        status_url: str = STATUS_URL,
        export_format: str = "markdown",
        poll_interval_seconds: float = 5.0,
        max_polls: int = 60,
        upload_timeout_seconds: float = 60.0,
        request_timeout_seconds: float = 30.0,
        download_timeout_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.app_id = app_id
        self.api_secret = api_secret
        self.start_url = start_url
        self.status_url = status_url
        self.export_format = export_format
        self.poll_interval_seconds = poll_interval_seconds
        self.max_polls = max_polls
        self.upload_timeout_seconds = upload_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.download_timeout_seconds = download_timeout_seconds
        self._sleep = sleep

    def ocr_pdf(self, pdf_path: Path) -> str:
        """Run the full OCR cycle for *pdf_path*; return Markdown text."""
        task_no = self._start_task(pdf_path)
        data = self._poll(task_no)
        return self._download(data)

    def _headers(self) -> dict[str, str]:
        timestamp = str(int(time.time()))
        return {
            "appId": self.app_id,
            "timestamp": timestamp,
            "signature": make_signature(self.app_id, timestamp, self.api_secret),
        }

    def _start_task(self, pdf_path: Path) -> str:
        try:
            with open(pdf_path, "rb") as f:
                resp = requests.post(
                    self.start_url,
                    headers=self._headers(),
                    files={"file": (Path(pdf_path).name, f, "application/pdf")},
                    data={"exportFormat": self.export_format},
                    timeout=self.upload_timeout_seconds,
                )
            result = resp.json()
        except (OSError, requests.RequestException, ValueError) as exc:
            raise PdfOcrUploadError(f"upload failed: {exc}") from exc
        if not result.get("flag"):
            raise PdfOcrUploadError(f"start rejected: {result.get('desc', result)}")
        return result["data"]["taskNo"]

    def _poll(self, task_no: str) -> dict:
        for _ in range(self.max_polls):
            try:
                resp = requests.get(
                    self.status_url,
                    headers=self._headers(),
                    params={"taskNo": task_no},
                    timeout=self.request_timeout_seconds,
                )
                result = resp.json()
            except (requests.RequestException, ValueError):
                self._sleep(self.poll_interval_seconds)
                continue
            if not result.get("flag"):
                raise PdfOcrTaskError(
                    f"status query rejected: {result.get('desc', result)}"
                )
            data = result["data"]
            status = data.get("status")
            if status == "FINISH":
                return data
            if status in _TERMINAL_FAILURE_STATUSES:
                raise PdfOcrTaskError(f"task ended with status {status}")
            self._sleep(self.poll_interval_seconds)
        raise PdfOcrTimeoutError(
            f"task {task_no} not FINISH after {self.max_polls} polls"
        )

    def _download(self, data: dict) -> str:
        down_url = data.get("downUrl")
        if not down_url:
            raise PdfOcrDownloadError("task FINISH without downUrl")
        try:
            resp = requests.get(down_url, timeout=self.download_timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PdfOcrDownloadError(f"download failed: {exc}") from exc
        raw = resp.content
        try:
            # API returns double-UTF-8-encoded text; undo the latin-1 mojibake.
            text = raw.decode("utf-8").encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            text = raw.decode("utf-8", errors="replace")
        return clean_markdown(text)
