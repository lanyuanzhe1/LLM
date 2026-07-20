# RAG Project Knowledge Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a project-scoped ingestion pipeline (`ingest_knowledge.py`) that parses knowledge files, performs incremental embedding with manifest-based caching, and publishes per-project vector stores. Add a runtime `VectorStoreRegistry` + `ProjectRetriever` so retrieval merges base knowledge with one project's private store.

**Architecture:** Extract reusable ingestion modules from `build_vector_store.py` into `app/ingest/` (reader, scanner, manifest, builder). The new `ingest_knowledge.py` CLI orchestrates these modules. Runtime adds `VectorStoreRegistry` (load/cache by path) and `ProjectRetriever` (embed once, search base + project, merge scored hits). `project_id` flows from public API through tools to retrieval — never leaks across projects.

**Tech Stack:** Python 3.11, Pydantic v2, httpx, NumPy, scikit-learn, PyMuPDF, python-docx, pytest/pytest-asyncio.

## Global Constraints

- Use the `LLM` Conda environment: `/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`.
- Install packages with `python -m pip` from that environment.
- Follow strict RED-GREEN-REFACTOR; each task gets its own commit.
- Keep one Uvicorn worker/process.
- All secrets from environment variables; never in code, logs, or commits.
- Do not create or commit `.env`, `vector_store/`, or credentials.
- v1 scope: PDF, DOCX, TXT, Markdown. No PPTX, no legacy PPT, no OCR.
- Design philosophy: local code does lightweight extraction + format routing only. The embedding model handles text quality.
- Preserve existing `build_vector_store.py` as a migration reference; new code lives in `app/ingest/`.
- Existing `app/` modules (`VectorStore`, `IflytekEmbeddingClient`, `Retriever`, `Evidence`) remain unchanged except where explicitly listed.
- Unsupported extensions or zero-text files → skip with report entry, never crash.

## File Responsibility Map

| Area | Files | Responsibility |
|------|-------|----------------|
| Ingestion modules | `app/ingest/reader.py`, `scanner.py`, `manifest.py`, `builder.py` | Format routing, file discovery, incremental state, index+save |
| CLI entry | `ingest_knowledge.py` | Argument parsing, pipeline orchestration, report writing |
| Runtime retrieval | `app/rag/registry.py`, `app/rag/project_retriever.py` | Multi-store loading, merged search |
| Schema changes | `app/schemas/api.py`, `app/schemas/tools.py` | `project_id` field on requests |
| Wiring | `app/main.py`, `app/api/chat.py`, `app/api/cases.py`, `app/tools/routes.py`, `app/services/workflow_gateway.py` | Pass `project_id` through |
| Verification | `tests/unit/test_reader.py`, `test_scanner.py`, `test_manifest.py`, `test_builder.py`, `test_registry.py`, `test_project_retriever.py`, `tests/contract/test_tool_api.py`, `tests/contract/test_public_api.py` | Offline + contract coverage |

---

### Task 1: Reader module — format routing and text extraction

**Files:**
- Create: `app/ingest/__init__.py`
- Create: `app/ingest/reader.py`
- Create: `tests/unit/test_reader.py`

**Interfaces:**
- Consumes: file path on disk.
- Produces: `SUPPORTED_EXTENSIONS: frozenset[str]`, `read_file(file_path: Path) -> str`.

- [ ] **Step 1: Write failing reader tests**

```python
# tests/unit/test_reader.py
from pathlib import Path

import pytest

from app.ingest.reader import SUPPORTED_EXTENSIONS, read_file


def test_supported_extensions_are_v1_scope():
    assert SUPPORTED_EXTENSIONS == frozenset({".pdf", ".docx", ".txt", ".md"})


def test_txt_returns_full_content(tmp_path: Path):
    f = tmp_path / "test.txt"
    f.write_text("低温储粮技术", encoding="utf-8")
    assert read_file(f) == "低温储粮技术"


def test_md_returns_full_content(tmp_path: Path):
    f = tmp_path / "readme.md"
    f.write_text("# 标题\n内容", encoding="utf-8")
    assert "内容" in read_file(f)


def test_docx_extracts_paragraphs(tmp_path: Path):
    from docx import Document

    f = tmp_path / "test.docx"
    doc = Document()
    doc.add_paragraph("第一段内容")
    doc.add_paragraph("第二段内容")
    doc.save(str(f))
    text = read_file(f)
    assert "第一段内容" in text
    assert "第二段内容" in text


def test_pdf_extracts_text(tmp_path: Path):
    import fitz

    f = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "低温储粮害虫防治")
    doc.save(str(f))
    doc.close()
    text = read_file(f)
    assert "低温储粮害虫防治" in text


def test_unsupported_extension_returns_empty(tmp_path: Path):
    f = tmp_path / "slides.pptx"
    f.write_text("dummy")
    assert read_file(f) == ""


def test_empty_file_returns_empty(tmp_path: Path):
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    assert read_file(f) == ""


def test_missing_file_returns_empty(tmp_path: Path):
    assert read_file(tmp_path / "nonexistent.pdf") == ""


def test_pdf_with_no_text_returns_empty(tmp_path: Path):
    import fitz

    f = tmp_path / "image_only.pdf"
    doc = fitz.open()
    doc.new_page()  # blank page, no text
    doc.save(str(f))
    doc.close()
    assert read_file(f) == ""
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_reader.py -v
```
Expected: collection fails with `ModuleNotFoundError: No module named 'app.ingest'`.

- [ ] **Step 3: Implement reader module**

```python
# app/ingest/__init__.py (empty)

# app/ingest/reader.py
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
        return "\n".join(
            p.text for p in doc.paragraphs if p.text.strip()
        )
    except Exception:
        return ""


_READERS = {
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".txt": _read_text_file,
    ".md": _read_text_file,
}


def read_file(file_path: Path) -> str:
    """Extract text from a document. Returns empty string on any failure."""
    ext = file_path.suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        return ""
    return reader(file_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_reader.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/ingest/__init__.py app/ingest/reader.py tests/unit/test_reader.py
git commit -m "feat: add ingestion reader module with format routing"
```

---

### Task 2: Scanner module — scope-aware file discovery + project_id validation

**Files:**
- Create: `app/ingest/scanner.py`
- Create: `tests/unit/test_scanner.py`

**Interfaces:**
- Consumes: `Path` to document root.
- Produces: `ScannedDocument` dataclass, `scan_base(doc_dir: Path) -> Iterator[ScannedDocument]`, `scan_project(doc_dir: Path, project_id: str) -> Iterator[ScannedDocument]`, `validate_project_id(value: str) -> str`.

- [ ] **Step 1: Write failing scanner tests**

