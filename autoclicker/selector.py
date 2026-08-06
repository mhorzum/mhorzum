"""Ekran uzerinde fare ile alan secme katmani."""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from . import winapi


class RegionSelector:
    """Tum ekrani kaplayan yari saydam bir pencere acar ve kullanicinin
    fareyle surukleyerek bir dikdortgen secmesini bekler.

    Kullanim:
        region = RegionSelector(root).select()   # (x1, y1, x2, y2) veya None
    """

    def __init__(self, master: tk.Misc):
        self.master = master
        self.result: Optional[tuple[int, int, int, int]] = None
        self._start: Optional[tuple[int, int]] = None
        self._rect_id: Optional[int] = None

    def select(self) -> Optional[tuple[int, int, int, int]]:
        vx, vy, vw, vh = winapi.get_virtual_screen()

        top = tk.Toplevel(self.master)
        self.top = top
        top.overrideredirect(True)
        top.geometry(f"{vw}x{vh}+{vx}+{vy}")
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.35)
        top.configure(bg="black", cursor="crosshair")

        self._offset = (vx, vy)

        canvas = tk.Canvas(
            top, bg="black", highlightthickness=0, cursor="crosshair"
        )
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas

        canvas.create_text(
            vw // 2,
            40,
            text="Tiklama alanini secmek icin fareyle surukleyin  —  Iptal: ESC",
            fill="white",
            font=("Segoe UI", 16, "bold"),
        )

        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        top.bind("<Escape>", lambda _e: self._cancel())

        top.focus_force()
        top.grab_set()
        self.master.wait_window(top)
        return self.result

    # --- olaylar ---------------------------------------------------------

    def _on_press(self, event: tk.Event) -> None:
        self._start = (event.x, event.y)
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#00e5ff", width=2, fill="white"
        )

    def _on_drag(self, event: tk.Event) -> None:
        if self._start is None or self._rect_id is None:
            return
        x0, y0 = self._start
        self.canvas.coords(self._rect_id, x0, y0, event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        if self._start is None:
            return
        x0, y0 = self._start
        x1, y1 = event.x, event.y
        left, right = sorted((x0, x1))
        top_, bottom = sorted((y0, y1))

        ox, oy = self._offset
        if right - left < 2 or bottom - top_ < 2:
            # Tek tiklama gibi cok kucuk secimler yok sayilir.
            self.result = None
        else:
            self.result = (left + ox, top_ + oy, right + ox, bottom + oy)
        self._close()

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()
