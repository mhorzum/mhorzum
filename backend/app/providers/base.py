"""Veri sağlayıcı arayüzü."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import pandas as pd


@dataclass
class SymbolInfo:
    market: str  # 'BIST' | 'US'
    exchange: str  # 'BIST' | 'NASDAQ' | 'NYSE' ...
    ticker: str
    name: str | None = None
    sector: str | None = None
    indexes: list[str] = field(default_factory=list)


@dataclass
class Quote:
    exchange: str
    ticker: str
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    change_pct: float | None = None
    update_mode: str | None = None


class Provider(Protocol):
    name: str

    def universe(self) -> list[SymbolInfo]:
        """BIST hisseleri + S&P 500 + Nasdaq-100 bileşenleri."""

    def history(self, exchange: str, ticker: str, timeframe: str, start: datetime) -> pd.DataFrame:
        """OHLCV geçmişi.

        timeframe: '4h' veya '1d'.
        Dönen DataFrame: UTC zaman damgalı index (barın açılış zamanı),
        sütunlar: open, high, low, close, volume.
        """

    def quotes(self, market: str) -> list[Quote]:
        """Bir borsadaki evren sembollerinin anlık (15 dk gecikmeli) fiyatları."""


def empty_bars() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"],
        index=pd.DatetimeIndex([], tz="UTC"),
        dtype=float,
    )
