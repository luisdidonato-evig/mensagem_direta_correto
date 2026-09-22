from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_organization_id
from app.core.auth import Principal, require_operator
from app.core.database import get_db
from app.core.privacy import hash_phone
from app.models.compliance import Consent, OptOut
from app.schemas.compliance import ConsentCreate, ConsentRead, OptOutCreate, OptOutRead
from app.services.audit_service import add_audit

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.post("/consents", response_model=ConsentRead, status_code=status.HTTP_201_CREATED)
async def register_consent(
    payload: ConsentCreate,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    actor: str = Header(default="system", alias="X-Actor"),
    _: Principal = Depends(require_operator),
) -> Consent:
    consent = Consent(organization_id=organization_id, **payload.model_dump())
    db.add(consent)
    await db.flush()
    add_audit(
        db,
        action="consent.registered",
        resource_type="contact",
        resource_id=payload.external_contact_id,
        actor=actor,
        details={"category": payload.category, "source": payload.source},
    )
    await db.commit()
    await db.refresh(consent)
    return consent


@router.get("/consents/{external_contact_id}", response_model=list[ConsentRead])
async def list_contact_consents(
    external_contact_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> list[Consent]:
    result = await db.scalars(
        select(Consent)
        .where(
            Consent.organization_id == organization_id,
            Consent.external_contact_id == external_contact_id,
        )
        .order_by(Consent.granted_at.desc())
    )
    return list(result)


@router.post("/consents/{consent_id}/revoke", response_model=ConsentRead)
async def revoke_consent(
    consent_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    actor: str = Header(default="system", alias="X-Actor"),
    _: Principal = Depends(require_operator),
) -> Consent:
    consent = await db.scalar(
        select(Consent).where(Consent.id == consent_id, Consent.organization_id == organization_id)
    )
    if consent is None:
        raise HTTPException(status_code=404, detail="Consentimento não encontrado")
    if consent.revoked_at is None:
        consent.revoked_at = datetime.now(UTC)
        add_audit(
            db,
            action="consent.revoked",
            resource_type="contact",
            resource_id=consent.external_contact_id,
            actor=actor,
            details={"category": consent.category},
        )
        await db.commit()
        await db.refresh(consent)
    return consent


@router.post("/opt-outs", response_model=OptOutRead)
async def register_opt_out(
    payload: OptOutCreate,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    actor: str = Header(default="system", alias="X-Actor"),
    _: Principal = Depends(require_operator),
) -> OptOut:
    phone_hash = hash_phone(payload.phone)
    opt_out = await db.scalar(
        select(OptOut).where(
            OptOut.organization_id == organization_id,
            OptOut.phone_hash == phone_hash,
            OptOut.scope == payload.scope,
        )
    )
    if opt_out is None:
        opt_out = OptOut(
            organization_id=organization_id,
            phone_hash=phone_hash,
            scope=payload.scope,
            source=payload.source,
            reason=payload.reason,
        )
        db.add(opt_out)
        await db.flush()
        add_audit(
            db,
            action="contact.opted_out",
            resource_type="contact",
            resource_id=phone_hash,
            actor=actor,
            details={"scope": payload.scope, "source": payload.source},
        )
        await db.commit()
        await db.refresh(opt_out)
    return opt_out
