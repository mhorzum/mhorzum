"""REST API."""

from __future__ import annotations

import json
import threading
from typing import Literal

import pandas as pd
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import db, indicators, jobs, scheduler
from .bars import chart_time, frame_to_chart, load_bars
from .config import settings
from .markets import MARKETS, TIMEFRAME_LABELS, TIMEFRAMES
from .scans import run_saved_scan
from .screener import FUNCTIONS, ExprError, compile_expr, run_screen
from .snapshot import FIELDS

router = APIRouter(prefix="/api")

Timeframe = Literal["4h", "1d", "1w", "1mo", "3mo"]
MarketCode = Literal["BIST", "US"]


def _symbol(symbol_id: int) -> dict:
    s = db.fetch_one("SELECT * FROM symbols WHERE id = %s", (symbol_id,))
    if s is None:
        raise HTTPException(404, "sembol bulunamadı")
    return s


def _expr_or_400(text: str):
    try:
        return compile_expr(text)
    except ExprError as e:
        raise HTTPException(400, str(e)) from None


# --------------------------------------------------------------------- durum
@router.get("/status")
def status():
    counts = db.fetch_all(
        """
        SELECT s.market, count(*) AS symbols, count(s.backfilled_at) AS backfilled
        FROM symbols s WHERE s.active GROUP BY s.market
        """
    )
    last_bars = db.fetch_all(
        """
        SELECT s.market, (max(n.bar_time) AT TIME ZONE 'UTC')::date AS last_day FROM indicator_snapshots n
        JOIN symbols s ON s.id = n.symbol_id WHERE n.timeframe = '1d' GROUP BY s.market
        """
    )
    runs = db.fetch_all(
        """
        SELECT DISTINCT ON (job) job, started_at, finished_at, status, message
        FROM job_runs ORDER BY job, started_at DESC
        """
    )
    return {
        "provider": settings.data_provider,
        "markets": {
            code: {"open": m.is_open(), "timezone": str(m.tz)} for code, m in MARKETS.items()
        },
        "symbols": {r["market"]: {"total": r["symbols"], "backfilled": r["backfilled"]} for r in counts},
        "last_bar": {r["market"]: r["last_day"].isoformat() for r in last_bars},
        "jobs": runs,
        "progress": jobs.progress,
        "schedule": scheduler.describe(),
        "timeframes": [{"id": tf, "label": TIMEFRAME_LABELS[tf]} for tf in TIMEFRAMES],
    }


class JobRequest(BaseModel):
    market: MarketCode | None = None


@router.post("/jobs/{name}")
def trigger_job(name: Literal["sync_universe", "backfill", "update", "live"], body: JobRequest | None = None):
    market = body.market if body else None
    if name == "sync_universe":
        target = jobs.sync_universe_job
    elif name == "backfill":
        target = lambda: jobs.backfill_job(market, only_missing=True)  # noqa: E731
    elif name == "update":
        if market is None:
            raise HTTPException(400, "market gerekli")
        target = lambda: jobs.update_market_job(market)  # noqa: E731
    else:
        target = lambda: jobs.live_quotes_job(force=True)  # noqa: E731

    def run():
        try:
            target()
        except jobs.JobBusy:
            pass
        except Exception:
            pass  # job() hatayı job_runs tablosuna yazar

    threading.Thread(target=run, daemon=True).start()
    return {"started": name}


# ------------------------------------------------------------------ semboller
@router.get("/symbols")
def search_symbols(q: str = "", market: MarketCode | None = None, limit: int = Query(30, le=2000)):
    sql = "SELECT id, market, exchange, ticker, name, sector, indexes FROM symbols WHERE active"
    params: list = []
    if q:
        sql += " AND (ticker ILIKE %s OR name ILIKE %s)"
        params += [f"{q}%", f"%{q}%"]
    if market:
        sql += " AND market = %s"
        params.append(market)
    sql += " ORDER BY (ticker ILIKE %s) DESC, length(ticker), ticker LIMIT %s"
    params += [q or "", limit]
    return db.fetch_all(sql, params)


@router.get("/symbols/{symbol_id}")
def get_symbol(symbol_id: int):
    s = _symbol(symbol_id)
    s["quote"] = db.fetch_one("SELECT * FROM live_quotes WHERE symbol_id = %s", (symbol_id,))
    return s


# --------------------------------------------------------------------- barlar
@router.get("/bars")
def get_bars(symbol_id: int, tf: Timeframe = "1d", limit: int = Query(2000, le=5000)):
    s = _symbol(symbol_id)
    df = load_bars(symbol_id, tf, limit)
    quote = db.fetch_one("SELECT * FROM live_quotes WHERE symbol_id = %s", (symbol_id,))
    return {
        "symbol": s,
        "timeframe": tf,
        "bars": frame_to_chart(df, tf, s["market"]),
        "live": quote,
        "market_open": MARKETS[s["market"]].is_open(),
    }


