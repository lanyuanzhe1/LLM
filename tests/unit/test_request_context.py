import pytest

from app.core.request_context import RequestContextStore
from app.rag.evidence import Evidence


@pytest.mark.asyncio
async def test_context_round_trip_and_pop():
    store = RequestContextStore(ttl_seconds=300)
    evidence = Evidence(
        evidence_id="sha256:e1",
        document_id="sha256:d1",
        title="测试文档",
        source="测试文档.pdf",
        text="证据",
        score=0.9,
        authority_level="unknown",
    )

    await store.set_evidences("req-1", [evidence])
    await store.set_citations("req-1", ["sha256:e1"])

    context = await store.pop("req-1")
    assert context is not None
    assert context.evidences == (evidence,)
    assert context.citation_ids == ["sha256:e1"]
    assert await store.pop("req-1") is None


@pytest.mark.asyncio
async def test_retrieval_evidence_is_stored_as_a_deep_immutable_snapshot():
    store = RequestContextStore(ttl_seconds=300)
    evidence = Evidence(
        evidence_id="sha256:e1",
        document_id="sha256:d1",
        title="原始标题",
        source="original.pdf",
        text="原始证据",
        score=0.9,
        authority_level="industry",
        quality_flags=["reviewed"],
    )

    await store.set_retrieval_result("req", [evidence], sufficient=True)
    evidence.title = "MUTATED_TITLE"
    evidence.quality_flags.append("MUTATED_FLAG")

    snapshot = await store.get_retrieval_snapshot("req")
    context = await store.pop("req")

    assert snapshot is not None
    assert snapshot[0].title == "原始标题"
    assert snapshot[0].quality_flags == ["reviewed"]
    assert context is not None
    assert isinstance(context.evidences, tuple)
    assert context.evidences[0].title == "原始标题"
    assert context.evidences[0].quality_flags == ["reviewed"]


@pytest.mark.asyncio
async def test_context_records_retrieval_validation_and_case_terminal_state():
    store = RequestContextStore(ttl_seconds=300)
    evidence = Evidence(
        evidence_id="sha256:e1",
        document_id="sha256:d1",
        title="测试文档",
        source="测试文档.pdf",
        text="证据",
        score=0.9,
        authority_level="unknown",
    )

    await store.set_retrieval_result(
        "req",
        [evidence],
        sufficient=True,
    )
    await store.set_validation_result(
        "req",
        valid=True,
        answer="已验证回答。[E1]",
        citation_ids=[evidence.evidence_id],
    )
    await store.set_case_result(
        "req",
        needs_input=False,
        missing_fields=[],
        question=None,
    )

    context = await store.pop("req")
    assert context is not None
    assert context.evidences == (evidence,)
    assert context.retrieval_sufficient is True
    assert context.validation_valid is True
    assert context.validated_answer == "已验证回答。[E1]"
    assert context.citation_ids == [evidence.evidence_id]
    assert context.needs_input is False
    assert context.missing_fields == []
    assert context.question is None


@pytest.mark.asyncio
async def test_failed_validation_clears_answer_and_citations_atomically():
    store = RequestContextStore(ttl_seconds=300)
    await store.set_validation_result(
        "req",
        valid=True,
        answer="旧回答",
        citation_ids=["sha256:e1"],
    )

    await store.set_validation_result(
        "req",
        valid=False,
        answer="RAW_UNVALIDATED_ANSWER",
        citation_ids=["sha256:e1"],
    )

    context = await store.pop("req")
    assert context is not None
    assert context.validation_valid is False
    assert context.validated_answer is None
    assert context.citation_ids == []


@pytest.mark.asyncio
async def test_stale_validation_revision_cannot_overwrite_new_retrieval():
    store = RequestContextStore(ttl_seconds=300)
    evidence_a = Evidence(
        evidence_id="sha256:a",
        document_id="sha256:da",
        title="A",
        source="a.pdf",
        text="A evidence",
        score=0.9,
    )
    evidence_b = evidence_a.model_copy(
        update={
            "evidence_id": "sha256:b",
            "document_id": "sha256:db",
            "title": "B",
            "source": "b.pdf",
            "text": "B evidence",
        }
    )
    await store.set_retrieval_result("req", [evidence_a], sufficient=True)
    snapshot_a = await store.get_retrieval_state("req")
    await store.set_retrieval_result("req", [evidence_b], sufficient=True)

    committed = await store.reconcile_and_set_validation(
        "req",
        revision=snapshot_a.revision,
        submitted_evidences=[evidence_a],
        valid=True,
        answer="A VALIDATED ANSWER",
        citation_ids=[evidence_a.evidence_id],
    )
    context = await store.pop("req")

    assert committed is False
    assert context.evidences == (evidence_b,)
    assert context.validation_valid is None
    assert context.validated_answer is None


@pytest.mark.asyncio
async def test_same_revision_mismatch_clears_old_valid_state_then_allows_retry():
    store = RequestContextStore(ttl_seconds=300)
    evidence = Evidence(
        evidence_id="sha256:e1",
        document_id="sha256:d1",
        title="Trusted",
        source="trusted.pdf",
        text="Trusted evidence",
        score=0.9,
    )
    await store.set_retrieval_result("req", [evidence], sufficient=True)
    snapshot = await store.get_retrieval_state("req")
    await store.set_validation_result(
        "req",
        valid=True,
        answer="OLD VALID",
        citation_ids=[evidence.evidence_id],
    )

    mismatch = await store.reconcile_and_set_validation(
        "req",
        revision=snapshot.revision,
        submitted_evidences=[
            evidence.model_copy(update={"title": "Injected"})
        ],
        valid=True,
        answer="INJECTED",
        citation_ids=[evidence.evidence_id],
    )
    cleared = await store.get_retrieval_state("req")
    retry = await store.reconcile_and_set_validation(
        "req",
        revision=snapshot.revision,
        submitted_evidences=[evidence],
        valid=True,
        answer="RETRY VALID",
        citation_ids=[evidence.evidence_id],
    )
    context = await store.pop("req")

    assert mismatch is False
    assert cleared.validation_valid is None
    assert retry is True
    assert context.validated_answer == "RETRY VALID"
