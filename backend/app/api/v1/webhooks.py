import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.privacy import hash_phone
from app.models.campaign import Campaign, CampaignRecipient, RecipientStatus
from app.models.compliance import OptOut
from app.models.operations import HandoffDelivery, WebhookEvent
from app.models.organization import WabaConnection
from app.models.template import MessageTemplate, TemplateStatus
from app.services.audit_service import add_audit
from app.services.handoff_service import deliver_handoff

router = APIRouter(prefix="/webhooks/meta", tags=["webhooks"])

STATUS_RANK = {
    RecipientStatus.SELECTED: 0,
    RecipientStatus.ACCEPTED: 1,
    RecipientStatus.SENT: 2,
    RecipientStatus.DELIVERED: 3,
    RecipientStatus.READ: 4,
    RecipientStatus.REPLIED: 5,
}


@router.get("")
async def verify_webhook(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> Response:
    if mode != "subscribe" or token != settings.meta_webhook_verify_token:
        raise HTTPException(status_code=403, detail="Token de verificação inválido")
    return Response(content=challenge, media_type="text/plain")


def transition_recipient(recipient: CampaignRecipient, new_status: RecipientStatus) -> None:
    if new_status in {RecipientStatus.FAILED, RecipientStatus.OPTED_OUT}:
        recipient.status = new_status
        return
    if STATUS_RANK.get(new_status, -1) > STATUS_RANK.get(recipient.status, -1):
        recipient.status = new_status


def verify_signature(raw_body: bytes, signature: str | None, app_secret: str) -> bool:
    if not signature or not app_secret:
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("")
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | str]:
    raw_body = await request.body()
    if settings.meta_mode == "live" and not verify_signature(
        raw_body,
        request.headers.get("X-Hub-Signature-256"),
        settings.meta_app_secret,
    ):
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida")
    try:
        payload: dict[str, Any] = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    event_key = hashlib.sha256(raw_body).hexdigest()
    if await db.scalar(select(WebhookEvent).where(WebhookEvent.event_key == event_key)):
        return {"received": True, "status": "duplicate"}
    first_change = next(
        (change for entry in payload.get("entry", []) for change in entry.get("changes", [])),
        {},
    )
    db.add(
        WebhookEvent(
            event_key=event_key,
            event_type=str(first_change.get("field", "unknown")),
            payload=payload if settings.store_webhook_payloads else None,
        )
    )

    handoff_delivery_ids: list[str] = []
    for entry in payload.get("entry", []):
        connection = await db.scalar(
            select(WabaConnection).where(WabaConnection.waba_id == str(entry.get("id", "")))
        )
        if connection is None:
            # Eventos sem conta conhecida não podem alterar dados de outra empresa.
            continue
        organization_id = connection.organization_id
        for change in entry.get("changes", []):
            field = change.get("field")
            value = change.get("value", {})
            if field == "message_template_status_update":
                template = await db.scalar(
                    select(MessageTemplate).where(
                        MessageTemplate.organization_id == organization_id,
                        MessageTemplate.meta_template_id == str(value.get("message_template_id")),
                    )
                )
                event = value.get("event")
                if template and event in TemplateStatus.__members__:
                    template.status = TemplateStatus[event]
                    template.rejection_reason = value.get("reason")
            if field == "messages":
                for item in value.get("statuses", []):
                    recipient = await db.scalar(
                        select(CampaignRecipient)
                        .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
                        .where(
                            Campaign.organization_id == organization_id,
                            CampaignRecipient.wamid == item.get("id"),
                        )
                    )
                    status_value = str(item.get("status", "")).upper()
                    if recipient and status_value in RecipientStatus.__members__:
                        transition_recipient(recipient, RecipientStatus[status_value])
                        if status_value == "FAILED":
                            errors = item.get("errors", [])
                            if errors:
                                recipient.failure_code = str(errors[0].get("code", "unknown"))
                                recipient.failure_detail = errors[0].get("title")
                for message in value.get("messages", []):
                    sender = str(message.get("from", ""))
                    sender_hash = hash_phone(sender)
                    recipient = await db.scalar(
                        select(CampaignRecipient)
                        .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
                        .where(
                            Campaign.organization_id == organization_id,
                            CampaignRecipient.phone_hash == sender_hash,
                        )
                        .order_by(CampaignRecipient.updated_at.desc())
                    )
                    if recipient is None:
                        # Compatibilidade com destinatários gravados antes da migração de PII.
                        recipient = await db.scalar(
                            select(CampaignRecipient)
                            .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
                            .where(
                                Campaign.organization_id == organization_id,
                                CampaignRecipient.phone_hash.is_(None),
                                CampaignRecipient.phone_e164.in_([sender, f"+{sender}"]),
                            )
                            .order_by(CampaignRecipient.updated_at.desc())
                        )
                    if recipient:
                        text = str(message.get("text", {}).get("body", "")).strip().casefold()
                        transition_recipient(
                            recipient,
                            RecipientStatus.OPTED_OUT
                            if text == "sair"
                            else RecipientStatus.REPLIED,
                        )
                        if text == "sair":
                            phone_hash = sender_hash
                            existing = await db.scalar(
                                select(OptOut).where(
                                    OptOut.organization_id == organization_id,
                                    OptOut.phone_hash == phone_hash,
                                    OptOut.scope == "ALL",
                                )
                            )
                            if existing is None:
                                db.add(
                                    OptOut(
                                        organization_id=organization_id,
                                        phone_hash=phone_hash,
                                        scope="ALL",
                                        source="whatsapp_keyword",
                                        reason="SAIR",
                                    )
                                )
                            add_audit(
                                db,
                                action="contact.opted_out",
                                resource_type="contact",
                                resource_id=recipient.external_contact_id,
                                details={"source": "whatsapp_keyword"},
                            )
                        else:
                            event = {
                                "event": "whatsapp.reply_received",
                                "organization_id": organization_id,
                                "campaign_id": recipient.campaign_id,
                                "external_contact_id": recipient.external_contact_id,
                                "message_id": message.get("id"),
                                "text": str(message.get("text", {}).get("body", "")),
                                "received_at": message.get("timestamp"),
                            }
                            delivery_key = f"{organization_id}:{message.get('id')}"
                            delivery = await db.scalar(
                                select(HandoffDelivery).where(
                                    HandoffDelivery.event_key == delivery_key
                                )
                            )
                            if delivery is None:
                                delivery = HandoffDelivery(
                                    event_key=delivery_key,
                                    payload=event,
                                )
                                db.add(delivery)
                                await db.flush()
                            if delivery.status != "DELIVERED":
                                handoff_delivery_ids.append(delivery.id)
    await db.commit()
    for delivery_id in handoff_delivery_ids:
        await deliver_handoff(delivery_id, settings)
    return {"received": True, "status": "processed"}
