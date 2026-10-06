"""Teknik indikatörler.

Formüller TradingView'ın Pine Script tanımlarıyla uyumlu olacak şekilde yazıldı
(ör. RSI/ATR/ADX için Wilder RMA, Bollinger için popülasyon std sapması).
Girdi: open/high/low/close/volume sütunlu, zamana göre sıralı DataFrame.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


# --------------------------------------------------------------------- temel
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    # Pine ta.ema: ilk değerle başlar, alpha = 2/(n+1)
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n, min_periods=n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder hareketli ortalaması (Pine ta.rma): ilk değer SMA, sonra alpha=1/n."""
    values = s.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    alpha = 1.0 / n
    acc = np.nan
    window: list[float] = []
    for i, v in enumerate(values):
        if np.isnan(acc):
            if np.isnan(v):
                window.clear()
                continue
            window.append(v)
            if len(window) == n:
                acc = sum(window) / n
                out[i] = acc
        else:
            if not np.isnan(v):
                acc = alpha * v + (1 - alpha) * acc
            out[i] = acc
    return pd.Series(out, index=s.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


# --------------------------------------------------------------- indikatörler
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    change = close.diff()
    up = rma(change.clip(lower=0), n)
    down = rma((-change).clip(lower=0), n)
    # Pine: down == 0 ? 100 : up == 0 ? 0 : 100 - 100 / (1 + up / down)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = 100 - 100 / (1 + up / down)
    out = np.select([down == 0, up == 0], [100.0, 0.0], default=raw)
    return pd.Series(out, index=close.index).where(up.notna() & down.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return {"macd": line, "signal": sig, "hist": line - sig}


def bollinger(close: pd.Series, n: int = 20, mult: float = 2.0) -> dict[str, pd.Series]:
    mid = sma(close, n)
    dev = close.rolling(n, min_periods=n).std(ddof=0)
    return {"upper": mid + mult * dev, "middle": mid, "lower": mid - mult * dev}


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def stoch(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> dict[str, pd.Series]:
    ll = df["low"].rolling(k, min_periods=k).min()
    hh = df["high"].rolling(k, min_periods=k).max()
    raw = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    k_line = sma(raw, smooth)
    return {"k": k_line, "d": sma(k_line, d)}


def adx(df: pd.DataFrame, n: int = 14) -> dict[str, pd.Series]:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan
    tr = true_range(df)
    tr.iloc[0] = np.nan
    trur = rma(tr, n)
    plus = 100 * rma(plus_dm, n) / trur
    minus = 100 * rma(minus_dm, n) / trur
    total = (plus + minus).replace(0, np.nan)
    dx = 100 * (plus - minus).abs() / total
    return {"adx": rma(dx, n), "plus_di": plus, "minus_di": minus}


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mean = sma(tp, n)
    md = tp.rolling(n, min_periods=n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - mean) / (0.015 * md.replace(0, np.nan))


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    flow = tp * df["volume"]
    delta = tp.diff()
    pos = flow.where(delta > 0, 0.0).rolling(n, min_periods=n).sum()
    neg = flow.where(delta < 0, 0.0).rolling(n, min_periods=n).sum()
    out = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    return out.where(neg != 0, 100.0).where(pos.notna())


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> dict[str, pd.Series]:
    """Pine ta.supertrend. 'dir' = +1 yükseliş, -1 düşüş."""
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    a = atr(df, n).to_numpy()
    size = len(df)
    st = np.full(size, np.nan)
    direction = np.full(size, np.nan)
    lower_prev = upper_prev = st_prev = np.nan
    for i in range(size):
        if np.isnan(a[i]):
            continue
        lower = hl2[i] - mult * a[i]
        upper = hl2[i] + mult * a[i]
        if not np.isnan(lower_prev):
            if not (lower > lower_prev or close[i - 1] < lower_prev):
                lower = lower_prev
            if not (upper < upper_prev or close[i - 1] > upper_prev):
                upper = upper_prev
        if np.isnan(st_prev):
            d = -1.0  # Pine'da ilk geçerli bar düşüş yönüyle başlar
        elif st_prev == upper_prev:
            d = 1.0 if close[i] > upper else -1.0
        else:
            d = -1.0 if close[i] < lower else 1.0
        st[i] = lower if d == 1.0 else upper
        direction[i] = d
        lower_prev, upper_prev, st_prev = lower, upper, st[i]
    return {"supertrend": pd.Series(st, index=df.index), "dir": pd.Series(direction, index=df.index)}


# ------------------------------------------------------ grafik için kayıt defteri
# pane: 'overlay' fiyat grafiğinin üstüne, 'separate' ayrı panelde çizilir
INDICATORS: dict[str, dict] = {
    "sma": {"label": "SMA", "pane": "overlay", "params": {"length": 20}},
    "ema": {"label": "EMA", "pane": "overlay", "params": {"length": 20}},
    "wma": {"label": "WMA", "pane": "overlay", "params": {"length": 20}},
    "bb": {"label": "Bollinger", "pane": "overlay", "params": {"length": 20, "mult": 2.0}},
    "supertrend": {"label": "SuperTrend", "pane": "overlay", "params": {"length": 10, "mult": 3.0}},
    "rsi": {"label": "RSI", "pane": "separate", "params": {"length": 14}, "levels": [30, 70]},
    "macd": {"label": "MACD", "pane": "separate", "params": {"fast": 12, "slow": 26, "signal": 9}},
    "stoch": {"label": "Stokastik", "pane": "separate", "params": {"k": 14, "d": 3, "smooth": 3}, "levels": [20, 80]},
    "adx": {"label": "ADX / DMI", "pane": "separate", "params": {"length": 14}, "levels": [25]},
    "cci": {"label": "CCI", "pane": "separate", "params": {"length": 20}, "levels": [-100, 100]},
    "mfi": {"label": "MFI", "pane": "separate", "params": {"length": 14}, "levels": [20, 80]},
    "atr": {"label": "ATR", "pane": "separate", "params": {"length": 14}},
    "obv": {"label": "OBV", "pane": "separate", "params": {}},
}

_COMPUTE: dict[str, Callable[[pd.DataFrame, dict], dict[str, pd.Series]]] = {
    "sma": lambda df, p: {"sma": sma(df["close"], int(p["length"]))},
    "ema": lambda df, p: {"ema": ema(df["close"], int(p["length"]))},
    "wma": lambda df, p: {"wma": wma(df["close"], int(p["length"]))},
    "bb": lambda df, p: bollinger(df["close"], int(p["length"]), float(p["mult"])),
    "supertrend": lambda df, p: supertrend(df, int(p["length"]), float(p["mult"])),
    "rsi": lambda df, p: {"rsi": rsi(df["close"], int(p["length"]))},
    "macd": lambda df, p: macd(df["close"], int(p["fast"]), int(p["slow"]), int(p["signal"])),
    "stoch": lambda df, p: stoch(df, int(p["k"]), int(p["d"]), int(p["smooth"])),
    "adx": lambda df, p: adx(df, int(p["length"])),
    "cci": lambda df, p: {"cci": cci(df, int(p["length"]))},
    "mfi": lambda df, p: {"mfi": mfi(df, int(p["length"]))},
    "atr": lambda df, p: {"atr": atr(df, int(p["length"]))},
    "obv": lambda df, p: {"obv": obv(df)},
}


def compute(name: str, df: pd.DataFrame, params: dict | None = None) -> dict[str, pd.Series]:
    if name not in INDICATORS:
        raise ValueError(f"bilinmeyen indikatör: {name}")
    merged = {**INDICATORS[name]["params"], **(params or {})}
    return _COMPUTE[name](df, merged)
