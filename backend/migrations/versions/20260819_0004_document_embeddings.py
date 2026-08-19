"""Store one vector per source document, so retrieval can compare meanings.

Revision ID: 20260819_0004
Revises: 20260818_0003
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260819_0004"
down_revision: str | None = "20260818_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# multilingual-e5-base. The column is declared with this number, so it is not a
# setting: changing models means a migration, which is the honest cost of the
# change rather than a surprise at query time.
DIMENSIONS = 768


def upgrade() -> None:
    # The extension is already created by the initial migration; this only fails
    # loudly if that ever stops being true.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "document_embeddings",
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        # The provider's own identifier. Part of the key so that re-indexing a
        # document replaces its vector instead of adding a second one -- two rows
        # for one ticket would let it outvote the rest of the corpus purely by
        # having been indexed twice.
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("resource_reference", sa.String(length=1000), nullable=True),
        # Vectors from two models share a dimension count and nothing else.
        # Recorded so a model change is detectable rather than silently mixed in.
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(DIMENSIONS), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "source_system",
            "external_id",
            name="pk_document_embeddings",
        ),
        sa.UniqueConstraint("id", name="uq_document_embeddings_id"),
    )
    # No ivfflat or hnsw index, deliberately. Both are APPROXIMATE: they trade
    # recall for speed, and ivfflat additionally needs to be built on a populated
    # table to place its lists sensibly. At this corpus size an exact scan is
    # already sub-millisecond, so an approximate index would cost recall -- the
    # very thing being measured here -- and buy nothing. Add one when the corpus
    # makes the scan the bottleneck, and re-measure recall when doing so.
    op.create_index(
        "ix_document_embeddings_tenant_source",
        "document_embeddings",
        ["tenant_id", "source_system"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_embeddings_tenant_source", table_name="document_embeddings")
    op.drop_table("document_embeddings")
