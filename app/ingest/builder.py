"""Vector index construction, artifact saving, and atomic publish for RAG ingestion."""

import json
import os
import shutil
from pathlib import Path

import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize


def build_index_from_chunks(chunks: list[dict]) -> NearestNeighbors:
    """Stack embeddings, L2-normalize, fit sklearn NearestNeighbors with cosine metric.

    Each chunk dict must have an "embedding" key with a float32 numpy array.
    Raises ValueError if chunks is empty or vectors contain NaN/Inf.
    """
    if not chunks:
        raise ValueError("chunk list is empty")
    vectors = np.stack([np.asarray(c["embedding"], dtype=np.float32) for c in chunks])
    if vectors.ndim != 2 or vectors.shape[0] == 0 or vectors.shape[1] == 0:
        raise ValueError("embedding vectors are invalid")
    if not np.isfinite(vectors).all():
        raise ValueError("embedding vectors contain NaN or Inf")
    vectors = normalize(vectors, norm="l2")
    nbrs = NearestNeighbors(
        n_neighbors=min(10, len(chunks)), metric="cosine", algorithm="brute"
    )
    nbrs.fit(vectors)
    return nbrs


def save_artifacts(nbrs: NearestNeighbors, chunks: list[dict], output_dir: Path) -> None:
    """Save vectors.npy and chunks_metadata.json. Strips "embedding" key from metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    vectors = nbrs._fit_X
    np.save(str(output_dir / "vectors.npy"), vectors)
    metadata = [
        {key: value for key, value in c.items() if key != "embedding"} for c in chunks
    ]
    (output_dir / "chunks_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def publish_store(staging_dir: Path, target_dir: Path) -> None:
    """Atomically replace target_dir with staging_dir.

    If target exists: rename target -> .old, rename staging -> target, then
    rmtree .old.  On failure during rename: restore .old -> target (rollback).
    If target doesn't exist: directly rename staging -> target.
    Validates staging contains vectors.npy + chunks_metadata.json before
    publishing.
    """
    staging_dir = Path(staging_dir)
    target_dir = Path(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not staging_dir.is_dir():
        raise FileNotFoundError(f"staging directory not found: {staging_dir}")
    if not (staging_dir / "vectors.npy").is_file():
        raise FileNotFoundError("staging directory missing vectors.npy")
    if not (staging_dir / "chunks_metadata.json").is_file():
        raise FileNotFoundError("staging directory missing chunks_metadata.json")
    if target_dir.exists():
        tmp = target_dir.parent / f".{target_dir.name}.old"
        if tmp.exists():
            shutil.rmtree(tmp)
        os.replace(target_dir, tmp)
        try:
            os.replace(staging_dir, target_dir)
        except Exception:
            os.replace(tmp, target_dir)
            raise
        else:
            shutil.rmtree(tmp)
    else:
        os.replace(staging_dir, target_dir)
