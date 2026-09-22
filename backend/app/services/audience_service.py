from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.privacy import hash_phone
from app.models.compliance import Consent, OptOut
from app.schemas.campaigns import AudiencePreviewResponse, AudienceRules


class ContactCandidate(BaseModel):
    id: str
    phone_e164: str
    first_name: str
    product: str
    eligible: bool
    deal_status: str
    last_customer_reply_at: datetime | None
    direct_messages_90d: int
    has_consent: bool
    opted_out: bool = False
    frequency_limited: bool = False
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


def demo_contacts() -> list[ContactCandidate]:
    now = datetime.now(UTC)
    return [
        ContactCandidate(
            id="1",
            phone_e164="+5511999990001",
            first_name="Ana",
            product="Crédito",
            eligible=True,
            deal_status="open",
            last_customer_reply_at=now - timedelta(days=12),
            direct_messages_90d=1,
            has_consent=True,
        ),
        ContactCandidate(
            id="2",
            phone_e164="+5511999990002",
            first_name="Bruno",
            product="Crédito",
            eligible=True,
            deal_status="open",
            last_customer_reply_at=now - timedelta(days=100),
            direct_messages_90d=2,
            has_consent=True,
        ),
        ContactCandidate(
            id="3",
            phone_e164="+5511999990003",
            first_name="Carla",
            product="Crédito",
            eligible=True,
            deal_status="won",
            last_customer_reply_at=now - timedelta(days=30),
            direct_messages_90d=0,
            has_consent=True,
        ),
        ContactCandidate(
            id="4",
            phone_e164="+5511999990004",
            first_name="Diego",
            product="Crédito",
            eligible=True,
            deal_status="open",
            last_customer_reply_at=now - timedelta(days=2),
            direct_messages_90d=0,
            has_consent=True,
        ),
        ContactCandidate(
            id="5",
            phone_e164="+5511999990005",
            first_name="Eva",
            product="Crédito",
            eligible=True,
            deal_status="open",
            last_customer_reply_at=now - timedelta(days=110),
            direct_messages_90d=4,
            has_consent=True,
        ),
        ContactCandidate(
            id="6",
            phone_e164="+5511999990006",
            first_name="Fábio",
            product="Crédito",
            eligible=True,
            deal_status="open",
            last_customer_reply_at=now - timedelta(days=20),
            direct_messages_90d=1,
            has_consent=False,
        ),
        ContactCandidate(
            id="7",
            phone_e164="+5511999990007",
            first_name="Gabi",
            product="Crédito",
            eligible=True,
            deal_status="open",
            last_customer_reply_at=now - timedelta(days=60),
            direct_messages_90d=1,
            has_consent=True,
            opted_out=True,
        ),
    ]


def evaluate_candidate(
    candidate: ContactCandidate, rules: AudienceRules, product: str | None
) -> list[str]:
    reasons: list[str] = []
    if product and candidate.product.casefold() != product.casefold():
        reasons.append("produto_diferente")
    if not candidate.eligible or candidate.deal_status in {"won", "closed"}:
        reasons.append("nao_elegivel_ou_fechado")
    if not candidate.has_consent:
        reasons.append("sem_consentimento")
    if candidate.opted_out:
        reasons.append("opt_out")
    if candidate.frequency_limited:
        reasons.append("limite_consecutivo_sem_resposta")
    if rules.no_response_days:
        threshold = datetime.now(UTC) - timedelta(days=rules.no_response_days)
        if candidate.last_customer_reply_at and candidate.last_customer_reply_at > threshold:
            reasons.append("resposta_recente")
    if (
        rules.fewer_than_direct_messages is not None
        and candidate.direct_messages_90d >= rules.fewer_than_direct_messages
    ):
        reasons.append("limite_de_frequencia")
    return reasons


def eligible_contacts(
    rules: AudienceRules, product: str | None, candidates: list[ContactCandidate] | None = None
) -> list[ContactCandidate]:
    return (
        [candidate for candidate in candidates if not evaluate_candidate(candidate, rules, product)]
        if candidates is not None
        else [
            candidate
            for candidate in demo_contacts()
            if not evaluate_candidate(candidate, rules, product)
        ]
    )


def preview_audience(
    rules: AudienceRules, product: str | None, candidates: list[ContactCandidate] | None = None
) -> AudiencePreviewResponse:
    contacts = candidates if candidates is not None else demo_contacts()
    reasons: dict[str, int] = {}
    eligible = 0
    for candidate in contacts:
        failures = evaluate_candidate(candidate, rules, product)
        if failures:
            for failure in failures:
                reasons[failure] = reasons.get(failure, 0) + 1
        else:
            eligible += 1
    return AudiencePreviewResponse(
        total_considered=len(contacts),
        eligible=eligible,
        suppressed=len(contacts) - eligible,
        suppression_reasons=reasons,
        normalized_rules=rules,
    )


async def apply_persisted_compliance(
    db: AsyncSession,
    organization_id: str,
    candidates: list[ContactCandidate],
    category: str | None,
) -> list[ContactCandidate]:
    hashes = {hash_phone(candidate.phone_e164) for candidate in candidates}
    if not hashes:
        return candidates
    scopes = ["ALL", category] if category else ["ALL"]
    persisted = set(
        await db.scalars(
            select(OptOut.phone_hash).where(
                OptOut.organization_id == organization_id,
                OptOut.scope.in_(scopes),
                OptOut.phone_hash.in_(hashes),
            )
        )
    )
    from app.services.frequency_service import blocked_phone_hashes

    frequency_blocked = await blocked_phone_hashes(db, organization_id, hashes)
    contact_ids = [candidate.id for candidate in candidates]
    consent_rows = list(
        await db.scalars(
            select(Consent).where(
                Consent.organization_id == organization_id,
                Consent.external_contact_id.in_(contact_ids),
                Consent.category.in_(scopes),
            )
        )
    )
    latest_consent: dict[str, tuple[datetime, bool]] = {}
    for consent in consent_rows:
        event_at = consent.revoked_at or consent.granted_at
        current = latest_consent.get(consent.external_contact_id)
        if current is None or event_at > current[0]:
            latest_consent[consent.external_contact_id] = (
                event_at,
                consent.revoked_at is None,
            )
    return [
        candidate.model_copy(
            update={
                "opted_out": candidate.opted_out or hash_phone(candidate.phone_e164) in persisted,
                "frequency_limited": hash_phone(candidate.phone_e164) in frequency_blocked,
                "has_consent": latest_consent.get(
                    candidate.id, (datetime.min.replace(tzinfo=UTC), candidate.has_consent)
                )[1],
            }
        )
        for candidate in candidates
    ]
