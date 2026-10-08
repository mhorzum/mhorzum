"""Sembol evreni, geçmiş veri yükleme (backfill) ve günlük güncelleme."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd

from . import db
from .config import settings
from .markets import MARKETS, STORED_TIMEFRAMES
from .providers import Provider, get_provider

log = logging.getLogger(__name__)

# Güncellemede geriye dönük kaç günlük bar yeniden çekilsin (düzeltmeler + eksik günler)
UPDATE_LOOKBACK_DAYS = 12
# Eski bir barın kapanışı bu orandan fazla değiştiyse bölünme/bedelsiz var sayılır
SPLIT_TOLERANCE = 0.005
# Kapanıştan sonra günlük barın kesinleşmesi için beklenen süre
SETTLE_MINUTES = 15


# ------------------------------------------------------------------- evren
def sync_universe(provider: Provider | None = None) -> dict:
    provider = provider or get_provider()
    infos = provider.universe()
    if not infos:
        raise RuntimeError("sağlayıcı boş sembol listesi döndürdü")
    seen: set[tuple[str, str]] = set()
    with db.connection() as conn, conn.transaction():
        for s in infos:
            seen.add((s.exchange, s.ticker))
            conn.execute(
                """
                INSERT INTO symbols (market, exchange, ticker, name, sector, indexes, active)
                VALUES (%s, %s, %s, %s, %s, %s, true)
                ON CONFLICT (exchange, ticker) DO UPDATE
                SET market = EXCLUDED.market, name = EXCLUDED.name, sector = EXCLUDED.sector,
                    indexes = EXCLUDED.indexes, active = true
                """,
                (s.market, s.exchange, s.ticker, s.name, s.sector, sorted(set(s.indexes))),
            )
        existing = conn.execute("SELECT id, exchange, ticker FROM symbols WHERE active").fetchall()
        gone = [r["id"] for r in existing if (r["exchange"], r["ticker"]) not in seen]
        if gone:
            # Endeksten çıkan / işlem görmeyen semboller silinmez, pasife alınır (geçmiş korunur)
            conn.execute("UPDATE symbols SET active = false WHERE id = ANY(%s)", (gone,))
    counts = db.fetch_all("SELECT market, count(*) AS n FROM symbols WHERE active GROUP BY market")
    return {"active": {r["market"]: r["n"] for r in counts}, "deactivated": len(gone)}


def active_symbols(market: str | None = None) -> list[dict]:
    sql = "SELECT * FROM symbols WHERE active"
    params: list = []
    if market:
        sql += " AND market = %s"
        params.append(market)
    return db.fetch_all(sql + " ORDER BY market, ticker", params)


# --------------------------------------------------------------- dönüşümler
def trading_day(ts: pd.Timestamp, market: str) -> date:
    """Günlük bar zaman damgasını borsanın yerel işlem gününe çevirir.

    TradingView günlük barları seans açılışı ya da gece yarısı (UTC) ile
    damgalayabilir; +6 saat kaydırma her iki durumda da doğru günü verir.
    """
    return (ts.tz_convert(MARKETS[market].tz) + pd.Timedelta(hours=6)).date()


def completed_daily(df: pd.DataFrame, market: str, now: datetime) -> pd.DataFrame:
    """Günlük barları işlem gününe göre indeksler, henüz kapanmamış günü atar."""
    if df.empty:
        return df.iloc[0:0]
    m = MARKETS[market]
    local_now = now.astimezone(m.tz)
    days = [trading_day(ts, market) for ts in df.index]
    out = df.copy()
    out.index = pd.Index(days, name="day")
    out = out[~out.index.duplicated(keep="last")]
    cutoff = m.session_close(local_now.date()) + timedelta(minutes=SETTLE_MINUTES)
    today = local_now.date()
    keep = [d < today or (d == today and local_now >= cutoff) for d in out.index]
    return out[keep]


def completed_4h(df: pd.DataFrame, market: str, now: datetime) -> pd.DataFrame:
    """Kapanmış 4 saatlik barları döndürür (seans sonundaki kısa bar dahil)."""
    if df.empty:
        return df
    m = MARKETS[market]
    keep = []
    for ts in df.index:
        local = ts.tz_convert(m.tz)
        end = min(local + pd.Timedelta(hours=4), pd.Timestamp(m.session_close(local.date())))
        keep.append(now >= end.to_pydatetime() + timedelta(minutes=SETTLE_MINUTES))
    return df[keep]


# ------------------------------------------------------------------ yazma
def _upsert(conn, timeframe: str, symbol_id: int, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    table, tcol = ("bars_1d", "day") if timeframe == "1d" else ("bars_4h", "ts")
    rows = [
        (
            symbol_id,
            idx.to_pydatetime() if isinstance(idx, pd.Timestamp) else idx,
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            float(r.volume) if pd.notna(r.volume) else 0.0,
        )
        for idx, r in zip(df.index, df.itertuples(index=False))
    ]
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {table} (symbol_id, {tcol}, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol_id, {tcol}) DO UPDATE
            SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume
            """,
            rows,
        )
    return len(rows)


