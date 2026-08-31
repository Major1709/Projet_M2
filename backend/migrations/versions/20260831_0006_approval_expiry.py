"""Bind an approval to a deadline and to the tool shape it was granted for.

Revision ID: 20260831_0006
Revises: 20260820_0005
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0006"
down_revision: str | None = "20260820_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both columns are NOT NULL, so existing rows need a value. There is no honest
    # backfill: a proposal created before this migration was never pinned to a schema
    # and never carried a deadline. They are therefore expired on the spot -- an epoch
    # deadline and an all-zero fingerprint that no real schema can match. Whoever still
    # wants such an action proposes it again and sees it on screen first, which is the
    # behaviour this control exists to guarantee.
    op.add_column(
        "action_proposals",
        sa.Column(
            "tool_schema_sha256",
            sa.String(length=64),
            nullable=False,
            server_default="0" * 64,
        ),
    )
    op.add_column(
        "action_proposals",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("TIMESTAMP WITH TIME ZONE '1970-01-01 00:00:00+00'"),
        ),
    )
    # The defaults existed only to make the columns writable for legacy rows. Leaving
    # them in place would silently date every future insert to the epoch if a caller
    # forgot the value, which is safe but incomprehensible; the application always
    # supplies both.
    op.alter_column("action_proposals", "tool_schema_sha256", server_default=None)
    op.alter_column("action_proposals", "expires_at", server_default=None)


def downgrade() -> None:
    op.drop_column("action_proposals", "expires_at")
    op.drop_column("action_proposals", "tool_schema_sha256")
