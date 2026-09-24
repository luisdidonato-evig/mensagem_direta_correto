from typing import Any, Protocol

from app.core.config import Settings
from app.integrations.gateway.provider import (
    GatewayProviderError,
    MiddlewareTemplateDispatchProvider,
)


class TemplateDispatchProvider(Protocol):
    async def send_template(
        self,
        *,
        recipient: str,
        template_name: str,
        language: str,
        components: list[dict[str, Any]],
        idempotency_key: str,
    ) -> str: ...


def build_campaign_provider(
    settings: Settings,
    connection: Any,
) -> TemplateDispatchProvider:
    if connection is None or not connection.channel_account_id:
        raise GatewayProviderError(
            "Tenant sem channel_account_id configurado", code="missing_channel_account"
        )
    return MiddlewareTemplateDispatchProvider(
        base_url=settings.gateway_url,
        internal_key=settings.gateway_internal_key,
        tenant_id=connection.organization_id,
        channel_account_id=connection.channel_account_id,
    )
