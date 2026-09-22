from fastapi import APIRouter

from app.api.v1 import audiences, auth, campaigns, compliance, organizations, templates, webhooks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(templates.router)
api_router.include_router(audiences.router)
api_router.include_router(campaigns.router)
api_router.include_router(compliance.router)
api_router.include_router(webhooks.router)