```python
# tests/unit/test_scanner.py
from pathlib import Path

import pytest

from app.ingest.scanner import (
    ScannedDocument,
    scan_base,
    scan_project,
    validate_project_id,
)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_validate_project_id_rejects_empty():
    for bad in ("", "  ", "\t"):
        with pytest.raises(ValueError):
            validate_project_id(bad)


def test_validate_project_id_rejects_path_traversal():
    for bad in ("../etc", "a/b", "/root", "C:\\windows", "./hidden"):
        with pytest.raises(ValueError):
            validate_project_id(bad)


def test_validate_project_id_rejects_unprintable():
    for bad in ("proj\nect", "proj\0id", "proj\tid"):
        with pytest.raises(ValueError):
            validate_project_id(bad)


def test_validate_project_id_accepts_valid():
    assert validate_project_id("demo") == "demo"
    assert validate_project_id("my-project_2024") == "my-project_2024"
    assert validate_project_id("project-123") == "project-123"


def test_scan_base_excludes_projects_dir(tmp_path: Path):
    _write_file(tmp_path / "doc.pdf", "base doc")
    _write_file(tmp_path / "projects" / "demo" / "project_file.txt", "project")
    _write_file(tmp_path / "subdir" / "nested.txt", "nested")

    docs = list(scan_base(tmp_path))
    sources = {d.path for d in docs}

    assert "doc.pdf" in sources
    assert "subdir/nested.txt" in sources
    assert "projects/demo/project_file.txt" not in sources


def test_scan_project_only_sees_one_project(tmp_path: Path):
    _write_file(tmp_path / "projects" / "demo" / "a.txt", "demo A")
    _write_file(tmp_path / "projects" / "demo" / "sub" / "b.pdf", "demo B")
    _write_file(tmp_path / "projects" / "other" / "c.txt", "other")

    docs = list(scan_project(tmp_path, "demo"))
    sources = {d.path for d in docs}

    assert "projects/demo/a.txt" in sources
    assert "projects/demo/sub/b.pdf" in sources
    assert "projects/other/c.txt" not in sources


def test_scan_base_skips_unsupported_extensions(tmp_path: Path):
    _write_file(tmp_path / "readme.txt", "ok")
    _write_file(tmp_path / "slides.pptx", "no")
    _write_file(tmp_path / "image.png", "no")

    docs = list(scan_base(tmp_path))
    sources = {d.path for d in docs}

    assert "readme.txt" in sources
    assert "slides.pptx" not in sources
    assert "image.png" not in sources


def test_scan_base_skips_symlinks(tmp_path: Path):
    _write_file(tmp_path / "real.txt", "real")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")

    docs = list(scan_base(tmp_path))
    sources = {d.path for d in docs}
    assert "link.txt" not in sources


def test_scanned_document_has_checksum(tmp_path: Path):
    _write_file(tmp_path / "doc.txt", "hello world")
    [doc] = list(scan_base(tmp_path))
    assert len(doc.sha256) == 64
    assert doc.size_bytes == 11
    assert doc.source_type is not None


def test_scan_project_nonexistent_dir_yields_empty(tmp_path: Path):
    docs = list(scan_project(tmp_path, "no-such-project"))
    assert docs == []
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_scanner.py -v
```
Expected: collection fails with `ModuleNotFoundError: No module named 'app.ingest.scanner'`.

- [ ] **Step 3: Implement scanner module**

```python
# app/ingest/scanner.py
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator

from app.ingest.reader import SUPPORTED_EXTENSIONS


_VALID_PROJECT_ID = re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9_]*[a-zA-Z0-9]$")


@dataclass(frozen=True)
class ScannedDocument:
    path: str          # posix relative path
    sha256: str        # hex digest
    source_type: str | None  # first path segment
    size_bytes: int
    mtime_ns: int


def validate_project_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("project_id must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("project_id must not be empty")
    if stripped != value:
        raise ValueError("project_id must not have leading/trailing whitespace")
    if not _VALID_PROJECT_ID.fullmatch(stripped):
        raise ValueError(
            "project_id must match [a-zA-Z0-9][-a-zA-Z0-9_]*[a-zA-Z0-9]"
        )
    if len(stripped) > 64:
        raise ValueError("project_id must be at most 64 characters")
    return stripped


def _scan_directory(
    doc_dir: Path,
    *,
    exclude_prefixes: tuple[str, ...] = (),
) -> Iterator[ScannedDocument]:
    doc_dir = doc_dir.resolve(strict=False)
    if not doc_dir.is_dir():
        return

    for file_path in doc_dir.rglob("*"):
        if file_path.is_symlink() or not file_path.is_file():
            continue
        if file_path.name.startswith("~") or file_path.name.startswith("."):
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            relative = file_path.relative_to(doc_dir).as_posix()
        except ValueError:
            continue

        if exclude_prefixes and relative.startswith(exclude_prefixes):
            continue

        try:
            raw = file_path.read_bytes()
        except OSError:
            continue

        parts = relative.split("/")
        source_type = parts[0] if len(parts) > 1 else None
        stat = file_path.stat()

        yield ScannedDocument(
            path=relative,
            sha256=hashlib.sha256(raw).hexdigest(),
            source_type=source_type,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )


def scan_base(doc_dir: Path) -> Iterator[ScannedDocument]:
    yield from _scan_directory(
        doc_dir,
        exclude_prefixes=("projects/",),
    )


def scan_project(doc_dir: Path, project_id: str) -> Iterator[ScannedDocument]:
    project_dir = doc_dir / "projects" / validate_project_id(project_id)
    yield from _scan_directory(project_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_scanner.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app/ingest/scanner.py tests/unit/test_scanner.py
git commit -m "feat: add ingestion scanner with project_id validation"
```

---

### Task 3: Manifest module — incremental state management

**Files:**
- Create: `app/ingest/manifest.py`
- Create: `tests/unit/test_manifest.py`

**Interfaces:**
- Consumes: store directory `Path`.
- Produces: `Manifest` dataclass, `load_manifest(store_dir: Path) -> Manifest | None`, `save_manifest(manifest: Manifest, store_dir: Path) -> None`, `find_reusable(manifest: Manifest, current_docs: dict[str, ScannedDocument], config: ManifestConfig) -> tuple[list[str], list[str]]` — returns `(reusable_paths, new_or_changed_paths)`.

- [ ] **Step 1: Write failing manifest tests**

```python
# tests/unit/test_manifest.py
import json
from pathlib import Path

import pytest

from app.ingest.manifest import (
    Manifest,
    ManifestConfig,
    DocumentEntry,
    find_reusable,
    load_manifest,
    save_manifest,
)
from app.ingest.scanner import ScannedDocument


MANIFEST_CONFIG = ManifestConfig(
    parser_version="2026-07-20",
    chunk_size=600,
    chunk_overlap=100,
    embedding_provider="iflytek",
    embedding_url="https://emb-cn-huabei-1.xf-yun.com/",
    embedding_dimension=2560,
)


def _doc(path: str, sha256: str = "a" * 64) -> ScannedDocument:
    return ScannedDocument(
        path=path,
        sha256=sha256,
        source_type=None,
        size_bytes=100,
        mtime_ns=0,
    )


def test_load_manifest_returns_none_for_missing_file(tmp_path: Path):
    assert load_manifest(tmp_path) is None


def test_save_and_load_round_trip(tmp_path: Path):
    manifest = Manifest(
        schema_version=1,
        scope="project",
        project_id="demo",
        source_root="knowledge/projects/demo",
        parser_version="2026-07-20",
        documents={
            "file.pdf": DocumentEntry(
                sha256="b" * 64,
                mtime_ns=123,
                size_bytes=456,
                status="indexed",
                chunk_count=8,
            )
        },
    )
    save_manifest(manifest, tmp_path)
    loaded = load_manifest(tmp_path)
    assert loaded is not None
    assert loaded.scope == "project"
    assert loaded.project_id == "demo"
    assert loaded.documents["file.pdf"].sha256 == "b" * 64
    assert loaded.documents["file.pdf"].chunk_count == 8


def test_find_reusable_returns_unchanged_documents():
    manifest = Manifest(
        schema_version=1,
        scope="base",
        parser_version="2026-07-20",
        documents={
            "unchanged.pdf": DocumentEntry(
                sha256="a" * 64,
                mtime_ns=0,
                size_bytes=100,
                status="indexed",
                chunk_count=3,
            ),
            "changed.pdf": DocumentEntry(
                sha256="b" * 64,
                mtime_ns=0,
                size_bytes=200,
                status="indexed",
                chunk_count=5,
            ),
        },
    )
    current = {
        "unchanged.pdf": _doc("unchanged.pdf", sha256="a" * 64),
        "changed.pdf": _doc("changed.pdf", sha256="c" * 64),  # hash differs
        "new.pdf": _doc("new.pdf", sha256="d" * 64),
    }

    reusable, new_changed = find_reusable(manifest, current, MANIFEST_CONFIG)

    assert reusable == ["unchanged.pdf"]
    assert set(new_changed) == {"changed.pdf", "new.pdf"}


def test_find_reusable_requires_parser_version_match():
    manifest = Manifest(
        schema_version=1,
        scope="base",
        parser_version="2025-01-01",  # old parser
        documents={
            "file.pdf": DocumentEntry(
                sha256="a" * 64,
                mtime_ns=0,
                size_bytes=100,
                status="indexed",
                chunk_count=3,
            ),
        },
    )
    current = {"file.pdf": _doc("file.pdf", sha256="a" * 64)}
    reusable, new_changed = find_reusable(manifest, current, MANIFEST_CONFIG)

    # Same hash, but parser version changed → must re-embed
    assert reusable == []
    assert new_changed == ["file.pdf"]


def test_find_reusable_deleted_file_not_reused():
    manifest = Manifest(
        schema_version=1,
        scope="base",
        parser_version="2026-07-20",
        documents={
            "removed.pdf": DocumentEntry(
                sha256="a" * 64,
                mtime_ns=0,
                size_bytes=100,
                status="indexed",
                chunk_count=3,
            ),
        },
    )
    current = {}  # file no longer on disk
    reusable, new_changed = find_reusable(manifest, current, MANIFEST_CONFIG)
    assert reusable == []
    assert new_changed == []
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_manifest.py -v
```
Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement manifest module**