def _fetch(provider: Provider, sym: dict, timeframe: str, start: datetime, now: datetime) -> pd.DataFrame:
    raw = provider.history(sym["exchange"], sym["ticker"], timeframe, start)
    raw = raw.dropna(subset=["open", "high", "low", "close"])
    if timeframe == "1d":
        return completed_daily(raw, sym["market"], now)
    return completed_4h(raw, sym["market"], now)


def backfill_symbol(sym: dict, provider: Provider | None = None, years: int | None = None,
                    now: datetime | None = None) -> dict:
    """Sembolün tüm geçmişini (varsayılan 5 yıl) baştan yazar."""
    provider = provider or get_provider()
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=365 * (years or settings.history_years) + 7)
    frames = {tf: _fetch(provider, sym, tf, start, now) for tf in STORED_TIMEFRAMES}
    with db.connection() as conn, conn.transaction():
        counts = {}
        for tf, df in frames.items():
            table = "bars_1d" if tf == "1d" else "bars_4h"
            conn.execute(f"DELETE FROM {table} WHERE symbol_id = %s", (sym["id"],))
            counts[tf] = _upsert(conn, tf, sym["id"], df)
        conn.execute("UPDATE symbols SET backfilled_at = now() WHERE id = %s", (sym["id"],))
    return counts


def _split_suspected(conn, sym_id: int, daily: pd.DataFrame, now: datetime, market: str) -> bool:
    """Daha önce kaydedilmiş barlar sağlayıcıda farklı fiyatla geliyorsa (bölünme
    düzeltmesi) True döner."""
    if daily.empty:
        return False
    old_cutoff = now.astimezone(MARKETS[market].tz).date() - timedelta(days=3)
    overlap = daily[[d <= old_cutoff for d in daily.index]]
    if overlap.empty:
        return False
    stored = conn.execute(
        "SELECT day, close FROM bars_1d WHERE symbol_id = %s AND day = ANY(%s)",
        (sym_id, list(overlap.index)),
    ).fetchall()
    for r in stored:
        new_close = overlap.loc[r["day"], "close"]
        if r["close"] and abs(new_close / r["close"] - 1) > SPLIT_TOLERANCE:
            return True
    return False


def update_symbol(sym: dict, provider: Provider | None = None, now: datetime | None = None,
                  timeframes: tuple[str, ...] = STORED_TIMEFRAMES) -> dict:
    """Son barları ekler. Bölünme tespit edilirse sembolü baştan yükler."""
    provider = provider or get_provider()
    now = now or datetime.now(timezone.utc)
    if sym.get("backfilled_at") is None:
        return {"backfill": backfill_symbol(sym, provider, now=now)}

    last = db.fetch_one("SELECT max(day) AS d FROM bars_1d WHERE symbol_id = %s", (sym["id"],))
    last_day = last["d"] if last and last["d"] else (now - timedelta(days=30)).date()
    start_day = min(last_day, (now - timedelta(days=UPDATE_LOOKBACK_DAYS)).date()) - timedelta(days=3)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)

    frames = {tf: _fetch(provider, sym, tf, start, now) for tf in timeframes}
    with db.connection() as conn:
        if "1d" in frames and _split_suspected(conn, sym["id"], frames["1d"], now, sym["market"]):
            log.info("%s:%s fiyat düzeltmesi (bölünme?) tespit edildi, yeniden yükleniyor",
                     sym["exchange"], sym["ticker"])
            return {"backfill": backfill_symbol(sym, provider, now=now), "split": True}
        with conn.transaction():
            return {tf: _upsert(conn, tf, sym["id"], df) for tf, df in frames.items()}


def run_for_symbols(symbols: list[dict], fn: Callable[[dict], dict],
                    progress: Callable[[int, int], None] | None = None) -> dict:
    """fn'i semboller üzerinde paralel çalıştırır; hataları toplar."""
    done = 0
    errors: dict[str, str] = {}
    workers = max(1, settings.fetch_workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, s): s for s in symbols}
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                fut.result()
            except Exception as e:  # tek sembolün hatası işi durdurmasın
                errors[f"{s['exchange']}:{s['ticker']}"] = str(e)[:300]
                log.warning("%s:%s hata: %s", s["exchange"], s["ticker"], e)
            done += 1
            if progress:
                progress(done, len(symbols))
    return {"total": len(symbols), "errors": errors}
