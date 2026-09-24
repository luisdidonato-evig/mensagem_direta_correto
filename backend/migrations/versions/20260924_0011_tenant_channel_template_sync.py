"""Persist tenant channel account and template synchronization timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0011"
down_revision = "20260922_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("waba_connections") as batch:
        batch.add_column(sa.Column("channel_account_id", sa.String(36), nullable=True))
    with op.batch_alter_table("message_templates") as batch:
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("message_templates") as batch:
        batch.drop_column("last_synced_at")
        batch.drop_column("submitted_at")
    with op.batch_alter_table("waba_connections") as batch:
        batch.drop_column("channel_account_id")
