import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.neighbors import NearestNeighbors

from app.core.errors import ProviderUnavailable, VectorStoreNotReady
from app.rag.evidence import Evidence, build_evidence


MAX_VECTOR_FILE_BYTES = 512 * 1024 * 1024
MAX_METADATA_FILE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class SearchHit:
    index: int
    score: float
    metadata: dict[str, Any]


def _safe_normalize_rows(values: Any) -> np.ndarray:
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise ValueError("complex vectors are not supported")
    array = np.asarray(raw, dtype=np.float64)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise ValueError("vectors must be a finite two-dimensional array")
    maximum = np.max(np.abs(array), axis=1)
    if not np.isfinite(maximum).all() or np.any(maximum <= 0):
        raise ValueError("vectors must have finite positive norms")
    scaled = array / maximum[:, np.newaxis]
    scaled_norm = np.sqrt(np.sum(scaled * scaled, axis=1))
    if not np.isfinite(scaled_norm).all() or np.any(scaled_norm <= 0):
        raise ValueError("vectors must have finite positive norms")
    normalized = scaled / scaled_norm[:, np.newaxis]
    normalized_float32 = normalized.astype(np.float32)
    post_maximum = np.max(np.abs(normalized_float32), axis=1)
    if (
        not np.isfinite(normalized_float32).all()
        or not np.isfinite(post_maximum).all()
        or np.any(post_maximum <= 0)
    ):
        raise ValueError("normalized vectors must remain finite and non-zero")
    post_scaled = normalized_float32 / post_maximum[:, np.newaxis]
    post_norm = np.sqrt(
        np.sum(post_scaled.astype(np.float64) ** 2, axis=1)
    )
    if not np.isfinite(post_norm).all() or np.any(post_norm <= 0):
        raise ValueError("normalized vectors must retain positive norms")
    return normalized_float32


def _safe_artifact_paths(directory: Path) -> tuple[Path, Path]:
    if directory.is_symlink():
        raise VectorStoreNotReady("vector store directory is a symlink")
    try:
        resolved_directory = directory.resolve(strict=True)
    except OSError as exc:
        raise VectorStoreNotReady("向量库目录不可用") from exc
    if not resolved_directory.is_dir():
        raise VectorStoreNotReady("向量库路径必须是目录")

    artifacts: list[Path] = []
    for name in ("vectors.npy", "chunks_metadata.json"):
        artifact = directory / name
        if artifact.is_symlink():
            raise VectorStoreNotReady(f"{name} is a symlink")
        try:
            resolved_artifact = artifact.resolve(strict=True)
            resolved_artifact.relative_to(resolved_directory)
        except FileNotFoundError as exc:
            raise VectorStoreNotReady(f"缺少 {name}") from exc
        except (OSError, ValueError) as exc:
            raise VectorStoreNotReady(
                f"{name} resolves outside vector store"
            ) from exc
        if not resolved_artifact.is_file():
            raise VectorStoreNotReady(f"{name} must be a regular file")
        artifacts.append(resolved_artifact)
    return artifacts[0], artifacts[1]


def _bounded_artifact_size(path: Path, maximum: int) -> int:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VectorStoreNotReady(f"{path.name} is unavailable") from exc
    if size <= 0:
        raise VectorStoreNotReady(f"{path.name} is empty")
    if size > maximum:
        raise VectorStoreNotReady(f"{path.name} is too large")
    return size


def _npy_shape_preflight(path: Path, file_size: int) -> tuple[int, int]:
    try:
        with path.open("rb") as artifact:
            version = np.lib.format.read_magic(artifact)
            if version == (1, 0):
                shape, _, dtype = np.lib.format.read_array_header_1_0(
                    artifact
                )
            elif version == (2, 0):
                shape, _, dtype = np.lib.format.read_array_header_2_0(
                    artifact
                )
            else:
                raise ValueError("unsupported npy format version")
            header_size = artifact.tell()
    except (OSError, TypeError, ValueError) as exc:
        raise VectorStoreNotReady("vectors.npy header is invalid") from exc

    dtype = np.dtype(dtype)
    if (
        not isinstance(shape, tuple)
        or len(shape) != 2
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in shape
        )
        or dtype.hasobject
        or dtype.itemsize <= 0
    ):
        raise VectorStoreNotReady("vectors.npy shape or dtype is invalid")
    expected_size = header_size + math.prod(shape) * dtype.itemsize
    if expected_size != file_size:
        raise VectorStoreNotReady("vectors.npy payload size is invalid")
    return int(shape[0]), int(shape[1])


