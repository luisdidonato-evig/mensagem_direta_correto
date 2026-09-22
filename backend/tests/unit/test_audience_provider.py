import pytest
import respx
from httpx import Response

from app.core.config import Settings
from app.integrations.audience.provider import HttpAudienceSource, build_audience_source


@pytest.mark.asyncio
@respx.mock
async def test_http_source_sends_tenant_and_parses_candidates() -> None:
    route = respx.get("https://crm.example.test/audience").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "contact-1",
                        "phone_e164": "+5511999990000",
                        "first_name": "Ana",
                        "product": "Crédito",
                        "eligible": True,
                        "deal_status": "open",
                        "last_customer_reply_at": None,
                        "direct_messages_90d": 0,
                        "has_consent": True,
                    }
                ]
            },
        )
    )
    source = HttpAudienceSource("https://crm.example.test/audience", "token", 2)

    candidates = await source.list_candidates("org-1", "Crédito")

    assert candidates[0].id == "contact-1"
    assert route.calls[0].request.url.params["organization_id"] == "org-1"
    assert route.calls[0].request.headers["Authorization"] == "Bearer token"


def test_builder_keeps_mock_as_explicit_development_mode() -> None:
    source = build_audience_source(Settings(audience_mode="mock"))
    assert source.__class__.__name__ == "MockAudienceSource"
