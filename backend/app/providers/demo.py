"""İnternet gerektirmeyen sentetik veri sağlayıcı (deneme ve testler için).

Her sembol için sabit tohumlu bir rastgele yürüyüş üretir; aynı sembol her
çağrıda aynı geçmişi verir, böylece artımlı güncellemeler tutarlı kalır.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta, timezone

import numpy as np
import pandas as pd

from ..markets import MARKETS
from .base import Quote, SymbolInfo, empty_bars

DEMO_BIST = [
    ("THYAO", "Türk Hava Yolları", "Transportation", ["XU030", "XU100"]),
    ("GARAN", "Garanti BBVA", "Finance", ["XU030", "XU100"]),
    ("AKBNK", "Akbank", "Finance", ["XU030", "XU100"]),
    ("ASELS", "Aselsan", "Electronic Technology", ["XU030", "XU100"]),
    ("BIMAS", "BİM Mağazalar", "Retail Trade", ["XU030", "XU100"]),
    ("EREGL", "Ereğli Demir Çelik", "Non-Energy Minerals", ["XU030", "XU100"]),
    ("FROTO", "Ford Otosan", "Consumer Durables", ["XU030", "XU100"]),
    ("KCHOL", "Koç Holding", "Finance", ["XU030", "XU100"]),
    ("SISE", "Şişecam", "Process Industries", ["XU030", "XU100"]),
    ("TUPRS", "Tüpraş", "Energy Minerals", ["XU030", "XU100"]),
    ("YKBNK", "Yapı Kredi", "Finance", ["XU030", "XU100"]),
    ("TCELL", "Turkcell", "Communications", ["XU030", "XU100"]),
    ("PGSUS", "Pegasus", "Transportation", ["XU100"]),
    ("TOASO", "Tofaş", "Consumer Durables", ["XU100"]),
    ("ARCLK", "Arçelik", "Consumer Durables", ["XU100"]),
    ("MGROS", "Migros", "Retail Trade", ["XU100"]),
    ("ENKAI", "Enka İnşaat", "Industrial Services", ["XU100"]),
    ("SAHOL", "Sabancı Holding", "Finance", ["XU030", "XU100"]),
    ("ULKER", "Ülker", "Consumer Non-Durables", ["XU100"]),
    ("DOAS", "Doğuş Otomotiv", "Retail Trade", []),
]

DEMO_US = [
    ("NASDAQ", "AAPL", "Apple Inc.", "Electronic Technology", ["SPX", "NDX"]),
    ("NASDAQ", "MSFT", "Microsoft Corp.", "Technology Services", ["SPX", "NDX"]),
    ("NASDAQ", "NVDA", "NVIDIA Corp.", "Electronic Technology", ["SPX", "NDX"]),
    ("NASDAQ", "AMZN", "Amazon.com Inc.", "Retail Trade", ["SPX", "NDX"]),
    ("NASDAQ", "META", "Meta Platforms", "Technology Services", ["SPX", "NDX"]),
    ("NASDAQ", "GOOGL", "Alphabet Inc. A", "Technology Services", ["SPX", "NDX"]),
    ("NASDAQ", "TSLA", "Tesla Inc.", "Consumer Durables", ["SPX", "NDX"]),
    ("NASDAQ", "AVGO", "Broadcom Inc.", "Electronic Technology", ["SPX", "NDX"]),
    ("NASDAQ", "COST", "Costco Wholesale", "Retail Trade", ["SPX", "NDX"]),
    ("NASDAQ", "AMD", "Advanced Micro Devices", "Electronic Technology", ["SPX", "NDX"]),
    ("NYSE", "JPM", "JPMorgan Chase", "Finance", ["SPX"]),
    ("NYSE", "V", "Visa Inc.", "Commercial Services", ["SPX"]),
    ("NYSE", "XOM", "Exxon Mobil", "Energy Minerals", ["SPX"]),
    ("NYSE", "UNH", "UnitedHealth Group", "Health Services", ["SPX"]),
    ("NYSE", "KO", "Coca-Cola Co.", "Consumer Non-Durables", ["SPX"]),
    ("NYSE", "BRK.B", "Berkshire Hathaway B", "Finance", ["SPX"]),
    ("NASDAQ", "PDD", "PDD Holdings", "Retail Trade", ["NDX"]),
    ("NASDAQ", "ASML", "ASML Holding", "Electronic Technology", ["NDX"]),
    ("NYSE", "WMT", "Walmart Inc.", "Retail Trade", ["SPX"]),
    ("NYSE", "LLY", "Eli Lilly", "Health Technology", ["SPX"]),
]

# Sentetik verinin başladığı sabit tarih (geçmiş her çağrıda aynı olsun diye)
EPOCH = datetime(2015, 1, 1, tzinfo=timezone.utc)


def _seed(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "little")


class DemoProvider:
    name = "demo"

    def universe(self) -> list[SymbolInfo]:
        out = [SymbolInfo("BIST", "BIST", t, n, s, list(ix)) for t, n, s, ix in DEMO_BIST]
        out += [SymbolInfo("US", ex, t, n, s, list(ix)) for ex, t, n, s, ix in DEMO_US]
        return out

    def _market(self, exchange: str):
        return MARKETS["BIST" if exchange == "BIST" else "US"]

    def _bars_4h(self, exchange: str, ticker: str) -> pd.DataFrame:
        """EPOCH'tan bugüne kadar günde iki 4 saatlik bar üretir."""
        m = self._market(exchange)
        starts = [time(10, 0), time(14, 0)] if exchange == "BIST" else [time(9, 30), time(13, 30)]

        today = datetime.now(m.tz).date()
        days = pd.bdate_range(EPOCH.date(), today)
        stamps = [
            datetime.combine(d.date(), t, tzinfo=m.tz).astimezone(timezone.utc) for d in days for t in starts
        ]
        n = len(stamps)
        rng = np.random.default_rng(_seed(f"{exchange}:{ticker}"))
        base = 5 + (_seed(ticker) % 400)
        drift = rng.normal(0.00008, 0.0001)
        rets = rng.normal(drift, 0.014, n)
        close = base * np.exp(np.cumsum(rets))
        open_ = np.concatenate([[base], close[:-1]]) * (1 + rng.normal(0, 0.002, n))
        spread = np.abs(rng.normal(0, 0.008, n))
        high = np.maximum(open_, close) * (1 + spread)
        low = np.minimum(open_, close) * (1 - spread)
        volume = np.round(rng.lognormal(13, 0.6, n))
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=pd.DatetimeIndex(stamps),
        )
        return df.round(4)

    def history(self, exchange: str, ticker: str, timeframe: str, start: datetime) -> pd.DataFrame:
        bars = self._bars_4h(exchange, ticker)
        if timeframe == "1d":
            m = self._market(exchange)
            local_day = bars.index.tz_convert(m.tz).normalize()
            g = bars.groupby(local_day)
            daily = pd.DataFrame(
                {
                    "open": g["open"].first(),
                    "high": g["high"].max(),
                    "low": g["low"].min(),
                    "close": g["close"].last(),
                    "volume": g["volume"].sum(),
                }
            )
            # TradingView günlük barları seans açılışıyla damgalar; aynısını taklit et
            open_t = time(10, 0) if exchange == "BIST" else time(9, 30)
            daily.index = pd.DatetimeIndex(
                [datetime.combine(d.date(), open_t, tzinfo=m.tz).astimezone(timezone.utc) for d in daily.index]
            )
            bars = daily
        elif timeframe != "4h":
            raise ValueError(timeframe)
        start_ts = pd.Timestamp(start)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        out = bars[bars.index >= start_ts]
        return out if not out.empty else empty_bars()

    def quotes(self, market: str) -> list[Quote]:
        out = []
        minute = int(datetime.now(timezone.utc).timestamp() // 60)
        for s in self.universe():
            if s.market != market:
                continue
            daily = self.history(s.exchange, s.ticker, "1d", datetime.now(timezone.utc) - timedelta(days=10))
            if daily.empty:
                continue
            last = daily.iloc[-1]
            prev_close = daily["close"].iloc[-2] if len(daily) > 1 else last["open"]
            wiggle = np.random.default_rng(_seed(f"{s.ticker}:{minute}")).normal(0, 0.002)
            price = round(float(last["close"]) * (1 + wiggle), 4)
            out.append(
                Quote(
                    exchange=s.exchange,
                    ticker=s.ticker,
                    price=price,
                    open=float(last["open"]),
                    high=max(float(last["high"]), price),
                    low=min(float(last["low"]), price),
                    volume=float(last["volume"]),
                    change_pct=round((price / prev_close - 1) * 100, 2),
                    update_mode="demo",
                )
            )
        return out
