from app.core.config import Settings
from app.integrations.campaign_provider import MetaCampaignProviderAdapter, build_campaign_provider
from app.integrations.gateway.provider import GatewayTemplateProvider
from app.integrations.meta.provider import MockWhatsAppProvider


def test_campaign_provider_uses_gateway_when_configured() -> None:
    provider = build_campaign_provider(
        Settings(
            gateway_url="https://gateway.example.test",
            gateway_internal_key="secret",
        ),
        connection=None,
    )

    assert isinstance(provider, GatewayTemplateProvider)


def test_campaign_provider_keeps_meta_mock_when_gateway_is_disabled() -> None:
    provider = build_campaign_provider(Settings(meta_mode="mock"), connection=None)

    assert isinstance(provider, MetaCampaignProviderAdapter)
    assert isinstance(provider.provider, MockWhatsAppProvider)
