"""Convert supported documents to PDF via LibreOffice headless."""

from __future__ import annotations

import subprocess
from pathlib import Path


class ConversionError(Exception):
    """Raised when a document cannot be converted to PDF."""


def to_pdf(
    path: Path,
    work_dir: Path,
    *,
    timeout_seconds: float = 120.0,
    soffice: str = "soffice",
) -> Path:
    """Return *path* unchanged for PDFs; convert other formats via soffice.

    The converted file lands at ``<work_dir>/<stem>.pdf``. Raises
    ConversionError on missing soffice, timeout, non-zero exit, or
    missing output. ``.md`` converts as plain text (LibreOffice does not
    render Markdown syntax); raw markers are acceptable for extraction.
    """
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return path
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(work_dir),
                str(path),
            ],
            capture_output=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise ConversionError(f"soffice not found: {soffice}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            f"conversion timed out after {timeout_seconds}s: {path.name}"
        ) from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ConversionError(f"soffice exited {proc.returncode}: {detail}")
    output = work_dir / f"{path.stem}.pdf"
    if not output.is_file():
        raise ConversionError(f"soffice produced no output for {path.name}")
    return output
