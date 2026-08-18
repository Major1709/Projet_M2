"""Persist conversation turns and the sources each answer cited.

Revision ID: 20260818_0002
Revises: 20260811_0001
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the two tables a conversation needs to survive a page reload."""

    op.create_table(
        "conversation_messages",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.String(length=255), nullable=False),
        # Ordering on created_at alone is not reliable: both turns of one
        # exchange land inside a single clock tick on some platforms, and the
        # tie then falls to a random identifier.
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 0",
            name=op.f("ck_conversation_messages_sequence_not_negative"),
        ),
        sa.CheckConstraint(
            "role in ('user', 'assistant')",
            name=op.f("ck_conversation_messages_role_known"),
        ),
        sa.CheckConstraint(
            "status in ('complete', 'error')",
            name=op.f("ck_conversation_messages_status_known"),
        ),
        # The owner column travels in the foreign key so that attaching a turn to
        # someone else's conversation is rejected by PostgreSQL, not by a check a
        # later caller could bypass.
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "author_user_id"],
            [
                "conversations.tenant_id",
                "conversations.id",
                "conversations.owner_user_id",
            ],
            name=op.f("fk_conversation_messages_tenant_conversation_owner"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_conversation_messages")),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "sequence",
            name=op.f("uq_conversation_messages_tenant_id_conversation_id_sequence"),
        ),
    )
    # Reading a conversation always means "this tenant, this thread, in rank order".
    op.create_index(
        "ix_conversation_messages_thread",
        "conversation_messages",
        ["tenant_id", "conversation_id", "sequence"],
    )

    op.create_table(
        "message_sources",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("resource_reference", sa.String(length=2000), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_message_sources_position_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["conversation_messages.tenant_id", "conversation_messages.id"],
            name=op.f("fk_message_sources_tenant_message"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_message_sources")),
        sa.UniqueConstraint(
            "tenant_id",
            "message_id",
            "position",
            name=op.f("uq_message_sources_tenant_id_message_id_position"),
        ),
    )


def downgrade() -> None:
    op.drop_table("message_sources")
    op.drop_index("ix_conversation_messages_thread", table_name="conversation_messages")
    op.drop_table("conversation_messages")
