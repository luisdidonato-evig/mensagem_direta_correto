import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.integrations.meta.provider import MetaProviderError, build_provider_for_connection
from app.models.campaign import Campaign, CampaignStatus
from app.models.operations import HandoffDelivery
from app.models.organization import Organization
from app.services.audit_service import add_audit
from app.services.handoff_service import deliver_handoff
from app.services.organization_service import get_waba_connection
from app.services.template_service import sync_templates
from app.workers.celery_app import celery_app, dispatch_campaign_task

STUCK_CAMPAIGN_THRESHOLD = timedelta(minutes=10)


async def _reconcile_stuck_campaigns() -> int:
    """Re-queue campaigns left mid-flight (worker crash, missed retry, or the
    inline dispatch path — which has no retry of its own). Protects against
    a campaign getting stranded in QUEUED/SENDING forever (PLANEJAMENTO.md §13,
    Fase 5: "reconciliação periódica" — this is the piece that never got built).

    Only re-queues campaigns whose `updated_at` is stale: one that's actively
    being worked by a live dispatch pass gets its `updated_at` touched on every
    recipient commit, so a genuinely in-flight campaign never qualifies here —
    re-queuing it too would race the running dispatch and could double-send.
    """
    requeued = 0
    cutoff = datetime.now(UTC) - STUCK_CAMPAIGN_THRESHOLD
    async with SessionLocal() as db:
        stuck = await db.scalars(
            select(Campaign).where(
                Campaign.status.in_([CampaignStatus.QUEUED, CampaignStatus.SENDING]),
                Campaign.updated_at < cutoff,
                or_(
                    Campaign.dispatch_lease_until.is_(None),
                    Campaign.dispatch_lease_until <= datetime.now(UTC),
                ),
            )
        )
        for campaign in stuck:
            dispatch_campaign_task.delay(campaign.id)
            requeued += 1
        if requeued:
            add_audit(
                db,
                action="campaign.reconciliation_requeued",
                resource_type="campaign",
                resource_id="batch",
                details={"count": requeued},
            )
            await db.commit()
    return requeued


async def _dispatch_due_campaigns() -> int:
    now = datetime.now(UTC)
    queued = 0
    async with SessionLocal() as db:
        due = await db.scalars(
            select(Campaign)
            .where(
                Campaign.status == CampaignStatus.SCHEDULED,
                Campaign.scheduled_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
        for campaign in due:
            campaign.status = CampaignStatus.QUEUED
            campaign.updated_at = now
            await db.commit()
            dispatch_campaign_task.delay(campaign.id)
            queued += 1
    return queued


async def _retry_handoffs() -> int:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        ids = list(
            await db.scalars(
                select(HandoffDelivery.id).where(
                    HandoffDelivery.status.in_(["PENDING", "PROCESSING"]),
                    HandoffDelivery.next_attempt_at <= now,
                )
            )
        )
    delivered = 0
    for delivery_id in ids:
        if await deliver_handoff(delivery_id):
            delivered += 1
    return delivered


async def _sync_all_organizations() -> dict[str, int]:
    """Periodic template sync per org — the safety net for a lost webhook
    (PLANEJAMENTO.md §6.3: "reconciliação periódica como proteção contra
    webhook perdido")."""
    settings = get_settings()
    results: dict[str, int] = {}
    async with SessionLocal() as db:
        organizations = await db.scalars(select(Organization))
        for organization in organizations:
            connection = await get_waba_connection(db, organization.id)
            try:
                provider = build_provider_for_connection(
                    settings.meta_mode, connection, settings.meta_graph_version
                )
                created, updated = await sync_templates(db, provider, organization.id)
                results[organization.id] = created + updated
            except MetaProviderError:
                # Sem conexão configurada ainda, ou Meta fora do ar — próxima
                # rodada tenta de novo, isso é best-effort.
                continue
    return results


@celery_app.task(name="scheduler.reconcile_campaigns")
def reconcile_campaigns_task() -> int:
    return asyncio.run(_reconcile_stuck_campaigns())


@celery_app.task(name="scheduler.sync_all_organizations")
def sync_all_organizations_task() -> dict[str, int]:
    return asyncio.run(_sync_all_organizations())


@celery_app.task(name="scheduler.dispatch_due_campaigns")
def dispatch_due_campaigns_task() -> int:
    return asyncio.run(_dispatch_due_campaigns())


@celery_app.task(name="scheduler.retry_handoffs")
def retry_handoffs_task() -> int:
    return asyncio.run(_retry_handoffs())
