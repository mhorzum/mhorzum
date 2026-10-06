"""Borsa tanımları (saat dilimi, seans saatleri) ve periyotlar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Market:
    code: str
    tz: ZoneInfo
    open: time
    close: time
    # Gün sonu güncellemesinin çalışacağı yerel saat (kapanış + kapanış seansı payı)
    eod_run: time

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def is_open(self, at: datetime | None = None) -> bool:
        local = (at or datetime.now(timezone.utc)).astimezone(self.tz)
        if local.weekday() >= 5:
            return False
        # Gecikmeli veri yüzünden kapanıştan sonra 20 dk daha takip edilir
        end = (datetime.combine(local.date(), self.close) + timedelta(minutes=20)).time()
        return self.open <= local.time() <= end

    def session_close(self, day: date) -> datetime:
        return datetime.combine(day, self.close, tzinfo=self.tz)


MARKETS: dict[str, Market] = {
    "BIST": Market("BIST", ZoneInfo("Europe/Istanbul"), time(9, 55), time(18, 10), time(18, 40)),
    "US": Market("US", ZoneInfo("America/New_York"), time(9, 30), time(16, 0), time(16, 40)),
}

# Saklanan periyotlar
STORED_TIMEFRAMES = ("4h", "1d")
# Günlükten türetilen periyotlar
DERIVED_TIMEFRAMES = ("1w", "1mo", "3mo")
TIMEFRAMES = STORED_TIMEFRAMES + DERIVED_TIMEFRAMES

TIMEFRAME_TABLE = {
    "4h": "bars_4h",
    "1d": "bars_1d",
    "1w": "bars_1w",
    "1mo": "bars_1mo",
    "3mo": "bars_3mo",
}

TIMEFRAME_LABELS = {"4h": "4S", "1d": "G", "1w": "H", "1mo": "A", "3mo": "3A"}


def check_timeframe(tf: str) -> str:
    if tf not in TIMEFRAME_TABLE:
        raise ValueError(f"geçersiz periyot: {tf} (geçerli: {', '.join(TIMEFRAMES)})")
    return tf


def market_of_exchange(exchange: str) -> str:
    return "BIST" if exchange.upper() == "BIST" else "US"
