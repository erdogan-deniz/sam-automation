"""Lock-файл против одновременного запуска farm и boost.

Оба скрипта поднимают SAM.Game.exe и конфликтуют за Steam global user
('failed to connect to global user'), поэтому запускать их вместе нельзя.

Лок хранит `PID:create_time:name`. Сверка create_time отсекает PID-reuse
(тот же номер PID, но другой процесс), захват атомарен через O_EXCL, а release
снимает ТОЛЬКО собственный лок (не чужой).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psutil

log = logging.getLogger("sam_automation")

_PROJECT_ROOT = Path(__file__).parent.parent
LOCK_FILE = _PROJECT_ROOT / "data" / ".sam_run.lock"


def _proc_create_time(pid: int) -> str | None:
    """create_time процесса как стабильная строка; None если PID мёртв/недоступен."""
    try:
        return f"{psutil.Process(pid).create_time():.3f}"
    except (psutil.Error, ValueError):
        return None


def _own_token(name: str) -> str:
    pid = os.getpid()
    return f"{pid}:{_proc_create_time(pid)}:{name}"


def _is_live_owner(pid_str: str, ctime_str: str) -> bool:
    """Жив ли владелец лока: PID существует И его create_time совпадает.

    Совпадение create_time отсекает PID-reuse: тот же номер PID у другого
    процесса даёт другой create_time → лок считается устаревшим, а не живым.
    """
    try:
        pid = int(pid_str)
    except ValueError:
        return False
    ctime = _proc_create_time(pid)
    return ctime is not None and ctime == ctime_str


def _remove_stale_lock(expected: str) -> None:
    """Снимает lock ТОЛЬКО если на диске всё ещё ровно `expected` (мёртвый токен).

    Между чтением мёртвого токена в acquire_run_lock и этим unlink другой
    инстанс мог успеть создать СВОЙ живой лок. Безусловный unlink снёс бы чужой
    живой лок — оба инстанса решили бы, что владеют локом → параллельный
    farm+boost, ровно то, что лок обязан предотвращать. Compare-and-delete:
    содержимое изменилось → не трогаем, пусть повторный цикл перечитает и найдёт
    живого владельца (→ RuntimeError).
    """
    try:
        current = LOCK_FILE.read_text(encoding="utf-8")
    except OSError:
        return  # уже удалён/недоступен — нечего сносить
    if current != expected:
        return  # лок подменён (чужой захват) — не наш stale-токен
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


def acquire_run_lock(name: str) -> None:
    """Атомарно захватывает lock. Если другой farm/boost активен — RuntimeError.

    Args:
        name: имя текущего скрипта (для понятного сообщения).
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = _own_token(name)
    for _ in range(2):
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            # Лок уже есть — жив ли владелец?
            try:
                raw = LOCK_FILE.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            parts = raw.split(":", 2)
            pid_str, ctime_str, owner = (parts + ["", "", ""])[:3]
            if _is_live_owner(pid_str, ctime_str):
                raise RuntimeError(
                    f"Уже запущен '{owner.strip()}' (PID {pid_str.strip()}). "
                    f"farm и boost нельзя запускать одновременно — останови "
                    f"первый или дождись его завершения."
                )
            # Мёртвый/битый/PID-reuse лок — снести (только если содержимое
            # неизменно: compare-and-delete против гонки с чужим захватом)
            # и повторить атомарный захват.
            _remove_stale_lock(raw)
            continue
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token)
            log.debug("Run-lock захвачен: %s (PID %d)", name, os.getpid())
            return
    raise RuntimeError(
        "Не удалось захватить run-lock (гонка с другим инстансом) — повтори."
    )


def release_run_lock() -> None:
    """Снимает lock ТОЛЬКО если он наш (совпадают PID и create_time).

    Чужой лок (перехваченный или созданный другим инстансом) не трогаем.
    """
    try:
        content = LOCK_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    pid_str, _, rest = content.partition(":")
    ctime_str, _, _ = rest.partition(":")
    if pid_str == str(os.getpid()) and ctime_str == _proc_create_time(
        os.getpid()
    ):
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
