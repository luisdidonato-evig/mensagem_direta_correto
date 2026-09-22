import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.crypto import encrypt_token
from app.core.database import SessionLocal
from app.core.privacy import hash_phone
from app.integrations.audience.provider import AudienceSourceError, build_audience_source
from app.integrations.meta.circuit_breaker import meta_circuit_breaker
from app.integrations.meta.provider import MetaProviderError, build_provider_for_connection
from app.models.campaign import Campaign, CampaignRecipient, CampaignStatus, RecipientStatus
from app.models.compliance import OptOut
from app.models.template import MessageTemplate, TemplateStatus
from app.schemas.campaigns import AudienceRules
from app.services.audience_service import (
    apply_persisted_compliance,
    eligible_contacts,
    evaluate_candidate,
)
from app.services.audit_service import add_audit
from app.services.frequency_service import (
    confirm_template_send,
    release_template_send,
    reserve_template_send,
)
from app.services.organization_service import get_waba_connection
from app.services.template_service import build_send_components

MAX_SEND_RETRIES = 5
DISPATCH_LEASE = timedelta(minutes=15)

_TERMINAL_STATUSES = {
    RecipientStatus.ACCEPTED,
    RecipientStatus.SENT,
    RecipientStatus.DELIVERED,
    RecipientStatus.READ,
    RecipientStatus.REPLIED,
    RecipientStatus.FAILED,
    RecipientStatus.SUPPRESSED,
    RecipientStatus.OPTED_OUT,
}


def resolve_template_variables(contact, variable_schema: dict, mapping: dict) -> dict:
    values: dict[str, object] = {}
    for definition in variable_schema.values():
        alias = definition["alias"]
        source = mapping.get(alias, definition.get("source", alias))
        if source == "contact.first_name":
            value = contact.first_name
        elif source in {"deal.product_name", "contact.product"}:
            value = contact.product
        elif source.startswith("contact.attributes."):
            value = contact.attributes.get(source.removeprefix("contact.attributes."))
        elif source.startswith("attributes."):
            value = contact.attributes.get(source.removeprefix("attributes."))
        else:
            value = contact.attributes.get(source)
        if value is not None:
            values[alias] = value
    return values