@router.get("/indicators")
def list_indicators():
    return indicators.INDICATORS


@router.get("/indicator")
def get_indicator(symbol_id: int, name: str, tf: Timeframe = "1d", params: str = "{}",
                  limit: int = Query(2000, le=5000)):
    s = _symbol(symbol_id)
    try:
        p = json.loads(params) if params else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "params geçerli bir JSON nesnesi olmalı") from None
    # Isınma süresi için fazladan bar yükle, sonra kırp
    df = load_bars(symbol_id, tf, limit + 300)
    try:
        outputs = indicators.compute(name, df, p)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e)) from None
    keep = df.index[-limit:]
    result = {}
    for key, series in outputs.items():
        series = series.reindex(keep)
        result[key] = [
            {"time": chart_time(ts, tf, s["market"]), "value": float(v)}
            for ts, v in series.items()
            if pd.notna(v)
        ]
    return {"name": name, "meta": indicators.INDICATORS[name], "outputs": result}


@router.get("/quotes")
def get_quotes(ids: str):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids virgülle ayrılmış sayılar olmalı") from None
    return _quotes(id_list)


def _quotes(id_list: list[int]) -> list[dict]:
    if not id_list:
        return []
    return db.fetch_all(
        """
        SELECT s.id AS symbol_id, s.market, s.exchange, s.ticker, s.name,
               COALESCE(q.price, d.close) AS price,
               COALESCE(q.change_pct, d.change_pct) AS change_pct,
               q.fetched_at, q.update_mode, (q.price IS NOT NULL) AS live
        FROM symbols s
        LEFT JOIN live_quotes q ON q.symbol_id = s.id
        LEFT JOIN LATERAL (
            SELECT close, (close / NULLIF(lag(close) OVER (ORDER BY day), 0) - 1) * 100 AS change_pct, day
            FROM (SELECT day, close FROM bars_1d WHERE symbol_id = s.id ORDER BY day DESC LIMIT 2) t
            ORDER BY day DESC LIMIT 1
        ) d ON true
        WHERE s.id = ANY(%s)
        """,
        (id_list,),
    )


# --------------------------------------------------------------- izleme listesi
class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WatchlistItemIn(BaseModel):
    symbol_id: int


class OrderIn(BaseModel):
    symbol_ids: list[int]


@router.get("/watchlists")
def list_watchlists():
    return db.fetch_all(
        """
        SELECT w.*, (SELECT count(*) FROM watchlist_items i WHERE i.watchlist_id = w.id) AS count
        FROM watchlists w ORDER BY position, id
        """
    )


@router.post("/watchlists")
def create_watchlist(body: WatchlistIn):
    return db.fetch_one(
        "INSERT INTO watchlists (name, position) "
        "VALUES (%s, (SELECT COALESCE(max(position), 0) + 1 FROM watchlists)) RETURNING *",
        (body.name,),
    )


@router.patch("/watchlists/{wid}")
def rename_watchlist(wid: int, body: WatchlistIn):
    row = db.fetch_one("UPDATE watchlists SET name = %s WHERE id = %s RETURNING *", (body.name, wid))
    if row is None:
        raise HTTPException(404, "liste bulunamadı")
    return row


@router.delete("/watchlists/{wid}")
def delete_watchlist(wid: int):
    db.execute("DELETE FROM watchlists WHERE id = %s", (wid,))
    return {"ok": True}


@router.get("/watchlists/{wid}/items")
def watchlist_items(wid: int):
    ids = [r["symbol_id"] for r in db.fetch_all(
        "SELECT symbol_id FROM watchlist_items WHERE watchlist_id = %s ORDER BY position, added_at", (wid,)
    )]
    by_id = {q["symbol_id"]: q for q in _quotes(ids)}
    return [by_id[i] for i in ids if i in by_id]


@router.post("/watchlists/{wid}/items")
def add_watchlist_item(wid: int, body: WatchlistItemIn):
    _symbol(body.symbol_id)
    db.execute(
        """
        INSERT INTO watchlist_items (watchlist_id, symbol_id, position)
        VALUES (%s, %s, (SELECT COALESCE(max(position), 0) + 1 FROM watchlist_items WHERE watchlist_id = %s))
        ON CONFLICT DO NOTHING
        """,
        (wid, body.symbol_id, wid),
    )
    return {"ok": True}


