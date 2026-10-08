# CLAUDE.md

Personal TradingView-like stock terminal (BIST + S&P 500 + Nasdaq-100). User-facing docs are in Turkish (README.md); keep UI strings and docs in Turkish.

## Layout
- `backend/app/` – FastAPI app + APScheduler in one process (`app.main:app`), CLI in `app/cli.py`
  - `providers/` – data sources: `tradingview.py` (borsapy history + tradingview-screener scanner), `demo.py` (offline synthetic data)
  - `ingest.py` – universe sync, 5y backfill, daily incremental update, split detection, completed-bar filtering
  - `snapshot.py` – per symbol/timeframe indicator snapshot (`indicator_snapshots`), defines screener `FIELDS`
  - `screener.py` – AST-whitelisted expression language; `alerts.py`, `scans.py`, `jobs.py`, `scheduler.py`, `api.py`
  - `migrations/*.sql` – applied in order on startup (`db.migrate()`); add new numbered files, never edit applied ones
- `frontend/` – static, no build step: vanilla ES modules + vendored lightweight-charts v5 (`frontend/vendor/`)

## Data model
Only `bars_4h` (UTC open time) and `bars_1d` (exchange-local trading date) are stored; `bars_1w/1mo/3mo` are SQL views over `bars_1d`. 15-min delayed quotes live only in `live_quotes` (latest value, no history).

## Commands
- Tests (need PostgreSQL; schema is dropped/recreated): `cd backend && TEST_DATABASE_URL=postgresql://... ../.venv/bin/python -m pytest -q`
- Run locally offline: `cd backend && DATABASE_URL=... DATA_PROVIDER=demo ../.venv/bin/uvicorn app.main:app`
- Production: `docker compose up -d --build`