```python
# app/ingest/manifest.py
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ingest.scanner import ScannedDocument


@dataclass
class DocumentEntry:
    sha256: str
    mtime_ns: int
    size_bytes: int
    status: str = "indexed"
    chunk_count: int = 0


@dataclass
class Manifest:
    schema_version: int = 1
    scope: str = "base"
    project_id: str | None = None
    source_root: str = ""
    embedding_dimension: int = 2560
    embedding_provider: str = "iflytek"
    embedding_url: str = "https://emb-cn-huabei-1.xf-yun.com/"
    chunk_size: int = 600
    chunk_overlap: int = 100
    parser_version: str = ""
    documents: dict[str, DocumentEntry] = field(default_factory=dict)


@dataclass
class ManifestConfig:
    parser_version: str
    chunk_size: int
    chunk_overlap: int
    embedding_provider: str
    embedding_url: str
    embedding_dimension: int


def load_manifest(store_dir: Path) -> Manifest | None:
    path = store_dir / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    docs_raw = data.get("documents", {})
    documents: dict[str, DocumentEntry] = {}
    if isinstance(docs_raw, dict):
        for name, entry in docs_raw.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            documents[name] = DocumentEntry(
                sha256=str(entry.get("sha256", "")),
                mtime_ns=int(entry.get("mtime_ns", 0)),
                size_bytes=int(entry.get("size_bytes", 0)),
                status=str(entry.get("status", "indexed")),
                chunk_count=int(entry.get("chunk_count", 0)),
            )

    return Manifest(
        schema_version=int(data.get("schema_version", 1)),
        scope=str(data.get("scope", "base")),
        project_id=data.get("project_id"),
        source_root=str(data.get("source_root", "")),
        embedding_dimension=int(data.get("embedding_dimension", 2560)),
        embedding_provider=str(data.get("embedding_provider", "iflytek")),
        embedding_url=str(data.get("embedding_url", "")),
        chunk_size=int(data.get("chunk_size", 600)),
        chunk_overlap=int(data.get("chunk_overlap", 100)),
        parser_version=str(data.get("parser_version", "")),
        documents=documents,
    )


def save_manifest(manifest: Manifest, store_dir: Path) -> None:
    data = {
        "schema_version": manifest.schema_version,
        "scope": manifest.scope,
        "project_id": manifest.project_id,
        "source_root": manifest.source_root,
        "embedding_dimension": manifest.embedding_dimension,
        "embedding_provider": manifest.embedding_provider,
        "embedding_url": manifest.embedding_url,
        "chunk_size": manifest.chunk_size,
        "chunk_overlap": manifest.chunk_overlap,
        "parser_version": manifest.parser_version,
        "documents": {
            name: {
                "sha256": entry.sha256,
                "mtime_ns": entry.mtime_ns,
                "size_bytes": entry.size_bytes,
                "status": entry.status,
                "chunk_count": entry.chunk_count,
            }
            for name, entry in manifest.documents.items()
        },
    }
    path = store_dir / "manifest.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_reusable(
    manifest: Manifest,
    current_docs: dict[str, ScannedDocument],
    config: ManifestConfig,
) -> tuple[list[str], list[str]]:
    """Compare manifest against current files + config. Returns (reusable_paths, new_or_changed_paths)."""
    config_match = (
        manifest.parser_version == config.parser_version
        and manifest.chunk_size == config.chunk_size
        and manifest.chunk_overlap == config.chunk_overlap
        and manifest.embedding_provider == config.embedding_provider
        and manifest.embedding_url == config.embedding_url
        and manifest.embedding_dimension == config.embedding_dimension
    )

    reusable: list[str] = []
    new_or_changed: list[str] = []

    for path, doc in current_docs.items():
        entry = manifest.documents.get(path)
        if (
            config_match
            and entry is not None
            and entry.sha256 == doc.sha256
            and entry.status == "indexed"
        ):
            reusable.append(path)
        else:
            new_or_changed.append(path)

    return reusable, new_or_changed
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_manifest.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/ingest/manifest.py tests/unit/test_manifest.py
git commit -m "feat: add manifest module for incremental ingestion state"
```

---

### Task 4: Builder module — index construction and atomic publish

**Files:**
- Create: `app/ingest/builder.py`
- Create: `tests/unit/test_builder.py`

**Interfaces:**
- Consumes: list of chunk dicts, output directory `Path`.
- Produces: `build_index_from_chunks(chunks: list[dict]) -> NearestNeighbors`, `save_artifacts(nbrs: NearestNeighbors, chunks: list[dict], output_dir: Path) -> None`, `publish_store(staging_dir: Path, target_dir: Path) -> None`.

- [ ] **Step 1: Write failing builder tests**

```python
# tests/unit/test_builder.py
import json
from pathlib import Path

import numpy as np
import pytest
from sklearn.neighbors import NearestNeighbors

from app.ingest.builder import (
    build_index_from_chunks,
    save_artifacts,
    publish_store,
)


def _make_chunks(n: int = 3) -> list[dict]:
    rng = np.random.RandomState(42)
    return [
        {
            "text": f"chunk {i}",
            "source": f"doc{i}.pdf",
            "start_pos": i * 100,
            "char_count": 50,
            "embedding": rng.randn(2560).astype(np.float32),
            "document_checksum": "a" * 64,
            "source_type": "papers",
        }
        for i in range(n)
    ]


def test_build_index_returns_neighbors():
    chunks = _make_chunks(5)
    nbrs = build_index_from_chunks(chunks)
    assert isinstance(nbrs, NearestNeighbors)
    vectors = nbrs._fit_X
    assert vectors.shape == (5, 2560)


def test_build_index_rejects_empty():
    with pytest.raises(ValueError):
        build_index_from_chunks([])


def test_save_artifacts_writes_vectors_and_metadata(tmp_path: Path):
    chunks = _make_chunks(3)
    nbrs = build_index_from_chunks(chunks)
    save_artifacts(nbrs, chunks, tmp_path)

    assert (tmp_path / "vectors.npy").is_file()
    assert (tmp_path / "chunks_metadata.json").is_file()

    with open(tmp_path / "chunks_metadata.json", encoding="utf-8") as f:
        meta = json.load(f)
    assert len(meta) == 3
    assert "embedding" not in meta[0]
    assert meta[0]["source"] == "doc0.pdf"


def test_save_artifacts_strips_embedding_from_metadata(tmp_path: Path):
    chunks = _make_chunks(1)
    nbrs = build_index_from_chunks(chunks)
    save_artifacts(nbrs, chunks, tmp_path)

    with open(tmp_path / "chunks_metadata.json", encoding="utf-8") as f:
        meta = json.load(f)
    for key in meta[0]:
        assert key != "embedding"


def test_publish_store_atomic_swap(tmp_path: Path):
    target = tmp_path / "store"
    staging = tmp_path / ".store.staging"
    staging.mkdir()

    # Write artifacts into staging
    chunks = _make_chunks(2)
    nbrs = build_index_from_chunks(chunks)
    save_artifacts(nbrs, chunks, staging)

    publish_store(staging, target)

    assert target.is_dir()
    assert not staging.exists()
    assert (target / "vectors.npy").is_file()
    assert (target / "chunks_metadata.json").is_file()


def test_publish_store_replaces_existing(tmp_path: Path):
    target = tmp_path / "store"
    target.mkdir()
    (target / "old_file.txt").write_text("old")

    staging = tmp_path / ".store.staging"
    staging.mkdir()
    chunks = _make_chunks(1)
    nbrs = build_index_from_chunks(chunks)
    save_artifacts(nbrs, chunks, staging)

    publish_store(staging, target)

    assert not (target / "old_file.txt").exists()
    assert (target / "vectors.npy").is_file()
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_builder.py -v
```
Expected: collection fails with `ModuleNotFoundError: No module named 'app.ingest.builder'`.

