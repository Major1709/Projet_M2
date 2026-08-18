"""Hold sessions server-side so identity stops being a caller-supplied header.

Revision ID: 20260818_0003
Revises: 20260818_0002
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0003"
down_revision: str | None = "20260818_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        # Deliberately not keyed by tenant, unlike every other table: a session is
        # what establishes the tenant, so it cannot already be scoped by one.
        sa.Column("id", sa.Uuid(), nullable=False),
        # Only the hash. The token is handed to the browser once and never written
        # down, so a leaked dump yields no usable session.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_sessions_expiry_after_creation"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    # Expired rows are swept by this, and the lookup itself rides the unique index.
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_table("sessions")
