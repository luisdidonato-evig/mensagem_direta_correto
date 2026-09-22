"""track utility revisions and consecutive template sends

Revision ID: 20260922_0010
Revises: 20260921_0009
"""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0010"
down_revision = "20260921_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("message_templates") as batch:
        batch.add_column(sa.Column("requested_category", sa.String(9), nullable=True))
        batch.add_column(sa.Column("correct_category", sa.String(9), nullable=True))
        batch.add_column(sa.Column("parent_template_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("submission_attempt", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("category_changed_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_message_templates_parent", "message_templates", ["parent_template_id"], ["id"]
        )
        batch.create_index("ix_message_templates_parent_template_id", ["parent_template_id"])
    op.execute("UPDATE message_templates SET requested_category = category")
    with op.batch_alter_table("message_templates") as batch:
        batch.alter_column("requested_category", nullable=False)

    op.create_table(
        "contact_messaging_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("phone_hash", sa.String(64), nullable=False),
        sa.Column(
            "consecutive_template_sends", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("reserved_template_sends", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True)),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.UniqueConstraint(
            "organization_id", "phone_hash", name="uq_contact_messaging_org_phone"
        ),
    )
    op.create_index(
        "ix_contact_messaging_states_organization_id",
        "contact_messaging_states",
        ["organization_id"],
    )
    op.create_index(
        "ix_contact_messaging_states_phone_hash",
        "contact_messaging_states",
        ["phone_hash"],
    )


def downgrade() -> None:
    op.drop_table("contact_messaging_states")
    with op.batch_alter_table("message_templates") as batch:
        batch.drop_index("ix_message_templates_parent_template_id")
        batch.drop_constraint("fk_message_templates_parent", type_="foreignkey")
        batch.drop_column("category_changed_at")
        batch.drop_column("submission_attempt")
        batch.drop_column("parent_template_id")
        batch.drop_column("correct_category")
        batch.drop_column("requested_category")
