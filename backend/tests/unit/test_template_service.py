import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.integrations.meta.provider import MockWhatsAppProvider
from app.models import MessageTemplate, Organization
from app.services.template_service import (
    build_send_components,
    compile_components,
    infer_variable_schema,
    sync_templates,
)


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