class VectorStore:
    def __init__(
        self,
        vectors: np.ndarray,
        metadata: list[dict[str, Any]],
    ) -> None:
        if not isinstance(metadata, list):
            raise VectorStoreNotReady("知识块元数据必须是 JSON 数组")
        try:
            raw_array = np.asarray(vectors)
        except (TypeError, ValueError, OverflowError) as exc:
            raise VectorStoreNotReady("向量数据格式无效") from exc
        if (
            raw_array.ndim != 2
            or raw_array.shape[0] == 0
            or raw_array.shape[1] == 0
        ):
            raise VectorStoreNotReady("向量库必须是非空二维数组")
        if raw_array.shape[0] != len(metadata):
            raise VectorStoreNotReady("向量数量与知识块元数据不一致")
        try:
            normalized_vectors = _safe_normalize_rows(raw_array)
        except (TypeError, ValueError, OverflowError) as exc:
            raise VectorStoreNotReady(f"向量数据无效: {exc}") from exc

        validated_metadata: list[dict[str, Any]] = []
        evidences: list[Evidence] = []
        evidence_ids: set[str] = set()
        try:
            for item in metadata:
                if not isinstance(item, dict):
                    raise ValueError("metadata item must be an object")
                text = item.get("text")
                source = item.get("source")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("metadata text must be non-empty")
                if not isinstance(source, str) or not source.strip():
                    raise ValueError("metadata source must be non-empty")
                start_pos = item.get("start_pos", 0)
                if (
                    isinstance(start_pos, bool)
                    or not isinstance(start_pos, int)
                    or start_pos < 0
                ):
                    raise ValueError("metadata start_pos must be non-negative")
                quality_flags = item.get("quality_flags", [])
                if not isinstance(quality_flags, list) or any(
                    not isinstance(flag, str) or not flag.strip()
                    for flag in quality_flags
                ):
                    raise ValueError("metadata quality_flags must be strings")
                for optional_key in ("source_type", "authority_level"):
                    optional_value = item.get(optional_key)
                    if optional_value is not None and (
                        not isinstance(optional_value, str)
                        or not optional_value.strip()
                    ):
                        raise ValueError(
                            f"metadata {optional_key} must be non-empty"
                        )
                normalized_item = dict(item)
                evidence = build_evidence(normalized_item, score=None)
                normalized_item["source"] = evidence.source
                if evidence.evidence_id in evidence_ids:
                    raise ValueError("duplicate evidence identity")
                evidence_ids.add(evidence.evidence_id)
                validated_metadata.append(normalized_item)
                evidences.append(evidence)
        except (KeyError, TypeError, ValueError) as exc:
            raise VectorStoreNotReady(f"知识块元数据无效: {exc}") from exc

        self.vectors = normalized_vectors
        self.metadata = validated_metadata
        self.index = NearestNeighbors(metric="cosine", algorithm="brute")
        self.index.fit(self.vectors)
        self._evidence_by_id = {
            evidence.evidence_id: evidence for evidence in evidences
        }

    @classmethod
    def load(cls, directory: Path) -> "VectorStore":
        directory = Path(directory)
        try:
            vectors_path, metadata_path = _safe_artifact_paths(directory)
            vector_size = _bounded_artifact_size(
                vectors_path,
                MAX_VECTOR_FILE_BYTES,
            )
            _bounded_artifact_size(
                metadata_path,
                MAX_METADATA_FILE_BYTES,
            )
            vector_rows, _ = _npy_shape_preflight(
                vectors_path,
                vector_size,
            )
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
            if not isinstance(metadata, list):
                raise VectorStoreNotReady(
                    "知识块元数据必须是 JSON 数组"
                )
            if len(metadata) != vector_rows:
                raise VectorStoreNotReady(
                    "向量数量与知识块元数据不一致"
                )
            vectors = np.load(vectors_path, allow_pickle=False)
        except VectorStoreNotReady:
            raise
        except Exception as exc:
            raise VectorStoreNotReady(f"向量库无法加载: {exc}") from exc
        try:
            return cls(vectors=vectors, metadata=metadata)
        except VectorStoreNotReady:
            raise
        except Exception as exc:
            raise VectorStoreNotReady(f"向量库无法加载: {exc}") from exc

    @property
    def dimension(self) -> int:
        return int(self.vectors.shape[1])

    def search(self, query_vector: np.ndarray, top_k: int) -> list[SearchHit]:
        try:
            raw_vector = np.asarray(query_vector)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ProviderUnavailable(
                "EMBEDDING_UNAVAILABLE", "查询向量不可用"
            ) from exc
        if raw_vector.ndim == 2 and raw_vector.shape[0] == 1:
            raw_vector = raw_vector[0]
        if (
            raw_vector.ndim != 1
            or raw_vector.size != self.dimension
        ):
            raise ProviderUnavailable(
                "EMBEDDING_UNAVAILABLE", "查询向量不可用"
            )
        try:
            vector = _safe_normalize_rows(raw_vector.reshape(1, -1))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ProviderUnavailable(
                "EMBEDDING_UNAVAILABLE", "查询向量不可用"
            ) from exc
        count = min(top_k, len(self.metadata))
        distances, indices = self.index.kneighbors(vector, n_neighbors=count)
        return [
            SearchHit(
                index=int(index),
                score=max(-1.0, min(1.0, 1.0 - float(distance))),
                metadata=self.metadata[int(index)],
            )
            for distance, index in zip(distances[0], indices[0])
        ]

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        return self._evidence_by_id.get(evidence_id)
