import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.services.frequency_service import (
    confirm_template_send,
    record_inbound_message,
    release_template_send,
    reserve_template_send,
)


@pytest.mark.asyncio
async def test_blocks_fourth_template_until_contact_replies() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        for expected_count in (1, 2, 3):
            allowed, count = await reserve_template_send(db, "org", "phone-hash")
            assert allowed is True
            assert count == expected_count
            state = await confirm_template_send(db, "org", "phone-hash")
            assert state.consecutive_template_sends == expected_count
            await db.commit()

        allowed, count = await reserve_template_send(db, "org", "phone-hash")
        assert allowed is False
        assert count == 3

        _, previous_count = await record_inbound_message(db, "org", "phone-hash")
        assert previous_count == 3
        allowed, count = await reserve_template_send(db, "org", "phone-hash")
        assert allowed is True
        assert count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_send_releases_reserved_slot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        allowed, _ = await reserve_template_send(db, "org", "phone-hash")
        assert allowed is True
        state = await release_template_send(db, "org", "phone-hash")
        assert state.consecutive_template_sends == 0
        assert state.reserved_template_sends == 0

    await engine.dispose()
