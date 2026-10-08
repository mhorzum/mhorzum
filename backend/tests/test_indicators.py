import numpy as np
import pandas as pd
import pytest

from app import indicators as ta


def frame(closes, spread=1.0, volume=1000.0):
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + spread, "low": c - spread,
                         "close": c, "volume": volume})


def test_sma_ema():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert ta.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    e = ta.ema(s, 3)
    # alpha = 0.5, ilk değerden başlar: 1, 1.5, 2.25, 3.125, 4.0625
    assert e.iloc[2] == pytest.approx(2.25)
    assert e.iloc[4] == pytest.approx(4.0625)
    assert np.isnan(e.iloc[1])


def test_rma_seeds_with_sma():
    s = pd.Series([2, 4, 6, 8], dtype=float)
    r = ta.rma(s, 3)
    assert np.isnan(r.iloc[1])
    assert r.iloc[2] == pytest.approx(4.0)
    assert r.iloc[3] == pytest.approx(4.0 + (8 - 4.0) / 3)


def reference_rsi(closes, n):
    gains, losses = [], []
    for a, b in zip(closes[:-1], closes[1:]):
        gains.append(max(b - a, 0))
        losses.append(max(a - b, 0))
    avg_g, avg_l = sum(gains[:n]) / n, sum(losses[:n]) / n
    out = [100 - 100 / (1 + avg_g / avg_l)]
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
        out.append(100 - 100 / (1 + avg_g / avg_l))
    return out


def test_rsi_matches_wilder_reference():
    rng = np.random.default_rng(1)
    closes = list(100 + np.cumsum(rng.normal(0, 1, 120)))
    got = ta.rsi(pd.Series(closes), 14).dropna().tolist()
    assert got == pytest.approx(reference_rsi(closes, 14))


def test_rsi_edge_cases():
    up = ta.rsi(pd.Series(np.arange(1, 40, dtype=float)), 14)
    assert up.iloc[-1] == 100
    flat = ta.rsi(pd.Series([5.0] * 30), 14)
    assert flat.iloc[-1] == 100  # Pine: down == 0 -> 100


def test_bollinger_population_std():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    bb = ta.bollinger(s, 5, 2)
    std = np.std([1, 2, 3, 4, 5])
    assert bb["upper"].iloc[-1] == pytest.approx(3 + 2 * std)
    assert bb["lower"].iloc[-1] == pytest.approx(3 - 2 * std)


def test_macd_definition():
    s = pd.Series(np.linspace(10, 50, 80))
    m = ta.macd(s)
    expected = ta.ema(s, 12) - ta.ema(s, 26)
    pd.testing.assert_series_equal(m["macd"], expected)
    assert (m["hist"].dropna() == (m["macd"] - m["signal"]).dropna()).all()


def test_atr_constant_range():
    df = frame([10.0] * 30, spread=1.0)
    assert ta.atr(df, 14).iloc[-1] == pytest.approx(2.0)


def test_supertrend_direction():
    rising = frame(np.linspace(10, 60, 80), spread=0.5)
    falling = frame(np.linspace(60, 10, 80), spread=0.5)
    assert ta.supertrend(rising)["dir"].iloc[-1] == 1
    assert ta.supertrend(falling)["dir"].iloc[-1] == -1
    st = ta.supertrend(rising)
    assert st["supertrend"].iloc[-1] < rising["close"].iloc[-1]


def test_stoch_and_adx_ranges():
    rng = np.random.default_rng(3)
    df = frame(list(100 + np.cumsum(rng.normal(0, 1, 200))))
    st = ta.stoch(df)
    assert st["k"].dropna().between(0, 100).all()
    dmi = ta.adx(df)
    assert dmi["adx"].dropna().between(0, 100).all()
    assert ta.mfi(df).dropna().between(0, 100).all()


def test_compute_registry_all():
    rng = np.random.default_rng(5)
    df = frame(list(100 + np.cumsum(rng.normal(0, 1, 300))))
    for name in ta.INDICATORS:
        out = ta.compute(name, df)
        assert out and all(len(s) == len(df) for s in out.values()), name
    with pytest.raises(ValueError):
        ta.compute("nope", df)
