from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from wallabot import backup, scanner
from wallabot.config import settings
from wallabot.searches import Search, list_active_searches

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()

BACKUP_JOB_ID = "db-backup"


def _job_id(search_id: int) -> str:
    return f"search:{search_id}"


def _run_scan(search_id: int) -> None:
    try:
        new_results = scanner.scan_search(search_id)
        logger.info("Búsqueda %s escaneada: %d resultado(s) nuevo(s)", search_id, len(new_results))
    except Exception:
        logger.exception("Fallo inesperado escaneando la búsqueda %s", search_id)


def _run_backup() -> None:
    try:
        backup.backup_database()
    except Exception:
        logger.exception("Fallo haciendo el backup diario de la base de datos")


def schedule_search(search: Search) -> None:
    _scheduler.add_job(
        _run_scan,
        trigger=IntervalTrigger(minutes=search.scan_interval_minutes),
        args=[search.id],
        id=_job_id(search.id),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        jitter=30,
    )


def unschedule_search(search_id: int) -> None:
    if _scheduler.get_job(_job_id(search_id)) is not None:
        _scheduler.remove_job(_job_id(search_id))


def reschedule_search(search: Search) -> None:
    if search.is_active:
        schedule_search(search)
    else:
        unschedule_search(search.id)


def start() -> None:
    for search in list_active_searches():
        schedule_search(search)
    _scheduler.add_job(
        _run_backup,
        trigger=CronTrigger(hour=3, minute=0, timezone=settings.timezone),
        id=BACKUP_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Scheduler arrancado con %d búsqueda(s) activa(s)", len(list_active_searches()))


def shutdown() -> None:
    _scheduler.shutdown(wait=False)
