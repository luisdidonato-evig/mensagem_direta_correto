from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def create_schema() -> None:
    from app.models import (  # noqa: F401
        Campaign,
        CampaignRecipient,
        ContactMessagingState,
        HandoffDelivery,
        IdempotencyRecord,
        MessageTemplate,
        Organization,
        WabaConnection,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    from app.services.organization_service import ensure_default_organization

    async with SessionLocal() as session:
        await ensure_default_organization(session, settings)