- [ ] **Step 3: Implement builder module**

```python
# app/ingest/builder.py
import json
import os
import shutil
from pathlib import Path

import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize


def build_index_from_chunks(chunks: list[dict]) -> NearestNeighbors:
    if not chunks:
        raise ValueError("chunk list is empty")
    vectors = np.stack(
        [np.asarray(c["embedding"], dtype=np.float32) for c in chunks]
    )
    if vectors.ndim != 2 or vectors.shape[0] == 0 or vectors.shape[1] == 0:
        raise ValueError("embedding vectors are invalid")
    if not np.isfinite(vectors).all():
        raise ValueError("embedding vectors contain NaN or Inf")

    vectors = normalize(vectors, norm="l2")
    nbrs = NearestNeighbors(
        n_neighbors=min(10, len(chunks)),
        metric="cosine",
        algorithm="brute",
    )
    nbrs.fit(vectors)
    return nbrs


def save_artifacts(
    nbrs: NearestNeighbors,
    chunks: list[dict],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    vectors = nbrs._fit_X
    np.save(str(output_dir / "vectors.npy"), vectors)

    metadata = [
        {key: value for key, value in c.items() if key != "embedding"}
        for c in chunks
    ]
    (output_dir / "chunks_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def publish_store(staging_dir: Path, target_dir: Path) -> None:
    staging_dir = Path(staging_dir)
    target_dir = Path(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    if not staging_dir.is_dir():
        raise FileNotFoundError(f"staging directory not found: {staging_dir}")
    if not (staging_dir / "vectors.npy").is_file():
        raise FileNotFoundError("staging directory missing vectors.npy")
    if not (staging_dir / "chunks_metadata.json").is_file():
        raise FileNotFoundError("staging directory missing chunks_metadata.json")

    # Atomic: rename staging into target position
    if target_dir.exists():
        tmp = target_dir.parent / f".{target_dir.name}.old"
        if tmp.exists():
            shutil.rmtree(tmp)
        os.replace(target_dir, tmp)
        try:
            os.replace(staging_dir, target_dir)
        except Exception:
            os.replace(tmp, target_dir)  # rollback
            raise
        else:
            shutil.rmtree(tmp)
    else:
        os.replace(staging_dir, target_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_builder.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/ingest/builder.py tests/unit/test_builder.py
git commit -m "feat: add ingestion builder with atomic publish"
```

---

### Task 5: ingest_knowledge.py CLI entry point

**Files:**
- Create: `ingest_knowledge.py`
- Create: `tests/unit/test_ingest_cli.py`

**Interfaces:**
- Consumes: CLI arguments, `.env` for credentials, `knowledge/` on disk.
- Produces: published `vector_store/base/` or `vector_store/projects/<id>/` with `manifest.json` and `ingest_report.json`.

- [ ] **Step 1: Write failing CLI integration tests**

```python
# tests/unit/test_ingest_cli.py
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import ingest_knowledge as ik


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class FakeEmbeddingClient:
    def __init__(self, *args, **kwargs):
        pass

    async def embed(self, text: str, domain: str) -> "np.ndarray":
        import numpy as np
        rng = np.random.RandomState(hash(text) % 2**31)
        return rng.randn(2560).astype(np.float32)

    async def close(self):
        pass


def test_resolve_scope_base_excludes_projects(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "base_doc.txt", "base content")
    _write_file(tmp_path / "projects" / "demo" / "proj.txt", "project")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        report = ik.run_ingestion(scope="base")

    assert report["files_indexed"] == 1
    assert (tmp_path / "out" / "vectors.npy").is_file()
    assert (tmp_path / "out" / "manifest.json").is_file()


def test_resolve_scope_project_only_sees_project(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "projects" / "demo" / "a.txt", "demo content")
    _write_file(tmp_path / "projects" / "other" / "b.txt", "other")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        report = ik.run_ingestion(scope="project", project_id="demo")

    assert report["project_id"] == "demo"
    assert report["files_indexed"] == 1
    assert (tmp_path / "out" / "projects" / "demo" / "vectors.npy").is_file()


def test_resolve_scope_all_projects(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "projects" / "demo" / "a.txt", "A")
    _write_file(tmp_path / "projects" / "other" / "b.txt", "B")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        report = ik.run_ingestion(scope="all-projects")

    assert report["projects_processed"] == 2


def test_empty_knowledge_dir_exits_nonzero(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ik, "DOC_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()

    with pytest.raises(SystemExit):
        ik.run_ingestion(scope="base")


def test_all_files_skipped_exits_nonzero(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "slides.pptx", "no parser for pptx")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)

    with pytest.raises(SystemExit):
        ik.run_ingestion(scope="base")


def test_ingest_report_is_valid_json(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "doc.txt", "test content for report validation")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        ik.run_ingestion(scope="base")

    report_path = tmp_path / "out" / "ingest_report.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert "files_scanned" in report
    assert "chunks_embedded" in report
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_ingest_cli.py -v
```
Expected: collection fails — `ingest_knowledge.py` does not import cleanly.

- [ ] **Step 3: Implement ingest_knowledge.py**

