from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.organization import WabaConnectionStatus


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    timezone: str = "America/Sao_Paulo"


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    timezone: str
    created_at: datetime


class WabaConnectionWrite(BaseModel):
    business_id: str | None = None
    waba_id: str | None = None
    phone_number_id: str | None = None
    api_version: str = "v23.0"
    access_token: str | None = None


class WabaConnectionRead(BaseModel):
    organization_id: str
    business_id: str | None
    waba_id: str | None
    phone_number_id: str | None
    api_version: str
    has_token: bool
    status: WabaConnectionStatus
    last_synced_at: datetime | None
    updated_at: datetime


class WabaConnectionTestResult(BaseModel):
    status: WabaConnectionStatus
    detail: str
