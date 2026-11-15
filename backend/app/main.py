from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import FinnError, finn_error_handler, unhandled_exception_handler
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(FinnError, finn_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api_router, prefix=settings.api_prefix)


@app.on_event("startup")
def _start_market_data_scheduler() -> None:
    """Best-effort in-process scheduler — only started when explicitly enabled via
    ENABLE_MARKET_DATA_SCHEDULER=true. See docs/FINN_PHASE_12A_REPORT.md: this is
    NOT the recommended production mechanism on a web dyno that can idle or
    restart (the scheduled job silently never fires while the process is down) —
    scripts/run_market_data_refresh.py, triggered by an external scheduler (e.g. a
    Render Cron Job), is. This path exists as a free, zero-extra-infrastructure
    fallback for deployments that keep one process running continuously."""
    if not any((settings.enable_market_data_scheduler, settings.enable_document_discovery_scheduler, settings.enable_announcement_discovery_scheduler)):
        return
    from app.services.scheduler import start_scheduler

    start_scheduler(
        settings.market_data_refresh_cron if settings.enable_market_data_scheduler else None,
        settings.document_discovery_cron if settings.enable_document_discovery_scheduler else None,
        settings.announcement_discovery_cron if settings.enable_announcement_discovery_scheduler else None,
    )
