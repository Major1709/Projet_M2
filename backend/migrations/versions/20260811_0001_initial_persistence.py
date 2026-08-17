"""Create the initial tenant-aware persistence schema.

Revision ID: 20260811_0001
Revises:
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add pgvector and the first durable, tenant-scoped tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "conversations",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_conversations")),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "owner_user_id",
            name="uq_conversations_tenant_id_id_owner_user_id",
        ),
    )

    op.create_table(
        "action_proposals",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_by_user_id", sa.String(length=255), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("action_class", sa.String(length=20), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("diff_json", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("execution_context_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decision_token_hash", sa.String(length=64), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_user_id", sa.String(length=255), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_action_proposals_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "proposed_by_user_id"],
            [
                "conversations.tenant_id",
                "conversations.id",
                "conversations.owner_user_id",
            ],
            name="fk_action_proposals_tenant_conversation_owner",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supersedes_id"],
            ["action_proposals.tenant_id", "action_proposals.id"],
            name="fk_action_proposals_tenant_supersedes",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_action_proposals")),
    )

    op.create_table(
        "audit_events",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("action_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "action_proposal_id"],
            ["action_proposals.tenant_id", "action_proposals.id"],
            name="fk_audit_events_tenant_action_proposal",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_audit_events")),
    )


def downgrade() -> None:
    """Refuse an automatic data-destructive rollback."""

    raise RuntimeError(
        "The initial persistence migration has no automatic downgrade; "
        "roll back the application or follow the approved restore procedure"
    )
