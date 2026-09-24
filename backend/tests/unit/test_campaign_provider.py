from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations.campaign_provider import build_campaign_provider
from app.integrations.gateway.provider import GatewayTemplateProvider


def test_campaign_provider_uses_gateway_when_configured() -> None:
    provider = build_campaign_provider(
        Settings(
            gateway_url="https://gateway.example.test",
            gateway_internal_key="secret",
        ),
        connection=SimpleNamespace(
            organization_id="11111111-1111-4111-8111-111111111111",
            channel_account_id="22222222-2222-4222-8222-222222222222",
        ),
    )

    assert isinstance(provider, GatewayTemplateProvider)


def test_campaign_provider_requires_tenant_channel() -> None:
    with pytest.raises(Exception, match="channel_account_id"):
        build_campaign_provider(Settings(meta_mode="mock"), connection=None)
