import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.meta.provider import WhatsAppProvider
from app.models.template import MessageTemplate, TemplateCategory, TemplateStatus

ALIAS_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
ALIAS_POSITION_PATTERN = re.compile(r"{{\s*(\d+)\s*}}")


def infer_variable_schema(components: list[dict]) -> dict:
    """Build a usable schema for templates imported from Meta.

    Meta returns numbered placeholders but not the CRM source. Positions one
    and two use the product defaults; additional values come from attributes.
    Operators can override these sources in campaign.variable_mapping.
    """
    positions: set[int] = set()
    for component in components:
        if str(component.get("type", "")).upper() != "BODY":
            continue
        positions.update(
            int(value) for value in ALIAS_POSITION_PATTERN.findall(str(component.get("text", "")))
        )
    schema: dict[str, dict] = {}
    for position in sorted(positions):
        alias = "nome" if position == 1 else "produto" if position == 2 else f"var_{position}"
        source = (
            "contact.first_name"
            if position == 1
            else "deal.product_name"
            if position == 2
            else f"contact.attributes.var_{position}"
        )
        schema[str(position)] = {"alias": alias, "source": source, "required": True}
    return schema


def compile_components(components: list[dict], variable_schema: dict) -> list[dict]:
    alias_to_position = {
        value["alias"]: str(position) for position, value in variable_schema.items()
    }
    compiled: list[dict] = []
    for component in components:
        item = dict(component)
        if str(item.get("type", "")).upper() == "HEADER" and ALIAS_PATTERN.search(
            str(item.get("text", ""))
        ):
            raise ValueError("Variáveis em título ainda não são suportadas; use-as no corpo")
        if "text" in item:
            missing: set[str] = set()

            def replace(match: re.Match[str], missing_aliases: set[str] = missing) -> str:
                alias = match.group(1)
                position = alias_to_position.get(alias)
                if position is None:
                    missing_aliases.add(alias)
                    return match.group(0)
                return "{{" + position + "}}"

            item["text"] = ALIAS_PATTERN.sub(replace, str(item["text"]))
            if missing:
                raise ValueError(f"Variáveis sem mapeamento: {', '.join(sorted(missing))}")
        compiled.append(item)
    return compiled


def build_variable_examples(components: list[dict], variable_schema: dict) -> list[dict]:
    """Fill in `example` for components with unexampled {{n}} placeholders.

    Meta rejects template submissions that reference a numbered variable
    without a matching example, so any BODY/HEADER text edited by hand
    (rather than coming from a preset that already ships its own example)
    needs one synthesized before it reaches the Graph API.
    """
    if not variable_schema:
        return components
    result: list[dict] = []
    for component in components:
        item = dict(component)
        text = item.get("text")
        component_type = str(item.get("type", "")).upper()
        if text and "example" not in item and component_type in {"BODY", "HEADER"}:
            positions = ALIAS_POSITION_PATTERN.findall(text)
            values = [
                _example_value(variable_schema[position]["alias"])
                for position in positions
                if position in variable_schema
            ]
            if values:
                if component_type == "HEADER":
                    item["example"] = {"header_text": values[:1]}
                else:
                    item["example"] = {"body_text": [values]}
        result.append(item)
    return result


def _example_value(alias: str) -> str:
    return alias.replace("_", " ").strip().title() or "Exemplo"


def build_send_components(variable_schema: dict, variables: dict) -> list[dict]:
    if not variable_schema:
        return []
    parameters: list[dict[str, str]] = []
    missing: list[str] = []
    for position in sorted(variable_schema, key=int):
        definition = variable_schema[position]
        alias = definition["alias"]
        value = variables.get(alias)
        if value is None or value == "":
            if definition.get("required", True):
                missing.append(alias)
            continue
        parameters.append({"type": "text", "text": str(value)})
    if missing:
        raise ValueError(f"Variáveis obrigatórias ausentes: {', '.join(missing)}")
    return [{"type": "body", "parameters": parameters}] if parameters else []


async def sync_templates(
    db: AsyncSession, provider: WhatsAppProvider, organization_id: str
) -> tuple[int, int]:
    created = 0
    updated = 0
    for remote in await provider.list_templates():
        statement = select(MessageTemplate).where(
            MessageTemplate.organization_id == organization_id,
            MessageTemplate.meta_template_id == str(remote["id"]),
            MessageTemplate.language == remote.get("language", "pt_BR"),
        )
        template = await db.scalar(statement)
        if template is None:
            components = remote.get("components", [])
            template = MessageTemplate(
                organization_id=organization_id,
                meta_template_id=str(remote["id"]),
                name=remote["name"],
                display_name=remote["name"].replace("_", " ").title(),
                language=remote.get("language", "pt_BR"),
                category=TemplateCategory(remote.get("category", "MARKETING")),
                status=TemplateStatus(remote.get("status", "PENDING")),
                components=components,
                variable_schema=infer_variable_schema(components),
                source="META",
            )
            db.add(template)
            created += 1
        else:
            template.category = TemplateCategory(remote.get("category", template.category.value))
            template.status = TemplateStatus(remote.get("status", template.status.value))
            template.components = remote.get("components", template.components)
            template.variable_schema = infer_variable_schema(template.components)
            template.rejection_reason = remote.get("rejected_reason")
            updated += 1
    await db.commit()
    return created, updated
