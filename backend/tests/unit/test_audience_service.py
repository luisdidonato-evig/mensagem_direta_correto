from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.privacy import hash_phone
from app.models import Consent, OptOut, Organization
from app.schemas.campaigns import AudienceRules
from app.services.audience_service import (
    apply_persisted_compliance,
    demo_contacts,
    preview_audience,
)
from app.services.frequency_service import confirm_template_send, reserve_template_send


def test_preview_applies_required_guards_and_frequency_limit() -> None:
    result = preview_audience(
        AudienceRules(
            eligible_not_closed=True,
            no_response_days=7,
            fewer_than_direct_messages=3,
        ),
        "Crédito",
    )

    assert result.total_considered == 7
    assert result.eligible == 2
    assert result.suppression_reasons["nao_elegivel_ou_fechado"] == 1
    assert result.suppression_reasons["sem_consentimento"] == 1
    assert result.suppression_reasons["opt_out"] == 1
    assert result.suppression_reasons["limite_de_frequencia"] == 1


def test_ninety_days_is_more_restrictive_than_seven_days() -> None:
    seven_days = preview_audience(
        AudienceRules(no_response_days=7, fewer_than_direct_messages=3), "Crédito"
    )
    ninety_days = preview_audience(
        AudienceRules(no_response_days=90, fewer_than_direct_messages=3), "Crédito"
    )

    assert ninety_days.eligible < seven_days.eligible


@pytest.mark.asyncio
async def test_category_opt_out_and_revoked_consent_suppress_candidates() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(Organization(id="org", name="Teste"))
        from app.core.privacy import hash_phone

        db.add(
            OptOut(
                organization_id="org",
                phone_hash=hash_phone("+5511999990001"),
                scope="MARKETING",
                source="test",
            )
        )
        db.add(
            Consent(
                organization_id="org",
                external_contact_id="2",
                category="MARKETING",
                source="test",
                evidence={},
                granted_at=datetime(2026, 1, 1, tzinfo=UTC),
                revoked_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )
        await db.commit()

        result = await apply_persisted_compliance(db, "org", demo_contacts(), "MARKETING")

    by_id = {candidate.id: candidate for candidate in result}
    assert by_id["1"].opted_out is True
    assert by_id["2"].has_consent is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_trusted_audience_reply_releases_local_frequency_limit() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        candidate = demo_contacts()[0]
        phone_hash = hash_phone(candidate.phone_e164)
        for _ in range(3):
            await reserve_template_send(db, "org", phone_hash)
            state = await confirm_template_send(db, "org", phone_hash)
        state.last_outbound_at = datetime.now(UTC) - timedelta(days=1)
        candidate.last_customer_reply_at = datetime.now(UTC)
        await db.commit()
        result = await apply_persisted_compliance(db, "org", [candidate], "UTILITY")
        assert not result[0].frequency_limited
        assert state.consecutive_template_sends == 0
    await engine.dispose()
