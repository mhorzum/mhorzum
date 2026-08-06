"""Otomatik tiklama motoru (arka plan is parcacigi)."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Callable

from . import winapi


@dataclass
class ClickConfig:
    """Tiklama ayarlari."""

    # Ekran koordinatlarinda alan: (sol, ust, sag, alt)
    region: tuple[int, int, int, int] = (0, 0, 0, 0)
    # 0 = sinirsiz
    total_clicks: int = 10
    min_interval: float = 10.0
    max_interval: float = 90.0
    start_delay: float = 3.0
    button: str = "left"
    double_click: bool = False
    # True: alan icinde rastgele nokta, False: alanin merkezi
    random_point: bool = True
    # Tiklamadan sonra imleci onceki konumuna dondur
    restore_cursor: bool = False

    def validate(self) -> list[str]:
        """Ayarlari dogrular, hata mesajlarinin listesini dondurur."""
        errors: list[str] = []
        x1, y1, x2, y2 = self.region
        if x2 - x1 < 1 or y2 - y1 < 1:
            errors.append("Gecerli bir tiklama alani secilmedi.")
        if self.total_clicks < 0:
            errors.append("Toplam tiklama sayisi negatif olamaz.")
        if self.min_interval < 0.05:
            errors.append("En kisa sure en az 0.05 saniye olmali.")
        if self.max_interval < self.min_interval:
            errors.append("En uzun sure, en kisa sureden kucuk olamaz.")
        if self.start_delay < 0:
            errors.append("Baslangic gecikmesi negatif olamaz.")
        if self.button not in winapi.BUTTON_FLAGS:
            errors.append("Gecersiz fare tusu.")
        return errors

    def to_dict(self) -> dict:
        data = asdict(self)
        data["region"] = list(self.region)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ClickConfig":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        if "region" in clean and clean["region"] is not None:
            try:
                clean["region"] = tuple(int(v) for v in clean["region"])[:4]
            except (TypeError, ValueError):
                clean.pop("region")
            else:
                if len(clean["region"]) != 4:
                    clean.pop("region")
        return cls(**clean)


class ClickWorker(threading.Thread):
    """Ayarlara gore tiklamalari yapan is parcacigi.

    Olaylar `emit(event_type, **payload)` ile disariya bildirilir. Emit
    cagrisi bu is parcacigindan yapilir; arayuz tarafinda kuyruk kullanilmali.

    Olaylar:
        status    (text)                     - genel durum mesaji
        countdown (remaining, interval)      - sonraki tiklamaya kalan sure
        click     (index, total, x, y)       - tiklama yapildi
        finished  (reason, done)             - is bitti / durduruldu
    """

    TICK = 0.1  # geri sayim guncelleme araligi (sn)

    def __init__(self, config: ClickConfig, emit: Callable[..., None]):
        super().__init__(daemon=True)
        self.config = config
        self._emit = emit
        self._stop_event = threading.Event()
        self.clicks_done = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    # --- yardimcilar -----------------------------------------------------

    def _pick_point(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.config.region
        if self.config.random_point:
            return random.randint(x1, x2 - 1), random.randint(y1, y2 - 1)
        return (x1 + x2) // 2, (y1 + y2) // 2

    def _wait(self, seconds: float, label: str) -> bool:
        """Kesilebilir bekleme. Durdurulursa False dondurur."""
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self._emit("countdown", remaining=remaining, interval=seconds, label=label)
            if self._stop_event.wait(min(self.TICK, remaining)):
                return False

    # --- ana dongu -------------------------------------------------------

    def run(self) -> None:
        cfg = self.config
        total = cfg.total_clicks
        reason = "Tamamlandi"

        try:
            if cfg.start_delay > 0:
                self._emit("status", text="Baslangic gecikmesi bekleniyor...")
                if not self._wait(cfg.start_delay, "Baslangic"):
                    self._emit("finished", reason="Durduruldu", done=self.clicks_done)
                    return

            while not self._stop_event.is_set():
                if total and self.clicks_done >= total:
                    break

                x, y = self._pick_point()
                previous = winapi.get_cursor_pos() if cfg.restore_cursor else None
                winapi.click(x, y, cfg.button, cfg.double_click)
                if previous is not None:
                    winapi.set_cursor_pos(*previous)

                self.clicks_done += 1
                self._emit("click", index=self.clicks_done, total=total, x=x, y=y)

                if total and self.clicks_done >= total:
                    break

                interval = random.uniform(cfg.min_interval, cfg.max_interval)
                self._emit("status", text="Sonraki tiklama bekleniyor...")
                if not self._wait(interval, "Sonraki tiklama"):
                    reason = "Durduruldu"
                    break
            else:
                reason = "Durduruldu"
        except Exception as exc:  # beklenmeyen hata arayuze bildirilir
            reason = f"Hata: {exc}"

        if self._stop_event.is_set() and reason == "Tamamlandi":
            reason = "Durduruldu"
        self._emit("finished", reason=reason, done=self.clicks_done)
