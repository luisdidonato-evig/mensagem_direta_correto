import pytest
from fastapi import HTTPException

from app.core.auth import get_principal
from app.core.config import Settings


@pytest.mark.asyncio
async def test_static_bearer_token_resolves_role_and_tenant() -> None:
    settings = Settings(
        auth_enabled=True,
        auth_tokens="secret:OPERATOR:org-1,root:ADMIN:*",
    )

    principal = await get_principal("Bearer secret", settings)

    assert principal.role == "OPERATOR"
    assert principal.organization_id == "org-1"


@pytest.mark.asyncio
async def test_invalid_bearer_token_is_rejected() -> None:
    settings = Settings(auth_enabled=True, auth_tokens="secret:VIEWER:org-1")

    with pytest.raises(HTTPException) as error:
        await get_principal("Bearer wrong", settings)

    assert error.value.status_code == 401
