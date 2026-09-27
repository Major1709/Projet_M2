"""Garder le nom que la personne se connait, pour que l'ecran puisse la nommer.

Revision ID: 20260927_0008
Revises: 20260831_0007
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0008"
down_revision: str | None = "20260831_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, et sans valeur de remplacement. Les sessions ouvertes avant cette
    # migration n'ont jamais porte de nom, et en inventer un -- l'identifiant de
    # compte, par exemple -- afficherait une initiale qui n'est celle de personne.
    # Elles resteront sans initiale jusqu'a la prochaine connexion, ce qui est la
    # verite.
    op.add_column(
        "sessions",
        sa.Column("display_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "display_name")
