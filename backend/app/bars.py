"""Veritabanından bar okuma ve grafik için zaman dönüşümü."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from . import db
from .markets import MARKETS, TIMEFRAME_TABLE, check_timeframe

COLUMNS = ["open", "high", "low", "close", "volume"]


def load_bars(symbol_id: int, timeframe: str, limit: int | None = None) -> pd.DataFrame:
    """Barları eskiden yeniye sıralı DataFrame olarak döndürür.

    Index: 4h için barın UTC açılış zamanı; diğer periyotlar için günün 00:00 UTC'si.
    """
    check_timeframe(timeframe)
    table = TIMEFRAME_TABLE[timeframe]
    tcol = "ts" if timeframe == "4h" else "day"
    sql = (
        f"SELECT {tcol} AS t, open, high, low, close, volume FROM {table} "
        f"WHERE symbol_id = %s ORDER BY {tcol} DESC"
    )
    params: list = [symbol_id]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    rows = db.fetch_all(sql, params)
    if not rows:
        return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    rows.reverse()
    index = pd.DatetimeIndex([_to_utc(r["t"]) for r in rows])
    return pd.DataFrame([[r[c] for c in COLUMNS] for r in rows], index=index, columns=COLUMNS, dtype=float)


def _to_utc(t) -> pd.Timestamp:
    if isinstance(t, datetime):
        return pd.Timestamp(t).tz_convert("UTC")
    return pd.Timestamp(t).tz_localize("UTC")


def chart_time(ts: pd.Timestamp, timeframe: str, market: str):
    """lightweight-charts zaman değeri.

    Günlük ve üstü periyotlarda 'YYYY-MM-DD'. 4 saatlikte grafik borsanın yerel
    saatini göstersin diye yerel saat sanki UTC'ymiş gibi epoch saniyesine çevrilir.
    """
    if timeframe != "4h":
        return ts.strftime("%Y-%m-%d")
    local = ts.tz_convert(MARKETS[market].tz)
    return int(local.replace(tzinfo=timezone.utc).timestamp())


def frame_to_chart(df: pd.DataFrame, timeframe: str, market: str) -> list[dict]:
    out = []
    for ts, row in df.iterrows():
        out.append(
            {
                "time": chart_time(ts, timeframe, market),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
        )
    return out
