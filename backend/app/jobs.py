"""Zamanlanmış / elle tetiklenen işler."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from . import db, ingest
from .alerts import check_expression_alerts, check_price_alerts
from .markets import MARKETS, STORED_TIMEFRAMES, TIMEFRAMES, Market
from .providers import get_provider
from .scans import run_after_close_scans
from .snapshot import update_symbol_snapshots

log = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
# Arayüzde gösterilecek ilerleme bilgisi: job adı -> {"done": int, "total": int}
progress: dict[str, dict] = {}


class JobBusy(RuntimeError):
    pass


@contextmanager
def job(name: str):
    with _locks_guard:
        lock = _locks.setdefault(name, threading.Lock())
    if not lock.acquire(blocking=False):
        raise JobBusy(f"{name} zaten çalışıyor")
    row = db.fetch_one("INSERT INTO job_runs (job) VALUES (%s) RETURNING id", (name,))
    info: dict = {}
    try:
        yield info
        db.execute(
            "UPDATE job_runs SET finished_at = now(), status = 'ok', message = %s WHERE id = %s",
            (info.get("message"), row["id"]),
        )
    except Exception as e:
        log.exception("iş başarısız: %s", name)
        db.execute(
            "UPDATE job_runs SET finished_at = now(), status = 'error', message = %s WHERE id = %s",
            (str(e)[:1000], row["id"]),
        )
        raise
    finally:
        progress.pop(name, None)
        lock.release()


def _progress(name: str):
    def cb(done: int, total: int) -> None:
        progress[name] = {"done": done, "total": total}

    return cb


def sync_universe_job() -> dict:
    with job("sync_universe") as info:
        res = ingest.sync_universe()
        info["message"] = str(res)
        return res


def backfill_job(market: str | None = None, only_missing: bool = True) -> dict:
    name = f"backfill_{market or 'ALL'}"
    with job(name) as info:
        symbols = ingest.active_symbols(market)
        if only_missing:
            symbols = [s for s in symbols if s["backfilled_at"] is None]
        provider = get_provider()

        def work(s: dict) -> dict:
            res = ingest.backfill_symbol(s, provider)
            update_symbol_snapshots(s["id"])
            return res

        res = ingest.run_for_symbols(symbols, work, _progress(name))
        info["message"] = f"{res['total']} sembol, {len(res['errors'])} hata"
        return res


def update_market_job(market: str, timeframes: tuple[str, ...] = STORED_TIMEFRAMES,
                      after_close: bool = True) -> dict:
    """Bir borsadaki tüm sembollerin son barlarını ekler, indikatörleri günceller,
    alarmları ve gün sonu taramalarını çalıştırır."""
    name = f"update_{market}"
    with job(name) as info:
        provider = get_provider()
        now = datetime.now(timezone.utc)
        snap_tfs = TIMEFRAMES if "1d" in timeframes else timeframes

        def work(s: dict) -> dict:
            res = ingest.update_symbol(s, provider, now=now, timeframes=timeframes)
            update_symbol_snapshots(s["id"], snap_tfs)
            return res

        res = ingest.run_for_symbols(ingest.active_symbols(market), work, _progress(name))
        fired = check_expression_alerts(market, snap_tfs)
        scans = run_after_close_scans(market) if after_close else 0
        info["message"] = f"{res['total']} sembol, {len(res['errors'])} hata, {fired} alarm, {scans} tarama"
        return {**res, "alerts": fired, "scans": scans}


def live_quotes_job(force: bool = False) -> dict:
    """Açık borsaların anlık (15 dk gecikmeli) fiyatlarını çeker ve fiyat alarmlarını kontrol eder."""
    provider = get_provider()
    out = {}
    for code, market in MARKETS.items():
        if not (force or market.is_open()):
            continue
        quotes = provider.quotes(code)
        ids = {
            (r["exchange"], r["ticker"]): r["id"]
            for r in db.fetch_all("SELECT id, exchange, ticker FROM symbols WHERE market = %s", (code,))
        }
        rows = [
            (ids[(q.exchange, q.ticker)], q.price, q.open, q.high, q.low, q.volume, q.change_pct, q.update_mode)
            for q in quotes
            if (q.exchange, q.ticker) in ids
        ]
        with db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO live_quotes (symbol_id, price, open, high, low, volume, change_pct, update_mode, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (symbol_id) DO UPDATE
                SET price = EXCLUDED.price, open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                    volume = EXCLUDED.volume, change_pct = EXCLUDED.change_pct,
                    update_mode = EXCLUDED.update_mode, fetched_at = now()
                """,
                rows,
            )
        out[code] = {"quotes": len(rows), "alerts": check_price_alerts(code)}
    return out


def expected_last_day(m: Market, now: datetime) -> date:
    """Gün sonu güncellemesi yapılmış olması gereken en son işlem günü (tatiller hariç)."""
    local = now.astimezone(m.tz)
    d = local.date()
    if local.weekday() >= 5 or local.time() < m.eod_run:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def catch_up_job() -> list[str]:
    """Bilgisayar gün sonu saatinde kapalıysa kaçırılan güncellemeyi yapar."""
    now = datetime.now(timezone.utc)
    ran = []
    for code, m in MARKETS.items():
        row = db.fetch_one(
            """
            SELECT max(n.bar_time) AS t FROM indicator_snapshots n
            JOIN symbols s ON s.id = n.symbol_id
            WHERE n.timeframe = '1d' AND s.market = %s AND s.active
            """,
            (code,),
        )
        if row is None or row["t"] is None or m.is_open(now):
            continue
        if row["t"].date() < expected_last_day(m, now):
            log.info("%s için kaçırılan gün sonu güncellemesi çalıştırılıyor", code)
            update_market_job(code)
            ran.append(code)
    return ran


def bootstrap_job() -> None:
    """Açılış: sembol listesi yoksa indir, eksik geçmişleri yükle, kaçırılan günleri tamamla."""
    try:
        if not db.fetch_one("SELECT 1 FROM symbols LIMIT 1"):
            sync_universe_job()
        backfill_job(None, only_missing=True)
        catch_up_job()
    except JobBusy:
        pass
    except Exception:
        log.exception("açılış işleri başarısız")
