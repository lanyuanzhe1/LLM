import ast
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest


BUILD_SCRIPT = Path(__file__).parents[2] / "build_vector_store.py"
REQUIRED_ENV = (
    "XF_APP_ID",
    "XF_EMBEDDING_API_KEY",
    "XF_EMBEDDING_API_SECRET",
)


def _load_build_module(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "build_vector_store_under_test", BUILD_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_chunks():
    return [
        {
            "text": "低温储粮",
            "source": "政策文件类/sample.txt",
            "document_checksum": "a" * 64,
            "source_type": "政策文件类",
            "embedding": np.array([1.0, 0.0], dtype=np.float32),
        }
    ]


def test_vector_build_reads_credentials_from_environment():
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    for variable, environment_name in {
        "APP_ID": "XF_APP_ID",
        "API_KEY": "XF_EMBEDDING_API_KEY",
        "API_SECRET": "XF_EMBEDDING_API_SECRET",
    }.items():
        expression = assignments[variable]
        assert isinstance(expression, ast.Call)
        assert ast.unparse(expression.func) == "os.environ.get"
        assert [
            argument.value
            for argument in expression.args
            if isinstance(argument, ast.Constant)
        ] == [environment_name, ""]
    assert "SKIP_VECTOR_SEARCH" in source


def test_vector_build_rejects_missing_environment_before_reading_documents(
    monkeypatch, tmp_path
):
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    module = _load_build_module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "load_documents",
        lambda *_: pytest.fail("documents were read before configuration validation"),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Missing required environment variables: XF_APP_ID, "
            "XF_EMBEDDING_API_KEY, XF_EMBEDDING_API_SECRET"
        ),
    ):
        module.main()


def test_import_does_not_create_vector_store_directory(monkeypatch, tmp_path):
    _load_build_module(monkeypatch, tmp_path)

    assert not (tmp_path / "vector_store").exists()


def test_loaded_documents_use_relative_posix_source_and_raw_checksum(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)
    doc_dir = tmp_path / "knowledge"
    source = doc_dir / "政策文件类" / "sample.txt"
    source.parent.mkdir(parents=True)
    raw = "低温储粮\r\n".encode()
    source.write_bytes(raw)

    documents = module.load_documents(doc_dir)

    assert documents == [
        {
            "file": "政策文件类/sample.txt",
            "text": "低温储粮\n",
            "char_count": 5,
            "document_checksum": hashlib.sha256(raw).hexdigest(),
            "source_type": "政策文件类",
        }
    ]


