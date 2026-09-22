from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_audience_source, get_organization_id
from app.core.auth import Principal, require_operator
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.integrations.audience.provider import AudienceSource, AudienceSourceError
from app.models.campaign import Campaign, CampaignStatus
from app.models.template import MessageTemplate, TemplateStatus
from app.schemas.campaigns import (
    CampaignCreate,
    CampaignRead,
    CampaignResults,
    CampaignValidation,
)
from app.services.audience_service import apply_persisted_compliance, preview_audience
from app.services.audit_service import add_audit
from app.services.campaign_dispatcher import dispatch_campaign
from app.services.idempotency_service import run_idempotent
from app.workers.celery_app import dispatch_campaign_task

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignRead])
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> list[Campaign]:
    result = await db.scalars(
        select(Campaign)
        .where(Campaign.organization_id == organization_id)
        .order_by(Campaign.created_at.desc())
    )
    return list(result)


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: Principal = Depends(require_operator),
) -> CampaignRead | dict:
    async def handler() -> CampaignRead:
        template = await db.get(MessageTemplate, payload.template_id)
        if template is None or template.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Template não encontrado")
        campaign = Campaign(
            organization_id=organization_id,
            name=payload.name,
            product=payload.product,
            template_id=payload.template_id,
            audience_rules=payload.audience_rules.model_dump(),
            variable_mapping=payload.variable_mapping,
            scheduled_at=payload.scheduled_at,
            timezone=payload.timezone,
        )
        db.add(campaign)
        await db.flush()
        add_audit(
            db,
            action="campaign.created",
            resource_type="campaign",
            resource_id=campaign.id,
        )
        await db.commit()
        await db.refresh(campaign)
        return CampaignRead.model_validate(campaign)

    return await run_idempotent(
        db,
        scope="campaign.create",
        namespace=organization_id,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        handler=handler,
    )


@router.get("/{campaign_id}", response_model=CampaignRead)
async def get_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> Campaign:
    campaign = await db.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.organization_id == organization_id
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    return campaign


@router.get("/{campaign_id}/results", response_model=CampaignResults)
async def get_campaign_results(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> CampaignResults:
    from app.models.campaign import CampaignRecipient

    campaign = await db.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.organization_id == organization_id
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    rows = await db.execute(
        select(CampaignRecipient.status, func.count(CampaignRecipient.id))
        .where(CampaignRecipient.campaign_id == campaign_id)
        .group_by(CampaignRecipient.status)
    )
    by_status = {status.value: count for status, count in rows.all()}
    return CampaignResults(
        campaign_id=campaign.id,
        campaign_status=campaign.status,
        total=sum(by_status.values()),
        by_status=by_status,
    )


async def validate_campaign_entity(
    campaign: Campaign, db: AsyncSession, source: AudienceSource
) -> CampaignValidation:
    from app.schemas.campaigns import AudienceRules

    errors: list[str] = []
    template = await db.get(MessageTemplate, campaign.template_id)
    if template is None:
        errors.append("Template não encontrado")
    elif template.status != TemplateStatus.APPROVED:
        errors.append("O template precisa estar aprovado pela Meta")
    rules = AudienceRules.model_validate(campaign.audience_rules)
    try:
        candidates = await source.list_candidates(campaign.organization_id, campaign.product)
        candidates = await apply_persisted_compliance(
            db,
            campaign.organization_id,
            candidates,
            template.category.value if template else None,
        )
        audience = preview_audience(rules, campaign.product, candidates)
    except AudienceSourceError as exc:
        errors.append(str(exc))
        audience = preview_audience(rules, campaign.product, [])
    if audience.eligible == 0:
        errors.append("Nenhum destinatário elegível")
    return CampaignValidation(valid=not errors, errors=errors, audience=audience)


@router.post("/{campaign_id}/validate", response_model=CampaignValidation)
async def validate_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    source: AudienceSource = Depends(get_audience_source),
    _: Principal = Depends(require_operator),
) -> CampaignValidation:
    campaign = await db.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.organization_id == organization_id
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    result = await validate_campaign_entity(campaign, db, source)
    if result.valid:
        campaign.status = CampaignStatus.VALIDATED
        add_audit(
            db,
            action="campaign.validated",
            resource_type="campaign",
            resource_id=campaign.id,
            details={"eligible": result.audience.eligible},
        )
        await db.commit()
    return result


@router.post("/{campaign_id}/send", response_model=CampaignRead)
async def send_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    organization_id: str = Depends(get_organization_id),
    source: AudienceSource = Depends(get_audience_source),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: Principal = Depends(require_operator),
) -> CampaignRead | dict:
    async def handler() -> CampaignRead:
        campaign = await db.scalar(
            select(Campaign).where(
                Campaign.id == campaign_id, Campaign.organization_id == organization_id
            )
        )
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campanha não encontrada")
        if campaign.status not in {CampaignStatus.DRAFT, CampaignStatus.VALIDATED}:
            raise HTTPException(status_code=409, detail="Campanha não está disponível para envio")
        validation = await validate_campaign_entity(campaign, db, source)
        if not validation.valid:
            raise HTTPException(status_code=422, detail=validation.errors)
        campaign.status = CampaignStatus.QUEUED
        add_audit(
            db,
            action="campaign.queued",
            resource_type="campaign",
            resource_id=campaign.id,
            details={"dispatch_mode": settings.dispatch_mode},
        )
        await db.commit()
        if settings.dispatch_mode == "celery":
            dispatch_campaign_task.delay(campaign.id)
        else:
            await dispatch_campaign(campaign.id)
        await db.refresh(campaign)
        return CampaignRead.model_validate(campaign)

    return await run_idempotent(
        db,
        scope="campaign.send",
        namespace=campaign_id,
        key=idempotency_key,
        status_code=status.HTTP_200_OK,
        handler=handler,
    )


@router.post("/{campaign_id}/schedule", response_model=CampaignRead)
async def schedule_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    organization_id: str = Depends(get_organization_id),
    source: AudienceSource = Depends(get_audience_source),
    _: Principal = Depends(require_operator),
) -> Campaign:
    if settings.dispatch_mode != "celery":
        raise HTTPException(status_code=409, detail="Agendamento requer DISPATCH_MODE=celery")
    campaign = await db.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.organization_id == organization_id
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    if campaign.scheduled_at is None:
        raise HTTPException(status_code=422, detail="scheduled_at é obrigatório")
    scheduled_at = campaign.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    if scheduled_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="scheduled_at deve estar no futuro")
    validation = await validate_campaign_entity(campaign, db, source)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    campaign.status = CampaignStatus.SCHEDULED
    add_audit(
        db,
        action="campaign.scheduled",
        resource_type="campaign",
        resource_id=campaign.id,
        details={"scheduled_at": scheduled_at.isoformat()},
    )
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/cancel", response_model=CampaignRead)
async def cancel_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    _: Principal = Depends(require_operator),
) -> Campaign:
    campaign = await db.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.organization_id == organization_id
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    if campaign.status not in {
        CampaignStatus.DRAFT,
        CampaignStatus.VALIDATED,
        CampaignStatus.SCHEDULED,
        CampaignStatus.QUEUED,
    }:
        raise HTTPException(status_code=409, detail="Campanha não pode mais ser cancelada")
    campaign.status = CampaignStatus.CANCELLED
    add_audit(
        db,
        action="campaign.cancelled",
        resource_type="campaign",
        resource_id=campaign.id,
    )
    await db.commit()
    await db.refresh(campaign)
    return campaign
