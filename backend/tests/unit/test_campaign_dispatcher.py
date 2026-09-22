from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models import Campaign, CampaignRecipient, MessageTemplate, Organization, WabaConnection
from app.models.campaign import CampaignStatus, RecipientStatus
from app.models.template import TemplateCategory, TemplateStatus
from app.services import campaign_dispatcher


async def build_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, sessions


async def seed_campaign(sessions, *, status: CampaignStatus = CampaignStatus.QUEUED) -> str:
    async with sessions() as db:
        organization = Organization(id="org", name="Teste")
        template = MessageTemplate(
            id="template",
            organization_id="org",
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
            organization_id="org",
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
            [organization, WabaConnection(id="waba", organization_id="org"), template, campaign]
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
    monkeypatch.setattr(campaign_dispatcher, "get_settings", lambda: Settings(meta_mode="mock"))

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
