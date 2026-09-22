from unittest.mock import AsyncMock

import pytest
import respx
from httpx import Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.templates import create_draft
from app.core.database import Base
from app.integrations.meta.provider import (
    MetaGraphProvider,
    MetaProviderError,
    MockWhatsAppProvider,
)
from app.models import MessageTemplate, Organization
from app.schemas.templates import TemplateDraftCreate, TemplateTestSendRequest
from app.services.template_service import (
    build_company_meta_name,
    build_send_components,
    compile_components,
    infer_variable_schema,
    sync_templates,
)


def test_meta_template_name_is_prefixed_with_normalized_company_name() -> None:
    assert (
        build_company_meta_name("Crédito Fácil & Cia", "Documento Pendente")
        == "credito_facil_cia_documento_pendente"
    )
    assert (
        build_company_meta_name("Crédito Fácil & Cia", "credito_facil_cia_retorno")
        == "credito_facil_cia_retorno"
    )


@pytest.mark.asyncio
async def test_draft_uses_company_prefix_for_meta_name() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(Organization(id="org", name="Empresa Ágil"))
        await db.commit()
        draft = await create_draft(
            payload=TemplateDraftCreate(
                name="documento_pendente",
                display_name="Documento pendente",
                category="UTILITY",
                components=[{"type": "BODY", "text": "Documento pendente"}],
            ),
            db=db,
            organization_id="org",
            idempotency_key=None,
            _=None,  # type: ignore[arg-type]
        )

        assert draft.name == "empresa_agil_documento_pendente"

    await engine.dispose()
def test_compiles_aliases_to_stable_meta_positions() -> None:
    components = [{"type": "BODY", "text": "Oi, {{nome}}! Veja {{produto}}."}]
    schema = {
        "1": {"alias": "nome", "source": "contact.first_name"},
        "2": {"alias": "produto", "source": "deal.product_name"},
    }

    compiled = compile_components(components, schema)

    assert compiled[0]["text"] == "Oi, {{1}}! Veja {{2}}."
    assert components[0]["text"] == "Oi, {{nome}}! Veja {{produto}}."


def test_rejects_unmapped_alias() -> None:
    with pytest.raises(ValueError, match="produto"):
        compile_components(
            [{"type": "BODY", "text": "Veja {{produto}}"}],
            {"1": {"alias": "nome", "source": "contact.first_name"}},
        )


def test_builds_ordered_body_parameters_for_send() -> None:
    schema = {
        "2": {"alias": "produto", "required": True},
        "1": {"alias": "nome", "required": True},
    }

    result = build_send_components(schema, {"produto": "Crédito", "nome": "Ana"})

    assert result == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Ana"},
                {"type": "text", "text": "Crédito"},
            ],
        }
    ]


def test_rejects_missing_required_send_parameter() -> None:
    with pytest.raises(ValueError, match="nome"):
        build_send_components({"1": {"alias": "nome", "required": True}}, {})


def test_infers_sources_for_synced_meta_template() -> None:
    schema = infer_variable_schema([{"type": "BODY", "text": "Oi {{1}}, veja {{2}} e use {{3}}"}])

    assert schema["1"]["source"] == "contact.first_name"
    assert schema["2"]["source"] == "deal.product_name"
    assert schema["3"]["source"] == "contact.attributes.var_3"


def test_rejects_header_alias_until_header_parameters_are_supported() -> None:
    with pytest.raises(ValueError, match="título"):
        compile_components(
            [{"type": "HEADER", "text": "Olá {{nome}}"}, {"type": "BODY", "text": "Oi"}],
            {"1": {"alias": "nome", "source": "contact.first_name"}},
        )


def test_test_send_normalizes_brazilian_phone_and_requires_explicit_opt_in() -> None:
    payload = TemplateTestSendRequest(
        phone_e164="(11) 99999-9999",
        variables={"nome": "Ana"},
        confirm_recipient_opt_in=True,
    )
    assert payload.phone_e164 == "+5511999999999"
    with pytest.raises(ValidationError, match="autorizou"):
        TemplateTestSendRequest(
            phone_e164="+5511999999999",
            variables={"nome": "Ana"},
        )


@pytest.mark.asyncio
async def test_meta_error_surfaces_actionable_user_message() -> None:
    provider = MetaGraphProvider(
        access_token="token",
        waba_id="waba",
        phone_number_id="phone",
    )
    with respx.mock:
        respx.get("https://graph.facebook.com/v23.0/waba/message_templates").mock(
            return_value=Response(
                400,
                json={
                    "error": {
                        "message": "Invalid parameter",
                        "error_user_msg": "Token expirado; gere um token novo",
                        "code": 190,
                    }
                },
            )
        )
        with pytest.raises(MetaProviderError, match="Token expirado"):
            await provider.list_templates()


@pytest.mark.asyncio
async def test_same_meta_template_can_be_synced_for_two_organizations() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([Organization(id="one", name="One"), Organization(id="two", name="Two")])
        await db.commit()
        provider = MockWhatsAppProvider()
        await sync_templates(db, provider, "one")
        await sync_templates(db, provider, "two")
        count = await db.scalar(select(func.count(MessageTemplate.id)))

    assert count == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_tracks_effective_and_announced_category_changes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(Organization(id="org", name="Org"))
        await db.commit()
        provider = MockWhatsAppProvider()
        await sync_templates(db, provider, "org")
        provider.list_templates = AsyncMock(
            return_value=[
                {
                    "id": "mock-approved-template",
                    "name": "retomada_simulacao",
                    "language": "pt_BR",
                    "category": "MARKETING",
                    "correct_category": "UTILITY",
                    "status": "APPROVED",
                    "components": [{"type": "BODY", "text": "Oi {{1}}"}],
                }
            ]
        )
        await sync_templates(db, provider, "org")
        template = await db.scalar(select(MessageTemplate))

        assert template is not None
        assert template.requested_category.value == "UTILITY"
        assert template.category.value == "MARKETING"
        assert template.correct_category.value == "UTILITY"
        assert template.category_changed_at is not None

    await engine.dispose()