def test_loaded_documents_reject_symlinked_files_and_directories_before_read(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)
    doc_dir = tmp_path / "knowledge"
    external_dir = tmp_path / "external"
    doc_dir.mkdir()
    external_dir.mkdir()
    safe = doc_dir / "safe.txt"
    external = external_dir / "secret.txt"
    safe.write_text("safe", encoding="utf-8")
    external.write_text("external", encoding="utf-8")
    try:
        (doc_dir / "linked-file.txt").symlink_to(external)
        (doc_dir / "linked-dir").symlink_to(
            external_dir,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    read_paths = []
    real_read_text_file = module.read_text_file

    def record_read(path):
        read_paths.append(path)
        return real_read_text_file(path)

    monkeypatch.setattr(module, "read_text_file", record_read)

    documents = module.load_documents(doc_dir)

    assert [item["file"] for item in documents] == ["safe.txt"]
    assert read_paths == [safe]


def test_symlinked_document_root_is_rejected(monkeypatch, tmp_path):
    module = _load_build_module(monkeypatch, tmp_path)
    real_dir = tmp_path / "real-knowledge"
    linked_dir = tmp_path / "knowledge"
    real_dir.mkdir()
    (real_dir / "secret.txt").write_text("external", encoding="utf-8")
    try:
        linked_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(RuntimeError, match="symlink"):
        module.load_documents(linked_dir)


def test_chunk_metadata_propagates_checksum_and_source_type(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)

    chunks = module.chunk_text(
        "第一段。\n\n第二段。",
        "政策文件类/sample.txt",
        document_checksum="a" * 64,
        source_type="政策文件类",
        chunk_size=5,
        overlap=0,
    )

    assert chunks
    assert {chunk["document_checksum"] for chunk in chunks} == {"a" * 64}
    assert {chunk["source_type"] for chunk in chunks} == {"政策文件类"}


@pytest.mark.parametrize(
    ("text", "chunk_size", "overlap"),
    [
        ("ABCDEFGHIJK\n\nTAIL", 5, 0),
        ("无标点长句ABCDEFGHIJKLMN", 5, 0),
        ("重复\n\n重复\n\n重复", 4, 0),
        ("第一段。\n\n第二段。\n\n第三段。", 7, 2),
        ("粮温🌾监测ABC粮温🌾监测", 6, 2),
    ],
)
def test_chunk_text_uses_exact_source_offsets_and_hard_size_bound(
    monkeypatch,
    tmp_path,
    text,
    chunk_size,
    overlap,
):
    module = _load_build_module(monkeypatch, tmp_path)

    chunks = module.chunk_text(
        text,
        "sample.txt",
        chunk_size=chunk_size,
        overlap=overlap,
    )

    assert chunks
    for chunk in chunks:
        start = chunk["start_pos"]
        assert start >= 0
        assert chunk["text"] == text[start : start + chunk["char_count"]]
        assert chunk["char_count"] == len(chunk["text"])
        assert chunk["char_count"] <= chunk_size


def test_chunk_size_five_probe_has_deterministic_real_offsets(
    monkeypatch,
    tmp_path,
):
    module = _load_build_module(monkeypatch, tmp_path)
    text = "ABCDEFGHIJK\n\nTAIL"

    chunks = module.chunk_text(
        text,
        "sample.txt",
        chunk_size=5,
        overlap=0,
    )

    assert [
        (chunk["start_pos"], chunk["text"], chunk["char_count"])
        for chunk in chunks
    ] == [
        (0, "ABCDE", 5),
        (5, "FGHIJ", 5),
        (10, "K\n\n", 3),
        (13, "TAIL", 4),
    ]


def test_overlap_is_an_exact_source_prefix_with_bounded_windows(
    monkeypatch,
    tmp_path,
):
    module = _load_build_module(monkeypatch, tmp_path)
    text = "ABCDEFGHIJK"

    chunks = module.chunk_text(
        text,
        "sample.txt",
        chunk_size=5,
        overlap=2,
    )

    assert [
        (chunk["start_pos"], chunk["text"])
        for chunk in chunks
    ] == [
        (0, "ABCDE"),
        (3, "DEFGH"),
        (6, "GHIJK"),
    ]


def test_embed_all_chunks_aborts_without_zero_vector_substitution(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)

    class PartiallyFailingClient:
        calls = 0

        def embed(self, text, domain):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("provider failure")
            return np.array([1.0, 0.0], dtype=np.float32)

    chunks = [
        {"text": "one"},
        {"text": "two"},
        {"text": "three"},
    ]

    with pytest.raises(RuntimeError, match="chunk 1"):
        module.embed_all_chunks(chunks, PartiallyFailingClient())
    assert "embedding" not in chunks[1]
    assert "embedding" not in chunks[2]


@pytest.mark.parametrize(
    "embedding",
    [
        np.array([0.0, 0.0], dtype=np.float32),
        np.array([np.nan, 1.0], dtype=np.float32),
    ],
)
def test_build_index_rejects_invalid_embeddings(
    monkeypatch, tmp_path, embedding
):
    module = _load_build_module(monkeypatch, tmp_path)
    chunks = _valid_chunks()
    chunks[0]["embedding"] = embedding

    with pytest.raises(RuntimeError, match="embedding"):
        module.build_index(chunks)


def _write_old_store(path: Path):
    path.mkdir()
    np.save(path / "vectors.npy", np.array([[0.0, 1.0]], dtype=np.float32))
    (path / "chunks_metadata.json").write_text(
        json.dumps(
            [
                {
                    "text": "old",
                    "source": "old.pdf",
                    "document_checksum": "f" * 64,
                }
            ]
        ),
        encoding="utf-8",
    )


def test_invalid_staged_store_preserves_existing_published_store(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)
    output = tmp_path / "vector_store"
    _write_old_store(output)

    class InvalidIndex:
        _fit_X = np.array([[0.0, 0.0]], dtype=np.float32)

    with pytest.raises(Exception):
        module.publish_vector_store(InvalidIndex(), _valid_chunks(), output)

    assert np.load(output / "vectors.npy").tolist() == [[0.0, 1.0]]
    assert json.loads(
        (output / "chunks_metadata.json").read_text(encoding="utf-8")
    )[0]["text"] == "old"


def test_swap_failure_rolls_back_existing_published_store(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)
    output = tmp_path / "vector_store"
    _write_old_store(output)

    class ValidIndex:
        _fit_X = np.array([[1.0, 0.0]], dtype=np.float32)

    real_replace = os.replace
    calls = 0

    def fail_new_store_swap(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated swap failure")
        return real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_new_store_swap)

    with pytest.raises(OSError, match="simulated swap failure"):
        module.publish_vector_store(ValidIndex(), _valid_chunks(), output)

    assert np.load(output / "vectors.npy").tolist() == [[0.0, 1.0]]
    assert not list(tmp_path.glob(".vector_store.staging-*"))
    assert not (tmp_path / ".vector_store.backup").exists()


def test_failed_swap_and_failed_restore_preserve_recoverable_backup(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)
    output = tmp_path / "vector_store"
    backup = tmp_path / ".vector_store.backup"
    _write_old_store(output)

    class ValidIndex:
        _fit_X = np.array([[1.0, 0.0]], dtype=np.float32)

    real_replace = os.replace
    calls = 0

    def fail_activation_and_restore(source, destination):
        nonlocal calls
        calls += 1
        if calls in (2, 3):
            raise OSError(f"simulated replace failure {calls}")
        return real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_activation_and_restore)

    with pytest.raises(RuntimeError, match=str(backup)):
        module.publish_vector_store(ValidIndex(), _valid_chunks(), output)

    assert not output.exists()
    assert np.load(backup / "vectors.npy").tolist() == [[0.0, 1.0]]
    assert json.loads(
        (backup / "chunks_metadata.json").read_text(encoding="utf-8")
    )[0]["text"] == "old"
    assert not list(tmp_path.glob(".vector_store.staging-*"))


