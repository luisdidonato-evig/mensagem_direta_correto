"""encrypt new recipient PII and add lookup hash

Revision ID: 20260921_0007
Revises: 20260921_0006
"""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0007"
down_revision = "20260921_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaign_recipients") as batch:
        batch.alter_column("phone_e164", type_=sa.String(512), existing_type=sa.String(32))
        batch.add_column(sa.Column("phone_hash", sa.String(64), nullable=True))
        batch.create_index("ix_campaign_recipients_phone_hash", ["phone_hash"])


def downgrade() -> None:
    with op.batch_alter_table("campaign_recipients") as batch:
        batch.drop_index("ix_campaign_recipients_phone_hash")
        batch.drop_column("phone_hash")
        batch.alter_column("phone_e164", type_=sa.String(32), existing_type=sa.String(512))
