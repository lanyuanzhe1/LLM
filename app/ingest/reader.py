"""Format-routing text extraction module for RAG knowledge ingestion.

Routes file extensions to the correct parser.  Thin local extraction only;
the embedding model handles text quality.
"""

from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md"})


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


def read_file(file_path: Path) -> str:
    """Extract text from a document.  Returns "" on any failure."""
    ext = file_path.suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        return ""
    return reader(file_path)
