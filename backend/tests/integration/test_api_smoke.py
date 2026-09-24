import json

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.main import app
from app.models import MessageTemplate, Organization, WabaConnection
from app.models.template import TemplateCategory, TemplateStatus


@pytest.mark.asyncio
async def test_audience_preview_works_through_http_api() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(Organization(id="default", name="Teste"))
        session.add(WabaConnection(id="default", organization_id="default"))
        await session.commit()

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/audiences/preview?organization_id=default",
                json={
                    "product": "Crédito",
                    "rules": {
                        "eligible_not_closed": True,
                        "no_response_days": 7,
                        "fewer_than_direct_messages": 3,
                    },
                },
            )
            missing = await client.post(
                "/api/v1/compliance/opt-outs?organization_id=missing",
                json={
                    "phone": "+5511999999999",
                    "scope": "ALL",
                    "source": "test",
                },
            )
        assert response.status_code == 200
        assert response.json()["eligible"] == 2
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_template_test_send_requires_unique_retry_key_and_tenant_channel() -> None:
    tenant_id = "11111111-1111-4111-8111-111111111111"
    channel_id = "22222222-2222-4222-8222-222222222222"
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all(
            [
                Organization(id=tenant_id, name="Teste"),
                WabaConnection(organization_id=tenant_id, channel_account_id=channel_id),
                MessageTemplate(
                    id="template-1",
                    organization_id=tenant_id,
                    meta_template_id="remote-1",
                    name="teste",
                    display_name="Teste",
                    language="pt_BR",
                    category=TemplateCategory.UTILITY,
                    requested_category=TemplateCategory.UTILITY,
                    status=TemplateStatus.APPROVED,
                    components=[{"type": "BODY", "text": "Oi"}],
                    variable_schema={},
                ),
            ]
        )
        await db.commit()

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        gateway_url="https://gateway.example.test", gateway_internal_key="secret"
    )
    try:
        with respx.mock:
            route = respx.post("https://gateway.example.test/internal/v1/messages").mock(
                return_value=Response(202, json={"status": "queued", "delivery_id": "delivery-1"})
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                url = f"/api/v1/templates/template-1/test-send?organization_id={tenant_id}"
                payload = {"phone_e164": "+5511999990000", "confirm_recipient_opt_in": True}
                missing_key = await client.post(url, json=payload)
                first = await client.post(
                    url, json=payload, headers={"Idempotency-Key": "attempt-1"}
                )
                second = await client.post(
                    url, json=payload, headers={"Idempotency-Key": "attempt-2"}
                )
                replay = await client.post(
                    url, json=payload, headers={"Idempotency-Key": "attempt-1"}
                )
            assert missing_key.status_code == 422
            assert first.status_code == second.status_code == replay.status_code == 200
            assert first.json()["delivery_id"] == "delivery-1"
            assert replay.json() == first.json()
            assert len(route.calls) == 2
            bodies = [json.loads(call.request.content) for call in route.calls]
            assert bodies[0]["idempotency_key"].startswith("template-test:")
            assert bodies[0]["idempotency_key"] != bodies[1]["idempotency_key"]
            assert all(body["tenant_id"] == tenant_id for body in bodies)
            assert all(body["channel_account_id"] == channel_id for body in bodies)
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
