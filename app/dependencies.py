from dataclasses import dataclass
from typing import Any

from app.core.request_context import RequestContextStore
from app.rag.vector_store import VectorStore


@dataclass
class ServiceContainer:
    retriever: Any
    generation: Any
    cases: Any
    citations: Any
    contexts: RequestContextStore
    vector_store: VectorStore | None
    workflow: Any
