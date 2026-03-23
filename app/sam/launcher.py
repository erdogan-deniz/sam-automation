"""Запуск и остановка процессов SAM (SAM.Picker.exe, SAM.Game.exe)."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from pywinauto import Application

from ..exceptions import SAMConnectionError, SAMLaunchError
from .picker_session import PickerSession
from .win32_utils import _kill_pid

log = logging.getLogger("sam_automation")


def launch_game(sam_game_exe: str, appid: int) -> subprocess.Popen:
    """Запускает SAM.Game.exe для указанного appid (card farming — без UI автоматизации).

    В отличие от launch_picker, не подключается через pywinauto —
    SAM.Game.exe работает тихо, сохраняя игровую сессию в Steam.

    Raises:
        RuntimeError: если exe не удалось запустить.
    """
    exe = Path(sam_game_exe)
    try:
        proc = subprocess.Popen([str(exe), str(appid)], cwd=str(exe.parent))
    except OSError as e:
        raise RuntimeError(
            f"Не удалось запустить SAM.Game.exe для {appid}: {e}"
        ) from e
    log.info("[%d] SAM.Game.exe запущен (PID=%d)", appid, proc.pid)
    return proc


def close_game(game_app: Application | None) -> None:
    """Убивает SAM.Game по PID через Win32 API. Не трогает Picker."""
    if game_app is None:
        return
    try:
        _kill_pid(game_app.process)
    except Exception:
        pass


def launch_picker(
    exe_path: str, launch_delay: float = 10.0
) -> tuple[subprocess.Popen, PickerSession]:
    """Запускает SAM.Picker.exe, подключается и создаёт PickerSession."""
    exe = Path(exe_path)
    picker = exe.parent / "SAM.Picker.exe"
    if not picker.exists():
        raise SAMLaunchError(f"SAM.Picker.exe не найден: {picker}")

    log.info("Запуск SAM.Picker.exe ...")

    try:
        proc = subprocess.Popen([str(picker)], cwd=str(picker.parent))
    except OSError as e:
        raise SAMLaunchError(f"Не удалось запустить SAM.Picker.exe: {e}") from e

    deadline = time.time() + launch_delay
    last_error: Exception | None = None

    while time.time() < deadline:
        if proc.poll() is not None:
            raise SAMLaunchError(
                f"SAM.Picker.exe завершился с кодом {proc.returncode}"
            )
        try:
            app = Application(backend="uia").connect(
                process=proc.pid, timeout=1
            )
            win = app.top_window()
            win.wait("visible", timeout=2)
            session = PickerSession(app)
            log.info("SAM.Picker.exe подключён (PID=%d)", proc.pid)
            return proc, session
        except Exception as e:
            last_error = e
            time.sleep(0.3)

    if proc.poll() is not None:
        raise SAMLaunchError(
            f"SAM.Picker.exe завершился с кодом {proc.returncode}"
        )
    proc.kill()
    raise SAMConnectionError(
        f"Не удалось подключиться к SAM.Picker.exe: {last_error}"
    )


def kill_process(proc: subprocess.Popen) -> None:
    """Принудительно завершает процесс."""
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
