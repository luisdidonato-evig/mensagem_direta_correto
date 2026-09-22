import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import Celery

from app.core.config import get_settings
from app.core.database import engine
from app.models.campaign import CampaignStatus
from app.services.campaign_dispatcher import dispatch_campaign

settings = get_settings()
celery_app = Celery("evig_direct_messages", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "reconcile-stuck-campaigns": {
            "task": "scheduler.reconcile_campaigns",
            "schedule": 300.0,  # 5 min — protege campanha travada por worker morto ou modo inline
        },
        "sync-templates-all-organizations": {
            "task": "scheduler.sync_all_organizations",
            # 30 min — rede de segurança pra webhook perdido (PLANEJAMENTO.md §6.3)
            "schedule": 1800.0,
        },
        "dispatch-due-campaigns": {
            "task": "scheduler.dispatch_due_campaigns",
            "schedule": 30.0,
        },
        "retry-handoff-deliveries": {
            "task": "scheduler.retry_handoffs",
            "schedule": 30.0,
        },
    },
)


class DispatchStillPending(Exception):
    """Raised to trigger a Celery retry — some recipients hit a transient
    Meta error and are still waiting their turn (see campaign_dispatcher)."""


def run_async(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Run one Celery async job without reusing asyncpg connections across event loops."""

    async def runner() -> Any:
        try:
            return await coroutine
        finally:
            await engine.dispose()

    return asyncio.run(runner())


@celery_app.task(
    bind=True,
    name="campaign.dispatch",
    autoretry_for=(ConnectionError, DispatchStillPending),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=8,
)
def dispatch_campaign_task(self, campaign_id: str) -> str:
    result = run_async(dispatch_campaign(campaign_id))
    if result == CampaignStatus.SENDING:
        raise DispatchStillPending(campaign_id)
    return result.value


# Registers the periodic tasks referenced by beat_schedule above. Imported at
# the bottom (not the top) because scheduled_tasks.py imports `celery_app`
# from this same module — safe here since `celery_app` is already bound.
from app.workers import scheduled_tasks  # noqa: E402,F401
