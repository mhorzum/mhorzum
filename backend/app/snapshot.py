"""Tarayıcı ve alarmlar için her sembol/periyotta son barın indikatör değerleri."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from . import db
from . import indicators as ta
from .bars import load_bars
from .markets import TIMEFRAMES

# Tarayıcı ifadelerinde kullanılabilen alanlar ve açıklamaları
FIELDS: dict[str, str] = {
    "open": "Açılış",
    "high": "En yüksek",
    "low": "En düşük",
    "close": "Kapanış",
    "volume": "Hacim",
    "price": "Anlık fiyat (15 dk gecikmeli; seans dışında son kapanış)",
    "change_pct": "Önceki bara göre değişim %",
    "perf_5": "Son 5 bar getirisi %",
    "perf_20": "Son 20 bar getirisi %",
    "sma20": "SMA 20", "sma50": "SMA 50", "sma100": "SMA 100", "sma200": "SMA 200",
    "ema9": "EMA 9", "ema20": "EMA 20", "ema50": "EMA 50", "ema200": "EMA 200",
    "rsi14": "RSI 14",
    "macd": "MACD (12,26)", "macd_signal": "MACD sinyal (9)", "macd_hist": "MACD histogram",
    "bb_upper": "Bollinger üst (20,2)", "bb_middle": "Bollinger orta", "bb_lower": "Bollinger alt",
    "bb_width": "Bollinger bant genişliği %",
    "atr14": "ATR 14", "atr_pct": "ATR / kapanış %",
    "stoch_k": "Stokastik %K (14,3,3)", "stoch_d": "Stokastik %D",
    "adx14": "ADX 14", "plus_di": "+DI 14", "minus_di": "-DI 14",
    "cci20": "CCI 20", "mfi14": "MFI 14", "obv": "OBV",
    "vol_sma20": "20 bar ortalama hacim", "rel_volume": "Göreli hacim (hacim / 20 bar ort.)",
    "supertrend": "SuperTrend (10,3)", "st_dir": "SuperTrend yönü (1 yükseliş, -1 düşüş)",
    "hh20": "Son 20 barın en yükseği", "ll20": "Son 20 barın en düşüğü",
    "hh55": "Son 55 barın en yükseği", "ll55": "Son 55 barın en düşüğü",
    "high_52w": "52 haftalık en yüksek", "low_52w": "52 haftalık en düşük",
    "bars": "Bar sayısı",
}

MIN_BARS = 2


def indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    out = pd.DataFrame(index=df.index)
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = df[col]
    out["change_pct"] = c.pct_change() * 100
    out["perf_5"] = c.pct_change(5) * 100
    out["perf_20"] = c.pct_change(20) * 100
    for n in (20, 50, 100, 200):
        out[f"sma{n}"] = ta.sma(c, n)
    for n in (9, 20, 50, 200):
        out[f"ema{n}"] = ta.ema(c, n)
    out["rsi14"] = ta.rsi(c, 14)
    m = ta.macd(c)
    out["macd"], out["macd_signal"], out["macd_hist"] = m["macd"], m["signal"], m["hist"]
    bb = ta.bollinger(c)
    out["bb_upper"], out["bb_middle"], out["bb_lower"] = bb["upper"], bb["middle"], bb["lower"]
    out["bb_width"] = (bb["upper"] - bb["lower"]) / bb["middle"] * 100
    out["atr14"] = ta.atr(df, 14)
    out["atr_pct"] = out["atr14"] / c * 100
    st = ta.stoch(df)
    out["stoch_k"], out["stoch_d"] = st["k"], st["d"]
    dmi = ta.adx(df)
    out["adx14"], out["plus_di"], out["minus_di"] = dmi["adx"], dmi["plus_di"], dmi["minus_di"]
    out["cci20"] = ta.cci(df)
    out["mfi14"] = ta.mfi(df)
    out["obv"] = ta.obv(df)
    out["vol_sma20"] = ta.sma(df["volume"], 20)
    out["rel_volume"] = df["volume"] / out["vol_sma20"].replace(0, np.nan)
    s = ta.supertrend(df)
    out["supertrend"], out["st_dir"] = s["supertrend"], s["dir"]
    out["hh20"] = df["high"].rolling(20, min_periods=1).max()
    out["ll20"] = df["low"].rolling(20, min_periods=1).min()
    out["hh55"] = df["high"].rolling(55, min_periods=1).max()
    out["ll55"] = df["low"].rolling(55, min_periods=1).min()
    out["bars"] = np.arange(1, len(df) + 1, dtype=float)
    return out


def _clean(row: pd.Series) -> dict:
    out = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
            continue
        v = float(v)
        out[k] = None if math.isnan(v) or math.isinf(v) else round(v, 6)
    return out


def compute_snapshot(df: pd.DataFrame, daily: pd.DataFrame | None = None) -> tuple[pd.Timestamp, dict, dict] | None:
    if len(df) < MIN_BARS:
        return None
    frame = indicator_frame(df)
    vals, prev = _clean(frame.iloc[-1]), _clean(frame.iloc[-2])
    if daily is not None and not daily.empty:
        last_day = daily.index[-1]
        year = daily[daily.index > last_day - pd.Timedelta(days=365)]
        vals["high_52w"] = float(year["high"].max())
        vals["low_52w"] = float(year["low"].min())
        prev_year = daily[(daily.index > last_day - pd.Timedelta(days=366)) & (daily.index < last_day)]
        prev["high_52w"] = float(prev_year["high"].max()) if not prev_year.empty else None
        prev["low_52w"] = float(prev_year["low"].min()) if not prev_year.empty else None
    return frame.index[-1], vals, prev


def update_symbol_snapshots(symbol_id: int, timeframes: tuple[str, ...] = TIMEFRAMES) -> int:
    daily = load_bars(symbol_id, "1d")
    written = 0
    with db.connection() as conn:
        for tf in timeframes:
            df = daily if tf == "1d" else load_bars(symbol_id, tf)
            snap = compute_snapshot(df, daily)
            if snap is None:
                continue
            bar_time, vals, prev = snap
            conn.execute(
                """
                INSERT INTO indicator_snapshots (symbol_id, timeframe, bar_time, vals, prev, updated_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (symbol_id, timeframe) DO UPDATE
                SET bar_time = EXCLUDED.bar_time, vals = EXCLUDED.vals, prev = EXCLUDED.prev,
                    updated_at = now()
                """,
                (symbol_id, tf, bar_time.to_pydatetime(), json.dumps(vals), json.dumps(prev)),
            )
            written += 1
    return written
