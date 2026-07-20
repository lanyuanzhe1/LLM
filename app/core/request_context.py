import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.rag.evidence import Evidence


@dataclass
class RequestContext:
    evidences: tuple[Evidence, ...] = field(default_factory=tuple)
    retrieval_sufficient: bool | None = None
    validation_valid: bool | None = None
    validated_answer: str | None = None
    citation_ids: list[str] = field(default_factory=list)
    needs_input: bool = False
    missing_fields: list[str] = field(default_factory=list)
    question: str | None = None
    retrieval_revision: int = 0
    expires_at: float = 0.0


@dataclass(frozen=True)
class RetrievalState:
    revision: int
    evidences: tuple[Evidence, ...]
    validation_valid: bool | None


class RequestContextStore:
    def __init__(
        self,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._items: dict[str, RequestContext] = {}
        self._lock = asyncio.Lock()
        self._retrieval_revision = 0

    async def _get_or_create(self, request_id: str) -> RequestContext:
        now = self._clock()
        self._items = {
            key: value
            for key, value in self._items.items()
            if value.expires_at > now
        }
        context = self._items.get(request_id)
        if context is None:
            context = RequestContext(expires_at=now + self._ttl)
            self._items[request_id] = context
        return context

    async def set_evidences(
        self, request_id: str, evidences: list[Evidence]
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            context.evidences = self._snapshot_evidences(evidences)

    async def set_retrieval_result(
        self,
        request_id: str,
        evidences: list[Evidence],
        *,
        sufficient: bool,
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            self._retrieval_revision += 1
            context.evidences = self._snapshot_evidences(evidences)
            context.retrieval_sufficient = sufficient
            context.retrieval_revision = self._retrieval_revision
            context.validation_valid = None
            context.validated_answer = None
            context.citation_ids = []

    @staticmethod
    def _snapshot_evidences(
        evidences: list[Evidence] | tuple[Evidence, ...],
    ) -> tuple[Evidence, ...]:
        return tuple(
            Evidence.model_validate(evidence.model_dump(mode="python"))
            for evidence in evidences
        )

    async def get_retrieval_snapshot(
        self,
        request_id: str,
    ) -> tuple[Evidence, ...] | None:
        async with self._lock:
            now = self._clock()
            context = self._items.get(request_id)
            if context is None or context.expires_at <= now:
                self._items.pop(request_id, None)
                return None
            return self._snapshot_evidences(context.evidences)

    async def get_retrieval_state(
        self,
        request_id: str,
    ) -> RetrievalState | None:
        async with self._lock:
            now = self._clock()
            context = self._items.get(request_id)
            if context is None or context.expires_at <= now:
                self._items.pop(request_id, None)
                return None
            return RetrievalState(
                revision=context.retrieval_revision,
                evidences=self._snapshot_evidences(context.evidences),
                validation_valid=context.validation_valid,
            )

    async def reconcile_and_set_validation(
        self,
        request_id: str,
        *,
        revision: int,
        submitted_evidences: list[Evidence],
        valid: bool,
        answer: str,
        citation_ids: list[str],
    ) -> bool:
        async with self._lock:
            context = self._items.get(request_id)
            if (
                context is None
                or context.expires_at <= self._clock()
                or context.retrieval_revision != revision
            ):
                return False
            trusted_by_id = {
                evidence.evidence_id: evidence
                for evidence in context.evidences
            }
            reconciled = (
                len(trusted_by_id) == len(context.evidences)
                and len(
                    {
                        evidence.evidence_id
                        for evidence in submitted_evidences
                    }
                )
                == len(submitted_evidences)
                and all(
                    evidence.evidence_id in trusted_by_id
                    and evidence.model_dump(mode="python")
                    == trusted_by_id[evidence.evidence_id].model_dump(
                        mode="python"
                    )
                    for evidence in submitted_evidences
                )
            )
            if not reconciled:
                context.validation_valid = None
                context.validated_answer = None
                context.citation_ids = []
                return False
            context.validation_valid = valid
            context.validated_answer = answer if valid else None
            context.citation_ids = list(citation_ids) if valid else []
            return True

    async def set_citations(
        self, request_id: str, citation_ids: list[str]
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            context.citation_ids = list(citation_ids)

    async def set_validation_result(
        self,
        request_id: str,
        *,
        valid: bool,
        answer: str,
        citation_ids: list[str],
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            context.validation_valid = valid
            if valid:
                context.validated_answer = answer
                context.citation_ids = list(citation_ids)
            else:
                context.validated_answer = None
                context.citation_ids = []

    async def set_case_result(
        self,
        request_id: str,
        *,
        needs_input: bool,
        missing_fields: list[str],
        question: str | None = None,
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            context.needs_input = needs_input
            context.missing_fields = list(missing_fields)
            context.question = question

    async def pop(self, request_id: str) -> RequestContext | None:
        async with self._lock:
            context = self._items.pop(request_id, None)
            if context is None or context.expires_at <= self._clock():
                return None
            return context
