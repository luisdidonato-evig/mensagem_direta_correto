"""Organizations and WABA connections; scope templates/campaigns per org.

Revision ID: 20260921_0002
Revises: 20260921_0001
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0002"
down_revision: str | None = "20260921_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

waba_connection_status = sa.Enum("DISCONNECTED", "CONNECTED", "ERROR", name="wabaconnectionstatus")

DEFAULT_ORGANIZATION_ID = "default"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "waba_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, unique=True),
        sa.Column("business_id", sa.String(128)),
        sa.Column("waba_id", sa.String(128)),
        sa.Column("phone_number_id", sa.String(128)),
        sa.Column("api_version", sa.String(16), nullable=False),
        sa.Column("access_token", sa.String(512)),
        sa.Column("status", waba_connection_status, nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
    )
    op.create_index("ix_waba_connections_organization_id", "waba_connections", ["organization_id"])

    organizations = sa.table(
        "organizations",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("timezone", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    waba_connections = sa.table(
        "waba_connections",
        sa.column("id", sa.String),
        sa.column("organization_id", sa.String),
        sa.column("api_version", sa.String),
        sa.column("status", waba_connection_status),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        organizations,
        [
            {
                "id": DEFAULT_ORGANIZATION_ID,
                "name": "Organização padrão",
                "timezone": "America/Sao_Paulo",
                "created_at": now,
            }
        ],
    )
    op.bulk_insert(
        waba_connections,
        [
            {
                "id": DEFAULT_ORGANIZATION_ID,
                "organization_id": DEFAULT_ORGANIZATION_ID,
                "api_version": "v23.0",
                "status": "DISCONNECTED",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    for table in ("message_templates", "campaigns"):
        op.add_column(table, sa.Column("organization_id", sa.String(36), nullable=True))
        op.execute(f"UPDATE {table} SET organization_id = '{DEFAULT_ORGANIZATION_ID}'")
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column("organization_id", nullable=False)
            batch_op.create_foreign_key(
                f"fk_{table}_organization_id", "organizations", ["organization_id"], ["id"]
            )
            batch_op.create_index(f"ix_{table}_organization_id", ["organization_id"])


def downgrade() -> None:
    for table in ("campaigns", "message_templates"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(f"ix_{table}_organization_id")
            batch_op.drop_constraint(f"fk_{table}_organization_id", type_="foreignkey")
            batch_op.drop_column("organization_id")
    op.drop_index("ix_waba_connections_organization_id", table_name="waba_connections")
    op.drop_table("waba_connections")
    op.drop_table("organizations")
    waba_connection_status.drop(op.get_bind(), checkfirst=True)
