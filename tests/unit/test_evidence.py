import pytest
from pydantic import ValidationError

from app.rag.evidence import Evidence, build_evidence


def _evidence_payload(**overrides):
    payload = {
        "evidence_id": "  sha256:e1  ",
        "document_id": "  sha256:d1  ",
        "title": "  测试证据  ",
        "source": "  test.pdf  ",
        "text": "  低温能够抑制害虫活动。  ",
        "score": 0.9,
        "section": "  第一章  ",
        "quality_flags": ["  checked  "],
    }
    payload.update(overrides)
    return payload


def test_evidence_is_strict_bounded_and_whitespace_normalized():
    evidence = Evidence(**_evidence_payload())

    assert evidence.evidence_id == "sha256:e1"
    assert evidence.section == "第一章"
    assert evidence.quality_flags == ["checked"]

    missing_score = _evidence_payload()
    del missing_score["score"]
    for payload in (
        missing_score,
        _evidence_payload(unexpected=True),
        _evidence_payload(score=1.01),
        _evidence_payload(score=-1.01),
        _evidence_payload(evidence_id="e" * 129),
        _evidence_payload(title="t" * 513),
        _evidence_payload(source="s" * 1025),
        _evidence_payload(text="x" * 32001),
        _evidence_payload(section="s" * 257),
        _evidence_payload(quality_flags=["ok"] * 21),
        _evidence_payload(quality_flags=["q" * 129]),
    ):
        with pytest.raises(ValidationError):
            Evidence(**payload)


def test_evidence_id_is_stable_and_missing_metadata_is_explicit():
    metadata = {
        "text": "低温能够抑制储粮害虫活动。",
        "source": "其他论文/低温储粮技术.pdf",
        "start_pos": 100,
        "char_count": 15,
    }

    first = build_evidence(metadata, score=0.82)
    second = build_evidence(metadata, score=0.82)

    assert first.evidence_id == second.evidence_id
    assert first.page is None
    assert first.authority_level == "unknown"
    assert "metadata_incomplete" in first.quality_flags
    assert "checksum_missing" in first.quality_flags


def test_real_underscore_filename_gets_renderer_safe_display_title():
    source = (
        "河南工业大学论文/"
        "储粮中粮食自身呼吸与霉菌活动产生CO_2的特点_张燕燕.pdf"
    )
    evidence = build_evidence(
        {"source": source, "text": "证据", "start_pos": 0},
        score=0.9,
    )

    assert evidence.title == "储粮中粮食自身呼吸与霉菌活动产生CO 2的特点 张燕燕"
    assert "_" not in evidence.title


def test_document_identity_uses_raw_checksum_and_normalized_source():
    common = {
        "text": "低温能够抑制储粮害虫活动。",
        "start_pos": 100,
    }

    windows = build_evidence(
        {
            **common,
            "source": r"政策文件类\粮食安全法.docx",
            "document_checksum": "a" * 64,
        },
        score=0.82,
    )
    posix = build_evidence(
        {
            **common,
            "source": "政策文件类/粮食安全法.docx",
            "document_checksum": "a" * 64,
        },
        score=0.82,
    )
    changed = build_evidence(
        {
            **common,
            "source": "政策文件类/粮食安全法.docx",
            "document_checksum": "b" * 64,
        },
        score=0.82,
    )

    assert windows.source == "政策文件类/粮食安全法.docx"
    assert windows.document_id == posix.document_id
    assert windows.evidence_id == posix.evidence_id
    assert changed.document_id != posix.document_id
    assert "checksum_missing" not in posix.quality_flags


@pytest.mark.parametrize(
    "source",
    [
        "/private/knowledge/doc.pdf",
        "../outside.pdf",
        "folder/../../outside.pdf",
        r"C:\knowledge\doc.pdf",
        r"\\server\share\doc.pdf",
    ],
)
def test_evidence_rejects_absolute_and_traversal_sources(source):
    with pytest.raises(ValueError, match="source"):
        build_evidence(
            {
                "source": source,
                "text": "证据",
                "document_checksum": "a" * 64,
            },
            score=0.5,
        )


def test_empty_optional_metadata_is_normalized():
    evidence = build_evidence(
        {
            "text": "证据",
            "source": "测试.pdf",
            "page": "",
            "section": "",
            "article_no": "",
            "version": "",
            "authority_level": "",
        },
        score=0.8,
    )

    assert evidence.page is None
    assert evidence.section is None
    assert evidence.article_no is None
    assert evidence.version is None
    assert evidence.authority_level == "unknown"


def test_source_detail_score_can_be_null_but_query_score_remains_bounded():
    detail = build_evidence(
        {
            "text": "证据",
            "source": "测试.pdf",
            "document_checksum": "a" * 64,
        },
        score=None,
    )

    assert detail.score is None
    with pytest.raises(ValidationError):
        detail.model_copy(update={"score": 2.0}).model_validate(
            detail.model_copy(update={"score": 2.0}).model_dump()
        )
