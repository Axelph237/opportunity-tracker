"""APScheduler wiring plus the shared run-state used by the scrape endpoints."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_setting, set_setting
from scraper import RunSummary, scrape_all

logger = logging.getLogger(__name__)

DEFAULT_CRON = "0 8,18 * * *"  # twice daily: 8am and 6pm local time
JOB_ID = "scrape_all_sources"
LOG_TAIL_SIZE = 400


def parse_cron(expression: str) -> CronTrigger:
    """Build a CronTrigger from a standard 5-field cron expression."""
    fields = (expression or "").split()
    if len(fields) != 5:
        raise ValueError(f"Expected 5 cron fields (m h dom mon dow), got {len(fields)}: {expression!r}")
    minute, hour, day, month, day_of_week = fields
    return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)


class ScrapeRunner:
    """Serialises scrape runs and keeps the last summary plus a live log tail."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.running = False
        self.last_run: Optional[str] = None
        self.last_summary: Optional[dict[str, Any]] = None
        self.log: deque[str] = deque(maxlen=LOG_TAIL_SIZE)

    def _record(self, message: str) -> None:
        stamped = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}"
        self.log.append(stamped)
        logger.info(message)

    async def run(self, source_ids: Optional[list[int]] = None) -> dict[str, Any]:
        if self.running:
            self._record("A scrape is already running; ignoring this request.")
            return self.last_summary or {"running": True}

        async with self._lock:
            self.running = True
            self.log.clear()
            try:
                summary: RunSummary = await scrape_all(source_ids, progress=self._record)
                self.last_summary = summary.to_dict()
                self.last_run = summary.finished_at
                set_setting("last_run", self.last_run or "")
                return self.last_summary
            except Exception as exc:
                message = f"Scrape run failed: {type(exc).__name__}: {exc}"
                self._record(message)
                logger.exception("Scrape run failed")
                self.last_summary = {
                    "started_at": None,
                    "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "sources_scraped": 0,
                    "new_opportunities": 0,
                    "errors": 1,
                    "running": False,
                    "detail": [{"source_name": "run", "status": "error", "error_message": message}],
                }
                return self.last_summary
            finally:
                self.running = False

    def log_tail(self, limit: int = 100) -> list[str]:
        return list(self.log)[-limit:]


runner = ScrapeRunner()
scheduler = AsyncIOScheduler()


async def _scheduled_job() -> None:
    logger.info("Scheduled scrape starting")
    await runner.run()


def current_cron() -> str:
    return get_setting("cron_schedule") or DEFAULT_CRON


def reschedule(expression: str) -> str:
    """Validate and apply a new cron expression. Returns the applied expression."""
    trigger = parse_cron(expression)
    set_setting("cron_schedule", expression)
    if scheduler.running:
        if scheduler.get_job(JOB_ID):
            scheduler.reschedule_job(JOB_ID, trigger=trigger)
        else:
            scheduler.add_job(_scheduled_job, trigger=trigger, id=JOB_ID, replace_existing=True)
    logger.info("Scrape schedule set to %s", expression)
    return expression


def next_run_time() -> Optional[str]:
    job = scheduler.get_job(JOB_ID) if scheduler.running else None
    if job and job.next_run_time:
        return job.next_run_time.isoformat(timespec="seconds")
    return None


def start() -> None:
    expression = current_cron()
    try:
        trigger = parse_cron(expression)
    except ValueError as exc:
        logger.warning("Invalid CRON_SCHEDULE %r (%s); falling back to %s", expression, exc, DEFAULT_CRON)
        expression = DEFAULT_CRON
        trigger = parse_cron(expression)
        set_setting("cron_schedule", expression)

    scheduler.add_job(_scheduled_job, trigger=trigger, id=JOB_ID, replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started with cron %r (next run: %s)", expression, next_run_time())


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def status() -> dict[str, Any]:
    return {
        "running": runner.running,
        "last_run": runner.last_run or get_setting("last_run") or None,
        "next_run": next_run_time(),
        "cron_schedule": current_cron(),
        "last_summary": runner.last_summary,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database import init_db

    init_db()
    print("cron:", current_cron())
    trigger = parse_cron(current_cron())
    print("trigger:", trigger)
    print("next fire times:")
    from datetime import timedelta

    cursor = datetime.now(trigger.timezone)
    for _ in range(4):
        cursor = trigger.get_next_fire_time(None, cursor)
        print("  ", cursor.isoformat(timespec="seconds"))
        cursor += timedelta(seconds=1)
