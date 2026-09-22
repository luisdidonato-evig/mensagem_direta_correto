from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConsentCreate(BaseModel):
    external_contact_id: str = Field(min_length=1, max_length=128)
    category: str = Field(pattern=r"^(MARKETING|UTILITY|ALL)$")
    source: str = Field(min_length=2, max_length=64)
    evidence: dict = Field(default_factory=dict)
    granted_at: datetime


class ConsentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    external_contact_id: str
    category: str
    source: str
    evidence: dict
    granted_at: datetime
    revoked_at: datetime | None


class OptOutCreate(BaseModel):
    phone: str = Field(min_length=8, max_length=32)
    scope: str = Field(default="ALL", pattern=r"^(MARKETING|UTILITY|ALL)$")
    source: str = Field(min_length=2, max_length=64)
    reason: str = Field(default="user_request", max_length=255)


class OptOutRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    scope: str
    source: str
    reason: str
    created_at: datetime
