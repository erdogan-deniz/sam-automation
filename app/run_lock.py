"""Lock-файл против одновременного запуска farm и boost.

Оба скрипта поднимают SAM.Game.exe и конфликтуют за Steam global user
('failed to connect to global user'), поэтому запускать их вместе нельзя.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psutil

log = logging.getLogger("sam_automation")

_PROJECT_ROOT = Path(__file__).parent.parent
LOCK_FILE = _PROJECT_ROOT / "data" / ".sam_run.lock"


def acquire_run_lock(name: str) -> None:
    """Захватывает lock. Если другой скрипт (farm/boost) активен — RuntimeError.

    Args:
        name: имя текущего скрипта (для понятного сообщения).
    """
    if LOCK_FILE.exists():
        try:
            pid_str, _, owner = LOCK_FILE.read_text(encoding="utf-8").partition(
                ":"
            )
            alive = psutil.pid_exists(int(pid_str.strip()))
        except (ValueError, OSError):
            alive = False  # битый lock — перезапишем
        else:
            if alive:
                raise RuntimeError(
                    f"Уже запущен '{owner.strip()}' (PID {pid_str.strip()}). "
                    f"farm и boost нельзя запускать одновременно — "
                    f"останови первый или дождись его завершения."
                )

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(f"{os.getpid()}:{name}", encoding="utf-8")
    log.debug("Run-lock захвачен: %s (PID %d)", name, os.getpid())


def release_run_lock() -> None:
    """Снимает lock (без ошибки, если файла нет)."""
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass
