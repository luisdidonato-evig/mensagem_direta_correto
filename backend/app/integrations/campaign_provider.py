from typing import Any, Protocol

from app.core.config import Settings
from app.integrations.gateway.provider import GatewayTemplateProvider
from app.integrations.meta.provider import WhatsAppProvider, build_provider_for_connection


class CampaignProvider(Protocol):
    async def send_template(
        self,
        *,
        recipient: str,
        template_name: str,
        language: str,
        components: list[dict[str, Any]],
        idempotency_key: str,
    ) -> str: ...


class MetaCampaignProviderAdapter:
    def __init__(self, provider: WhatsAppProvider) -> None:
        self.provider = provider

    async def send_template(
        self,
        *,
        recipient: str,
        template_name: str,
        language: str,
        components: list[dict[str, Any]],
        idempotency_key: str,
    ) -> str:
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language},
        }
        if components:
            template["components"] = components
        return await self.provider.send_template(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient.lstrip("+"),
                "type": "template",
                "template": template,
            }
        )


def build_campaign_provider(
    settings: Settings,
    connection: Any,
) -> CampaignProvider:
    if settings.gateway_dispatch_enabled:
        return GatewayTemplateProvider(
            base_url=settings.gateway_url,
            internal_key=settings.gateway_internal_key,
            channel_account_id=settings.gateway_channel_account_id,
        )
    return MetaCampaignProviderAdapter(
        build_provider_for_connection(settings.meta_mode, connection, settings.meta_graph_version)
    )
