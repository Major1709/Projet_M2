"""Public interface of the knowledge retrieval module."""

from app.knowledge.domain import (
    KnowledgePassage,
    KnowledgeQuery,
    RetrievalIntent,
    SourceProvenance,
)
from app.knowledge.ports import KnowledgeRetriever

__all__ = [
    "KnowledgePassage",
    "KnowledgeQuery",
    "KnowledgeRetriever",
    "RetrievalIntent",
    "SourceProvenance",
]