@router.put("/watchlists/{wid}/items")
def reorder_watchlist(wid: int, body: OrderIn):
    with db.connection() as conn, conn.transaction():
        for pos, sid in enumerate(body.symbol_ids):
            conn.execute(
                "UPDATE watchlist_items SET position = %s WHERE watchlist_id = %s AND symbol_id = %s",
                (pos, wid, sid),
            )
    return {"ok": True}


@router.delete("/watchlists/{wid}/items/{symbol_id}")
def remove_watchlist_item(wid: int, symbol_id: int):
    db.execute("DELETE FROM watchlist_items WHERE watchlist_id = %s AND symbol_id = %s", (wid, symbol_id))
    return {"ok": True}


# -------------------------------------------------------------------- tarayıcı
class ScreenIn(BaseModel):
    expression: str
    timeframe: Timeframe = "1d"
    markets: list[MarketCode] = Field(default_factory=lambda: ["BIST", "US"])
    indexes: list[str] = Field(default_factory=list)
    watchlist_id: int | None = None
    sort_by: str | None = None
    descending: bool = True
    limit: int = Field(500, le=2000)


@router.get("/screener/fields")
def screener_fields():
    return {"fields": FIELDS, "functions": FUNCTIONS,
            "indexes": {"BIST": ["XU030", "XU100"], "US": ["SPX", "NDX"]}}


@router.post("/screener/validate")
def screener_validate(body: ScreenIn):
    c = _expr_or_400(body.expression)
    return {"ok": True, "fields": c.fields}


@router.post("/screener/run")
def screener_run(body: ScreenIn):
    try:
        return run_screen(body.expression, body.timeframe, body.markets, body.indexes or None,
                          body.watchlist_id, body.sort_by, body.descending, body.limit)
    except ExprError as e:
        raise HTTPException(400, str(e)) from None


# ------------------------------------------------------------- kayıtlı taramalar
class ScanIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expression: str
    timeframe: Timeframe = "1d"
    markets: list[MarketCode] = Field(default_factory=lambda: ["BIST", "US"])
    indexes: list[str] = Field(default_factory=list)
    watchlist_id: int | None = None
    sort_by: str | None = None
    schedule: str = "after_close"
    notify: bool = True
    active: bool = True


def _check_scan(body: ScanIn) -> None:
    _expr_or_400(body.expression)
    if body.sort_by and body.sort_by not in FIELDS:
        raise HTTPException(400, f"bilinmeyen sıralama alanı: {body.sort_by}")
    if body.schedule not in ("after_close", "manual"):
        try:
            CronTrigger.from_crontab(body.schedule)
        except ValueError:
            raise HTTPException(400, "zamanlama 'after_close', 'manual' veya 5 alanlı bir cron ifadesi olmalı") from None


@router.get("/scans")
def list_scans():
    return db.fetch_all(
        """
        SELECT s.*, r.match_count AS last_count, r.new_matches AS last_new
        FROM scans s
        LEFT JOIN LATERAL (
            SELECT match_count, new_matches FROM scan_results WHERE scan_id = s.id ORDER BY run_at DESC LIMIT 1
        ) r ON true
        ORDER BY s.id
        """
    )


@router.post("/scans")
def create_scan(body: ScanIn):
    _check_scan(body)
    row = db.fetch_one(
        """
        INSERT INTO scans (name, expression, timeframe, markets, indexes, watchlist_id, sort_by, schedule, notify, active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
        """,
        (body.name, body.expression, body.timeframe, body.markets, body.indexes, body.watchlist_id,
         body.sort_by, body.schedule, body.notify, body.active),
    )
    scheduler.sync_scan_jobs()
    return row


@router.put("/scans/{scan_id}")
def update_scan(scan_id: int, body: ScanIn):
    _check_scan(body)
    row = db.fetch_one(
        """
        UPDATE scans SET name = %s, expression = %s, timeframe = %s, markets = %s, indexes = %s,
               watchlist_id = %s, sort_by = %s, schedule = %s, notify = %s, active = %s
        WHERE id = %s RETURNING *
        """,
        (body.name, body.expression, body.timeframe, body.markets, body.indexes, body.watchlist_id,
         body.sort_by, body.schedule, body.notify, body.active, scan_id),
    )
    if row is None:
        raise HTTPException(404, "tarama bulunamadı")
    scheduler.sync_scan_jobs()
    return row


@router.delete("/scans/{scan_id}")
def delete_scan(scan_id: int):
    db.execute("DELETE FROM scans WHERE id = %s", (scan_id,))
    scheduler.sync_scan_jobs()
    return {"ok": True}


