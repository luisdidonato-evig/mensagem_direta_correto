from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.campaigns import validate_campaign_entity
from app.core.config import Settings
from app.core.database import Base
from app.models import Campaign, CampaignRecipient, MessageTemplate, Organization, WabaConnection
from app.models.campaign import CampaignStatus, RecipientStatus
from app.models.template import TemplateCategory, TemplateStatus
from app.services import campaign_dispatcher


def test_dispatch_key_survives_recipient_row_recreation() -> None:
    first = campaign_dispatcher.recipient_dispatch_key("campaign-id", "contact-id")
    assert first == campaign_dispatcher.recipient_dispatch_key("campaign-id", "contact-id")
    assert first != campaign_dispatcher.recipient_dispatch_key("campaign-id", "other-contact")
    assert first != campaign_dispatcher.recipient_dispatch_key("other-campaign", "contact-id")


async def build_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, sessions


async def seed_campaign(sessions, *, status: CampaignStatus = CampaignStatus.QUEUED) -> str:
    async with sessions() as db:
        organization = Organization(id="11111111-1111-4111-8111-111111111111", name="Teste")
        template = MessageTemplate(
            id="template",
            organization_id=organization.id,
            meta_template_id="meta-template",
            name="retomada",
            display_name="Retomada",
            category=TemplateCategory.UTILITY,
            status=TemplateStatus.APPROVED,
            components=[{"type": "BODY", "text": "Oi {{1}}"}],
            variable_schema={
                "1": {
                    "alias": "nome",
                    "source": "contact.first_name",
                    "required": True,
                }
            },
        )
        campaign = Campaign(
            id="campaign",
            organization_id=organization.id,
            name="Campanha",
            product="Crédito",
            template_id="template",
            audience_rules={
                "eligible_not_closed": True,
                "no_response_days": 7,
                "fewer_than_direct_messages": 3,
            },
            status=status,
        )
        db.add_all(
            [
                organization,
                WabaConnection(
                    id="waba",
                    organization_id=organization.id,
                    channel_account_id="22222222-2222-4222-8222-222222222222",
                ),
                template,
                campaign,
            ]
        )
        await db.commit()
    return campaign.id


@pytest.mark.asyncio
async def test_previous_recipient_failure_keeps_partial_failure(monkeypatch) -> None:
    engine, sessions = await build_database()
    campaign_id = await seed_campaign(sessions)
    async with sessions() as db:
        db.add(
            CampaignRecipient(
                campaign_id=campaign_id,
                external_contact_id="1",
                phone_e164="encrypted",
                status=RecipientStatus.FAILED,
            )
        )
        await db.commit()
    monkeypatch.setattr(campaign_dispatcher, "SessionLocal", sessions)
    monkeypatch.setattr(
        campaign_dispatcher,
        "get_settings",
        lambda: Settings(gateway_url="https://gateway.example.test", gateway_internal_key="secret"),
    )
    monkeypatch.setattr(
        campaign_dispatcher,
        "build_campaign_provider",
        lambda *_: SimpleNamespace(send_template=AsyncMock(return_value="delivery-1")),
    )

    result = await campaign_dispatcher.dispatch_campaign(campaign_id)

    assert result == CampaignStatus.PARTIAL_FAILURE
    await engine.dispose()


@pytest.mark.asyncio
async def test_active_dispatch_lease_prevents_second_worker(monkeypatch) -> None:
    engine, sessions = await build_database()
    campaign_id = await seed_campaign(sessions, status=CampaignStatus.SENDING)
    async with sessions() as db:
        campaign = await db.get(Campaign, campaign_id)
        campaign.dispatch_lease_owner = "worker-1"
        campaign.dispatch_lease_until = datetime.now(UTC) + timedelta(minutes=5)
        await db.commit()
    monkeypatch.setattr(campaign_dispatcher, "SessionLocal", sessions)
    monkeypatch.setattr(campaign_dispatcher, "get_settings", lambda: Settings(meta_mode="mock"))

    result = await campaign_dispatcher.dispatch_campaign(campaign_id)

    assert result == CampaignStatus.SENDING
    async with sessions() as db:
        recipients = await db.get(CampaignRecipient, "missing")
        assert recipients is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_campaign_validation_blocks_missing_channel_before_queue() -> None:
    engine, sessions = await build_database()
    campaign_id = await seed_campaign(sessions)
    async with sessions() as db:
        connection = await db.get(WabaConnection, "waba")
        connection.channel_account_id = None
        await db.commit()
        campaign = await db.get(Campaign, campaign_id)
        source = SimpleNamespace(list_candidates=AsyncMock(return_value=[]))
        result = await validate_campaign_entity(
            campaign,
            db,
            source,
            Settings(gateway_url="https://gateway.example.test", gateway_internal_key="secret"),
        )
        assert not result.valid
        assert any("channel_account_id" in error for error in result.errors)
    await engine.dispose()
