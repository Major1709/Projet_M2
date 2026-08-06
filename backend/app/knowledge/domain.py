from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.domain import SourceSystem


class RetrievalIntent(StrEnum):
    LOOKUP = "lookup"
    SIMILARITY = "similarity"
    COVERAGE = "coverage"
    MULTI_HOP = "multi_hop"


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=10_000)
    intent: RetrievalIntent
    allowed_scope_ids: tuple[str, ...]
    top_k: int = Field(default=10, ge=1, le=50)


class SourceProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation_id: str
    source_system: SourceSystem
    source_resource_id: str
    source_version: str
    segment_locator: str | None = None
    title: str
    canonical_url: str
    source_updated_at: datetime | None = None
    authorization_decision_id: str


class KnowledgePassage(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    score: float
    provenance: SourceProvenance
