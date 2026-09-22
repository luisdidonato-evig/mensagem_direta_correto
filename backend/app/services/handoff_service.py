import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models.operations import HandoffDelivery

logger = logging.getLogger(__name__)


async def send_handoff_payload(event: dict, settings: Settings) -> None:
    if not settings.handoff_webhook_url:
        return
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    if settings.handoff_webhook_secret:
        signature = hmac.new(
            settings.handoff_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        headers["X-Evig-Signature-256"] = f"sha256={signature}"
    async with httpx.AsyncClient(timeout=settings.handoff_timeout_seconds) as client:
        response = await client.post(settings.handoff_webhook_url, content=body, headers=headers)
        response.raise_for_status()


async def deliver_handoff(delivery_id: str, settings: Settings | None = None) -> bool:
    runtime_settings = settings or get_settings()
    async with SessionLocal() as db:
        delivery = await db.scalar(
            select(HandoffDelivery).where(HandoffDelivery.id == delivery_id).with_for_update()
        )
        if delivery is None or delivery.status == "DELIVERED":
            return True
        now = datetime.now(UTC)
        next_attempt = delivery.next_attempt_at
        if next_attempt.tzinfo is None:
            next_attempt = next_attempt.replace(tzinfo=UTC)
        if delivery.status == "PROCESSING" and next_attempt > now:
            return False
        delivery.status = "PROCESSING"
        delivery.next_attempt_at = now + timedelta(minutes=5)
        await db.commit()
        try:
            await send_handoff_payload(delivery.payload, runtime_settings)
        except httpx.HTTPError as exc:
            delivery.attempt_count += 1
            delivery.status = "PENDING"
            delay_seconds = min(3600, 2 ** min(delivery.attempt_count, 10))
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
            delivery.last_error = str(exc)[:2000]
            await db.commit()
            logger.warning(
                "handoff_delivery_failed",
                extra={"request_id": delivery.id},
            )
            return False
        delivery.status = "DELIVERED"
        delivery.delivered_at = datetime.now(UTC)
        delivery.last_error = None
        await db.commit()
        return True
