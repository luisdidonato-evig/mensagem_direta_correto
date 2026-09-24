import uuid
from typing import Any

import httpx

GATEWAY_TIMEOUT_SECONDS = 30.0


class GatewayProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "gateway_error", transient: bool = False):
        super().__init__(message)
        self.code = code
        self.transient = transient


class MiddlewareTemplateDispatchProvider:
    def __init__(
        self,
        *,
        base_url: str,
        internal_key: str,
        tenant_id: str,
        channel_account_id: str,
        timeout: float = GATEWAY_TIMEOUT_SECONDS,
    ) -> None:
        if not base_url.strip():
            raise GatewayProviderError("GATEWAY_URL é obrigatória", code="missing_gateway_url")
        if not internal_key.strip():
            raise GatewayProviderError(
                "GATEWAY_INTERNAL_KEY é obrigatória", code="missing_gateway_key"
            )
        for name, value in {
            "tenant_id": tenant_id,
            "channel_account_id": channel_account_id,
        }.items():
            try:
                uuid.UUID(value)
            except (ValueError, TypeError) as exc:
                raise GatewayProviderError(
                    f"{name} deve ser UUID válido", code=f"invalid_{name}"
                ) from exc
        self.base_url = base_url.rstrip("/")
        self.internal_key = internal_key
        self.tenant_id = tenant_id
        self.channel_account_id = channel_account_id.strip()
        self.timeout = timeout

    async def send_template(
        self,
        *,
        recipient: str,
        template_name: str,
        language: str,
        components: list[dict[str, Any]],
        idempotency_key: str,
    ) -> str:
        body = self._build_request_body(
            recipient=recipient,
            template_name=template_name,
            language=language,
            components=components,
            idempotency_key=idempotency_key,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/internal/v1/messages",
                    headers={
                        "X-Internal-Key": self.internal_key,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise GatewayProviderError(
                "Falha de comunicação com gateway",
                code="gateway_unavailable",
                transient=True,
            ) from exc

        if not response.is_success:
            raise self._response_error(response)
        return self._extract_delivery_id(response)

    def _build_request_body(
        self,
        *,
        recipient: str,
        template_name: str,
        language: str,
        components: list[dict[str, Any]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if language != "pt_BR":
            # Current middleware renderer hardcodes pt_BR; refuse silent language substitution.
            raise GatewayProviderError(
                "Middleware só renderiza pt_BR atualmente", code="unsupported_language"
            )
        message: dict[str, Any] = {
            "kind": "template",
            "template_key": template_name,
        }
        if components:
            message["parameters"] = _components_to_parameters(components)

        body: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "recipient_id": recipient.lstrip("+"),
            "message": message,
            "idempotency_key": idempotency_key,
            "source": "mensagem_direta",
            "channel_account_id": self.channel_account_id,
        }
        return body

    @staticmethod
    def _response_error(response: httpx.Response) -> GatewayProviderError:
        detail = response.text or "Resposta inválida do gateway"
        try:
            payload = response.json()
            detail = str(payload.get("error") or payload.get("message") or detail)
        except ValueError:
            pass
        return GatewayProviderError(
            detail,
            code=f"gateway_http_{response.status_code}",
            transient=response.status_code == 429 or response.status_code >= 500,
        )

    @staticmethod
    def _extract_delivery_id(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayProviderError(
                "Resposta do gateway não é JSON", code="invalid_gateway_response", transient=True
            ) from exc
        if response.status_code != 202 or payload.get("status") != "queued":
            raise GatewayProviderError(
                "Gateway não confirmou enfileiramento",
                code="invalid_gateway_response",
                transient=True,
            )
        delivery_id = payload.get("delivery_id")
        if not delivery_id:
            raise GatewayProviderError(
                "Resposta do gateway sem identificador de entrega",
                code="invalid_gateway_response",
                transient=True,
            )
        return str(delivery_id)


def _components_to_parameters(components: list[dict[str, Any]]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    position = 1
    for component in components:
        if str(component.get("type", "")).lower() != "body":
            if component.get("parameters"):
                raise GatewayProviderError(
                    "Middleware suporta apenas parâmetros BODY", code="unsupported_components"
                )
            continue
        for parameter in component.get("parameters", []):
            if position > 9:
                raise GatewayProviderError(
                    "Middleware suporta até 9 parâmetros posicionais", code="unsupported_components"
                )
            key = str(parameter.get("parameter_name") or position)
            value = _parameter_value(parameter)
            if value is not None:
                parameters[key] = str(value)
            position += 1
    return parameters


def _parameter_value(parameter: dict[str, Any]) -> Any:
    parameter_type = parameter.get("type")
    if parameter_type == "text":
        return parameter.get("text")
    return parameter.get(parameter_type) or parameter.get("text")


GatewayTemplateProvider = MiddlewareTemplateDispatchProvider
