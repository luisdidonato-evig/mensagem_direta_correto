import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx
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
from app.models.template import MessageTemplate, TemplateCategory, TemplateStatus
from app.services.audit_service import add_audit
from app.services.frequency_service import record_inbound_message
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


async def forward_webhook(raw_body: bytes, signature: str | None, settings: Settings) -> None:
    if not settings.meta_webhook_forward_url:
        return
    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-Hub-Signature-256"] = signature
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                settings.meta_webhook_forward_url,
                content=raw_body,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Falha ao encaminhar webhook ao atendimento",
        ) from exc


@router.post("")
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | str]:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if settings.meta_mode == "live" and not verify_signature(
        raw_body,
        signature,
        settings.meta_app_secret,
    ):
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida")
    try:
        payload: dict[str, Any] = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    # A Meta permite um callback por app. Este projeto processa campanhas e
    # repassa o mesmo evento assinado para o centro de atendimento.
    await forward_webhook(raw_body, signature, settings)

    event_key = hashlib.sha256(raw_body).hexdigest()
    if await db.scalar(select(WebhookEvent).where(WebhookEvent.event_key == event_key)):
        return {"received": True, "status": "duplicate"}
    first_change = next(
        (change for entry in payload.get("entry", []) for change in entry.get("changes", [])),
        {},
    )
    status_diagnostics = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "errors": [
                {
                    "code": error.get("code"),
                    "title": error.get("title"),
                    "message": error.get("message"),
                    "details": (error.get("error_data") or {}).get("details"),
                }
                for error in item.get("errors", [])
            ],
        }
        for entry in payload.get("entry", [])
        for change in entry.get("changes", [])
        for item in (change.get("value") or {}).get("statuses", [])
    ]
    db.add(
        WebhookEvent(
            event_key=event_key,
            event_type=str(first_change.get("field", "unknown")),
            payload=payload if settings.store_webhook_payloads else None,
            error=json.dumps(status_diagnostics, ensure_ascii=False)
            if status_diagnostics
            else None,
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
                if template and value.get("category"):
                    category = TemplateCategory(value["category"])
                    if category != template.category:
                        template.category = category
                        template.category_changed_at = datetime.now(UTC)
            if field == "message_template_category_update":
                template = await db.scalar(
                    select(MessageTemplate).where(
                        MessageTemplate.organization_id == organization_id,
                        MessageTemplate.meta_template_id
                        == str(value.get("message_template_id")),
                    )
                )
                category_value = value.get("category") or value.get("new_category")
                if template and category_value:
                    category = TemplateCategory(category_value)
                    if category != template.category:
                        template.category = category
                        template.category_changed_at = datetime.now(UTC)
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
                    _, previous_count = await record_inbound_message(
                        db, organization_id, sender_hash
                    )
                    add_audit(
                        db,
                        action="contact.frequency_counter_reset",
                        resource_type="contact",
                        resource_id=sender_hash,
                        details={"previous_count": previous_count},
                    )
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
