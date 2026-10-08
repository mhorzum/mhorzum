"""Alarm değerlendirme.

- Fiyat alarmları: seans içinde her anlık fiyat güncellemesinde (15 dk gecikmeli)
  fiyatın seviyeyi kesip kesmediğine bakılır.
- İfade alarmları: bar kapanışında (gün sonu / 4 saatlik güncelleme sonrası)
  tarayıcı ifadesi sembolün son barında değerlendirilir.
"""

from __future__ import annotations

import json
import logging

from . import db
from .notify import emit
from .screener import ExprError, compile_expr, evaluate, load_candidates

log = logging.getLogger(__name__)

OP_TEXT = {"cross_up": "yukarı kesti", "cross_down": "aşağı kesti"}


def _fmt(v: float) -> str:
    return f"{v:,.4f}".rstrip("0").rstrip(".")


def check_price_alerts(market: str) -> int:
    alerts = db.fetch_all(
        """
        SELECT a.*, s.ticker, s.exchange, q.price
        FROM alerts a
        JOIN symbols s ON s.id = a.symbol_id
        JOIN live_quotes q ON q.symbol_id = a.symbol_id
        WHERE a.active AND a.kind = 'price' AND s.market = %s
        """,
        (market,),
    )
    fired = 0
    for a in alerts:
        price, state = a["price"], a["state"] or {}
        last = state.get("last_price")
        hit = False
        if last is not None:
            if a["operator"] == "cross_up":
                hit = last < a["value"] <= price
            else:
                hit = last > a["value"] >= price
        state["last_price"] = price
        if hit:
            fired += 1
            msg = f"🔔 {a['exchange']}:{a['ticker']} {_fmt(a['value'])} seviyesini {OP_TEXT[a['operator']]} " \
                  f"(fiyat {_fmt(price)})"
            if a["note"]:
                msg += f" — {a['note']}"
            emit(msg, alert_id=a["id"], symbol_id=a["symbol_id"])
            db.execute(
                "UPDATE alerts SET state = %s, last_triggered_at = now(), active = %s WHERE id = %s",
                (json.dumps(state), a["mode"] == "repeat", a["id"]),
            )
        else:
            db.execute("UPDATE alerts SET state = %s WHERE id = %s", (json.dumps(state), a["id"]))
    return fired


def check_expression_alerts(market: str | None = None, timeframes: tuple[str, ...] | None = None) -> int:
    sql = "SELECT * FROM alerts WHERE active AND kind = 'expression'"
    params: list = []
    if timeframes:
        sql += " AND timeframe = ANY(%s)"
        params.append(list(timeframes))
    fired = 0
    for a in db.fetch_all(sql, params):
        try:
            compiled = compile_expr(a["expression"])
        except ExprError as e:
            log.warning("alarm %s geçersiz ifade: %s", a["id"], e)
            continue
        if a["symbol_id"]:
            rows = load_candidates(a["timeframe"], [market] if market else None, symbol_ids=[a["symbol_id"]])
        else:
            rows = load_candidates(a["timeframe"], [market] if market else None, watchlist_id=a["watchlist_id"])
        state = a["state"] or {}
        triggered_any = False
        for r in rows:
            key = str(r["symbol_id"])
            bar = r["bar_time"].isoformat()
            if state.get(key) == bar:
                continue  # bu barda zaten tetiklendi
            if evaluate(compiled, r["vals"], r["prev"]):
                state[key] = bar
                triggered_any = True
                fired += 1
                msg = f"🔔 {r['exchange']}:{r['ticker']} [{a['timeframe']}] koşul sağlandı: {a['expression']}"
                if a["note"]:
                    msg += f" — {a['note']}"
                emit(msg, alert_id=a["id"], symbol_id=r["symbol_id"])
        if triggered_any:
            db.execute(
                "UPDATE alerts SET state = %s, last_triggered_at = now(), active = %s WHERE id = %s",
                (json.dumps(state), a["mode"] == "repeat", a["id"]),
            )
    return fired