@router.post("/scans/{scan_id}/run")
def run_scan_now(scan_id: int):
    try:
        res = run_saved_scan(scan_id, notify=False)
    except KeyError:
        raise HTTPException(404, "tarama bulunamadı") from None
    except ExprError as e:
        raise HTTPException(400, str(e)) from None
    return {"count": res["count"], "new": res["new"], **res["result"]}


@router.get("/scans/{scan_id}/results")
def scan_results(scan_id: int, limit: int = Query(20, le=200)):
    return db.fetch_all(
        "SELECT id, run_at, match_count, matches, new_matches FROM scan_results "
        "WHERE scan_id = %s ORDER BY run_at DESC LIMIT %s",
        (scan_id, limit),
    )


# --------------------------------------------------------------------- alarmlar
class AlertIn(BaseModel):
    kind: Literal["price", "expression"]
    symbol_id: int | None = None
    watchlist_id: int | None = None
    timeframe: Timeframe = "1d"
    operator: Literal["cross_up", "cross_down"] | None = None
    value: float | None = None
    expression: str | None = None
    mode: Literal["once", "repeat"] = "once"
    note: str | None = Field(None, max_length=300)
    active: bool = True


def _check_alert(body: AlertIn) -> None:
    if body.kind == "price":
        if body.symbol_id is None or body.operator is None or body.value is None:
            raise HTTPException(400, "fiyat alarmı için sembol, yön ve seviye gerekli")
    else:
        if not body.expression:
            raise HTTPException(400, "ifade gerekli")
        _expr_or_400(body.expression)
        if body.symbol_id is None and body.watchlist_id is None:
            raise HTTPException(400, "sembol veya izleme listesi seçin")


@router.get("/alerts")
def list_alerts():
    return db.fetch_all(
        """
        SELECT a.*, s.exchange, s.ticker, w.name AS watchlist_name
        FROM alerts a
        LEFT JOIN symbols s ON s.id = a.symbol_id
        LEFT JOIN watchlists w ON w.id = a.watchlist_id
        ORDER BY a.active DESC, a.created_at DESC
        """
    )


@router.post("/alerts")
def create_alert(body: AlertIn):
    _check_alert(body)
    return db.fetch_one(
        """
        INSERT INTO alerts (kind, symbol_id, watchlist_id, timeframe, operator, value, expression, mode, note, active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
        """,
        (body.kind, body.symbol_id, body.watchlist_id, body.timeframe, body.operator, body.value,
         body.expression, body.mode, body.note, body.active),
    )


@router.put("/alerts/{alert_id}")
def update_alert(alert_id: int, body: AlertIn):
    _check_alert(body)
    row = db.fetch_one(
        """
        UPDATE alerts SET kind = %s, symbol_id = %s, watchlist_id = %s, timeframe = %s, operator = %s,
               value = %s, expression = %s, mode = %s, note = %s, active = %s, state = '{}'
        WHERE id = %s RETURNING *
        """,
        (body.kind, body.symbol_id, body.watchlist_id, body.timeframe, body.operator, body.value,
         body.expression, body.mode, body.note, body.active, alert_id),
    )
    if row is None:
        raise HTTPException(404, "alarm bulunamadı")
    return row


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int):
    db.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
    return {"ok": True}


@router.get("/events")
def list_events(since_id: int = 0, limit: int = Query(100, le=500)):
    return db.fetch_all(
        """
        SELECT e.*, s.exchange, s.ticker FROM alert_events e
        LEFT JOIN symbols s ON s.id = e.symbol_id
        WHERE e.id > %s ORDER BY e.id DESC LIMIT %s
        """,
        (since_id, limit),
    )


@router.post("/events/seen")
def mark_events_seen():
    db.execute("UPDATE alert_events SET seen = true WHERE NOT seen")
    return {"ok": True}


# ------------------------------------------------------------------- çizimler
class DrawingIn(BaseModel):
    symbol_id: int
    kind: Literal["hline", "trendline"]
    data: dict


@router.get("/drawings")
def list_drawings(symbol_id: int):
    return db.fetch_all("SELECT * FROM drawings WHERE symbol_id = %s ORDER BY id", (symbol_id,))


@router.post("/drawings")
def create_drawing(body: DrawingIn):
    _symbol(body.symbol_id)
    return db.fetch_one(
        "INSERT INTO drawings (symbol_id, kind, data) VALUES (%s, %s, %s) RETURNING *",
        (body.symbol_id, body.kind, json.dumps(body.data)),
    )


@router.delete("/drawings/{drawing_id}")
def delete_drawing(drawing_id: int):
    db.execute("DELETE FROM drawings WHERE id = %s", (drawing_id,))
    return {"ok": True}
