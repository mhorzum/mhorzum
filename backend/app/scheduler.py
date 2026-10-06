"""APScheduler ile periyodik işler."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import db, jobs
from .config import settings
from .markets import MARKETS
from .scans import run_saved_scan

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# BIST'te ilk 4 saatlik bar 14:00'te, ABD'de 13:30'da kapanır
MIDDAY_4H = {"BIST": (14, 20), "US": (13, 50)}


def _safe(fn, *args, **kwargs):
    def run():
        try:
            fn(*args, **kwargs)
        except jobs.JobBusy as e:
            log.info("%s", e)
        except Exception:
            log.exception("zamanlanmış iş hata verdi")

    return run


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    s = BackgroundScheduler(timezone=settings.timezone, job_defaults={"coalesce": True, "max_instances": 1,
                                                                       "misfire_grace_time": 3600})
    s.add_job(_safe(jobs.live_quotes_job), IntervalTrigger(seconds=settings.live_poll_seconds), id="live_quotes")
    for code, m in MARKETS.items():
        s.add_job(
            _safe(jobs.update_market_job, code),
            CronTrigger(day_of_week="mon-fri", hour=m.eod_run.hour, minute=m.eod_run.minute, timezone=m.tz),
            id=f"eod_{code}",
        )
        h, mi = MIDDAY_4H[code]
        s.add_job(
            _safe(jobs.update_market_job, code, ("4h",), False),
            CronTrigger(day_of_week="mon-fri", hour=h, minute=mi, timezone=m.tz),
            id=f"midday_{code}",
        )
    s.add_job(_safe(jobs.sync_universe_job), CronTrigger(day_of_week="sun", hour=10, minute=7),
              id="sync_universe")
    s.start()
    _scheduler = s
    sync_scan_jobs()
    return s


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def sync_scan_jobs() -> None:
    """Cron zamanlamalı kayıtlı taramaları zamanlayıcıyla eşitler."""
    if _scheduler is None:
        return
    wanted = {}
    for scan in db.fetch_all("SELECT id, schedule FROM scans WHERE active"):
        sched = scan["schedule"]
        if sched in ("after_close", "manual"):
            continue
        try:
            wanted[f"scan_{scan['id']}"] = (scan["id"], CronTrigger.from_crontab(sched, timezone=settings.timezone))
        except ValueError:
            log.warning("tarama %s geçersiz cron: %s", scan["id"], sched)
    for j in _scheduler.get_jobs():
        if j.id.startswith("scan_") and j.id not in wanted:
            j.remove()
    for job_id, (scan_id, trigger) in wanted.items():
        _scheduler.add_job(_safe(run_saved_scan, scan_id), trigger, id=job_id, replace_existing=True)


def describe() -> list[dict]:
    if _scheduler is None:
        return []
    return [
        {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
        for j in _scheduler.get_jobs()
    ]
