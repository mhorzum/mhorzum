"""Demo sağlayıcı + gerçek PostgreSQL ile uçtan uca akış."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import db, ingest, jobs
from app.alerts import check_expression_alerts, check_price_alerts
from app.bars import load_bars
from app.scans import run_saved_scan
from app.screener import compile_expr, evaluate, load_candidates, run_screen
from app.snapshot import update_symbol_snapshots


@pytest.fixture()
def loaded(fresh_db, provider):
    ingest.sync_universe(provider)
    for s in ingest.active_symbols():
        ingest.backfill_symbol(s, provider, years=2)
        update_symbol_snapshots(s["id"])
    return {s["ticker"]: s for s in ingest.active_symbols()}


def test_universe_and_backfill(loaded):
    assert set(loaded) == {"THYAO", "GARAN", "AAPL", "JPM"}
    assert loaded["THYAO"]["indexes"] == ["XU030", "XU100"]
    daily = load_bars(loaded["AAPL"]["id"], "1d")
    four = load_bars(loaded["AAPL"]["id"], "4h")
    assert 480 < len(daily) < 540  # ~2 yıl iş günü
    assert len(four) == pytest.approx(2 * len(daily), abs=2)
    assert daily.index.is_monotonic_increasing and not daily.index.has_duplicates


@pytest.mark.parametrize("tf,rule", [("1w", "W-MON"), ("1mo", "MS"), ("3mo", "QS")])
def test_derived_timeframes_match_pandas(loaded, tf, rule):
    sid = loaded["THYAO"]["id"]
    daily = load_bars(sid, "1d")
    view = load_bars(sid, tf)
    if tf == "1w":
        key = daily.index - pd.to_timedelta(daily.index.dayofweek, unit="D")
    else:
        naive = daily.index.tz_localize(None)
        key = naive.to_period("M" if tf == "1mo" else "Q").start_time.tz_localize("UTC").as_unit(daily.index.unit)
    g = daily.groupby(key)
    expected = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                             "close": g["close"].last(), "volume": g["volume"].sum()})
    pd.testing.assert_frame_equal(view, expected, check_names=False, check_freq=False)


def test_update_is_idempotent_and_detects_splits(loaded, provider):
    s = loaded["GARAN"]
    before = load_bars(s["id"], "1d")
    res = ingest.update_symbol(s, provider)
    assert "backfill" not in res
    after = load_bars(s["id"], "1d")
    pd.testing.assert_frame_equal(before, after)

    # Eski barları bölünme öncesi fiyatlar gibi bozalım: güncelleme yeniden yüklemeli
    db.execute("UPDATE bars_1d SET close = close * 2 WHERE symbol_id = %s AND day > current_date - 9", (s["id"],))
    res = ingest.update_symbol(s, provider)
    assert res.get("split") is True
    reloaded = load_bars(s["id"], "1d")  # yeniden yükleme varsayılan 5 yılı çeker
    assert len(reloaded) > len(before)
    pd.testing.assert_frame_equal(before, reloaded.loc[before.index])


def test_update_fills_missing_days(loaded, provider):
    s = loaded["JPM"]
    full = load_bars(s["id"], "1d")
    db.execute("DELETE FROM bars_1d WHERE symbol_id = %s AND day > current_date - 6", (s["id"],))
    db.execute("DELETE FROM bars_4h WHERE symbol_id = %s AND ts > now() - interval '6 days'", (s["id"],))
    ingest.update_symbol(s, provider)
    pd.testing.assert_frame_equal(full, load_bars(s["id"], "1d"))


def test_snapshots_and_screen(loaded):
    rows = load_candidates("1d")
    assert len(rows) == 4
    for r in rows:
        assert r["vals"]["close"] is not None and r["vals"]["sma200"] is not None
        assert r["vals"]["high_52w"] >= r["vals"]["close"] >= r["vals"]["low_52w"]
    expr = "close > sma50"
    compiled = compile_expr(expr)
    expected = {r["ticker"] for r in rows if evaluate(compiled, r["vals"], r["prev"])}
    res = run_screen(expr, "1d")
    assert {r["ticker"] for r in res["rows"]} == expected
    assert res["columns"][:3] == ["close", "change_pct", "volume"]
    only_bist = run_screen("close > 0", "1w", markets=["BIST"])
    assert {r["ticker"] for r in only_bist["rows"]} == {"THYAO", "GARAN"}
    nasdaq100 = run_screen("close > 0", "1mo", indexes=["NDX"])
    assert {r["ticker"] for r in nasdaq100["rows"]} == {"AAPL"}


def test_price_alert_fires_once(loaded):
    sid = loaded["AAPL"]["id"]
    db.execute("INSERT INTO live_quotes (symbol_id, price) VALUES (%s, 100)", (sid,))
    a = db.fetch_one(
        "INSERT INTO alerts (kind, symbol_id, operator, value) VALUES ('price', %s, 'cross_up', 105) RETURNING id",
        (sid,),
    )
    assert check_price_alerts("US") == 0  # ilk görülen fiyat kaydedilir
    db.execute("UPDATE live_quotes SET price = 104 WHERE symbol_id = %s", (sid,))
    assert check_price_alerts("US") == 0
    db.execute("UPDATE live_quotes SET price = 106 WHERE symbol_id = %s", (sid,))
    assert check_price_alerts("US") == 1
    assert db.fetch_one("SELECT active FROM alerts WHERE id = %s", (a["id"],))["active"] is False
    ev = db.fetch_all("SELECT * FROM alert_events")
    assert len(ev) == 1 and "AAPL" in ev[0]["message"]


def test_expression_alert_once_per_bar(loaded):
    wl = db.fetch_one("INSERT INTO watchlists (name) VALUES ('t') RETURNING id")
    for t in ("THYAO", "AAPL"):
        db.execute("INSERT INTO watchlist_items (watchlist_id, symbol_id) VALUES (%s, %s)", (wl["id"], loaded[t]["id"]))
    db.execute(
        "INSERT INTO alerts (kind, watchlist_id, timeframe, expression, mode) VALUES ('expression', %s, '1d', 'close > 0', 'repeat')",
        (wl["id"],),
    )
    assert check_expression_alerts() == 2
    assert check_expression_alerts() == 0  # aynı bar için tekrar tetiklenmez


def test_saved_scan_tracks_new_matches(loaded):
    scan = db.fetch_one(
        "INSERT INTO scans (name, expression, markets) VALUES ('hepsi', 'close > 0', '{BIST,US}') RETURNING id"
    )
    first = run_saved_scan(scan["id"])
    assert first["count"] == 4 and len(first["new"]) == 4
    second = run_saved_scan(scan["id"])
    assert second["new"] == []
    events = db.fetch_all("SELECT * FROM alert_events WHERE scan_id = %s", (scan["id"],))
    assert len(events) == 1  # yeni eşleşme yoksa bildirim yok


def test_jobs_end_to_end(fresh_db, provider):
    jobs.sync_universe_job()
    res = jobs.backfill_job()
    assert res["total"] == 4 and not res["errors"]
    res = jobs.update_market_job("BIST")
    assert res["total"] == 2 and not res["errors"]
    out = jobs.live_quotes_job(force=True)
    assert out["BIST"]["quotes"] == 2 and out["US"]["quotes"] == 2
    runs = db.fetch_all("SELECT job, status FROM job_runs")
    assert {r["status"] for r in runs} == {"ok"}


def test_api(loaded):
    from app.main import app

    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert st["symbols"]["BIST"]["total"] == 2
        sid = loaded["THYAO"]["id"]
        found = c.get("/api/symbols", params={"q": "thy"}).json()
        assert found[0]["ticker"] == "THYAO"

        bars = c.get("/api/bars", params={"symbol_id": sid, "tf": "1d"}).json()
        assert bars["bars"] and isinstance(bars["bars"][0]["time"], str)
        b4 = c.get("/api/bars", params={"symbol_id": sid, "tf": "4h", "limit": 10}).json()
        assert len(b4["bars"]) == 10 and isinstance(b4["bars"][0]["time"], int)
        # 4h zamanı İstanbul yerel saatine kaydırılmış olmalı (10:00 veya 14:00)
        hours = {datetime.fromtimestamp(b["time"], tz=timezone.utc).hour for b in b4["bars"]}
        assert hours <= {10, 14}
        assert c.get("/api/bars", params={"symbol_id": sid, "tf": "2h"}).status_code == 422

        ind = c.get("/api/indicator", params={"symbol_id": sid, "tf": "1w", "name": "macd"}).json()
        assert set(ind["outputs"]) == {"macd", "signal", "hist"}
        assert c.get("/api/indicator", params={"symbol_id": sid, "name": "rsi", "params": "[1]"}).status_code == 400

        wl = c.post("/api/watchlists", json={"name": "BIST"}).json()
        assert c.post(f"/api/watchlists/{wl['id']}/items", json={"symbol_id": sid}).status_code == 200
        items = c.get(f"/api/watchlists/{wl['id']}/items").json()
        assert items[0]["ticker"] == "THYAO" and items[0]["price"] is not None

        r = c.post("/api/screener/run", json={"expression": "rsi14 >", "timeframe": "1d"})
        assert r.status_code == 400 and "Sözdizimi" in r.json()["detail"]
        r = c.post("/api/screener/run", json={"expression": "close > 0", "timeframe": "3mo", "markets": ["US"]})
        assert r.json()["count"] == 2

        bad = c.post("/api/scans", json={"name": "x", "expression": "close > 0", "schedule": "her gün"})
        assert bad.status_code == 400
        scan = c.post("/api/scans", json={"name": "x", "expression": "close > 0", "schedule": "0 10 * * 1-5"}).json()
        assert c.post(f"/api/scans/{scan['id']}/run").json()["count"] == 4

        r = c.post("/api/alerts", json={"kind": "price", "symbol_id": sid, "operator": "cross_up"})
        assert r.status_code == 400
        r = c.post("/api/alerts", json={"kind": "price", "symbol_id": sid, "operator": "cross_up", "value": 10})
        assert r.status_code == 200
        d = c.post("/api/drawings", json={"symbol_id": sid, "kind": "hline", "data": {"price": 12.5}}).json()
        assert c.get("/api/drawings", params={"symbol_id": sid}).json()[0]["id"] == d["id"]


def test_catch_up_updates_stale_market(loaded, monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "update_market_job", lambda m: calls.append(m))
    assert jobs.catch_up_job() == []  # veri güncel
    db.execute(
        "UPDATE indicator_snapshots SET bar_time = bar_time - interval '10 days' "
        "WHERE symbol_id IN (SELECT id FROM symbols WHERE market = 'US')"
    )
    monkeypatch.setattr(type(jobs.MARKETS["US"]), "is_open", lambda self, at=None: False)
    assert jobs.catch_up_job() == ["US"] and calls == ["US"]


def test_backfill_order_prioritizes_watchlists_and_indexes(loaded):
    syms = list(loaded.values())
    wl = db.fetch_one("INSERT INTO watchlists (name) VALUES ('t') RETURNING id")
    db.execute("INSERT INTO watchlist_items (watchlist_id, symbol_id) VALUES (%s, %s)", (wl["id"], loaded["JPM"]["id"]))
    # JPM listede; THYAO/GARAN XU030; AAPL NDX
    assert [s["ticker"] for s in jobs.backfill_order(syms)] == ["JPM", "GARAN", "THYAO", "AAPL"]


def test_update_skips_unbackfilled_while_backfill_runs(loaded, provider, monkeypatch):
    db.execute("UPDATE symbols SET backfilled_at = NULL WHERE ticker = 'THYAO'")
    called = []
    monkeypatch.setattr(jobs.ingest, "update_symbol", lambda s, *a, **k: called.append(s["ticker"]) or {})
    with jobs.job("backfill_ALL"):
        jobs.update_market_job("BIST")
    assert called == ["GARAN"]
    called.clear()
    jobs.update_market_job("BIST")
    assert sorted(called) == ["GARAN", "THYAO"]
