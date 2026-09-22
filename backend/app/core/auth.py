import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class Principal:
    role: str
    organization_id: str | None


def _configured_tokens(settings: Settings) -> list[tuple[str, Principal]]:
    configured: list[tuple[str, Principal]] = []
    for item in settings.auth_tokens.split(","):
        if not item.strip():
            continue
        parts = item.strip().split(":", 2)
        if len(parts) != 3 or parts[1] not in {"ADMIN", "OPERATOR", "VIEWER"}:
            raise RuntimeError("AUTH_TOKENS possui uma entrada inválida")
        token, role, organization_id = parts
        configured.append(
            (token, Principal(role, None if organization_id == "*" else organization_id))
        )
    return configured


async def get_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if not settings.auth_enabled:
        return Principal("ADMIN", None)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token de acesso ausente")
    supplied = authorization.removeprefix("Bearer ").strip()
    for token, principal in _configured_tokens(settings):
        if hmac.compare_digest(supplied, token):
            return principal
    raise HTTPException(status_code=401, detail="Token de acesso inválido")


def require_roles(*roles: str):
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="Permissão insuficiente")
        return principal

    return dependency


require_operator = require_roles("ADMIN", "OPERATOR")
require_admin = require_roles("ADMIN")
