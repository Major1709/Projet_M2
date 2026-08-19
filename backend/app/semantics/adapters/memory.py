from collections.abc import Sequence

from app.semantics.domain import SimilarDocument, StoredEmbedding


def cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    """The same measure pgvector applies, for stores that have no database."""

    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    if norm_left == 0 or norm_right == 0:
        return 1.0
    return 1.0 - dot / (norm_left * norm_right)


class InMemoryEmbeddingStore:
    """Vectors in a dictionary. For tests and for a build with no database."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], StoredEmbedding] = {}

    def digests_for(self, tenant_id: str, source_system: str) -> dict[str, str]:
        return {
            item.external_id: item.content_digest
            for (tenant, source, _), item in self._rows.items()
            if tenant == tenant_id and source == source_system
        }

    def upsert(self, embeddings: Sequence[StoredEmbedding]) -> None:
        for item in embeddings:
            key = (item.tenant_id, item.source_system, item.external_id)
            # Keep the identity the row was first given, like the SQL upsert does.
            existing = self._rows.get(key)
            self._rows[key] = item if existing is None else item.model_copy(
                update={"id": existing.id}
            )

    def nearest(
        self,
        tenant_id: str,
        embedding: Sequence[float],
        *,
        limit: int,
        exclude_external_id: str | None = None,
    ) -> list[SimilarDocument]:
        candidats = [
            item
            for (tenant, _, external_id), item in self._rows.items()
            if tenant == tenant_id and external_id != exclude_external_id
        ]
        classes = sorted(
            (
                SimilarDocument(
                    external_id=item.external_id,
                    title=item.title,
                    resource_reference=item.resource_reference,
                    source_system=item.source_system,
                    distance=cosine_distance(embedding, item.embedding),
                )
                for item in candidats
            ),
            key=lambda found: found.distance,
        )
        return classes[:limit]