```python
# ingest_knowledge.py
"""Project-scoped knowledge ingestion CLI.

Usage:
  python ingest_knowledge.py --scope base
  python ingest_knowledge.py --project-id demo
  python ingest_knowledge.py --project-id demo --source /path/to/file.pdf
  python ingest_knowledge.py --scope all-projects
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.ingest.reader import SUPPORTED_EXTENSIONS, read_file
from app.ingest.scanner import (
    ScannedDocument,
    scan_base,
    scan_project,
    validate_project_id,
)
from app.ingest.manifest import (
    Manifest,
    ManifestConfig,
    DocumentEntry,
    find_reusable,
    load_manifest,
    save_manifest,
)
from app.ingest.builder import (
    build_index_from_chunks,
    save_artifacts,
    publish_store,
)

# ---- Configuration (overridable via env) ----
DOC_DIR = Path(os.environ.get("KNOWLEDGE_DIR", "./knowledge"))
OUTPUT_BASE_DIR = Path(os.environ.get("VECTOR_STORE_DIR", "./vector_store"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "100"))
PARSER_VERSION = os.environ.get("PARSER_VERSION", "2026-07-20")
SLEEP_INTERVAL = float(os.environ.get("INGEST_SLEEP_INTERVAL", "0.3"))

# ---- Text cleaning (from build_vector_store.py) ----
import re


def clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"([，。！？；：、])\s+", r"\1", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


# ---- Chunking (from build_vector_store.py) ----
from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class _TextSegment:
    start: int
    end: int


_SEGMENT_BOUNDARY_PATTERN = re.compile(
    r"\n{2,}|[。！？!?]+|(?<!\d)\.(?!\d)"
)


def _offset_segments(text: str) -> list[_TextSegment]:
    segments: list[_TextSegment] = []
    cursor = 0
    for match in _SEGMENT_BOUNDARY_PATTERN.finditer(text):
        boundary = match.end()
        if boundary > cursor:
            segments.append(_TextSegment(start=cursor, end=boundary))
            cursor = boundary
    if cursor < len(text):
        segments.append(_TextSegment(start=cursor, end=len(text)))
    return segments


def chunk_text(
    text: str,
    source_file: str,
    chunk_size: int = 600,
    overlap: int = 100,
    *,
    document_checksum: str | None = None,
    source_type: str | None = None,
) -> list[dict]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be 0 <= overlap < chunk_size")
    if not text:
        return []

    segments = _offset_segments(text)
    preferred_ends = tuple(seg.end for seg in segments)
    chunks: list[dict] = []
    start = 0
    previous_end = 0
    while start < len(text):
        hard_end = min(start + chunk_size, len(text))
        semantic_ends = [
            end for end in preferred_ends
            if previous_end < end <= hard_end
        ]
        end = max(semantic_ends) if semantic_ends else hard_end
        if end <= previous_end or end <= start:
            end = hard_end
        chunk_value = text[start:end]
        meta = {
            "text": chunk_value,
            "source": source_file,
            "start_pos": start,
            "char_count": len(chunk_value),
        }
        if document_checksum is not None:
            meta["document_checksum"] = document_checksum
        if source_type is not None:
            meta["source_type"] = source_type
        chunks.append(meta)
        if end == len(text):
            break
        previous_end = end
        start = end - overlap
    return chunks


# ---- Pipeline orchestration ----

def _output_dir(scope: str, project_id: str | None = None) -> Path:
    if scope == "base":
        return OUTPUT_BASE_DIR / "base"
    if scope == "project" and project_id:
        return OUTPUT_BASE_DIR / "projects" / project_id
    raise ValueError(f"unknown scope: {scope}")


def _manifest_config() -> ManifestConfig:
    return ManifestConfig(
        parser_version=PARSER_VERSION,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        embedding_provider="iflytek",
        embedding_url="https://emb-cn-huabei-1.xf-yun.com/",
        embedding_dimension=2560,
    )


def _embed_batch(
    chunks: list[dict],
    client: IflytekEmbeddingClient,
) -> list[dict]:
    """Embed all chunks synchronously via the async client."""
    import time as _time

    async def _embed_all():
        for i, c in enumerate(chunks):
            vec = await client.embed(c["text"], domain="para")
            c["embedding"] = vec
            if (i + 1) % 50 == 0:
                _time.sleep(0.5)

    asyncio.run(_embed_all())
    return chunks


def _collect_preexisting_chunks(
    manifest: Manifest,
    reusable_paths: list[str],
    store_dir: Path,
) -> list[dict]:
    """Load previously embedded chunks for reusable documents."""
    import numpy as np

    vectors_path = store_dir / "vectors.npy"
    metadata_path = store_dir / "chunks_metadata.json"

    if not vectors_path.is_file() or not metadata_path.is_file():
        return []

    all_vectors = np.load(vectors_path, allow_pickle=False)
    all_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    reusable_set = set(reusable_paths)
    reused: list[dict] = []
    for i, meta in enumerate(all_metadata):
        if meta.get("source") in reusable_set:
            chunk = dict(meta)
            chunk["embedding"] = all_vectors[i].copy()
            reused.append(chunk)

    return reused


def run_ingestion(
    *,
    scope: str,
    project_id: str | None = None,
    source_file: str | None = None,
) -> dict:
    """Run the full ingestion pipeline. Returns an ingest_report dict."""

    # Validate
    if scope not in ("base", "project", "all-projects"):
        raise ValueError(f"unknown scope: {scope}")

    app_id = os.environ.get("XF_APP_ID", "")
    api_key = os.environ.get("XF_EMBEDDING_API_KEY", "")
    api_secret = os.environ.get("XF_EMBEDDING_API_SECRET", "")
    if not app_id or not api_key or not api_secret:
        print("[ERROR] Missing iFlytek credentials in environment")
        sys.exit(1)

    started = datetime.now(timezone.utc)
    report = {
        "scope": scope,
        "project_id": project_id,
        "started": started.isoformat(),
        "files_scanned": 0,
        "files_indexed": 0,
        "files_reused": 0,
        "files_replaced": 0,
        "files_deleted": 0,
        "files_skipped": 0,
        "files_failed": 0,
        "chunks_embedded": 0,
        "chunks_reused": 0,
        "published_path": "",
        "warnings": [],
    }

    # Handle --source copy
    if source_file:
        if scope != "project" or not project_id:
            print("[ERROR] --source requires --project-id")
            sys.exit(1)
        src = Path(source_file).resolve()
        if not src.is_file():
            print(f"[ERROR] source file not found: {source_file}")
            sys.exit(1)
        ext = src.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"[ERROR] unsupported file type: {ext}")
            sys.exit(1)
        dest_dir = DOC_DIR / "projects" / project_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        print(f"  Copied {src.name} -> {dest}")

    # Resolve scope to a list of (scope, project_id) jobs
    if scope == "all-projects":
        projects_root = DOC_DIR / "projects"
        if not projects_root.is_dir():
            print("[WARNING] No projects directory found")
            report["projects_processed"] = 0
            return report
        jobs = [
            ("project", d.name)
            for d in sorted(projects_root.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        ]
        report["projects_processed"] = len(jobs)
    else:
        jobs = [(scope, project_id)]

    for job_scope, job_project_id in jobs:
        _ingest_one_scope(job_scope, job_project_id, report)

    # Finalize
    completed = datetime.now(timezone.utc)
    report["completed"] = completed.isoformat()

    # Write report
    if scope != "all-projects":
        out_dir = _output_dir(scope, project_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ingest_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return report


def _ingest_one_scope(
    scope: str,
    project_id: str | None,
    report: dict,
) -> None:
    """Ingest a single scope (base or one project)."""

    # Scan
    if scope == "base":
        scanned = list(scan_base(DOC_DIR))
        source_root = str(DOC_DIR)
    else:
        scanned = list(scan_project(DOC_DIR, project_id))
        source_root = str(DOC_DIR / "projects" / project_id)

    report["files_scanned"] += len(scanned)
    if not scanned:
        print(f"[WARNING] No supported files found for scope={scope}")
        return

    # Separate supported vs unsupported
    current_docs: dict[str, ScannedDocument] = {}
    for doc in scanned:
        current_docs[doc.path] = doc

    # Read text
    docs_with_text: list[tuple[ScannedDocument, str]] = []
    for doc in scanned:
        full_path = DOC_DIR / doc.path
        text = read_file(full_path)
        if text.strip():
            docs_with_text.append((doc, text))
        else:
            report["files_skipped"] += 1

    if not docs_with_text:
        print(f"[ERROR] All {len(scanned)} files produced empty text")
        sys.exit(1)

    # Check manifest for incremental reuse
    out_dir = _output_dir(scope, project_id)
    manifest = load_manifest(out_dir)
    config = _manifest_config()

    reusable_paths: list[str] = []
    new_changed_paths: list[str] = []
    if manifest is not None:
        reusable_paths, new_changed_paths = find_reusable(
            manifest, current_docs, config
        )

    # Separate docs into reusable vs new
    reusable_set = set(reusable_paths)
    new_docs = [
        (doc, text)
        for doc, text in docs_with_text
        if doc.path not in reusable_set
    ]

    # Load preexisting chunks
    preexisting = _collect_preexisting_chunks(
        manifest, reusable_paths, out_dir
    ) if manifest else []

    report["files_reused"] += len(reusable_paths)
    report["chunks_reused"] += len(preexisting)

    # Chunk new documents
    new_chunks: list[dict] = []
    for doc, text in new_docs:
        cleaned = clean_text(text)
        chunks = chunk_text(
            cleaned,
            doc.path,
            CHUNK_SIZE,
            CHUNK_OVERLAP,
            document_checksum=doc.sha256,
            source_type=doc.source_type,
        )
        new_chunks.extend(chunks)

    # Embed new chunks
    if new_chunks:
        client = IflytekEmbeddingClient(
            app_id=os.environ["XF_APP_ID"],
            api_key=os.environ["XF_EMBEDDING_API_KEY"],
            api_secret=os.environ["XF_EMBEDDING_API_SECRET"],
            url="https://emb-cn-huabei-1.xf-yun.com/",
            timeout_seconds=30.0,
        )
        try:
            new_chunks = _embed_batch(new_chunks, client)
        except Exception as e:
            print(f"[ERROR] Embedding failed: {e}")
            sys.exit(1)
        finally:
            asyncio.run(client.close())

    report["files_indexed"] += len(new_docs)
    report["chunks_embedded"] += len(new_chunks)

    # Merge reused + new
    all_chunks = preexisting + new_chunks
    if not all_chunks:
        print("[ERROR] No chunks to publish")
        sys.exit(1)

    # Build index + save + publish
    nbrs = build_index_from_chunks(all_chunks)
    staging = out_dir.parent / f".{out_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        save_artifacts(nbrs, all_chunks, staging)
        # Write manifest
        new_manifest = Manifest(
            schema_version=1,
            scope=scope,
            project_id=project_id,
            source_root=source_root,
            parser_version=PARSER_VERSION,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            documents={
                doc.path: DocumentEntry(
                    sha256=doc.sha256,
                    mtime_ns=doc.mtime_ns,
                    size_bytes=doc.size_bytes,
                    status="indexed",
                    chunk_count=sum(
                        1 for c in all_chunks if c["source"] == doc.path
                    ),
                )
                for doc, _ in docs_with_text
            },
        )
        save_manifest(new_manifest, staging)
        publish_store(staging, out_dir)
        report["published_path"] = str(out_dir)
        print(f"  Published: {out_dir} ({len(all_chunks)} chunks)")
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


# ---- CLI ----

def main():
    parser = argparse.ArgumentParser(
        description="Grain Storage Knowledge Ingestion"
    )
    parser.add_argument(
        "--project-id",
        help="Target project ID",
        default=None,
    )
    parser.add_argument(
        "--scope",
        choices=["base", "all-projects"],
        default=None,
        help="Ingestion scope (default: inferred from --project-id)",
    )
    parser.add_argument(
        "--source",
        help="Copy this file into the project before ingestion",
        default=None,
    )

    args = parser.parse_args()

    # Resolve scope
    if args.scope:
        scope = args.scope
    elif args.project_id:
        scope = "project"
    else:
        scope = "base"

    if scope == "project" and not args.project_id:
        parser.error("--project-id is required for project scope")

    if args.project_id:
        validate_project_id(args.project_id)

    report = run_ingestion(
        scope=scope,
        project_id=args.project_id,
        source_file=args.source,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_ingest_cli.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ingest_knowledge.py tests/unit/test_ingest_cli.py
git commit -m "feat: add ingest_knowledge.py CLI with scope routing and incremental build"
```

