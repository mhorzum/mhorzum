"""Uygulama girişi: API + arayüz + zamanlayıcı tek süreçte çalışır."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, jobs, scheduler
from .api import router
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    db.migrate()
    if settings.scheduler_enabled:
        scheduler.start()
    if settings.auto_bootstrap:
        threading.Thread(target=jobs.bootstrap_job, daemon=True, name="bootstrap").start()
    yield
    scheduler.shutdown()
    db.close_pool()


app = FastAPI(title="Borsa Terminali", lifespan=lifespan)
app.include_router(router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
