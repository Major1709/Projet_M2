from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# multilingual-e5-base. Fixed here rather than configurable, because the number is
# not a preference: the stored column is declared with it, and a deployment that
# changed it would write vectors the index cannot compare and PostgreSQL would
# reject -- or worse, accept into a second dimension nobody notices until a search
# returns nothing.
EMBEDDING_DIMENSIONS = 768

# E5 models are trained with an asymmetric instruction prefix, and the two sides of
# a search are NOT interchangeable: a question is a "query", an indexed document is
# a "passage". Dropping the prefixes, or using one for both, still produces vectors
# and still produces rankings -- measurably worse ones, with nothing to indicate
# that anything is wrong. This is the single easiest way to quietly halve the
# quality of this whole slice, so the distinction is carried in the type.
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

TextKind = Literal["query", "passage"]


def prefixed(text: str, kind: TextKind) -> str:
    """Apply the instruction prefix the model was trained with."""

    return (QUERY_PREFIX if kind == "query" else PASSAGE_PREFIX) + text


def utc_now() -> datetime:
    return datetime.now(UTC)


class IndexableDocument(BaseModel):
    """A source document reduced to what gets embedded, plus how to find it again."""

    model_config = ConfigDict(frozen=True)

    source_system: str = Field(min_length=1, max_length=50)
    # The provider's own identifier, e.g. a Jira key. Paired with the tenant and the
    # source system it is what makes re-indexing an update rather than a duplicate.
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=100_000)
    resource_reference: str | None = Field(default=None, max_length=1000)

    def embeddable_text(self) -> str:
        """Title and body as one passage.

        Embedded together rather than separately: a Jira title states the symptom
        and the description states the circumstances, and the two halves of one
        report are only comparable to another report as a whole. Two vectors per
        ticket would also make every similarity threshold ambiguous -- matched on
        which half?
        """

        return f"{self.title}\n\n{self.body}".strip()


class StoredEmbedding(BaseModel):
    """One embedded document as it lives in the database."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1, max_length=200)
    source_system: str = Field(min_length=1, max_length=50)
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    resource_reference: str | None = Field(default=None, max_length=1000)
    # The model that produced the vector. Stored, not assumed: vectors from two
    # models share a dimension count and nothing else, so a comparison across them
    # returns confident nonsense. Recorded here, a model change is detectable.
    model_name: str = Field(min_length=1, max_length=200)
    # A digest of what was embedded. Re-indexing an unchanged document is then a
    # comparison rather than a model call.
    content_digest: str = Field(min_length=64, max_length=64)
    embedding: tuple[float, ...]
    indexed_at: datetime = Field(default_factory=utc_now)


class SimilarDocument(BaseModel):
    """A neighbour found by search, with the distance that made it one."""

    model_config = ConfigDict(frozen=True)

    external_id: str
    title: str
    resource_reference: str | None
    source_system: str
    # Cosine distance, not a percentage and not a confidence. Zero means identical
    # direction, one means orthogonal. It is deliberately not rescaled into
    # something that looks like a probability, because it is not one -- the
    # citations in this project carry no score for exactly the same reason.
    distance: float
