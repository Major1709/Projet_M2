from collections.abc import Sequence
from typing import Protocol

from app.semantics.domain import SimilarDocument, StoredEmbedding, TextKind


class EmbeddingProvider(Protocol):
    """Turns text into vectors, one model, one dimension count."""

    @property
    def model_name(self) -> str: ...

    def embed(self, texts: Sequence[str], *, kind: TextKind) -> list[tuple[float, ...]]:
        """Embed a batch, applying the model's instruction prefix for ``kind``.

        Batched rather than one call per text: the cost here is dominated by
        fixed per-call overhead, and a loop over thirty tickets pays it thirty
        times for no reason.
        """
        ...


class EmbeddingStore(Protocol):
    """Where vectors live, always scoped to one tenant."""

    def digests_for(self, tenant_id: str, source_system: str) -> dict[str, str]:
        """External id to stored content digest, for deciding what needs re-embedding."""
        ...

    def upsert(self, embeddings: Sequence[StoredEmbedding]) -> None: ...

    def nearest(
        self,
        tenant_id: str,
        embedding: Sequence[float],
        *,
        limit: int,
        exclude_external_id: str | None = None,
    ) -> list[SimilarDocument]:
        """The closest documents in this tenant, nearest first.

        ``exclude_external_id`` keeps a document from being its own best match,
        which is what "find tickets like this one" needs and what a naive
        similarity search always gets wrong on the first try.
        """
        ...
