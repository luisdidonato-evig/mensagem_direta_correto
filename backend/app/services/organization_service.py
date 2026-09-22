from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import encrypt_token
from app.models.organization import Organization, WabaConnection

DEFAULT_ORGANIZATION_ID = "default"


async def ensure_default_organization(db: AsyncSession, settings: Settings) -> Organization:
    """Seed the single-tenant organization dev/test environments boot with.

    Existing installs configured a WABA purely through env vars; this keeps
    that behavior working unchanged while giving every org (including this
    one) a real row to attach templates/campaigns to.
    """
    organization = await db.get(Organization, DEFAULT_ORGANIZATION_ID)
    if organization is not None:
        return organization
    organization = Organization(id=DEFAULT_ORGANIZATION_ID, name="Organização padrão")
    db.add(organization)
    db.add(
        WabaConnection(
            organization_id=DEFAULT_ORGANIZATION_ID,
            waba_id=settings.meta_waba_id or None,
            phone_number_id=settings.meta_phone_number_id or None,
            access_token=(
                encrypt_token(settings.meta_access_token, settings)
                if settings.meta_access_token
                else None
            ),
            api_version=settings.meta_graph_version,
        )
    )
    await db.commit()
    await db.refresh(organization)
    return organization


async def resolve_organization_id(db: AsyncSession, organization_id: str | None) -> str:
    if organization_id:
        organization = await db.get(Organization, organization_id)
        if organization is None:
            raise LookupError("Organização não encontrada")
        return organization.id
    settings_default = await db.get(Organization, DEFAULT_ORGANIZATION_ID)
    if settings_default is None:
        raise LookupError("Nenhuma organização configurada")
    return settings_default.id


async def get_waba_connection(db: AsyncSession, organization_id: str) -> WabaConnection | None:
    return await db.scalar(
        select(WabaConnection).where(WabaConnection.organization_id == organization_id)
    )
