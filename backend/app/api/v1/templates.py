import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_meta_provider, get_organization_id
from app.core.auth import Principal, require_admin, require_operator
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.privacy import hash_phone
from app.integrations.campaign_provider import build_campaign_provider
from app.integrations.gateway.provider import GatewayProviderError
from app.integrations.meta.provider import (
    MetaProviderError,
    WhatsAppProvider,
    build_provider_for_connection,
)
from app.models.campaign import Campaign
from app.models.organization import Organization
from app.models.template import MessageTemplate, TemplateCategory, TemplateStatus
from app.schemas.campaigns import AudienceRules
from app.schemas.templates import (
    SyncResult,
    TemplateDraftCreate,
    TemplateDraftUpdate,
    TemplatePreset,
    TemplateRead,
    TemplateTestSendRequest,
    TemplateTestSendResult,
)
from app.services.audience_service import preview_audience
from app.services.audit_service import add_audit
from app.services.frequency_service import (
    confirm_template_send,
    reserve_template_send,
)
from app.services.idempotency_service import run_idempotent
from app.services.organization_service import get_waba_connection
from app.services.template_service import (
    build_company_meta_name,
    build_send_components,
    build_variable_examples,
    compile_components,
    sync_templates,
    validate_dispatch_template,
)

router = APIRouter(prefix="/templates", tags=["templates"])


PRESETS = [
    TemplatePreset(
        id="simulation_resume",
        name="Simulação parada na metade",
        description="Retoma quem já demonstrou intenção e sumiu.",
        category="UTILITY",
        tags=["retomada", "crédito"],
        when_to_use="Até 72h depois de abandonar a simulação.",
        why_it_works=(
            "A pessoa já passou pelo esforço de começar. Lembrar que o progresso não se "
            "perdeu remove o único atrito real: recomeçar."
        ),
        caution=(
            "Só é utilidade enquanto a solicitação estiver aberta. Passado o prazo, vira "
            "marketing e precisa de consentimento."
        ),
        suggested_rules=AudienceRules(no_response_days=7),
        components=[
            {
                "type": "BODY",
                "text": (
                    "Oi, {{nome}}! Sua simulação de {{produto}} ficou guardada. "
                    "Posso retomar de onde você parou?"
                ),
                "example": {"body_text": [["Ana", "crédito consignado"]]},
            },
            {"type": "FOOTER", "text": "Responda SAIR para não receber mais mensagens."},
            {
                "type": "BUTTONS",
                "buttons": [{"type": "QUICK_REPLY", "text": "Retomar simulação"}],
            },
        ],
        variable_schema={
            "1": {"alias": "nome", "source": "contact.first_name", "required": True},
            "2": {"alias": "produto", "source": "deal.product_name", "required": True},
        },
    ),
    TemplatePreset(
        id="document_pending",
        name="Documento pendente travando a análise",
        description="Destrava a análise sem precisar de ligação.",
        category="UTILITY",
        tags=["documentos", "retomada"],
        when_to_use="Quando a análise está parada aguardando um documento do cliente.",
        why_it_works=(
            "Aponta exatamente o que falta, sem exigir que o cliente ligue ou releia a "
            "conversa inteira para lembrar onde parou."
        ),
        caution="Confirme que o documento pendente ainda é o mesmo antes de disparar.",
        suggested_rules=AudienceRules(no_response_days=None),
        components=[
            {
                "type": "BODY",
                "text": (
                    "Oi, {{nome}}! A análise de {{produto}} parou por um documento. Quer continuar?"
                ),
                "example": {"body_text": [["Ana", "crédito consignado"]]},
            },
            {"type": "FOOTER", "text": "Responda SAIR para não receber mais mensagens."},
            {
                "type": "BUTTONS",
                "buttons": [{"type": "QUICK_REPLY", "text": "Continuar análise"}],
            },
        ],
        variable_schema={
            "1": {"alias": "nome", "source": "contact.first_name", "required": True},
            "2": {"alias": "produto", "source": "deal.product_name", "required": True},
        },
    ),
]


@router.get("", response_model=list[TemplateRead])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> list[MessageTemplate]:
    result = await db.scalars(
        select(MessageTemplate)
        .where(MessageTemplate.organization_id == organization_id)
        .order_by(MessageTemplate.updated_at.desc())
    )
    return list(result)


@router.get("/presets", response_model=list[TemplatePreset])
async def list_presets() -> list[TemplatePreset]:
    return [
        preset.model_copy(
            update={"estimated_reach": preview_audience(preset.suggested_rules, None).eligible}
        )
        for preset in PRESETS
    ]


