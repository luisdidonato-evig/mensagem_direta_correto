from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_audience_source, get_organization_id
from app.core.database import get_db
from app.integrations.audience.provider import AudienceSource, AudienceSourceError
from app.schemas.campaigns import AudiencePreviewRequest, AudiencePreviewResponse
from app.services.audience_service import apply_persisted_compliance, preview_audience

router = APIRouter(prefix="/audiences", tags=["audiences"])


@router.post("/preview", response_model=AudiencePreviewResponse)
async def audience_preview(
    payload: AudiencePreviewRequest,
    organization_id: str = Depends(get_organization_id),
    source: AudienceSource = Depends(get_audience_source),
    db: AsyncSession = Depends(get_db),
) -> AudiencePreviewResponse:
    try:
        candidates = await source.list_candidates(organization_id, payload.product)
        candidates = await apply_persisted_compliance(
            db, organization_id, candidates, payload.category
        )
    except AudienceSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return preview_audience(payload.rules, payload.product, candidates)
