from datetime import date, datetime, timezone

import pandas as pd

from app.ingest import completed_4h, completed_daily, trading_day


def bars(stamps):
    idx = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True))
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}, index=idx)


def test_trading_day_handles_both_stamp_styles():
    # Seans açılışı damgası (09:30 NY = 13:30 UTC)
    assert trading_day(pd.Timestamp("2026-03-03 13:30", tz="UTC"), "US") == date(2026, 3, 3)
    # Gece yarısı UTC damgası: NY'de önceki akşam 19:00 olur, yine de doğru gün
    assert trading_day(pd.Timestamp("2026-03-03 00:00", tz="UTC"), "US") == date(2026, 3, 3)
    # BIST: 10:00 İstanbul = 07:00 UTC
    assert trading_day(pd.Timestamp("2026-03-03 07:00", tz="UTC"), "BIST") == date(2026, 3, 3)
    assert trading_day(pd.Timestamp("2026-03-02 21:00", tz="UTC"), "BIST") == date(2026, 3, 3)


def test_completed_daily_drops_open_session():
    df = bars(["2026-03-02 07:00", "2026-03-03 07:00"])
    during = datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)  # 15:00 İstanbul
    out = completed_daily(df, "BIST", during)
    assert list(out.index) == [date(2026, 3, 2)]
    after = datetime(2026, 3, 3, 15, 30, tzinfo=timezone.utc)  # 18:30 İstanbul
    assert list(completed_daily(df, "BIST", after).index) == [date(2026, 3, 2), date(2026, 3, 3)]


def test_completed_4h_bist_and_us():
    # BIST: 10:00 ve 14:00 barları (07:00 / 11:00 UTC)
    df = bars(["2026-03-03 07:00", "2026-03-03 11:00"])
    at_1430 = datetime(2026, 3, 3, 11, 30, tzinfo=timezone.utc)
    assert len(completed_4h(df, "BIST", at_1430)) == 1
    at_1830 = datetime(2026, 3, 3, 15, 30, tzinfo=timezone.utc)
    assert len(completed_4h(df, "BIST", at_1830)) == 2
    # ABD: 13:30-16:00 kısa barı seans kapanışında biter (EST: UTC-5)
    us = bars(["2026-03-03 14:30", "2026-03-03 18:30"])
    at_1620_ny = datetime(2026, 3, 3, 21, 20, tzinfo=timezone.utc)
    assert len(completed_4h(us, "US", at_1620_ny)) == 2
    at_1500_ny = datetime(2026, 3, 3, 20, 0, tzinfo=timezone.utc)
    assert len(completed_4h(us, "US", at_1500_ny)) == 1


def test_expected_last_day():
    from app.jobs import expected_last_day
    from app.markets import MARKETS

    bist = MARKETS["BIST"]
    # Salı 15:00 İstanbul: gün sonu henüz yok -> pazartesi
    assert expected_last_day(bist, datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)) == date(2026, 3, 2)
    # Salı 19:00 İstanbul -> salı
    assert expected_last_day(bist, datetime(2026, 3, 3, 16, 0, tzinfo=timezone.utc)) == date(2026, 3, 3)
    # Pazartesi sabahı -> cuma
    assert expected_last_day(bist, datetime(2026, 3, 2, 6, 0, tzinfo=timezone.utc)) == date(2026, 2, 27)
    # Pazar -> cuma
    assert expected_last_day(bist, datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)) == date(2026, 2, 27)
