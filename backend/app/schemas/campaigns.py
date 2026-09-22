from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.campaign import CampaignStatus


class AudienceRules(BaseModel):
    eligible_not_closed: bool = True
    no_response_days: int | None = Field(default=None)
    # Legado da fonte comercial. O limite obrigatório de três envios consecutivos
    # é aplicado pelo estado local, independentemente desta regra opcional.
    fewer_than_direct_messages: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def validate_rules(self) -> "AudienceRules":
        if not self.eligible_not_closed:
            raise ValueError("A regra 'elegível e não fechou' é obrigatória")
        if self.no_response_days not in {None, 7, 90}:
            raise ValueError("no_response_days deve ser 7, 90 ou nulo")
        return self


class AudiencePreviewRequest(BaseModel):
    product: str | None = None
    category: Literal["MARKETING", "UTILITY"] | None = None
    rules: AudienceRules


class AudiencePreviewResponse(BaseModel):
    total_considered: int
    eligible: int
    suppressed: int
    suppression_reasons: dict[str, int]
    normalized_rules: AudienceRules


class CampaignCreate(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    product: str | None = Field(default=None, max_length=255)
    template_id: str
    audience_rules: AudienceRules
    variable_mapping: dict = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    timezone: str = "America/Sao_Paulo"


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    product: str | None
    template_id: str
    audience_rules: dict
    variable_mapping: dict
    status: CampaignStatus
    scheduled_at: datetime | None
    timezone: str
    created_at: datetime


class CampaignValidation(BaseModel):
    valid: bool
    errors: list[str]
    audience: AudiencePreviewResponse


class CampaignResults(BaseModel):
    campaign_id: str
    campaign_status: CampaignStatus
    total: int
    by_status: dict[str, int]
