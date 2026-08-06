# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Windows auto clicker desktop app ("Otomatik Tıklayıcı"): clicks inside a
user-selected screen region at random intervals. Pure standard library —
Tkinter for the UI, Windows `SendInput` via `ctypes` for the clicks.
PyInstaller is used only to produce the `.exe`.

## Layout

- `autoclicker/winapi.py` — ctypes wrappers: `SendInput` clicks, cursor position,
  virtual-screen metrics, `GetAsyncKeyState` hotkeys, DPI awareness. Guarded by
  `IS_WINDOWS`, so the module imports (but does not run) on Linux/macOS.
- `autoclicker/clicker.py` — `ClickConfig` (dataclass + validation + JSON
  serialisation) and `ClickWorker`, a daemon thread that emits `status`,
  `countdown`, `click`, `finished` events.
- `autoclicker/gui.py` — Tkinter UI. Worker events cross into the UI thread
  through a `queue.Queue` drained by an `after()` loop; hotkeys are polled the
  same way.
- `autoclicker/selector.py` — fullscreen translucent overlay for drag-selecting
  the click region.
- `autoclicker/settings.py` — persists settings to `%APPDATA%\AutoClicker\settings.json`.
- `main.py` — entry point used by `OtomatikTiklayici.spec`.

## Commands

```bash
python main.py                              # run from source (Windows)
python -m unittest discover -s tests -v     # tests (no tkinter/Windows needed)
python -m PyInstaller --noconfirm --clean OtomatikTiklayici.spec   # build .exe
```

`build.bat` wraps the PyInstaller step; `.github/workflows/build-windows.yml`
runs tests and uploads the built `.exe` as an artifact.

## Conventions

- No third-party runtime dependencies — keep it standard library only.
- UI strings, code comments and docstrings are in Turkish, ASCII-only inside the
  source (Turkish characters are fine in Markdown).
- Anything touching the Windows API belongs in `winapi.py`, so the rest of the
  package stays testable off-Windows.
