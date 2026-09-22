"""updated_at on campaigns, so reconciliation can tell stuck from in-flight.

Revision ID: 20260921_0005
Revises: 20260921_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0005"
down_revision: str | None = "20260921_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE campaigns SET updated_at = created_at")
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.alter_column("updated_at", nullable=False)


def downgrade() -> None:
    op.drop_column("campaigns", "updated_at")
