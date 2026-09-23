import pytest
import respx
from httpx import Response

from app.integrations.gateway.provider import GatewayTemplateProvider


@pytest.mark.asyncio
@respx.mock
async def test_gateway_provider_sends_template_and_returns_delivery_id() -> None:
    route = respx.post("https://gateway.example.test/internal/v1/messages").mock(
        return_value=Response(202, json={"status": "queued", "delivery_id": "delivery-1"})
    )
    provider = GatewayTemplateProvider(
        base_url="https://gateway.example.test/",
        internal_key="internal-secret",
        channel_account_id="account-1",
    )

    result = await provider.send_template(
        recipient="+5511999990000",
        template_name="retomada",
        language="pt_BR",
        components=[
            {"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}
        ],
        idempotency_key="campaign:campaign-1:recipient:recipient-1",
    )

    assert result == "delivery-1"
    request = route.calls[0].request
    assert request.headers["X-Internal-Key"] == "internal-secret"
    assert request.json() == {
        "channel_account_id": "account-1",
        "recipient_id": "5511999990000",
        "message": {
            "kind": "template",
            "template_key": "retomada",
            "template_language": "pt_BR",
            "template_parameters": [
                {"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}
            ],
            "parameters": {"1": "Ana"},
        },
        "idempotency_key": "campaign:campaign-1:recipient:recipient-1",
    }


@pytest.mark.asyncio
@respx.mock
async def test_gateway_provider_returns_provider_message_id_when_present() -> None:
    respx.post("https://gateway.example.test/internal/v1/messages").mock(
        return_value=Response(202, json={"provider_message_id": "provider-1"})
    )
    provider = GatewayTemplateProvider(
        base_url="https://gateway.example.test", internal_key="secret"
    )

    result = await provider.send_template(
        recipient="5511999990000",
        template_name="retomada",
        language="pt_BR",
        components=[],
        idempotency_key="idempotency-1",
    )

    assert result == "provider-1"
