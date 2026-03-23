"""Пакет автоматизации SAM: запуск процессов, UI-автоматизация, Win32 утилиты."""

from .launcher import close_game, kill_process, launch_game, launch_picker
from .manager_window import process_game
from .picker_session import PickerSession
from .sam_downloader import check_steam_running, download_sam, ensure_sam

__all__ = [
    "close_game",
    "kill_process",
    "launch_game",
    "launch_picker",
    "process_game",
    "PickerSession",
    "check_steam_running",
    "download_sam",
    "ensure_sam",
]
