"""scope compliance records by organization

Revision ID: 20260921_0006
Revises: 20260921_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0006"
down_revision = "20260921_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    default_org = connection.execute(
        sa.text("SELECT id FROM organizations ORDER BY created_at LIMIT 1")
    ).scalar()
    if default_org is None:
        raise RuntimeError("Crie uma organização antes de migrar registros de compliance")

    with op.batch_alter_table("consents") as batch:
        batch.add_column(sa.Column("organization_id", sa.String(36), nullable=True))
    with op.batch_alter_table("opt_outs") as batch:
        batch.add_column(sa.Column("organization_id", sa.String(36), nullable=True))

    connection.execute(sa.text("UPDATE consents SET organization_id = :org"), {"org": default_org})
    connection.execute(sa.text("UPDATE opt_outs SET organization_id = :org"), {"org": default_org})

    with op.batch_alter_table("consents") as batch:
        batch.alter_column("organization_id", nullable=False)
        batch.create_foreign_key(
            "fk_consents_organization", "organizations", ["organization_id"], ["id"]
        )
        batch.create_index("ix_consents_organization_id", ["organization_id"])
    with op.batch_alter_table("opt_outs") as batch:
        batch.drop_constraint("uq_opt_out_phone_scope", type_="unique")
        batch.alter_column("organization_id", nullable=False)
        batch.create_foreign_key(
            "fk_opt_outs_organization", "organizations", ["organization_id"], ["id"]
        )
        batch.create_index("ix_opt_outs_organization_id", ["organization_id"])
        batch.create_unique_constraint(
            "uq_opt_out_org_phone_scope", ["organization_id", "phone_hash", "scope"]
        )


def downgrade() -> None:
    with op.batch_alter_table("opt_outs") as batch:
        batch.drop_constraint("uq_opt_out_org_phone_scope", type_="unique")
        batch.drop_index("ix_opt_outs_organization_id")
        batch.drop_constraint("fk_opt_outs_organization", type_="foreignkey")
        batch.drop_column("organization_id")
        batch.create_unique_constraint("uq_opt_out_phone_scope", ["phone_hash", "scope"])
    with op.batch_alter_table("consents") as batch:
        batch.drop_index("ix_consents_organization_id")
        batch.drop_constraint("fk_consents_organization", type_="foreignkey")
        batch.drop_column("organization_id")
