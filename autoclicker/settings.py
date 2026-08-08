"""Ayarlarin diske kaydedilmesi / okunmasi."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .clicker import ClickConfig

APP_NAME = "AutoClicker"


def config_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / APP_NAME / "settings.json"


def load() -> ClickConfig:
    path = config_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            return ClickConfig.from_dict(json.load(fh))
    except (OSError, ValueError, TypeError):
        return ClickConfig()


def save(config: ClickConfig) -> None:
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(config.to_dict(), fh, indent=2)
    except OSError:
        # Ayar kaydedilemezse uygulama calismaya devam eder.
        pass
