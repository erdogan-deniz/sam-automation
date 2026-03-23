"""Автоматическая подготовка: проверка Steam, скачивание SAM."""

from __future__ import annotations

import logging

log = logging.getLogger("sam_automation")

# Re-export для обратной совместимости (scripts не трогаем)
from .sam_downloader import download_sam, ensure_sam  # noqa: F401


def check_steam_running() -> bool:
    """Проверяет, запущен ли Steam."""
    try:
        import psutil

        for proc in psutil.process_iter(["name"]):
            if proc.info["name"] and proc.info["name"].lower() in (
                "steam.exe",
                "steam",
            ):
                return True
    except Exception:
        pass
    return False
