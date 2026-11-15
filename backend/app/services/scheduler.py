"""Optional in-process scheduler for the EOD market-data refresh — see the startup
hook in app.main for when/why this is used. Isolated into its own module so
importing app.jobs.market_data_refresh (and the admin/CLI paths that call it
directly) never requires apscheduler to be installed or working.
"""

import logging

logger = logging.getLogger("finn.services.scheduler")

_scheduler = None


def _cron_trigger(cron_expression: str):
    from apscheduler.triggers.cron import CronTrigger

    minute, hour, day, month, day_of_week = cron_expression.split()
    return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week, timezone="Asia/Kolkata")


def start_scheduler(market_data_cron: str | None, document_discovery_cron: str | None = None, announcement_discovery_cron: str | None = None):
    """Parses standard 5-field cron strings and schedules whichever of Phase
    12A's market-data refresh / Phase 12B's document discovery has a cron
    given (None skips that job), in Asia/Kolkata. Idempotent — calling this
    twice reuses the same running scheduler instance rather than starting a
    second one."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    if market_data_cron:
        from app.jobs.market_data_refresh import run_market_data_refresh

        scheduler.add_job(
            lambda: run_market_data_refresh(triggered_by="scheduler"),
            trigger=_cron_trigger(market_data_cron),
            id="market_data_refresh",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
    if document_discovery_cron:
        from app.jobs.document_discovery import run_document_discovery

        scheduler.add_job(
            lambda: run_document_discovery(triggered_by="scheduler"),
            trigger=_cron_trigger(document_discovery_cron),
            id="document_discovery",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
    if announcement_discovery_cron:
        from app.jobs.announcement_discovery import run_announcement_discovery

        scheduler.add_job(
            lambda: run_announcement_discovery(triggered_by="scheduler"),
            trigger=_cron_trigger(announcement_discovery_cron),
            id="announcement_discovery",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    logger.info(
        "In-process scheduler started (market_data_cron=%s, document_discovery_cron=%s, announcement_discovery_cron=%s, Asia/Kolkata).",
        market_data_cron, document_discovery_cron, announcement_discovery_cron,
    )
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
