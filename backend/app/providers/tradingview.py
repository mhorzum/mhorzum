"""TradingView üzerinden veri (borsapy + tradingview-screener).

- Geçmiş barlar: TradingView grafik WebSocket'i (borsapy'nin istemcisi)
- Evren ve anlık fiyatlar: TradingView tarayıcı (scanner) API'si

Giriş yapılmadan veriler 15 dk gecikmelidir. Resmi olmayan bir API'dir;
yalnızca kişisel kullanım içindir.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import settings
from .base import Quote, SymbolInfo, empty_bars

log = logging.getLogger(__name__)

# TradingView endeks kodları -> uygulamadaki etiket
BIST_INDEXES = {"XU030": "SYML:BIST;XU030", "XU100": "SYML:BIST;XU100"}
US_INDEXES = {"SPX": "SYML:SP;SPX", "NDX": "SYML:NASDAQ;NDX"}

ISTANBUL = ZoneInfo("Europe/Istanbul")

QUOTE_COLUMNS = ["close", "open", "high", "low", "volume", "change", "update_mode"]


class TradingViewProvider:
    name = "tradingview"

    def __init__(self) -> None:
        from borsapy._providers.tradingview import get_tradingview_provider

        self._tv = get_tradingview_provider()
        self._cookies: dict[str, str] | None = None
        if settings.tv_session:
            from borsapy import set_tradingview_auth

            set_tradingview_auth(session=settings.tv_session, session_sign=settings.tv_session_sign)
            self._cookies = {"sessionid": settings.tv_session, "sessionid_sign": settings.tv_session_sign}

    # ------------------------------------------------------------------ evren
    def _scan(self, query) -> pd.DataFrame:
        kwargs = {"cookies": self._cookies} if self._cookies else {}
        _, df = query.get_scanner_data(**kwargs)
        return df

    def _index_members(self, code: str) -> set[str]:
        from tradingview_screener import Query

        df = self._scan(Query().set_index(code).select("name").limit(2000))
        return set(df["ticker"])

    def universe(self) -> list[SymbolInfo]:
        from tradingview_screener import Query, col

        out: dict[str, SymbolInfo] = {}

        bist = self._scan(
            Query()
            .set_markets("turkey")
            .select("name", "description", "sector", "exchange", "type")
            .where(col("exchange") == "BIST", col("type") == "stock")
            .limit(2000)
        )
        for row in bist.itertuples(index=False):
            exchange, ticker = row.ticker.split(":", 1)
            out[row.ticker] = SymbolInfo("BIST", exchange, ticker, row.description, row.sector)
        for label, code in BIST_INDEXES.items():
            try:
                members = self._index_members(code)
            except Exception as e:  # endeks etiketi olmadan da evren kullanılabilir
                log.warning("%s üyeleri alınamadı: %s", label, e)
                continue
            for t in members:
                if t in out:
                    out[t].indexes.append(label)

        for label, code in US_INDEXES.items():
            df = self._scan(Query().set_index(code).select("name", "description", "sector").limit(2000))
            for row in df.itertuples(index=False):
                if row.ticker not in out:
                    exchange, ticker = row.ticker.split(":", 1)
                    out[row.ticker] = SymbolInfo("US", exchange, ticker, row.description, row.sector)
                out[row.ticker].indexes.append(label)

        return list(out.values())

    # ---------------------------------------------------------------- geçmiş
    def history(self, exchange: str, ticker: str, timeframe: str, start: datetime) -> pd.DataFrame:
        if timeframe not in ("4h", "1d"):
            raise ValueError(timeframe)
        # borsapy başlangıcı saat dilimsiz (İstanbul saati) bekliyor; saat dilimli
        # tarih verilirse kendi içinde datetime.now() ile çıkarırken TypeError atıyor
        if start.tzinfo is not None:
            start = start.astimezone(ISTANBUL).replace(tzinfo=None)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                df = self._tv.get_history(ticker, interval=timeframe, start=start, exchange=exchange)
                break
            except Exception as e:  # ağ hataları / geçici TradingView hataları
                last_err = e
                if "No data received" in str(e):
                    return empty_bars()
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"{exchange}:{ticker} {timeframe} indirilemedi: {last_err}")

        if df.empty:
            return empty_bars()
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
        df.index.name = None
        return df.astype(float).sort_index()

    # ----------------------------------------------------------------- anlık
    def quotes(self, market: str) -> list[Quote]:
        from tradingview_screener import Query, col

        if market == "BIST":
            q = (
                Query()
                .set_markets("turkey")
                .select(*QUOTE_COLUMNS)
                .where(col("exchange") == "BIST", col("type") == "stock")
                .limit(2000)
            )
        else:
            q = Query().set_index(*US_INDEXES.values()).select(*QUOTE_COLUMNS).limit(2000)
        df = self._scan(q)

        out: list[Quote] = []
        for row in df.itertuples(index=False):
            if row.close is None or (isinstance(row.close, float) and math.isnan(row.close)):
                continue
            exchange, ticker = row.ticker.split(":", 1)
            out.append(
                Quote(
                    exchange=exchange,
                    ticker=ticker,
                    price=float(row.close),
                    open=_f(row.open),
                    high=_f(row.high),
                    low=_f(row.low),
                    volume=_f(row.volume),
                    change_pct=_f(row.change),
                    update_mode=row.update_mode,
                )
            )
        return out


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v
