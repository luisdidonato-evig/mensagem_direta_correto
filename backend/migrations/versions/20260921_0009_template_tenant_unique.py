"""scope remote template uniqueness by organization

Revision ID: 20260921_0009
Revises: 20260921_0008
"""

from alembic import op

revision = "20260921_0009"
down_revision = "20260921_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("message_templates") as batch:
        batch.drop_constraint("uq_meta_template_language", type_="unique")
        batch.create_unique_constraint(
            "uq_org_meta_template_language",
            ["organization_id", "meta_template_id", "language"],
        )


def downgrade() -> None:
    with op.batch_alter_table("message_templates") as batch:
        batch.drop_constraint("uq_org_meta_template_language", type_="unique")
        batch.create_unique_constraint(
            "uq_meta_template_language", ["meta_template_id", "language"]
        )
