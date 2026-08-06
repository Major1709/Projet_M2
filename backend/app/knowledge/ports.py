from typing import Protocol

from app.core.identity import SecurityContext
from app.knowledge.domain import KnowledgePassage, KnowledgeQuery


class KnowledgeRetriever(Protocol):
    """Returns only prefiltered and source-reauthorized passages."""

    def retrieve(
        self,
        *,
        query: KnowledgeQuery,
        context: SecurityContext,
    ) -> tuple[KnowledgePassage, ...]: ...
