from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import Provider, Quote, SymbolInfo


@lru_cache(maxsize=1)
def get_provider() -> Provider:
    if settings.data_provider == "demo":
        from .demo import DemoProvider

        return DemoProvider()
    if settings.data_provider == "tradingview":
        from .tradingview import TradingViewProvider

        return TradingViewProvider()
    raise ValueError(f"bilinmeyen DATA_PROVIDER: {settings.data_provider}")


__all__ = ["Provider", "Quote", "SymbolInfo", "get_provider"]
