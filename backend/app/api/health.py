from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.db import storage_backend_name

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "supabase_configured": settings.supabase_configured,
        "storage_backend": storage_backend_name(),
        "llm_configured": settings.llm_configured,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
