"""Kayıtlı (periyodik) taramaları çalıştırma."""

from __future__ import annotations

import json
import logging

from . import db
from .notify import emit
from .screener import run_screen

log = logging.getLogger(__name__)


def run_saved_scan(scan_id: int, notify: bool | None = None) -> dict:
    scan = db.fetch_one("SELECT * FROM scans WHERE id = %s", (scan_id,))
    if scan is None:
        raise KeyError(scan_id)
    result = run_screen(
        scan["expression"],
        scan["timeframe"],
        scan["markets"] or None,
        scan["indexes"] or None,
        scan["watchlist_id"],
        scan["sort_by"],
        limit=1000,
    )
    tickers = [f"{r['exchange']}:{r['ticker']}" for r in result["rows"]]
    last = db.fetch_one(
        "SELECT matches FROM scan_results WHERE scan_id = %s ORDER BY run_at DESC LIMIT 1", (scan_id,)
    )
    previous = {f"{r['exchange']}:{r['ticker']}" for r in (last["matches"] if last else [])}
    new = [t for t in tickers if t not in previous]
    compact = [
        {"symbol_id": r["symbol_id"], "exchange": r["exchange"], "ticker": r["ticker"], "values": r["values"]}
        for r in result["rows"]
    ]
    with db.connection() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO scan_results (scan_id, match_count, matches, new_matches) VALUES (%s, %s, %s, %s)",
            (scan_id, len(tickers), json.dumps(compact), json.dumps(new)),
        )
        conn.execute("UPDATE scans SET last_run_at = now() WHERE id = %s", (scan_id,))

    should_notify = scan["notify"] if notify is None else notify
    if should_notify and (new or last is None):
        shown = new if last is not None else tickers
        head = f"📊 Tarama '{scan['name']}' [{scan['timeframe']}]: {len(tickers)} eşleşme"
        if last is not None:
            head += f", {len(new)} yeni"
        body = ", ".join(t.split(":", 1)[1] for t in shown[:40])
        if len(shown) > 40:
            body += f" … (+{len(shown) - 40})"
        emit(f"{head}\n{body}" if body else head, scan_id=scan_id)
    return {"count": len(tickers), "new": new, "result": result}


def run_after_close_scans(market: str) -> int:
    """Gün sonu güncellemesinden sonra, o borsayı kapsayan 'after_close' taramalarını çalıştırır."""
    scans = db.fetch_all(
        "SELECT id FROM scans WHERE active AND schedule = 'after_close' AND %s = ANY(markets)", (market,)
    )
    for s in scans:
        try:
            run_saved_scan(s["id"])
        except Exception as e:
            log.warning("tarama %s hata: %s", s["id"], e)
    return len(scans)