@router.get("/{template_id}", response_model=TemplateRead)
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> MessageTemplate:
    template = await db.get(MessageTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    organization_id: str = Depends(get_organization_id),
    _: Principal = Depends(require_operator),
) -> None:
    template = await db.get(MessageTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    if template.status == TemplateStatus.PENDING:
        raise HTTPException(status_code=409, detail="Aguarde a Meta responder antes de excluir")
    referenced = await db.scalar(
        select(Campaign.id).where(Campaign.template_id == template.id).limit(1)
    )
    child_revision = await db.scalar(
        select(MessageTemplate.id).where(MessageTemplate.parent_template_id == template.id).limit(1)
    )
    if referenced or child_revision:
        raise HTTPException(
            status_code=409,
            detail="Template possui campanha ou revisão dependente e não pode ser excluído",
        )
    if template.meta_template_id is not None:
        connection = await get_waba_connection(db, template.organization_id)
        provider = build_provider_for_connection(
            settings.meta_mode, connection, settings.meta_graph_version
        )
        try:
            await provider.delete_template(template.name)
        except MetaProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    add_audit(
        db,
        action="template.deleted",
        resource_type="template",
        resource_id=template.id,
        details={"name": template.name, "status": template.status.value},
    )
    await db.delete(template)
    await db.commit()


@router.post("/drafts", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: TemplateDraftCreate,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: Principal = Depends(require_operator),
) -> TemplateRead | dict:
    async def handler() -> TemplateRead:
        organization = await db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
        meta_name = build_company_meta_name(organization.name, payload.name)
        duplicate = await db.scalar(
            select(MessageTemplate).where(
                MessageTemplate.organization_id == organization_id,
                MessageTemplate.name == meta_name,
                MessageTemplate.language == payload.language,
            )
        )
        if duplicate:
            raise HTTPException(
                status_code=409, detail="Já existe um template com esse nome e idioma"
            )
        template = MessageTemplate(
            organization_id=organization_id,
            **payload.model_dump(exclude={"name"}),
            name=meta_name,
            requested_category=payload.category,
            status=TemplateStatus.DRAFT,
            source="LOCAL",
        )
        db.add(template)
        await db.flush()
        add_audit(
            db,
            action="template.draft_created",
            resource_type="template",
            resource_id=template.id,
        )
        await db.commit()
        await db.refresh(template)
        return TemplateRead.model_validate(template)

    return await run_idempotent(
        db,
        scope="template.create_draft",
        namespace=organization_id,
        key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        handler=handler,
    )


@router.put("/{template_id}/draft", response_model=TemplateRead)
async def update_draft(
    template_id: str,
    payload: TemplateDraftUpdate,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    _: Principal = Depends(require_operator),
) -> MessageTemplate:
    template = await db.get(MessageTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    if template.status not in {TemplateStatus.DRAFT, TemplateStatus.REJECTED}:
        raise HTTPException(
            status_code=409, detail="Somente rascunhos ou rejeitados podem ser editados"
        )
    for field, value in payload.model_dump().items():
        setattr(template, field, value)
    template.requested_category = payload.category
    template.status = TemplateStatus.DRAFT
    template.rejection_reason = None
    template.revision += 1
    add_audit(
        db,
        action="template.draft_updated",
        resource_type="template",
        resource_id=template.id,
        details={"revision": template.revision},
    )
    await db.commit()
    await db.refresh(template)
    return template


@router.post("/{template_id}/submit", response_model=TemplateRead)
async def submit_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    organization_id: str = Depends(get_organization_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: Principal = Depends(require_operator),
) -> TemplateRead | dict:
    async def handler() -> TemplateRead:
        template = await db.get(MessageTemplate, template_id)
        if template is None or template.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Template não encontrado")
        if template.status not in {TemplateStatus.DRAFT, TemplateStatus.REJECTED}:
            raise HTTPException(status_code=409, detail="Template já submetido")
        organization = await db.get(Organization, template.organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
        meta_name = build_company_meta_name(organization.name, template.name)
        duplicate = await db.scalar(
            select(MessageTemplate.id).where(
                MessageTemplate.organization_id == template.organization_id,
                MessageTemplate.name == meta_name,
                MessageTemplate.language == template.language,
                MessageTemplate.id != template.id,
            )
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="Já existe um template com esse nome empresarial e idioma",
            )
        template.name = meta_name
        connection = await get_waba_connection(db, template.organization_id)
        provider = build_provider_for_connection(
            settings.meta_mode, connection, settings.meta_graph_version
        )
        try:
            components = compile_components(template.components, template.variable_schema)
            components = build_variable_examples(components, template.variable_schema)
            response = await provider.create_template(
                {
                    "name": template.name,
                    "language": template.language,
                    "category": template.requested_category.value,
                    "components": components,
                }
            )
        except (ValueError, MetaProviderError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        template.meta_template_id = str(response["id"])
        template.status = TemplateStatus(response.get("status", "PENDING"))
        actual_category = TemplateCategory(
            response.get("category", template.requested_category.value)
        )
        if actual_category != template.category:
            template.category_changed_at = datetime.now(UTC)
        template.category = actual_category
        template.correct_category = (
            TemplateCategory(response["correct_category"])
            if response.get("correct_category")
            else None
        )
        template.submission_attempt += 1
        template.submitted_at = datetime.now(UTC)
        add_audit(
            db,
            action="template.submitted",
            resource_type="template",
            resource_id=template.id,
            details={
                "meta_template_id": template.meta_template_id,
                "requested_category": template.requested_category.value,
                "actual_category": template.category.value,
                "submission_attempt": template.submission_attempt,
            },
        )
        await db.commit()
        await db.refresh(template)
        return TemplateRead.model_validate(template)

    return await run_idempotent(
        db,
        scope="template.submit",
        namespace=template_id,
        key=idempotency_key,
        status_code=status.HTTP_200_OK,
        handler=handler,
    )


@router.post(
    "/{template_id}/utility-revision",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_utility_revision(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
    _: Principal = Depends(require_operator),
) -> MessageTemplate:
    source = await db.get(MessageTemplate, template_id)
    if source is None or source.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    if source.status != TemplateStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail="Nova versão utility exige template aprovado como origem",
        )
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    suffix = uuid.uuid4().hex[:8]
    revision_name = build_company_meta_name(organization.name, f"{source.name}_u_{suffix}")
    revision = MessageTemplate(
        organization_id=organization_id,
        name=revision_name,
        display_name=f"{source.display_name} · nova versão utility",
        language=source.language,
        category=TemplateCategory.UTILITY,
        requested_category=TemplateCategory.UTILITY,
        status=TemplateStatus.DRAFT,
        components=source.components,
        variable_schema=source.variable_schema,
        source="LOCAL",
        revision=source.revision + 1,
        parent_template_id=source.id,
    )
    db.add(revision)
    await db.flush()
    add_audit(
        db,
        action="template.utility_revision_created",
        resource_type="template",
        resource_id=revision.id,
        details={"parent_template_id": source.id},
    )
    await db.commit()
    await db.refresh(revision)
    return revision


@router.post("/sync", response_model=SyncResult)
async def synchronize_templates(
    db: AsyncSession = Depends(get_db),
    provider: WhatsAppProvider = Depends(get_meta_provider),
    organization_id: str = Depends(get_organization_id),
    _: Principal = Depends(require_operator),
) -> SyncResult:
    try:
        created, updated = await sync_templates(db, provider, organization_id)
    except MetaProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    add_audit(
        db,
        action="template.sync_completed",
        resource_type="waba",
        resource_id=organization_id,
        details={"created": created, "updated": updated},
    )
    await db.commit()
    return SyncResult(created=created, updated=updated)


@router.post("/{template_id}/test-send", response_model=TemplateTestSendResult)
async def test_send_template(
    template_id: str,
    payload: TemplateTestSendRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    organization_id: str = Depends(get_organization_id),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=512),
    _: Principal = Depends(require_admin),
) -> TemplateTestSendResult | dict:
    template = await db.get(MessageTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    retry_digest = hashlib.sha256(f"{organization_id}:{idempotency_key}".encode()).hexdigest()

    async def handler() -> TemplateTestSendResult:
        if template.status != TemplateStatus.APPROVED:
            raise HTTPException(
                status_code=409, detail="Envio de teste exige template aprovado pela Meta"
            )
        try:
            validate_dispatch_template(template)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        connection = await get_waba_connection(db, organization_id)
        try:
            provider = build_campaign_provider(settings, connection)
        except GatewayProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        phone_hash = hash_phone(payload.phone_e164)
        reserved, _ = await reserve_template_send(db, organization_id, phone_hash)
        if not reserved:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Limite de 3 templates sem resposta atingido; aguarde uma mensagem do usuário"
                ),
            )
        try:
            components = build_send_components(template.variable_schema, payload.variables)
            delivery_id = await provider.send_template(
                recipient=payload.phone_e164,
                template_name=template.name,
                language=template.language,
                components=components,
                idempotency_key=f"template-test:{retry_digest}",
            )
            frequency_state = await confirm_template_send(db, organization_id, phone_hash)
        except (ValueError, GatewayProviderError) as exc:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        add_audit(
            db,
            action="template.test_accepted",
            resource_type="template",
            resource_id=template.id,
            details={
                "phone_suffix": payload.phone_e164[-4:],
                "variable_aliases": sorted(payload.variables),
                "delivery_id": delivery_id,
                "consecutive_template_sends": frequency_state.consecutive_template_sends,
            },
        )
        return TemplateTestSendResult(
            accepted=True,
            delivery_id=delivery_id,
            wamid=delivery_id,
            consecutive_template_sends=frequency_state.consecutive_template_sends,
        )

    return await run_idempotent(
        db,
        scope="template.test_send",
        namespace=template.id,
        key=retry_digest,
        status_code=status.HTTP_200_OK,
        handler=handler,
    )
