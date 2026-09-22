import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.messaging import ContactMessagingState

MAX_CONSECUTIVE_TEMPLATE_SENDS = 3


async def get_contact_messaging_state(
    db: AsyncSession,
    organization_id: str,
    phone_hash: str,
    *,
    for_update: bool = False,
) -> ContactMessagingState | None:
    statement = select(ContactMessagingState).where(
        ContactMessagingState.organization_id == organization_id,
        ContactMessagingState.phone_hash == phone_hash,
    )
    if for_update:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def _locked_state(
    db: AsyncSession, organization_id: str, phone_hash: str
) -> ContactMessagingState:
    state = await get_contact_messaging_state(
        db, organization_id, phone_hash, for_update=True
    )
    if state is not None:
        return state
    values = {
        "id": str(uuid.uuid4()),
        "organization_id": organization_id,
        "phone_hash": phone_hash,
        "consecutive_template_sends": 0,
        "reserved_template_sends": 0,
        "updated_at": datetime.now(UTC),
    }
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "postgresql":
        statement = postgresql_insert(ContactMessagingState).values(**values)
        await db.execute(
            statement.on_conflict_do_nothing(
                index_elements=["organization_id", "phone_hash"]
            )
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(ContactMessagingState).values(**values)
        await db.execute(
            statement.on_conflict_do_nothing(
                index_elements=["organization_id", "phone_hash"]
            )
        )
    else:
        db.add(ContactMessagingState(**values))
        await db.flush()
    state = await get_contact_messaging_state(
        db, organization_id, phone_hash, for_update=True
    )
    if state is None:
        raise RuntimeError("Falha ao criar estado de frequência do contato")
    return state


async def reserve_template_send(
    db: AsyncSession, organization_id: str, phone_hash: str
) -> tuple[bool, int]:
    state = await _locked_state(db, organization_id, phone_hash)
    used = state.consecutive_template_sends + state.reserved_template_sends
    if used >= MAX_CONSECUTIVE_TEMPLATE_SENDS:
        return False, used
    state.reserved_template_sends += 1
    return True, used + 1


async def confirm_template_send(
    db: AsyncSession, organization_id: str, phone_hash: str
) -> ContactMessagingState:
    state = await _locked_state(db, organization_id, phone_hash)
    state.reserved_template_sends = max(0, state.reserved_template_sends - 1)
    state.consecutive_template_sends += 1
    state.last_outbound_at = datetime.now(UTC)
    return state


async def release_template_send(
    db: AsyncSession, organization_id: str, phone_hash: str
) -> ContactMessagingState:
    state = await _locked_state(db, organization_id, phone_hash)
    state.reserved_template_sends = max(0, state.reserved_template_sends - 1)
    return state


async def record_inbound_message(
    db: AsyncSession, organization_id: str, phone_hash: str
) -> tuple[ContactMessagingState, int]:
    state = await _locked_state(db, organization_id, phone_hash)
    previous_count = state.consecutive_template_sends
    state.consecutive_template_sends = 0
    state.reserved_template_sends = 0
    state.last_inbound_at = datetime.now(UTC)
    return state, previous_count


async def blocked_phone_hashes(
    db: AsyncSession, organization_id: str, phone_hashes: set[str]
) -> set[str]:
    if not phone_hashes:
        return set()
    rows = await db.scalars(
        select(ContactMessagingState.phone_hash).where(
            ContactMessagingState.organization_id == organization_id,
            ContactMessagingState.phone_hash.in_(phone_hashes),
            ContactMessagingState.consecutive_template_sends
            + ContactMessagingState.reserved_template_sends
            >= MAX_CONSECUTIVE_TEMPLATE_SENDS,
        )
    )
    return set(rows)