---

### Task 6: VectorStoreRegistry — multi-store loading and caching

**Files:**
- Create: `app/rag/registry.py`
- Create: `tests/unit/test_registry.py`

**Interfaces:**
- Consumes: `Path` to vector store root.
- Produces: `VectorStoreRegistry` class with `get_base() -> VectorStore | None`, `get_project(project_id: str) -> VectorStore | None`, `reload() -> None`.

- [ ] **Step 1: Write failing registry tests**

```python
# tests/unit/test_registry.py
import json
from pathlib import Path

import numpy as np
import pytest

from app.rag.registry import VectorStoreRegistry


def _write_store(path: Path, n: int = 2) -> None:
    path.mkdir(parents=True, exist_ok=True)
    np.save(
        path / "vectors.npy",
        np.array([[1.0, 0.0], [0.0, 1.0]][:n], dtype=np.float32),
    )
    metadata = [
        {"text": f"chunk {i}", "source": f"doc{i}.pdf", "start_pos": 0}
        for i in range(n)
    ]
    (path / "chunks_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )


def test_registry_loads_base_store(tmp_path: Path):
    _write_store(tmp_path / "base")
    registry = VectorStoreRegistry(tmp_path)
    store = registry.get_base()
    assert store is not None
    assert store.dimension == 2


def test_registry_loads_project_store(tmp_path: Path):
    _write_store(tmp_path / "projects" / "demo")
    registry = VectorStoreRegistry(tmp_path)
    store = registry.get_project("demo")
    assert store is not None
    assert store.dimension == 2


def test_registry_returns_none_for_missing_base(tmp_path: Path):
    registry = VectorStoreRegistry(tmp_path)
    assert registry.get_base() is None


def test_registry_returns_none_for_missing_project(tmp_path: Path):
    registry = VectorStoreRegistry(tmp_path)
    assert registry.get_project("no-such-project") is None


def test_registry_caches_loaded_stores(tmp_path: Path):
    _write_store(tmp_path / "base")
    registry = VectorStoreRegistry(tmp_path)
    s1 = registry.get_base()
    s2 = registry.get_base()
    assert s1 is s2  # same object (cached)


def test_registry_reload_clears_cache(tmp_path: Path):
    _write_store(tmp_path / "base")
    registry = VectorStoreRegistry(tmp_path)
    s1 = registry.get_base()
    registry.reload()
    s2 = registry.get_base()
    assert s1 is not s2  # new instance after reload
    assert s2 is not None


def test_registry_multiple_projects_isolated(tmp_path: Path):
    _write_store(tmp_path / "projects" / "alpha")
    _write_store(tmp_path / "projects" / "beta")
    registry = VectorStoreRegistry(tmp_path)
    alpha = registry.get_project("alpha")
    beta = registry.get_project("beta")
    assert alpha is not None
    assert beta is not None
    assert alpha is not beta
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_registry.py -v
```
Expected: collection fails with `ModuleNotFoundError: No module named 'app.rag.registry'`.

- [ ] **Step 3: Implement registry module**

```python
# app/rag/registry.py
from pathlib import Path

from app.rag.vector_store import VectorStore, VectorStoreNotReady


class VectorStoreRegistry:
    """Loads and caches VectorStore instances by scope + project_id.

    Cache is in-process; service restart clears it. Newly published stores
    become visible after calling reload() or restarting the service.
    """

    def __init__(self, root_dir: Path) -> None:
        self._root = Path(root_dir)
        self._base: VectorStore | None = None
        self._base_loaded = False
        self._projects: dict[str, VectorStore | None] = {}

    def get_base(self) -> VectorStore | None:
        if not self._base_loaded:
            self._base = self._load_store(self._root / "base")
            self._base_loaded = True
        return self._base

    def get_project(self, project_id: str) -> VectorStore | None:
        if project_id not in self._projects:
            store = self._load_store(
                self._root / "projects" / project_id
            )
            self._projects[project_id] = store
        return self._projects[project_id]

    def reload(self) -> None:
        self._base = None
        self._base_loaded = False
        self._projects.clear()

    @staticmethod
    def _load_store(directory: Path) -> VectorStore | None:
        try:
            return VectorStore.load(directory)
        except VectorStoreNotReady:
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_registry.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add app/rag/registry.py tests/unit/test_registry.py
git commit -m "feat: add VectorStoreRegistry for multi-store loading"
```

