from fastapi import APIRouter, Depends

from app.core.auth import Principal, get_principal

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def read_session(principal: Principal = Depends(get_principal)) -> dict[str, str | None]:
    return {
        "role": principal.role,
        "organization_id": principal.organization_id,
    }
