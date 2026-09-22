import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import Organization, WabaConnection


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
