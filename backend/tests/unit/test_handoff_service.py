import pytest
import respx
from httpx import Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models.operations import HandoffDelivery
from app.services import handoff_service


@pytest.mark.asyncio
@respx.mock
async def test_failed_handoff_stays_pending_and_can_be_retried(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(
            HandoffDelivery(
                id="delivery",
                event_key="org:message",
                payload={"event": "whatsapp.reply_received"},
            )
        )
        await db.commit()
    monkeypatch.setattr(handoff_service, "SessionLocal", sessions)
    settings = Settings(handoff_webhook_url="https://agent.example.test/handoff")
    route = respx.post("https://agent.example.test/handoff").mock(return_value=Response(503))

    assert await handoff_service.deliver_handoff("delivery", settings) is False
    async with sessions() as db:
        pending = await db.get(HandoffDelivery, "delivery")
        assert pending.status == "PENDING"
        assert pending.attempt_count == 1

    route.mock(return_value=Response(204))
    assert await handoff_service.deliver_handoff("delivery", settings) is True
    async with sessions() as db:
        delivered = await db.get(HandoffDelivery, "delivery")
        assert delivered.status == "DELIVERED"
        assert delivered.delivered_at is not None
    await engine.dispose()
