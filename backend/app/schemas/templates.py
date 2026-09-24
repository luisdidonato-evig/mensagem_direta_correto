from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.template import TemplateCategory, TemplateStatus
from app.schemas.campaigns import AudienceRules


class TemplateDraftCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_]+$", min_length=3, max_length=512)
    display_name: str = Field(min_length=3, max_length=512)
    language: str = Field(default="pt_BR", max_length=16)
    category: TemplateCategory
    components: list[dict]
    variable_schema: dict = Field(default_factory=dict)

    @field_validator("components")
    @classmethod
    def validate_components(cls, components: list[dict]) -> list[dict]:
        component_types = {str(item.get("type", "")).upper() for item in components}
        if "BODY" not in component_types:
            raise ValueError("O template precisa de um componente BODY")
        return components


class TemplateDraftUpdate(BaseModel):
    display_name: str = Field(min_length=3, max_length=512)
    category: TemplateCategory
    components: list[dict]
    variable_schema: dict = Field(default_factory=dict)


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    meta_template_id: str | None
    name: str
    display_name: str
    language: str
    category: TemplateCategory
    requested_category: TemplateCategory
    correct_category: TemplateCategory | None
    status: TemplateStatus
    components: list[dict]
    variable_schema: dict
    source: str
    revision: int
    parent_template_id: str | None
    submission_attempt: int
    category_changed_at: datetime | None
    rejection_reason: str | None
    submitted_at: datetime | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TemplatePreset(BaseModel):
    id: str
    name: str
    description: str
    category: TemplateCategory
    tags: list[str]
    when_to_use: str
    why_it_works: str
    caution: str
    suggested_rules: AudienceRules
    components: list[dict]
    variable_schema: dict
    estimated_reach: int = 0


class SyncResult(BaseModel):
    created: int
    updated: int


class TemplateTestSendRequest(BaseModel):
    phone_e164: str
    variables: dict[str, str] = Field(default_factory=dict)
    confirm_recipient_opt_in: bool = False

    @field_validator("phone_e164", mode="before")
    @classmethod
    def normalize_test_phone(cls, value: object) -> str:
        raw = str(value).strip()
        digits = "".join(character for character in raw if character.isdigit())
        if not raw.startswith("+") and len(digits) in {10, 11}:
            digits = "55" + digits
        if not 8 <= len(digits) <= 15 or digits.startswith("0"):
            raise ValueError("Informe telefone válido com DDI, por exemplo +5511999999999")
        return "+" + digits

    @model_validator(mode="after")
    def validate_opt_in(self) -> "TemplateTestSendRequest":
        if not self.confirm_recipient_opt_in:
            raise ValueError("Confirme que o número autorizou o recebimento")
        return self


class TemplateTestSendResult(BaseModel):
    accepted: bool
    delivery_id: str
    wamid: str
    consecutive_template_sends: int
