"""Ortam değişkenlerinden okunan ayarlar."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "evet"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql://borsa:borsa@localhost:5432/borsa"
        )
    )
    # 'tradingview' (gerçek veri) veya 'demo' (internetsiz deneme için sentetik veri)
    data_provider: str = field(default_factory=lambda: os.environ.get("DATA_PROVIDER", "tradingview"))
    history_years: int = field(default_factory=lambda: int(os.environ.get("HISTORY_YEARS", "5")))
    # Geçmiş veri indirirken aynı anda kaç sembol çekilsin
    fetch_workers: int = field(default_factory=lambda: int(os.environ.get("FETCH_WORKERS", "3")))
    live_poll_seconds: int = field(default_factory=lambda: int(os.environ.get("LIVE_POLL_SECONDS", "60")))
    scheduler_enabled: bool = field(default_factory=lambda: _bool("SCHEDULER_ENABLED", True))
    # İlk açılışta sembol listesi boşsa evren + 5 yıllık geçmiş otomatik indirilsin mi
    auto_bootstrap: bool = field(default_factory=lambda: _bool("AUTO_BOOTSTRAP", True))
    telegram_bot_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))
    # Kendi TradingView hesabınla giriş (isteğe bağlı; boşsa anonim 15 dk gecikmeli veri)
    tv_session: str = field(default_factory=lambda: os.environ.get("TV_SESSION", ""))
    tv_session_sign: str = field(default_factory=lambda: os.environ.get("TV_SESSION_SIGN", ""))
    timezone: str = field(default_factory=lambda: os.environ.get("APP_TIMEZONE", "Europe/Istanbul"))


settings = Settings()
