from collections.abc import Awaitable, Callable

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import IdempotencyRecord


def build_idempotency_id(scope: str, namespace: str, key: str) -> str:
    return f"{scope}:{namespace}:{key}"


async def run_idempotent[T](
    db: AsyncSession,
    *,
    scope: str,
    namespace: str,
    key: str | None,
    status_code: int,
    handler: Callable[[], Awaitable[T]],
) -> T | dict:
    """Run `handler` once per Idempotency-Key; replay the stored result after.

    `namespace` scopes the key to its owner (an organization for endpoints that
    create a resource, or the resource itself for endpoints that act on one
    that already exists) so the same key value can't collide across owners.
    Without a key, every call runs `handler` fresh — the header is honored
    when present, not required (see PLANEJAMENTO.md §8).
    """
    if not key:
        return await handler()

    record_id = build_idempotency_id(scope, namespace, key)
    existing = await db.get(IdempotencyRecord, record_id)
    if existing is not None:
        return existing.response_body

    result = await handler()
    db.add(
        IdempotencyRecord(
            id=record_id,
            status_code=status_code,
            response_body=jsonable_encoder(result),
        )
    )
    await db.commit()
    return result
