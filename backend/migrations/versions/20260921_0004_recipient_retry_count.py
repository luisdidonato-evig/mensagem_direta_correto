"""Retry count on campaign recipients, for transient-failure backoff.

Revision ID: 20260921_0004
Revises: 20260921_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0004"
down_revision: str | None = "20260921_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaign_recipients",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    with op.batch_alter_table("campaign_recipients") as batch_op:
        batch_op.alter_column("retry_count", server_default=None)


def downgrade() -> None:
    op.drop_column("campaign_recipients", "retry_count")
