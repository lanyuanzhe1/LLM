import json
from pathlib import Path

import numpy as np
import pytest

from app.core.errors import ProviderUnavailable, VectorStoreNotReady
from app.rag import vector_store as vector_store_module
from app.rag.vector_store import VectorStore


def write_store(
    path: Path,
    *,
    vectors: np.ndarray | None = None,
    metadata: object | None = None,
) -> None:
    path.mkdir()
    np.save(
        path / "vectors.npy",
        vectors
        if vectors is not None
        else np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )
    (path / "chunks_metadata.json").write_text(
        json.dumps(
            metadata
            if metadata is not None
            else [
                {"text": "低温储粮", "source": "a.pdf", "start_pos": 0},
                {"text": "害虫防治", "source": "b.pdf", "start_pos": 10},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_load_and_search_exact_cosine(tmp_path: Path):
    store_path = tmp_path / "vector_store"
    write_store(store_path)
    store = VectorStore.load(store_path)

    hits = store.search(np.array([0.9, 0.1], dtype=np.float32), top_k=1)

    assert hits[0].metadata["source"] == "a.pdf"
    assert hits[0].score > 0.9


def test_missing_store_is_readiness_error(tmp_path: Path):
    with pytest.raises(VectorStoreNotReady):
        VectorStore.load(tmp_path)


def test_truncated_numpy_artifact_is_readiness_error(tmp_path: Path):
    (tmp_path / "vectors.npy").write_bytes(b"")
    (tmp_path / "chunks_metadata.json").write_text(
        '[{"text":"x","source":"x.pdf"}]',
        encoding="utf-8",
    )

    with pytest.raises(VectorStoreNotReady):
        VectorStore.load(tmp_path)


def test_symlinked_store_directory_is_rejected(tmp_path: Path):
    real_store = tmp_path / "real-store"
    linked_store = tmp_path / "linked-store"
    write_store(real_store)
    try:
        linked_store.symlink_to(real_store, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(VectorStoreNotReady, match="symlink"):
        VectorStore.load(linked_store)


@pytest.mark.parametrize("artifact_name", ["vectors.npy", "chunks_metadata.json"])
def test_symlinked_or_escaping_vector_artifact_is_rejected(
    tmp_path: Path,
    artifact_name,
):
    store = tmp_path / "store"
    external = tmp_path / "external"
    write_store(store)
    external.mkdir()
    target = external / artifact_name
    original = store / artifact_name
    original.replace(target)
    try:
        original.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(VectorStoreNotReady, match="symlink|outside"):
        VectorStore.load(store)


@pytest.mark.parametrize(
    ("artifact_name", "limit_name"),
    [
        ("vectors.npy", "MAX_VECTOR_FILE_BYTES"),
        ("chunks_metadata.json", "MAX_METADATA_FILE_BYTES"),
    ],
)
def test_vector_artifact_size_is_bounded_before_full_load(
    monkeypatch,
    tmp_path: Path,
    artifact_name,
    limit_name,
):
    store = tmp_path / "store"
    write_store(store)
    artifact = store / artifact_name
    monkeypatch.setattr(
        vector_store_module,
        limit_name,
        artifact.stat().st_size - 1,
    )
    monkeypatch.setattr(
        np,
        "load",
        lambda *_args, **_kwargs: pytest.fail(
            "oversize artifact reached np.load"
        ),
    )

    with pytest.raises(VectorStoreNotReady, match="too large"):
        VectorStore.load(store)


def test_numpy_payload_size_must_exactly_match_header_shape(tmp_path: Path):
    store = tmp_path / "store"
    write_store(store)
    with (store / "vectors.npy").open("ab") as artifact:
        artifact.write(b"TRAILING_PROVIDER_DATA")

    with pytest.raises(VectorStoreNotReady, match="size"):
        VectorStore.load(store)


def test_vector_row_count_is_checked_before_numpy_payload_load(
    monkeypatch,
    tmp_path: Path,
):
    store = tmp_path / "store"
    write_store(
        store,
        metadata=[{"text": "only one", "source": "one.pdf"}],
    )
    monkeypatch.setattr(
        np,
        "load",
        lambda *_args, **_kwargs: pytest.fail(
            "row mismatch reached np.load"
        ),
    )

    with pytest.raises(VectorStoreNotReady, match="数量"):
        VectorStore.load(store)


def test_unexpected_numpy_parse_exception_is_readiness_error(
    monkeypatch, tmp_path
):
    store = tmp_path / "store"
    write_store(store)
    monkeypatch.setattr(
        np,
        "load",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("parser failure")
        ),
    )

    with pytest.raises(VectorStoreNotReady, match="parser failure"):
        VectorStore.load(store)


@pytest.mark.parametrize(
    ("vectors", "metadata"),
    [
        (np.empty((0, 2), dtype=np.float32), []),
        (np.empty((1, 0), dtype=np.float32), [{"text": "x", "source": "x.pdf"}]),
        (np.array([1.0, 0.0], dtype=np.float32), [{"text": "x", "source": "x.pdf"}]),
        (
            np.array([[np.nan, 0.0]], dtype=np.float32),
            [{"text": "x", "source": "x.pdf"}],
        ),
        (
            np.array([[np.inf, 0.0]], dtype=np.float32),
            [{"text": "x", "source": "x.pdf"}],
        ),
        (
            np.array([[0.0, 0.0]], dtype=np.float32),
            [{"text": "x", "source": "x.pdf"}],
        ),
        (
            np.array([[1.0, 0.0]], dtype=np.float32),
            [],
        ),
        (
            np.array([[1.0, 0.0]], dtype=np.float32),
            ["not-an-object"],
        ),
        (
            np.array([[1.0, 0.0]], dtype=np.float32),
            [{"text": "", "source": "x.pdf"}],
        ),
        (
            np.array([[1.0, 0.0]], dtype=np.float32),
            [{"text": "x", "source": "../x.pdf"}],
        ),
    ],
)
def test_load_normalizes_invalid_artifacts_to_readiness_error(
    tmp_path: Path, vectors, metadata
):
    path = tmp_path / "store"
    write_store(path, vectors=vectors, metadata=metadata)

    with pytest.raises(VectorStoreNotReady):
        VectorStore.load(path)


def test_load_rejects_duplicate_evidence_identity(tmp_path: Path):
    path = tmp_path / "store"
    duplicate = {
        "text": "same",
        "source": "same.pdf",
        "start_pos": 0,
        "document_checksum": "a" * 64,
    }
    write_store(path, metadata=[duplicate, duplicate])

    with pytest.raises(VectorStoreNotReady, match="duplicate"):
        VectorStore.load(path)


def test_legacy_metadata_without_checksum_is_loadable_and_flagged(tmp_path: Path):
    path = tmp_path / "store"
    write_store(path)

    store = VectorStore.load(path)

    assert all(
        "checksum_missing" in evidence.quality_flags
        for evidence in store._evidence_by_id.values()
    )


@pytest.mark.parametrize(
    "query",
    [
        np.array([np.nan, 0.0], dtype=np.float32),
        np.array([np.inf, 0.0], dtype=np.float32),
        np.array([0.0, 0.0], dtype=np.float32),
        np.array([1.0], dtype=np.float32),
        np.empty((0,), dtype=np.float32),
    ],
)
def test_invalid_query_vectors_map_to_stable_embedding_error(
    tmp_path: Path, query
):
    path = tmp_path / "store"
    write_store(path)
    store = VectorStore.load(path)

    with pytest.raises(ProviderUnavailable) as caught:
        store.search(query, top_k=1)

    assert caught.value.code == "EMBEDDING_UNAVAILABLE"


def test_search_scores_are_bounded_cosine_similarity(tmp_path: Path):
    path = tmp_path / "store"
    write_store(path)
    store = VectorStore.load(path)

    hits = store.search(np.array([-1.0, 0.0], dtype=np.float32), top_k=2)

    assert all(-1.0 <= hit.score <= 1.0 for hit in hits)


def test_huge_finite_stored_and_query_vectors_normalize_without_overflow(
    tmp_path: Path,
):
    path = tmp_path / "store"
    huge = np.finfo(np.float64).max
    write_store(
        path,
        vectors=np.array([[huge, huge], [huge, -huge]], dtype=np.float64),
        metadata=[
            {"text": "positive", "source": "a.pdf"},
            {"text": "negative", "source": "b.pdf"},
        ],
    )

    store = VectorStore.load(path)
    hits = store.search(
        np.array([huge, huge], dtype=np.float64),
        top_k=2,
    )

    assert np.isfinite(store.vectors).all()
    assert np.all(np.linalg.norm(store.vectors.astype(np.float64), axis=1) > 0)
    assert hits[0].metadata["source"] == "a.pdf"
    assert all(-1.0 <= hit.score <= 1.0 for hit in hits)


def test_huge_invalid_query_fails_with_stable_embedding_error(tmp_path: Path):
    path = tmp_path / "store"
    write_store(path)
    store = VectorStore.load(path)

    with pytest.raises(ProviderUnavailable) as caught:
        store.search(
            np.array([np.finfo(np.float64).max, np.inf]),
            top_k=1,
        )

    assert caught.value.code == "EMBEDDING_UNAVAILABLE"
