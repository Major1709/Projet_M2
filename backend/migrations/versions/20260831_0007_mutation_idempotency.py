"""Reserve the idempotency key of a mutation server-side and durably.

Revision ID: 20260831_0007
Revises: 20260831_0006
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0007"
down_revision: str | None = "20260831_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mutation_idempotency",
        # One reservation per approved proposal. The composite primary key is what
        # makes reserving idempotent: a concurrent second attempt collides here
        # instead of minting a second key for an action approved once.
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.Column("proposal_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "proposal_id"),
        # Two proposals sharing a key would let the provider silently discard the
        # second one as a duplicate of the first.
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_mutation_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["action_proposals.tenant_id", "action_proposals.id"],
            name="fk_mutation_idempotency_proposal",
        ),
    )


def downgrade() -> None:
    op.drop_table("mutation_idempotency")
