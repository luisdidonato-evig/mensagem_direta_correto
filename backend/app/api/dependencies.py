from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, get_principal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.integrations.audience.provider import AudienceSource, build_audience_source
from app.integrations.meta.provider import WhatsAppProvider, build_provider_for_connection
from app.services.organization_service import get_waba_connection, resolve_organization_id


async def get_organization_id(
    organization_id: str | None = Query(
        default=None, description="Organização atual. Padrão: organização única do ambiente."
    ),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> str:
    try:
        resolved = await resolve_organization_id(db, organization_id or principal.organization_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if principal.organization_id and principal.organization_id != resolved:
        raise HTTPException(status_code=403, detail="Acesso negado para esta organização")
    return resolved


async def get_meta_provider(
    organization_id: str = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WhatsAppProvider:
    connection = await get_waba_connection(db, organization_id)
    return build_provider_for_connection(
        settings.meta_mode, connection, settings.meta_graph_version
    )


def get_audience_source(settings: Settings = Depends(get_settings)) -> AudienceSource:
    return build_audience_source(settings)
