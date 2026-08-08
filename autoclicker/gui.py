"""Tkinter arayuzu."""

from __future__ import annotations

import queue
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import settings, winapi
from .clicker import ClickConfig, ClickWorker
from .selector import RegionSelector

APP_TITLE = "Otomatik Tiklayici"

BUTTON_LABELS = {"Sol tus": "left", "Sag tus": "right", "Orta tus": "middle"}
BUTTON_LABELS_REVERSE = {v: k for k, v in BUTTON_LABELS.items()}


def parse_number(text: str, name: str) -> float:
    """Metni sayiya cevirir; virgullu yazim da kabul edilir."""
    cleaned = text.strip().replace(",", ".")
    if not cleaned:
        raise ValueError(f"{name} bos birakilamaz.")
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"{name} sayisal olmali (girilen: {text!r}).") from None


class AutoClickerApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        self.master: tk.Tk = master
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.events: "queue.Queue[tuple[str, dict]]" = queue.Queue()
        self.worker: ClickWorker | None = None
        self.region: tuple[int, int, int, int] | None = None
        self._hotkey_state = {winapi.VK_F8: False, winapi.VK_ESCAPE: False}
        self._selecting = False

        self._build_ui()
        self._load_settings()
        self._poll_events()
        self._poll_hotkeys()

        master.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- arayuz ----------------------------------------------------------

    def _build_ui(self) -> None:
        row = 0

        # 1) Alan secimi
        area = ttk.LabelFrame(self, text="1. Tiklama alani", padding=10)
        area.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        area.columnconfigure(0, weight=1)
        self.area_var = tk.StringVar(value="Alan secilmedi")
        ttk.Label(area, textvariable=self.area_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            area,
            text="Chrome penceresini acin, ardindan tiklanacak alani fareyle secin.",
            foreground="#555555",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))
        buttons = ttk.Frame(area)
        buttons.grid(row=2, column=0, sticky="w")
        self.select_btn = ttk.Button(buttons, text="Alan Sec", command=self.select_region)
        self.select_btn.grid(row=0, column=0)
        self.fullscreen_btn = ttk.Button(
            buttons, text="Tum Ekran", command=self.use_full_screen
        )
        self.fullscreen_btn.grid(row=0, column=1, padx=(8, 0))
        row += 1

        # 2) Ayarlar
        opts = ttk.LabelFrame(self, text="2. Ayarlar", padding=10)
        opts.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(3, weight=1)

        self.total_var = tk.StringVar()
        self.min_var = tk.StringVar()
        self.max_var = tk.StringVar()
        self.delay_var = tk.StringVar()
        self.button_var = tk.StringVar()
        self.double_var = tk.BooleanVar()
        self.random_point_var = tk.BooleanVar()
        self.restore_var = tk.BooleanVar()

        ttk.Label(opts, text="Toplam tiklama (0 = sinirsiz):").grid(
            row=0, column=0, sticky="w", pady=3
        )
        ttk.Entry(opts, textvariable=self.total_var, width=10).grid(
            row=0, column=1, sticky="w", pady=3
        )

        ttk.Label(opts, text="Fare tusu:").grid(row=0, column=2, sticky="w", padx=(16, 6))
        ttk.Combobox(
            opts,
            textvariable=self.button_var,
            values=list(BUTTON_LABELS),
            state="readonly",
            width=12,
        ).grid(row=0, column=3, sticky="w")

        ttk.Label(opts, text="En kisa bekleme (sn):").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(opts, textvariable=self.min_var, width=10).grid(
            row=1, column=1, sticky="w", pady=3
        )
        ttk.Label(opts, text="En uzun bekleme (sn):").grid(
            row=1, column=2, sticky="w", padx=(16, 6)
        )
        ttk.Entry(opts, textvariable=self.max_var, width=10).grid(row=1, column=3, sticky="w")

        ttk.Label(opts, text="Baslangic gecikmesi (sn):").grid(
            row=2, column=0, sticky="w", pady=3
        )
        ttk.Entry(opts, textvariable=self.delay_var, width=10).grid(
            row=2, column=1, sticky="w", pady=3
        )

        ttk.Checkbutton(opts, text="Cift tiklama", variable=self.double_var).grid(
            row=2, column=2, columnspan=2, sticky="w", padx=(16, 0)
        )
        ttk.Checkbutton(
            opts, text="Alan icinde rastgele nokta sec", variable=self.random_point_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            opts, text="Tiklamadan sonra imleci geri dondur", variable=self.restore_var
        ).grid(row=3, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=(6, 0))

        ttk.Label(
            opts,
            text="Her tiklama arasinda en kisa ve en uzun sure arasindan rastgele bir "
            "bekleme secilir (orn. 10 - 90 sn).",
            foreground="#555555",
            wraplength=520,
            justify="left",
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        row += 1

        # 3) Kontrol
        control = ttk.LabelFrame(self, text="3. Calistir", padding=10)
        control.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        control.columnconfigure(2, weight=1)

        self.start_btn = ttk.Button(control, text="Baslat  (F8)", command=self.start)
        self.start_btn.grid(row=0, column=0)
        self.stop_btn = ttk.Button(
            control, text="Durdur  (F8 / ESC)", command=self.stop, state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            control,
            text="Kisayollar her yerde calisir: F8 baslat/durdur, ESC acil durdurma.",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        row += 1

        # 4) Durum
        status = ttk.LabelFrame(self, text="Durum", padding=10)
        status.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        status.columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Hazir")
        self.counter_var = tk.StringVar(value="Tiklama: 0")
        self.countdown_var = tk.StringVar(value="-")

        ttk.Label(status, text="Durum:").grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(status, text="Sonraki:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(status, textvariable=self.countdown_var).grid(
            row=1, column=1, sticky="w", pady=(4, 0)
        )
        self.wait_bar = ttk.Progressbar(status, maximum=100)
        self.wait_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(status, textvariable=self.counter_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self.progress = ttk.Progressbar(status, maximum=100)
        self.progress.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        row += 1

        # 5) Kayit
        log_frame = ttk.LabelFrame(self, text="Kayit", padding=6)
        log_frame.grid(row=row, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.rowconfigure(row, weight=1)

        self.log = tk.Text(log_frame, height=9, wrap="none", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    # --- yardimcilar -----------------------------------------------------

    def log_line(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_region(self, region: tuple[int, int, int, int] | None) -> None:
        self.region = region
        if region is None:
            self.area_var.set("Alan secilmedi")
            return
        x1, y1, x2, y2 = region
        self.area_var.set(
            f"Alan: ({x1}, {y1}) - ({x2}, {y2})   •   {x2 - x1} x {y2 - y1} piksel"
        )

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.select_btn.configure(state=state)
        self.fullscreen_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.stop_btn.configure(state="disabled" if enabled else "normal")

    # --- ayarlar ---------------------------------------------------------

    def _load_settings(self) -> None:
        cfg = settings.load()
        self.total_var.set(str(cfg.total_clicks))
        self.min_var.set(str(cfg.min_interval))
        self.max_var.set(str(cfg.max_interval))
        self.delay_var.set(str(cfg.start_delay))
        self.button_var.set(BUTTON_LABELS_REVERSE.get(cfg.button, "Sol tus"))
        self.double_var.set(cfg.double_click)
        self.random_point_var.set(cfg.random_point)
        self.restore_var.set(cfg.restore_cursor)
        x1, y1, x2, y2 = cfg.region
        self._set_region(cfg.region if x2 > x1 and y2 > y1 else None)

    def _collect_config(self) -> ClickConfig:
        total = parse_number(self.total_var.get(), "Toplam tiklama sayisi")
        return ClickConfig(
            region=self.region or (0, 0, 0, 0),
            total_clicks=int(total),
            min_interval=parse_number(self.min_var.get(), "En kisa bekleme"),
            max_interval=parse_number(self.max_var.get(), "En uzun bekleme"),
            start_delay=parse_number(self.delay_var.get(), "Baslangic gecikmesi"),
            button=BUTTON_LABELS.get(self.button_var.get(), "left"),
            double_click=self.double_var.get(),
            random_point=self.random_point_var.get(),
            restore_cursor=self.restore_var.get(),
        )

    # --- eylemler --------------------------------------------------------

    def select_region(self) -> None:
        if self.running:
            return
        self._selecting = True
        self.master.iconify()
        self.master.update()
        time.sleep(0.25)
        try:
            region = RegionSelector(self.master).select()
        finally:
            self._selecting = False
            self.master.deiconify()
            self.master.lift()
        if region:
            self._set_region(region)
            self.log_line(f"Alan secildi: {region}")
        else:
            self.log_line("Alan secimi iptal edildi.")

    def use_full_screen(self) -> None:
        if self.running:
            return
        vx, vy, vw, vh = winapi.get_virtual_screen()
        self._set_region((vx, vy, vx + vw, vy + vh))
        self.log_line("Tum ekran alan olarak secildi.")

    def start(self) -> None:
        if self.running:
            return
        try:
            config = self._collect_config()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        errors = config.validate()
        if errors:
            messagebox.showerror(APP_TITLE, "\n".join(errors))
            return

        settings.save(config)

        self.progress.configure(value=0)
        self.wait_bar.configure(value=0)
        self.counter_var.set("Tiklama: 0")
        hedef = "sinirsiz" if config.total_clicks == 0 else str(config.total_clicks)
        self.log_line(
            f"Baslatildi — hedef: {hedef} tiklama, aralik: "
            f"{config.min_interval:g}-{config.max_interval:g} sn"
        )

        self.worker = ClickWorker(config, self._emit)
        self.worker.start()
        self._set_controls_enabled(False)
        self.status_var.set("Calisiyor")

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.status_var.set("Durduruluyor...")

    def _emit(self, event_type: str, **payload) -> None:
        """Is parcacigindan cagrilir; olaylari arayuz kuyruguna aktarir."""
        self.events.put((event_type, payload))

    # --- dongu -----------------------------------------------------------

    def _poll_events(self) -> None:
        try:
            while True:
                event_type, payload = self.events.get_nowait()
                self._handle_event(event_type, payload)
        except queue.Empty:
            pass
        self.after(80, self._poll_events)

    def _handle_event(self, event_type: str, payload: dict) -> None:
        if event_type == "status":
            self.status_var.set(payload["text"])
        elif event_type == "countdown":
            remaining = payload["remaining"]
            interval = payload["interval"]
            label = payload.get("label", "Sonraki")
            self.countdown_var.set(
                f"{label}: {remaining:0.1f} sn  (secilen aralik {interval:0.1f} sn)"
            )
            done_ratio = 0.0 if interval <= 0 else (interval - remaining) / interval
            self.wait_bar.configure(value=max(0.0, min(100.0, done_ratio * 100)))
        elif event_type == "click":
            index = payload["index"]
            total = payload["total"]
            self.counter_var.set(
                f"Tiklama: {index}" + (f" / {total}" if total else " (sinirsiz)")
            )
            if total:
                self.progress.configure(value=index / total * 100)
            self.log_line(f"Tiklama #{index} → ({payload['x']}, {payload['y']})")
        elif event_type == "finished":
            self.status_var.set(payload["reason"])
            self.countdown_var.set("-")
            self.wait_bar.configure(value=0)
            self.log_line(f"{payload['reason']} — toplam {payload['done']} tiklama.")
            self._set_controls_enabled(True)
            self.worker = None

    def _poll_hotkeys(self) -> None:
        for vk in (winapi.VK_F8, winapi.VK_ESCAPE):
            down = winapi.is_key_down(vk)
            # Alan secimi sirasinda kisayollar devre disi kalir.
            if down and not self._hotkey_state[vk] and not self._selecting:
                self._on_hotkey(vk)
            self._hotkey_state[vk] = down
        self.after(50, self._poll_hotkeys)

    def _on_hotkey(self, vk: int) -> None:
        if vk == winapi.VK_F8:
            if self.running:
                self.stop()
            else:
                self.start()
        elif vk == winapi.VK_ESCAPE and self.running:
            self.log_line("ESC ile acil durdurma.")
            self.stop()

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askokcancel(
                APP_TITLE, "Tiklama devam ediyor. Yine de kapatilsin mi?"
            ):
                return
            self.stop()
        try:
            settings.save(self._collect_config())
        except ValueError:
            pass
        self.master.destroy()


def main() -> None:
    winapi.enable_dpi_awareness()
    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(620, 720)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    AutoClickerApp(root)
    root.mainloop()
