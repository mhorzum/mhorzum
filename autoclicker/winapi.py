"""Windows API sarmalayicilari (ctypes).

Fare tiklamalari SendInput ile gonderilir; harici bir bagimlilik gerekmez.
Modul Windows disinda da import edilebilir, ancak fonksiyonlar cagrilirsa
RuntimeError yukselir.
"""

from __future__ import annotations

import ctypes
import sys

IS_WINDOWS = sys.platform == "win32"

# --- Temel tipler --------------------------------------------------------

if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


# --- Sabitler ------------------------------------------------------------

INPUT_MOUSE = 0

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

# GetSystemMetrics indeksleri (sanal ekran = tum monitorler)
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# Sanal tus kodlari
VK_F8 = 0x77
VK_ESCAPE = 0x1B

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def _user32():
    if not IS_WINDOWS:
        raise RuntimeError("Bu ozellik yalnizca Windows uzerinde calisir.")
    return ctypes.windll.user32


# --- Genel fonksiyonlar --------------------------------------------------


def enable_dpi_awareness() -> None:
    """Ekran olcekleme (%125, %150 ...) kullanan sistemlerde koordinatlarin
    fiziksel piksellerle ayni olmasini saglar. Basarisiz olursa sessizce gecer.
    """
    if not IS_WINDOWS:
        return
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_virtual_screen() -> tuple[int, int, int, int]:
    """Tum monitorleri kapsayan sanal ekranin (x, y, genislik, yukseklik) degeri."""
    user32 = _user32()
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def get_cursor_pos() -> tuple[int, int]:
    point = POINT()
    _user32().GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def set_cursor_pos(x: int, y: int) -> None:
    _user32().SetCursorPos(int(x), int(y))


def _send_mouse_event(flags: int) -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
    _user32().SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def click(x: int, y: int, button: str = "left", double: bool = False) -> None:
    """Verilen ekran koordinatina tiklar.

    Imlec once hedefe tasinir; boylece tiklama o noktadaki pencereye (ornegin
    Chrome sekmesine) gider.
    """
    down, up = BUTTON_FLAGS[button]
    set_cursor_pos(x, y)
    # Hedef uygulamanin imlec hareketini islemesi icin cok kisa bir bekleme.
    ctypes.windll.kernel32.Sleep(15)
    _send_mouse_event(down)
    _send_mouse_event(up)
    if double:
        ctypes.windll.kernel32.Sleep(60)
        _send_mouse_event(down)
        _send_mouse_event(up)


def is_key_down(vk_code: int) -> bool:
    """Tus su anda basili mi (uygulama odakta olmasa da calisir)."""
    if not IS_WINDOWS:
        return False
    return bool(_user32().GetAsyncKeyState(vk_code) & 0x8000)
