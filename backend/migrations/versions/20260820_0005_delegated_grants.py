"""Hold delegated Atlassian grants durably, encrypted at rest.

Revision ID: 20260820_0005
Revises: 20260819_0004
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0005"
down_revision: str | None = "20260819_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delegated_grants",
        # One grant per person per tenant: that is what a read is performed on
        # behalf of, and two rows for one pair would mean two Atlassian
        # identities behind one user with nothing to choose between them.
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.String(length=200), nullable=False),
        # Ciphertext only. AES-256-GCM, nonce prefixed, tenant and user bound in
        # as associated data so a row copied onto another identity fails to
        # authenticate rather than handing over its access.
        sa.Column("access_token", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        # In the clear on purpose: the renewal decision must be takeable without
        # decrypting anything, and an expiry says nothing the sessions table does
        # not already say.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("key_version >= 1", name="key_version_positive"),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name="pk_delegated_grants"),
    )


def downgrade() -> None:
    # Dropping this table revokes nothing at Atlassian: the grants stay live on
    # the provider side, and everyone has to consent again. Destructive in the
    # ordinary sense, so it is left explicit rather than made convenient.
    op.drop_table("delegated_grants")
