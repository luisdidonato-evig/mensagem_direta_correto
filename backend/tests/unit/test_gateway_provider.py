import json

import pytest
import respx
from httpx import Response

from app.integrations.gateway.provider import GatewayProviderError, GatewayTemplateProvider


@pytest.mark.asyncio
@respx.mock
async def test_gateway_provider_sends_template_and_returns_delivery_id() -> None:
    route = respx.post("https://gateway.example.test/internal/v1/messages").mock(
        return_value=Response(202, json={"status": "queued", "delivery_id": "delivery-1"})
    )
    provider = GatewayTemplateProvider(
        base_url="https://gateway.example.test/",
        internal_key="internal-secret",
        tenant_id="11111111-1111-4111-8111-111111111111",
        channel_account_id="22222222-2222-4222-8222-222222222222",
    )

    result = await provider.send_template(
        recipient="+5511999990000",
        template_name="retomada",
        language="pt_BR",
        components=[{"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}],
        idempotency_key="campaign:campaign-1:recipient:recipient-1",
    )

    assert result == "delivery-1"
    request = route.calls[0].request
    assert request.headers["X-Internal-Key"] == "internal-secret"
    assert json.loads(request.content) == {
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "channel_account_id": "22222222-2222-4222-8222-222222222222",
        "source": "mensagem_direta",
        "recipient_id": "5511999990000",
        "message": {
            "kind": "template",
            "template_key": "retomada",
            "parameters": {"1": "Ana"},
        },
        "idempotency_key": "campaign:campaign-1:recipient:recipient-1",
    }


@pytest.mark.asyncio
@respx.mock
async def test_gateway_provider_rejects_response_without_queue_ack() -> None:
    respx.post("https://gateway.example.test/internal/v1/messages").mock(
        return_value=Response(202, json={"provider_message_id": "provider-1"})
    )
    provider = GatewayTemplateProvider(
        base_url="https://gateway.example.test",
        internal_key="secret",
        tenant_id="11111111-1111-4111-8111-111111111111",
        channel_account_id="22222222-2222-4222-8222-222222222222",
    )

    with pytest.raises(Exception, match="não confirmou enfileiramento"):
        await provider.send_template(
            recipient="5511999990000",
            template_name="retomada",
            language="pt_BR",
            components=[],
            idempotency_key="idempotency-1",
        )


def test_gateway_provider_rejects_invalid_tenant_and_unrenderable_language() -> None:
    with pytest.raises(GatewayProviderError, match="tenant_id"):
        GatewayTemplateProvider(
            base_url="https://gateway.example.test", internal_key="secret",
            tenant_id="default", channel_account_id="22222222-2222-4222-8222-222222222222",
        )
    provider = GatewayTemplateProvider(
        base_url="https://gateway.example.test", internal_key="secret",
        tenant_id="11111111-1111-4111-8111-111111111111",
        channel_account_id="22222222-2222-4222-8222-222222222222",
    )
    with pytest.raises(GatewayProviderError, match="pt_BR"):
        provider._build_request_body(
            recipient="5511999990000", template_name="retomada", language="en_US",
            components=[], idempotency_key="key",
        )
