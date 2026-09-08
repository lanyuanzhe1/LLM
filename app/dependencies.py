from dataclasses import dataclass
from typing import Any

from app.core.request_context import RequestContextStore


@dataclass
class ServiceContainer:
    retriever: Any
    generation: Any
    cases: Any
    citations: Any
    contexts: RequestContextStore
    workflow: Any
    knowledge: Any = None
