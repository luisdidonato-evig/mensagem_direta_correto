import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import httpx

from app.core.crypto import decrypt_token

if TYPE_CHECKING:
    from app.models.organization import WabaConnection


class MetaProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "meta_error", transient: bool = False):
        super().__init__(message)
        self.code = code
        self.transient = transient


class WhatsAppProvider(ABC):
    @abstractmethod
    async def list_templates(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def create_template(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    async def delete_template(self, name: str) -> None: ...

    @abstractmethod
    async def send_template(self, payload: dict[str, Any]) -> str: ...


class MockWhatsAppProvider(WhatsAppProvider):
    async def list_templates(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "mock-approved-template",
                "name": "simulacao_parada",
                "language": "pt_BR",
                "category": "UTILITY",
                "status": "APPROVED",
                "components": [
                    {
                        "type": "BODY",
                        "text": "Oi, {{1}}! Sua simulação de {{2}} ficou guardada aqui.",
                    },
                    {
                        "type": "FOOTER",
                        "text": "Responda SAIR para não receber mais mensagens.",
                    },
                    {
                        "type": "BUTTONS",
                        "buttons": [{"type": "QUICK_REPLY", "text": "Retomar simulação"}],
                    },
                ],
            }
        ]

    async def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"mock-{uuid.uuid4()}",
            "status": "PENDING",
            "category": payload["category"],
        }

    async def delete_template(self, name: str) -> None:
        return None

    async def send_template(self, payload: dict[str, Any]) -> str:
        return f"wamid.mock.{uuid.uuid4()}"


class MetaGraphProvider(WhatsAppProvider):
    def __init__(
        self,
        *,
        access_token: str,
        waba_id: str,
        phone_number_id: str,
        graph_version: str = "v23.0",
    ):
        missing = [
            name
            for name, value in {
                "access_token": access_token,
                "waba_id": waba_id,
                "phone_number_id": phone_number_id,
            }.items()
            if not value
        ]
        if missing:
            raise MetaProviderError(
                f"Conexão WABA incompleta: {', '.join(missing)}", code="incomplete_connection"
            )
        self.access_token = access_token
        self.waba_id = waba_id
        self.phone_number_id = phone_number_id
        self.base_url = f"https://graph.facebook.com/{graph_version}"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, headers=self.headers, **kwargs)
        if response.is_success:
            return response.json()
        detail = response.text
        try:
            error = response.json().get("error", {})
            detail = (
                error.get("error_user_msg")
                or error.get("error_data", {}).get("details")
                or error.get("message", detail)
            )
            code = str(error.get("code", response.status_code))
        except ValueError:
            code = str(response.status_code)
        raise MetaProviderError(
            detail,
            code=code,
            transient=response.status_code == 429 or response.status_code >= 500,
        )

    async def list_templates(self) -> list[dict[str, Any]]:
        url = f"{self.base_url}/{self.waba_id}/message_templates"
        templates: list[dict[str, Any]] = []
        params: dict[str, str] | None = {
            "fields": (
                "id,name,language,category,correct_category,status,components,rejected_reason"
            ),
            "limit": "100",
        }
        while url:
            body = await self._request("GET", url, params=params)
            templates.extend(body.get("data", []))
            url = body.get("paging", {}).get("next", "")
            params = None
        return templates

    async def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{self.waba_id}/message_templates"
        return await self._request("POST", url, json=payload)

    async def delete_template(self, name: str) -> None:
        url = f"{self.base_url}/{self.waba_id}/message_templates"
        await self._request("DELETE", url, params={"name": name})

    async def send_template(self, payload: dict[str, Any]) -> str:
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        body = await self._request("POST", url, json=payload)
        try:
            return str(body["messages"][0]["id"])
        except (KeyError, IndexError) as exc:
            raise MetaProviderError("Resposta da Meta sem wamid", code="invalid_response") from exc


def build_provider_for_connection(
    meta_mode: str,
    connection: "WabaConnection | None",
    graph_version_fallback: str = "v23.0",
) -> WhatsAppProvider:
    """Provider scoped to one organization's WABA connection."""
    if meta_mode != "live":
        return MockWhatsAppProvider()
    if connection is None:
        raise MetaProviderError(
            "Organização sem conexão WABA configurada", code="missing_connection"
        )
    access_token = decrypt_token(connection.access_token) if connection.access_token else None
    if connection.access_token and access_token is None:
        raise MetaProviderError(
            "Token da conexão WABA corrompido ou ilegível — reconfigure a conexão",
            code="undecryptable_token",
        )
    return MetaGraphProvider(
        access_token=access_token or "",
        waba_id=connection.waba_id or "",
        phone_number_id=connection.phone_number_id or "",
        graph_version=connection.api_version or graph_version_fallback,
    )