---

### Task 7: ProjectRetriever — merged base + project retrieval

**Files:**
- Create: `app/rag/project_retriever.py`
- Create: `tests/unit/test_project_retriever.py`

**Interfaces:**
- Consumes: `VectorStoreRegistry`, `EmbeddingProvider`, `min_score`.
- Produces: `ProjectRetriever.retrieve(request: RetrieveRequest) -> RetrieveResponse` — embeds once, searches base + project, merges by score descending, returns top-k.

- [ ] **Step 1: Write failing project retriever tests**

```python
# tests/unit/test_project_retriever.py
import json
from pathlib import Path

import numpy as np
import pytest

from app.rag.project_retriever import ProjectRetriever
from app.rag.registry import VectorStoreRegistry
from app.schemas.tools import RetrieveRequest


def _write_store(path: Path, texts: list[str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(42)
    vectors = rng.randn(len(texts), 2560).astype(np.float32)
    np.save(path / "vectors.npy", vectors)
    metadata = [
        {"text": t, "source": f"doc{i}.pdf", "start_pos": 0}
        for i, t in enumerate(texts)
    ]
    (path / "chunks_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )


class FakeEmbedding:
    async def embed(self, text: str, domain: str) -> np.ndarray:
        return np.ones(2560, dtype=np.float32)


@pytest.mark.asyncio
async def test_project_retriever_merges_base_and_project(tmp_path: Path):
    _write_store(tmp_path / "base", ["base chunk 1", "base chunk 2"])
    _write_store(tmp_path / "projects" / "demo", ["project chunk A"])

    registry = VectorStoreRegistry(tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-0.5,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="test query",
            top_k=5,
            project_id="demo",
        )
    )

    sources = {e.source for e in response.evidences}
    assert len(sources) == 3  # 2 base + 1 project
    assert response.request_id == "req"


@pytest.mark.asyncio
async def test_project_retriever_base_only_when_no_project_id(tmp_path: Path):
    _write_store(tmp_path / "base", ["base chunk"])

    registry = VectorStoreRegistry(tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-0.5,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="test",
            top_k=3,
            # no project_id
        )
    )

    assert len(response.evidences) == 1
    assert response.evidences[0].source == "doc0.pdf"


@pytest.mark.asyncio
async def test_project_retriever_respects_top_k(tmp_path: Path):
    _write_store(tmp_path / "base", [f"base {i}" for i in range(10)])

    registry = VectorStoreRegistry(tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="test",
            top_k=3,
        )
    )

    assert len(response.evidences) == 3


@pytest.mark.asyncio
async def test_project_retriever_never_leaks_cross_project(tmp_path: Path):
    _write_store(tmp_path / "projects" / "demo", ["demo chunk"])
    _write_store(tmp_path / "projects" / "other", ["other chunk"])

    registry = VectorStoreRegistry(tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="test",
            top_k=5,
            project_id="demo",
        )
    )

    sources = {e.source for e in response.evidences}
    assert len(response.evidences) == 1
    # "other" project's chunks should never appear
    assert all("other" not in s for s in sources)


@pytest.mark.asyncio
async def test_project_retriever_with_missing_project_still_uses_base(tmp_path: Path):
    _write_store(tmp_path / "base", ["base content"])

    registry = VectorStoreRegistry(tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="test",
            top_k=5,
            project_id="no-such-project",
        )
    )

    assert len(response.evidences) == 1
    assert response.quality.sufficient is True
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_project_retriever.py -v
```
Expected: collection fails because `app.rag.project_retriever` does not exist.

- [ ] **Step 3: Implement project retriever**

```python
# app/rag/project_retriever.py
from typing import Protocol

import numpy as np

from app.rag.evidence import build_evidence
from app.rag.registry import VectorStoreRegistry
from app.rag.vector_store import SearchHit
from app.schemas.tools import (
    RetrieveRequest,
    RetrieveResponse,
    RetrievalQuality,
)


class EmbeddingProvider(Protocol):
    async def embed(self, text: str, domain: str) -> np.ndarray: ...


class ProjectRetriever:
    """Embeds query once, searches base + project stores, merges results."""

    def __init__(
        self,
        *,
        registry: VectorStoreRegistry,
        embedding: EmbeddingProvider,
        min_score: float,
    ) -> None:
        self._registry = registry
        self._embedding = embedding
        self._min_score = min_score

    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        query_vector = await self._embedding.embed(
            request.query, domain="query"
        )

        # Collect hits from base + project
        all_hits: list[SearchHit] = []

        base = self._registry.get_base()
        if base is not None:
            all_hits.extend(base.search(query_vector, top_k=len(base.metadata)))

        project_id = getattr(request, "project_id", None)
        if project_id:
            project_store = self._registry.get_project(project_id)
            if project_store is not None:
                all_hits.extend(
                    project_store.search(
                        query_vector, top_k=len(project_store.metadata)
                    )
                )

        # Apply filters
        if request.filters.source_type:
            all_hits = [
                h for h in all_hits
                if h.metadata.get("source_type") == request.filters.source_type
            ]
        if request.filters.authority_level:
            all_hits = [
                h for h in all_hits
                if h.metadata.get("authority_level") == request.filters.authority_level
            ]

        # Sort by score descending, take top_k
        all_hits.sort(key=lambda h: h.score, reverse=True)
        top_hits = all_hits[: request.top_k]

        evidences = [
            build_evidence(h.metadata, h.score) for h in top_hits
        ]
        top_score = evidences[0].score if evidences else 0.0

        return RetrieveResponse(
            request_id=request.request_id,
            query=request.query,
            evidences=evidences,
            quality=RetrievalQuality(
                top_score=top_score,
                sufficient=bool(
                    evidences and top_score >= self._min_score
                ),
            ),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_project_retriever.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/rag/project_retriever.py tests/unit/test_project_retriever.py
git commit -m "feat: add ProjectRetriever with merged base+project search"
```

---

### Task 8: Schema extensions — add project_id to request models

**Files:**
- Modify: `app/schemas/api.py`
- Modify: `app/schemas/tools.py`
- Modify: `tests/unit/test_schemas.py`

**Interfaces:**
- Adds `project_id: str | None = None` to `ChatRequest`, `CaseAnalyzeRequest`, and `RetrieveRequest`.

- [ ] **Step 1: Write failing schema tests**

Add to `tests/unit/test_schemas.py`:

```python
def test_chat_request_accepts_project_id():
    request = ChatRequest(message="test", project_id="demo")
    assert request.project_id == "demo"


def test_chat_request_project_id_defaults_none():
    request = ChatRequest(message="test")
    assert request.project_id is None


def test_chat_request_project_id_rejects_invalid():
    with pytest.raises(ValidationError):
        ChatRequest(message="test", project_id="has/slash")


def test_retrieve_request_accepts_project_id():
    from app.schemas.tools import RetrieveRequest
    request = RetrieveRequest(request_id="req", query="q", project_id="demo")
    assert request.project_id == "demo"


def test_case_analyze_request_accepts_project_id():
    request = CaseAnalyzeRequest(
        case=CaseData(grain_type="小麦"),
        project_id="demo",
    )
    assert request.project_id == "demo"


def test_case_analyze_request_rejects_long_project_id():
    with pytest.raises(ValidationError):
        CaseAnalyzeRequest(
            case=CaseData(grain_type="小麦"),
            project_id="a" * 65,
        )
```

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_schemas.py -v -k "project_id"
```
Expected: 6 failures — `project_id` field does not exist yet.

- [ ] **Step 3: Add project_id to schemas**

In `app/schemas/api.py`, add to `ChatRequest`:
```python
class ChatRequest(StrictPublicRequest):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    role: Role = Role.STUDENT
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
```

In `app/schemas/api.py`, add to `CaseAnalyzeRequest`:
```python
class CaseAnalyzeRequest(StrictPublicRequest):
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    role: Role = Role.TECHNICIAN
    case: CaseData
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
```

In `app/schemas/tools.py`, add to `RetrieveRequest`:
```python
class RetrieveRequest(StrictToolRequest):
    request_id: RequestId
    query: QueryText
    top_k: StrictInteger = Field(default=5, ge=1, le=20)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    project_id: ShortText | None = Field(default=None, min_length=1, max_length=64)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_schemas.py -v -k "project_id"
