"""Bildirimler: uygulama içi olay kaydı + isteğe bağlı Telegram."""

from __future__ import annotations

import logging

import httpx

from . import db
from .config import settings

log = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text[:4000], "disable_web_page_preview": True},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning("Telegram gönderilemedi: %s", e)
        return False


def emit(message: str, alert_id: int | None = None, scan_id: int | None = None,
         symbol_id: int | None = None, telegram: bool = True) -> None:
    db.execute(
        "INSERT INTO alert_events (alert_id, scan_id, symbol_id, message) VALUES (%s, %s, %s, %s)",
        (alert_id, scan_id, symbol_id, message),
    )
    log.info("bildirim: %s", message)
    if telegram:
        send_telegram(message)