async def dispatch_campaign(campaign_id: str) -> CampaignStatus:
    settings = get_settings()
    async with SessionLocal() as db:
        campaign = await db.scalar(
            select(Campaign).where(Campaign.id == campaign_id).with_for_update()
        )
        if campaign is None:
            raise ValueError("Campanha não encontrada")
        dispatchable = {CampaignStatus.QUEUED, CampaignStatus.SCHEDULED, CampaignStatus.SENDING}
        if campaign.status not in dispatchable:
            return campaign.status
        now = datetime.now(UTC)
        if campaign.status == CampaignStatus.SCHEDULED and campaign.scheduled_at:
            scheduled_at = campaign.scheduled_at
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=UTC)
            if scheduled_at > now:
                return CampaignStatus.SCHEDULED
        lease_until = campaign.dispatch_lease_until
        if lease_until and lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=UTC)
        if lease_until and lease_until > now:
            return CampaignStatus.SENDING
        lease_owner = str(uuid.uuid4())
        campaign.dispatch_lease_owner = lease_owner
        campaign.dispatch_lease_until = now + DISPATCH_LEASE
        campaign.status = CampaignStatus.SENDING
        campaign.updated_at = now
        await db.commit()

        template = await db.get(MessageTemplate, campaign.template_id)
        if template is None or template.status != TemplateStatus.APPROVED:
            campaign.status = CampaignStatus.FAILED
            campaign.dispatch_lease_owner = None
            campaign.dispatch_lease_until = None
            add_audit(
                db,
                action="campaign.dispatch_failed",
                resource_type="campaign",
                resource_id=campaign.id,
                details={"reason": "template_not_approved"},
            )
            await db.commit()
            return campaign.status

        connection = await get_waba_connection(db, campaign.organization_id)
        try:
            provider = build_provider_for_connection(
                settings.meta_mode, connection, settings.meta_graph_version
            )
        except MetaProviderError as exc:
            campaign.status = CampaignStatus.FAILED
            campaign.dispatch_lease_owner = None
            campaign.dispatch_lease_until = None
            add_audit(
                db,
                action="campaign.dispatch_failed",
                resource_type="campaign",
                resource_id=campaign.id,
                details={"reason": exc.code, "detail": str(exc)},
            )
            await db.commit()
            return campaign.status

        rules = AudienceRules.model_validate(campaign.audience_rules)
        try:
            candidates = await build_audience_source(settings).list_candidates(
                campaign.organization_id, campaign.product
            )
        except AudienceSourceError as exc:
            campaign.status = CampaignStatus.QUEUED
            campaign.dispatch_lease_owner = None
            campaign.dispatch_lease_until = None
            await db.commit()
            raise ConnectionError(str(exc)) from exc
        candidates = await apply_persisted_compliance(
            db, campaign.organization_id, candidates, template.category.value
        )
        failures = 0
        pending_retry = False
        breaker_key = campaign.organization_id

        for contact in eligible_contacts(rules, campaign.product, candidates):
            variables = resolve_template_variables(
                contact, template.variable_schema, campaign.variable_mapping
            )
            recipient = await db.scalar(
                select(CampaignRecipient).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.external_contact_id == contact.id,
                )
            )
            if recipient and recipient.status in _TERMINAL_STATUSES:
                continue
            if recipient is None:
                recipient = CampaignRecipient(
                    campaign_id=campaign.id,
                    external_contact_id=contact.id,
                    phone_e164=encrypt_token(contact.phone_e164, settings),
                    phone_hash=hash_phone(contact.phone_e164),
                    variables={
                        "encrypted": encrypt_token(
                            json.dumps(
                                variables,
                                ensure_ascii=False,
                            ),
                            settings,
                        )
                    },
                    eligibility_snapshot=campaign.audience_rules,
                    status=RecipientStatus.SELECTED,
                )
                db.add(recipient)
                await db.flush()

            # Revalidação final: fonte comercial, consentimento e opt-out persistido.
            reasons = evaluate_candidate(contact, rules, campaign.product)
            opted_out = await db.scalar(
                select(OptOut).where(
                    OptOut.organization_id == campaign.organization_id,
                    OptOut.phone_hash == hash_phone(contact.phone_e164),
                    OptOut.scope.in_(["ALL", template.category.value]),
                )
            )
            if opted_out:
                reasons.append("opt_out_persistido")
            phone_hash = hash_phone(contact.phone_e164)
            frequency_reserved = False
            frequency_position = 0
            if not reasons:
                frequency_reserved, frequency_position = await reserve_template_send(
                    db, campaign.organization_id, phone_hash
                )
                if not frequency_reserved:
                    reasons.append("limite_consecutivo_sem_resposta")
            if reasons:
                recipient.status = RecipientStatus.SUPPRESSED
                recipient.eligibility_snapshot = {
                    **campaign.audience_rules,
                    "suppression_reasons": sorted(set(reasons)),
                    "consecutive_template_sends": frequency_position,
                }
                campaign.updated_at = datetime.now(UTC)
                campaign.dispatch_lease_until = campaign.updated_at + DISPATCH_LEASE
                await db.commit()
                continue

            if meta_circuit_breaker.is_open(breaker_key):
                # Meta está instável para esta organização: não bate na API de
                # novo agora, só deixa o destinatário pendente pra próxima
                # tentativa (com backoff/jitter no nível do worker Celery).
                pending_retry = True
                if frequency_reserved:
                    await release_template_send(db, campaign.organization_id, phone_hash)
                campaign.updated_at = datetime.now(UTC)
                campaign.dispatch_lease_until = campaign.updated_at + DISPATCH_LEASE
                await db.commit()
                continue

            template_payload: dict = {
                "name": template.name,
                "language": {"code": template.language},
            }
            try:
                components = build_send_components(template.variable_schema, variables)
                if components:
                    template_payload["components"] = components
                recipient.wamid = await provider.send_template(
                    {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": contact.phone_e164.lstrip("+"),
                        "type": "template",
                        "template": template_payload,
                    }
                )
                recipient.status = RecipientStatus.ACCEPTED
                state = await confirm_template_send(
                    db, campaign.organization_id, phone_hash
                )
                recipient.eligibility_snapshot = {
                    **campaign.audience_rules,
                    "consecutive_template_sends": state.consecutive_template_sends,
                }
                add_audit(
                    db,
                    action="template.send_accepted",
                    resource_type="contact",
                    resource_id=recipient.external_contact_id,
                    details={
                        "campaign_id": campaign.id,
                        "consecutive_template_sends": state.consecutive_template_sends,
                    },
                )
                recipient.failure_code = None
                recipient.failure_detail = None
                meta_circuit_breaker.record_success(breaker_key)
            except (MetaProviderError, ValueError) as exc:
                if frequency_reserved:
                    await release_template_send(db, campaign.organization_id, phone_hash)
                transient = isinstance(exc, MetaProviderError) and exc.transient
                recipient.failure_code = getattr(exc, "code", "invalid_variables")
                recipient.failure_detail = str(exc)
                if transient:
                    meta_circuit_breaker.record_failure(breaker_key)
                    recipient.retry_count += 1
                    if recipient.retry_count >= MAX_SEND_RETRIES:
                        recipient.status = RecipientStatus.FAILED
                        failures += 1
                    else:
                        # Fica em SELECTED de propósito: a próxima passada de
                        # dispatch_campaign reprocessa este destinatário.
                        pending_retry = True
                else:
                    # Erro permanente (ex.: variável obrigatória ausente) —
                    # retentar não resolve, então falha de vez.
                    recipient.status = RecipientStatus.FAILED
                    failures += 1
            campaign.updated_at = datetime.now(UTC)
            campaign.dispatch_lease_until = campaign.updated_at + DISPATCH_LEASE
            await db.commit()

        total_failures = await db.scalar(
            select(func.count(CampaignRecipient.id)).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.status == RecipientStatus.FAILED,
            )
        )
        campaign.dispatch_lease_owner = None
        campaign.dispatch_lease_until = None
        if pending_retry:
            campaign.status = CampaignStatus.SENDING
        else:
            campaign.status = (
                CampaignStatus.PARTIAL_FAILURE if total_failures else CampaignStatus.COMPLETED
            )
        add_audit(
            db,
            action="campaign.dispatch_completed",
            resource_type="campaign",
            resource_id=campaign.id,
            details={
                "failures_this_attempt": failures,
                "failures_total": total_failures,
                "pending_retry": pending_retry,
            },
        )
        await db.commit()
        return campaign.status
