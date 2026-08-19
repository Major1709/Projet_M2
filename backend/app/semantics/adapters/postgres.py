from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from app.persistence.schema import document_embeddings
from app.semantics.domain import SimilarDocument, StoredEmbedding


class PostgresEmbeddingStore:
    """Vectors in the same database as everything else, via pgvector."""

    def __init__(self, session_factory: sessionmaker[DatabaseSession]) -> None:
        self._session_factory = session_factory

    def digests_for(self, tenant_id: str, source_system: str) -> dict[str, str]:
        statement = select(
            document_embeddings.c.external_id,
            document_embeddings.c.content_digest,
        ).where(
            document_embeddings.c.tenant_id == tenant_id,
            document_embeddings.c.source_system == source_system,
        )
        with self._session_factory() as database:
            return {row.external_id: row.content_digest for row in database.execute(statement)}

    def upsert(self, embeddings: Sequence[StoredEmbedding]) -> None:
        if not embeddings:
            return
        rows = [
            {
                "tenant_id": item.tenant_id,
                "id": item.id,
                "source_system": item.source_system,
                "external_id": item.external_id,
                "title": item.title,
                "resource_reference": item.resource_reference,
                "model_name": item.model_name,
                "content_digest": item.content_digest,
                "embedding": list(item.embedding),
                "indexed_at": item.indexed_at,
            }
            for item in embeddings
        ]
        statement = insert(document_embeddings).values(rows)
        # Upsert on the natural key rather than delete-then-insert: a re-index must
        # never leave the corpus briefly short of a document, because a search
        # running at that moment would answer "nothing like this exists" -- which
        # reads as a fact rather than as a race.
        #
        # "id" is deliberately absent from the update: the row keeps the identity it
        # was first given, so anything referring to it stays valid.
        statement = statement.on_conflict_do_update(
            index_elements=["tenant_id", "source_system", "external_id"],
            set_={
                "title": statement.excluded.title,
                "resource_reference": statement.excluded.resource_reference,
                "model_name": statement.excluded.model_name,
                "content_digest": statement.excluded.content_digest,
                "embedding": statement.excluded.embedding,
                "indexed_at": statement.excluded.indexed_at,
            },
        )
        with self._session_factory.begin() as database:
            database.execute(statement)

    def nearest(
        self,
        tenant_id: str,
        embedding: Sequence[float],
        *,
        limit: int,
        exclude_external_id: str | None = None,
    ) -> list[SimilarDocument]:
        distance = document_embeddings.c.embedding.cosine_distance(list(embedding))
        statement = (
            select(
                document_embeddings.c.external_id,
                document_embeddings.c.title,
                document_embeddings.c.resource_reference,
                document_embeddings.c.source_system,
                distance.label("distance"),
            )
            # Scoped by tenant in the query itself, not filtered afterwards. A
            # nearest-neighbour search that ranked first and filtered second would
            # return fewer results than asked for, and the shortfall would be
            # another tenant's documents having been closer.
            .where(document_embeddings.c.tenant_id == tenant_id)
            .order_by(distance)
            .limit(limit)
        )
        if exclude_external_id is not None:
            statement = statement.where(
                document_embeddings.c.external_id != exclude_external_id
            )
        with self._session_factory() as database:
            return [
                SimilarDocument(
                    external_id=row.external_id,
                    title=row.title,
                    resource_reference=row.resource_reference,
                    source_system=row.source_system,
                    distance=float(row.distance),
                )
                for row in database.execute(statement)
            ]