def test_backup_cleanup_failure_keeps_new_store_active_and_old_store_recoverable(
    monkeypatch, tmp_path
):
    module = _load_build_module(monkeypatch, tmp_path)
    output = tmp_path / "vector_store"
    backup = tmp_path / ".vector_store.backup"
    _write_old_store(output)

    class ValidIndex:
        _fit_X = np.array([[1.0, 0.0]], dtype=np.float32)

    real_rmtree = module.shutil.rmtree

    def fail_backup_cleanup(path):
        if Path(path) == backup:
            raise OSError("simulated cleanup failure")
        return real_rmtree(path)

    monkeypatch.setattr(module.shutil, "rmtree", fail_backup_cleanup)

    with pytest.warns(RuntimeWarning, match="recoverable backup"):
        module.publish_vector_store(ValidIndex(), _valid_chunks(), output)

    assert np.load(output / "vectors.npy").tolist() == [[1.0, 0.0]]
    assert np.load(backup / "vectors.npy").tolist() == [[0.0, 1.0]]
    assert not list(tmp_path.glob(".vector_store.staging-*"))


def test_skip_vector_search_avoids_interactive_prompt(monkeypatch, tmp_path):
    for name in REQUIRED_ENV:
        monkeypatch.setenv(name, "test-only-value")
    monkeypatch.setenv("SKIP_VECTOR_SEARCH", "1")
    module = _load_build_module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "load_documents",
        lambda *_: [
            {
                "file": "sample.txt",
                "text": "低温储粮",
                "char_count": 4,
                "document_checksum": "a" * 64,
                "source_type": None,
            }
        ],
    )
    monkeypatch.setattr(module, "chunk_text", lambda *_, **__: _valid_chunks())
    monkeypatch.setattr(module, "EmbeddingClient", lambda *_: object())
    monkeypatch.setattr(module, "embed_all_chunks", lambda chunks, *_: chunks)
    monkeypatch.setattr(
        module, "build_index", lambda chunks: (object(), chunks)
    )
    monkeypatch.setattr(module, "publish_vector_store", lambda *_: None)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda *_: pytest.fail("interactive search prompt was reached"),
    )

    module.main()
