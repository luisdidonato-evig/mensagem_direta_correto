from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings
from app.services.audience_service import ContactCandidate, demo_contacts


class AudienceSourceError(RuntimeError):
    pass


class AudienceSource(ABC):
    @abstractmethod
    async def list_candidates(
        self, organization_id: str, product: str | None
    ) -> list[ContactCandidate]: ...


class MockAudienceSource(AudienceSource):
    async def list_candidates(
        self, organization_id: str, product: str | None
    ) -> list[ContactCandidate]:
        return demo_contacts()


class HttpAudienceSource(AudienceSource):
    def __init__(self, url: str, token: str, timeout: float) -> None:
        if not url:
            raise AudienceSourceError("AUDIENCE_API_URL é obrigatória no modo http")
        self.url = url
        self.token = token
        self.timeout = timeout

    async def list_candidates(
        self, organization_id: str, product: str | None
    ) -> list[ContactCandidate]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    self.url,
                    params={"organization_id": organization_id, "product": product or ""},
                    headers=headers,
                )
                response.raise_for_status()
                body: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AudienceSourceError(f"Falha ao consultar a fonte comercial: {exc}") from exc

        rows = body.get("items", body) if isinstance(body, dict) else body
        try:
            return TypeAdapter(list[ContactCandidate]).validate_python(rows)
        except ValidationError as exc:
            raise AudienceSourceError(
                "Resposta inválida da fonte comercial; consulte docs/audience-api.md"
            ) from exc


def build_audience_source(settings: Settings) -> AudienceSource:
    if settings.audience_mode == "http":
        return HttpAudienceSource(
            settings.audience_api_url,
            settings.audience_api_token,
            settings.audience_timeout_seconds,
        )
    return MockAudienceSource()
