from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, get_principal, require_admin
from app.core.config import Settings, get_settings
from app.core.crypto import encrypt_token
from app.core.database import get_db
from app.integrations.meta.provider import MetaProviderError, build_provider_for_connection
from app.models.organization import Organization, WabaConnection, WabaConnectionStatus
from app.schemas.organizations import (
    OrganizationCreate,
    OrganizationRead,
    WabaConnectionRead,
    WabaConnectionTestResult,
    WabaConnectionWrite,
)
from app.services.audit_service import add_audit
from app.services.organization_service import get_waba_connection

router = APIRouter(
    prefix="/organizations", tags=["organizations"], dependencies=[Depends(get_principal)]
)


def _to_connection_read(
    organization_id: str, connection: WabaConnection | None
) -> WabaConnectionRead:
    if connection is None:
        return WabaConnectionRead(
            organization_id=organization_id,
            business_id=None,
            waba_id=None,
            phone_number_id=None,
            api_version="v23.0",
            has_token=False,
            status=WabaConnectionStatus.DISCONNECTED,
            last_synced_at=None,
            updated_at=datetime.now(UTC),
        )
    return WabaConnectionRead(
        organization_id=connection.organization_id,
        business_id=connection.business_id,
        waba_id=connection.waba_id,
        phone_number_id=connection.phone_number_id,
        api_version=connection.api_version,
        has_token=bool(connection.access_token),
        status=connection.status,
        last_synced_at=connection.last_synced_at,
        updated_at=connection.updated_at,
    )


@router.get("", response_model=list[OrganizationRead])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[Organization]:
    statement = select(Organization).order_by(Organization.created_at)
    if principal.organization_id:
        statement = statement.where(Organization.id == principal.organization_id)
    result = await db.scalars(statement)
    return list(result)


@router.post("", response_model=OrganizationRead, status_code=201)
async def create_organization(
    payload: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> Organization:
    if principal.organization_id is not None:
        raise HTTPException(
            status_code=403, detail="Somente o administrador global pode criar empresas"
        )
    organization = Organization(name=payload.name, timezone=payload.timezone)
    db.add(organization)
    await db.flush()
    db.add(WabaConnection(organization_id=organization.id))
    add_audit(
        db,
        action="organization.created",
        resource_type="organization",
        resource_id=organization.id,
        details={"name": organization.name},
    )
    await db.commit()
    await db.refresh(organization)
    return organization


@router.get("/{organization_id}/waba-connection", response_model=WabaConnectionRead)
async def read_waba_connection(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> WabaConnectionRead:
    if principal.organization_id and principal.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Acesso negado para esta organização")
    if await db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=404, detail="Organização não encontrada")
    connection = await get_waba_connection(db, organization_id)
    return _to_connection_read(organization_id, connection)


@router.put("/{organization_id}/waba-connection", response_model=WabaConnectionRead)
async def upsert_waba_connection(
    organization_id: str,
    payload: WabaConnectionWrite,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_admin),
) -> WabaConnectionRead:
    if principal.organization_id and principal.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Acesso negado para esta organização")
    if await db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=404, detail="Organização não encontrada")
    connection = await get_waba_connection(db, organization_id)
    if connection is None:
        connection = WabaConnection(organization_id=organization_id)
        db.add(connection)
    connection.business_id = payload.business_id
    connection.waba_id = payload.waba_id
    connection.phone_number_id = payload.phone_number_id
    connection.api_version = payload.api_version
    if payload.access_token:
        connection.access_token = encrypt_token(payload.access_token, settings)
    connection.status = WabaConnectionStatus.DISCONNECTED
    add_audit(
        db,
        action="waba_connection.updated",
        resource_type="waba_connection",
        resource_id=organization_id,
        details={"waba_id": connection.waba_id, "phone_number_id": connection.phone_number_id},
    )
    await db.commit()
    await db.refresh(connection)
    return _to_connection_read(organization_id, connection)


@router.post("/{organization_id}/waba-connection/test", response_model=WabaConnectionTestResult)
async def test_waba_connection(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_admin),
) -> WabaConnectionTestResult:
    if principal.organization_id and principal.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Acesso negado para esta organização")
    if await db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=404, detail="Organização não encontrada")
    connection = await get_waba_connection(db, organization_id)
    try:
        provider = build_provider_for_connection(
            settings.meta_mode, connection, settings.meta_graph_version
        )
        await provider.list_templates()
    except MetaProviderError as exc:
        if connection is not None:
            connection.status = WabaConnectionStatus.ERROR
        add_audit(
            db,
            action="waba_connection.tested",
            resource_type="waba_connection",
            resource_id=organization_id,
            details={"result": "error", "detail": str(exc)},
        )
        await db.commit()
        return WabaConnectionTestResult(status=WabaConnectionStatus.ERROR, detail=str(exc))

    if connection is not None:
        connection.status = WabaConnectionStatus.CONNECTED
        connection.last_synced_at = datetime.now(UTC)
    add_audit(
        db,
        action="waba_connection.tested",
        resource_type="waba_connection",
        resource_id=organization_id,
        details={"result": "success"},
    )
    await db.commit()
    detail = (
        "Conexão mock — sempre disponível."
        if settings.meta_mode != "live"
        else "Conectado com sucesso."
    )
    return WabaConnectionTestResult(status=WabaConnectionStatus.CONNECTED, detail=detail)
