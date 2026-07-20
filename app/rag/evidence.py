import hashlib
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field


EvidenceId = Annotated[str, Field(min_length=1, max_length=128)]
EvidenceTitle = Annotated[str, Field(min_length=1, max_length=512)]
EvidenceSource = Annotated[str, Field(min_length=1, max_length=1024)]
EvidenceText = Annotated[str, Field(min_length=1, max_length=32000)]
EvidenceMetadata = Annotated[str, Field(min_length=1, max_length=256)]
QualityFlag = Annotated[str, Field(min_length=1, max_length=128)]
StrictPage = Annotated[int, Field(strict=True, ge=0)]
StrictScore = Annotated[
    float,
    Field(strict=True, ge=-1.0, le=1.0, allow_inf_nan=False),
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: EvidenceId
    document_id: EvidenceId
    title: EvidenceTitle
    source: EvidenceSource
    page: StrictPage | None = None
    section: EvidenceMetadata | None = None
    article_no: EvidenceMetadata | None = None
    text: EvidenceText
    score: StrictScore | None
    authority_level: EvidenceMetadata = "unknown"
    version: EvidenceMetadata | None = None
    quality_flags: list[QualityFlag] = Field(default_factory=list, max_length=20)


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _none_if_empty(value: Any) -> Any:
    return None if value in (None, "") else value


def normalize_source(source: Any) -> str:
    if not isinstance(source, str):
        raise ValueError("source must be a relative path string")
    value = source.strip().replace("\\", "/")
    if (
        not value
        or value.startswith("/")
        or value.startswith("//")
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ValueError("source must be a safe relative path")
    raw_parts = value.split("/")
    if ".." in raw_parts:
        raise ValueError("source must not contain traversal")
    normalized = PurePosixPath(value).as_posix()
    if normalized in ("", ".") or PurePosixPath(normalized).is_absolute():
        raise ValueError("source must be a safe relative path")
    return normalized


def canonical_display_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("_", " ")
    return " ".join(normalized.split())


def build_evidence(metadata: dict[str, Any], score: float | None) -> Evidence:
    source = normalize_source(metadata["source"])
    text = str(metadata["text"])
    start_pos = int(metadata.get("start_pos", 0))
    document_checksum = metadata.get("document_checksum")
    if document_checksum is not None:
        if not isinstance(document_checksum, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", document_checksum.strip()
        ):
            raise ValueError("document_checksum must be a SHA-256 hex digest")
        document_checksum = document_checksum.strip().lower()
    document_id = _sha256(f"{source}\n{document_checksum or ''}")
    evidence_id = _sha256(f"{document_id}\n{start_pos}\n{text}")
    optional = ("page", "section", "article_no", "version", "authority_level")
    flags = list(metadata.get("quality_flags", []))
    if document_checksum is None:
        flags.append("checksum_missing")
    if any(metadata.get(key) in (None, "") for key in optional):
        flags.append("metadata_incomplete")
    page = _none_if_empty(metadata.get("page"))
    section = _none_if_empty(metadata.get("section"))
    article_no = _none_if_empty(metadata.get("article_no"))
    version = _none_if_empty(metadata.get("version"))
    authority_level = _none_if_empty(metadata.get("authority_level"))
    return Evidence(
        evidence_id=evidence_id,
        document_id=document_id,
        title=canonical_display_label(
            str(metadata.get("title") or PurePosixPath(source).stem)
        ),
        source=source,
        page=page,
        section=section,
        article_no=article_no,
        text=text,
        score=score,
        authority_level=str(authority_level or "unknown"),
        version=version,
        quality_flags=sorted(set(flags)),
    )
