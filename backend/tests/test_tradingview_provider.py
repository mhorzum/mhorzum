"""TradingView sağlayıcısının ayrıştırma mantığı (ağ çağrıları sahte yanıtlarla)."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.providers.tradingview import TradingViewProvider

SCANS = {
    "turkey": pd.DataFrame({
        "ticker": ["BIST:THYAO", "BIST:GARAN", "BIST:NEWCO"],
        "name": ["THYAO", "GARAN", "NEWCO"],
        "description": ["Türk Hava Yolları", "Garanti BBVA", "Yeni Şirket"],
        "sector": ["Transportation", "Finance", None],
        "exchange": ["BIST"] * 3,
        "type": ["stock"] * 3,
    }),
    "SYML:BIST;XU030": pd.DataFrame({"ticker": ["BIST:THYAO"], "name": ["THYAO"]}),
    "SYML:BIST;XU100": pd.DataFrame({"ticker": ["BIST:THYAO", "BIST:GARAN"], "name": ["THYAO", "GARAN"]}),
    "SYML:SP;SPX": pd.DataFrame({
        "ticker": ["NASDAQ:AAPL", "NYSE:JPM"], "name": ["AAPL", "JPM"],
        "description": ["Apple", "JPMorgan"], "sector": ["Tech", "Finance"],
    }),
    "SYML:NASDAQ;NDX": pd.DataFrame({
        "ticker": ["NASDAQ:AAPL", "NASDAQ:ASML"], "name": ["AAPL", "ASML"],
        "description": ["Apple", "ASML"], "sector": ["Tech", "Tech"],
    }),
}


def fake_scan(fail_bist_index=False):
    def scan(query):
        q = query.query
        key = q["markets"][0] if q["markets"] else ",".join(q["symbols"]["symbolset"])
        if fail_bist_index and key.startswith("SYML:BIST"):
            raise RuntimeError("400 Bad Request")
        if key in SCANS:
            return SCANS[key]
        if key == "SYML:SP;SPX,SYML:NASDAQ;NDX":  # anlık fiyat sorgusu
            return pd.DataFrame({
                "ticker": ["NASDAQ:AAPL", "NYSE:JPM"], "close": [190.5, float("nan")],
                "open": [188.0, 200.0], "high": [191.0, 201.0], "low": [187.0, 199.0],
                "volume": [1e6, 2e6], "change": [1.2, -0.5], "update_mode": ["delayed_streaming_900"] * 2,
            })
        raise AssertionError(key)
    return scan


@pytest.fixture()
def tv(monkeypatch):
    p = TradingViewProvider()
    monkeypatch.setattr(p, "_scan", fake_scan())
    return p


def test_universe_merges_indexes(tv):
    syms = {f"{s.exchange}:{s.ticker}": s for s in tv.universe()}
    assert set(syms) == {"BIST:THYAO", "BIST:GARAN", "BIST:NEWCO", "NASDAQ:AAPL", "NYSE:JPM", "NASDAQ:ASML"}
    assert syms["BIST:THYAO"].indexes == ["XU030", "XU100"]
    assert syms["BIST:NEWCO"].indexes == []
    assert syms["NASDAQ:AAPL"].indexes == ["SPX", "NDX"] and syms["NASDAQ:AAPL"].market == "US"
    assert syms["NYSE:JPM"].indexes == ["SPX"]


def test_universe_survives_bist_index_failure(tv, monkeypatch):
    monkeypatch.setattr(tv, "_scan", fake_scan(fail_bist_index=True))
    syms = {s.ticker: s for s in tv.universe()}
    assert syms["THYAO"].indexes == [] and "AAPL" in syms


def test_quotes_skip_missing_prices(tv):
    quotes = tv.quotes("US")
    assert [(q.ticker, q.price, q.change_pct) for q in quotes] == [("AAPL", 190.5, 1.2)]


def test_history_normalizes_frame(tv, monkeypatch):
    idx = pd.DatetimeIndex(["2026-03-02 10:00", "2026-03-03 10:00"]).tz_localize("Europe/Istanbul")
    raw = pd.DataFrame({"Open": [1, 2], "High": [2, 3], "Low": [0.5, 1.5], "Close": [1.5, 2.5], "Volume": [10, 20]},
                       index=idx)
    calls = []

    def get_history(symbol, interval, start, exchange):
        calls.append((symbol, interval, exchange))
        return raw

    monkeypatch.setattr(tv._tv, "get_history", get_history)
    df = tv.history("NASDAQ", "AAPL", "4h", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert calls == [("AAPL", "4h", "NASDAQ")]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.tz) == "UTC" and df.index[0].hour == 7


def test_history_no_data_returns_empty(tv, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("API Error: No data received for BIST:XXXX")

    monkeypatch.setattr(tv._tv, "get_history", boom)
    assert tv.history("BIST", "XXXX", "1d", datetime(2026, 1, 1, tzinfo=timezone.utc)).empty
