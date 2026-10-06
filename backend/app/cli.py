"""Komut satırı araçları.

    python -m app.cli migrate
    python -m app.cli sync-universe
    python -m app.cli backfill [--market BIST|US] [--all]
    python -m app.cli update --market BIST
    python -m app.cli live
    python -m app.cli snapshots
    python -m app.cli scan "rsi14 < 30 and close > sma200" [--tf 1d] [--market BIST]
"""

from __future__ import annotations

import argparse
import json
import logging

from . import db, ingest, jobs
from .screener import ExprError, run_screen
from .snapshot import update_symbol_snapshots


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("sync-universe")
    b = sub.add_parser("backfill", help="eksik geçmişleri indir (--all: hepsini baştan)")
    b.add_argument("--market", choices=["BIST", "US"])
    b.add_argument("--all", action="store_true")
    u = sub.add_parser("update", help="son barları ekle")
    u.add_argument("--market", choices=["BIST", "US"], required=True)
    sub.add_parser("live", help="anlık fiyatları bir kez çek (borsa kapalı olsa da)")
    sub.add_parser("snapshots", help="tüm indikatör özetlerini yeniden hesapla")
    s = sub.add_parser("scan", help="tek seferlik tarama")
    s.add_argument("expression")
    s.add_argument("--tf", default="1d")
    s.add_argument("--market", action="append", choices=["BIST", "US"])
    args = p.parse_args(argv)

    db.init_pool()
    try:
        _run(args)
    except ExprError as e:
        raise SystemExit(f"Hata: {e}") from None
    finally:
        db.close_pool()


def _run(args: argparse.Namespace) -> None:
    db.migrate()
    if args.cmd == "migrate":
        print("tamam")
    elif args.cmd == "sync-universe":
        print(jobs.sync_universe_job())
    elif args.cmd == "backfill":
        res = jobs.backfill_job(args.market, only_missing=not args.all)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "update":
        res = jobs.update_market_job(args.market)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "live":
        print(jobs.live_quotes_job(force=True))
    elif args.cmd == "snapshots":
        syms = ingest.active_symbols()
        res = ingest.run_for_symbols(syms, lambda s: {"n": update_symbol_snapshots(s["id"])})
        print(res)
    elif args.cmd == "scan":
        res = run_screen(args.expression, args.tf, args.market)
        print(f"{res['count']} / {res['scanned']} eşleşme")
        for r in res["rows"]:
            vals = " ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in r["values"].items())
            print(f"{r['exchange']}:{r['ticker']:<8} {vals}")


if __name__ == "__main__":
    main()