```
Expected: 6 passed.

Then run the full schema suite to check no regressions:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_schemas.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/schemas/api.py app/schemas/tools.py tests/unit/test_schemas.py
git commit -m "feat: add project_id to ChatRequest, CaseAnalyzeRequest, RetrieveRequest"
```

---

### Task 9: Wire project_id through gateway, tools, and API endpoints

**Files:**
- Modify: `app/main.py` — use `ProjectRetriever` instead of `Retriever`, pass `VectorStoreRegistry`
- Modify: `app/tools/routes.py` — pass `project_id` from retrieve request
- Modify: `app/api/chat.py` — pass `project_id` from chat request to workflow gateway
- Modify: `app/api/cases.py` — pass `project_id` to workflow gateway
- Modify: `app/services/workflow_gateway.py` — accept optional `project_id` and include in workflow parameters
- Modify: `tests/contract/test_tool_api.py` — update retrieve test to include `project_id`
- Modify: `tests/contract/test_public_api.py` — update public API tests
- Modify: `tests/integration/test_workflow_gateway.py` — verify `project_id` flows through

**Interfaces:**
- `ProjectRetriever` replaces `Retriever` in `build_container()`.
- `WorkflowGateway.stream()` accepts `project_id: str | None`.
- Tool `/tools/v1/retrieve` passes `request.project_id` through.
- Public `/v1/chat` and `/v1/cases/analyze` pass `payload.project_id` through.

- [ ] **Step 1: Write failing integration tests**

Add to `tests/contract/test_tool_api.py`:

```python
def test_retrieve_passes_project_id_to_retriever():
    captured = {}

    class CapturingRetriever:
        async def retrieve(self, request):
            captured["project_id"] = getattr(request, "project_id", None)
            return RetrieveResponse(
                request_id=request.request_id,
                query=request.query,
                evidences=[],
                quality=RetrievalQuality(top_score=0.0, sufficient=False),
            )

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        tools_service_token=SimpleNamespace(
            get_secret_value=lambda: "tool-token"
        )
    )
    app.state.container = ServiceContainer(
        retriever=CapturingRetriever(),
        generation=None,
        cases=None,
        citations=None,
        contexts=RequestContextStore(ttl_seconds=300),
        vector_store=None,
        workflow=None,
    )
    app.include_router(router)

    client = TestClient(app)
    client.post(
        "/tools/v1/retrieve",
        headers={"Authorization": "Bearer tool-token"},
        json={
            "request_id": "req",
            "query": "test",
            "top_k": 3,
            "project_id": "demo",
        },
    )

    assert captured["project_id"] == "demo"
```

Add to `tests/contract/test_public_api.py` a test that verifies `project_id` appears in the SSE meta or workflow parameters.

- [ ] **Step 2: Run tests to verify failures**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_tool_api.py -v -k "project_id"
```
Expected: the new test fails — `project_id` not passed through.

- [ ] **Step 3: Wire project_id through the stack**

In `app/main.py`, update `build_container()` to use `ProjectRetriever`:

```python
from app.rag.registry import VectorStoreRegistry
from app.rag.project_retriever import ProjectRetriever

# In build_container():
registry = VectorStoreRegistry(settings.vector_store_dir)
if store is None:
    retriever: Any = UnavailableRetriever(unavailable_error)
else:
    retriever = ProjectRetriever(
        registry=registry,
        embedding=embedding,
        min_score=settings.retrieval_min_score,
    )
```

In `app/api/chat.py`, pass `project_id`:

```python
return StreamingResponse(
    gateway.stream(
        message=payload.message,
        request_id=request.state.request_id,
        session_id=payload.session_id,
        user_id=payload.user_id,
        role=payload.role,
        task_type="knowledge_qa",
        project_id=payload.project_id,
    ),
    ...
)
```

In `app/api/cases.py`, similarly pass `project_id`.

In `app/services/workflow_gateway.py`, add `project_id` parameter:

```python
async def stream(
    self,
    *,
    message: str,
    ...
    project_id: str | None = None,
) -> AsyncIterator[str]:
    ...
    parameters = {
        ...
        "PROJECT_ID": project_id or "",
    }
```

In `app/tools/routes.py`, no change needed — `RetrieveRequest` already has `project_id` and it flows through naturally because the `RetrieveRequest` object is passed directly to `retriever.retrieve(payload)`.

- [ ] **Step 4: Run all affected tests**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_tool_api.py tests/contract/test_public_api.py tests/integration/test_workflow_gateway.py -v
```
Expected: all pass with `project_id` flowing through.

- [ ] **Step 5: Run full offline suite**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
```
Expected: all 682+ new tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/api/chat.py app/api/cases.py app/services/workflow_gateway.py tests/contract/test_tool_api.py tests/contract/test_public_api.py tests/integration/test_workflow_gateway.py
git commit -m "feat: wire project_id through gateway, tools, and API endpoints"
```

---

### Task 10: End-to-end contract verification

**Files:**
- Modify: `tests/contract/test_public_api.py` — add project-isolated retrieval test
- Create: (no new files, verify-only)

**Purpose:** One final contract test proving project isolation end-to-end.

- [ ] **Step 1: Write end-to-end project isolation contract test**

```python
@pytest.mark.asyncio
async def test_project_retrieval_isolation():
    """Project A never sees Project B chunks."""
    import tempfile
    from pathlib import Path

    import numpy as np

    from app.rag.registry import VectorStoreRegistry
    from app.rag.vector_store import VectorStore

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base_dir = root / "base"
        base_dir.mkdir()
        np.save(base_dir / "vectors.npy", np.eye(2, dtype=np.float32))
        import json
        (base_dir / "chunks_metadata.json").write_text(
            json.dumps([
                {"text": "base chunk", "source": "base.pdf", "start_pos": 0},
                {"text": "base chunk 2", "source": "base2.pdf", "start_pos": 0},
            ]),
            encoding="utf-8",
        )

        proj_a = root / "projects" / "alpha"
        proj_a.mkdir(parents=True)
        np.save(proj_a / "vectors.npy", np.eye(1, dtype=np.float32))
        (proj_a / "chunks_metadata.json").write_text(
            json.dumps([
                {"text": "alpha secret", "source": "alpha.pdf", "start_pos": 0},
            ]),
            encoding="utf-8",
        )

        registry = VectorStoreRegistry(root)
        base = registry.get_base()
        alpha_store = registry.get_project("alpha")

        assert base is not None
        assert alpha_store is not None

        # Project "beta" should not see "alpha"
        assert registry.get_project("beta") is None
        # Base has 2 chunks
        assert len(base.metadata) == 2
        # Alpha has 1 chunk
        assert len(alpha_store.metadata) == 1
```

- [ ] **Step 2: Run verification**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_public_api.py -v -k "isolation"
```
Expected: PASS.

- [ ] **Step 3: Full suite final verification**

Run:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m compileall -q app/ ingest_knowledge.py
git diff --check
```

- [ ] **Step 4: Commit**

```bash
git add tests/contract/test_public_api.py
git commit -m "test: verify project isolation end-to-end"
```

---
