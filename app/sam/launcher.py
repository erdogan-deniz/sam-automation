"""Запуск и остановка процессов SAM (SAM.Picker.exe, SAM.Game.exe)."""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from pywinauto import Application

from ..exceptions import SAMConnectionError, SAMLaunchError
from .picker_session import PickerSession
from .win32_utils import _has_error_window, _kill_pid

log = logging.getLogger("sam_automation")

# Пауза между стартами SAM.Game.exe (сек). Одновременный запуск нескольких
# процессов вызывает гонку за Steam global user → 'failed to connect to
# global user'. Старт по очереди с задержкой её устраняет.
_LAUNCH_STAGGER = 3.0

# Интервал опроса процессов во время idle (сек). _has_error_window дёшев
# (EnumWindows), поэтому частый опрос недорог.
_IDLE_POLL_INTERVAL = 5.0


def launch_game(sam_game_exe: str, appid: int) -> subprocess.Popen:
    """Запускает SAM.Game.exe для указанного appid (card farming — без UI автоматизации).

    В отличие от launch_picker, не подключается через pywinauto —
    SAM.Game.exe работает тихо, сохраняя игровую сессию в Steam.

    Raises:
        RuntimeError: если exe не удалось запустить.
    """
    exe = Path(sam_game_exe)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 6  # SW_MINIMIZE
    try:
        proc = subprocess.Popen(
            [str(exe), str(appid)],
            cwd=str(exe.parent),
            startupinfo=startupinfo,
        )
    except OSError as e:
        raise RuntimeError(
            f"Не удалось запустить SAM.Game.exe для {appid}: {e}"
        ) from e

    return proc


def launch_games_staggered(
    sam_game_exe: str,
    games: list[tuple[int, str]],
    stagger: float = _LAUNCH_STAGGER,
) -> dict[int, subprocess.Popen]:
    """Запускает SAM.Game.exe для каждой (appid, name) по очереди с паузой.

    Пауза >= stagger МЕЖДУ запусками избегает гонки за Steam global user
    ('failed to connect to global user' при одновременном старте). Перед
    первым запуском паузы нет — она нужна только между процессами.

    Returns:
        Отображение appid → Popen запущенных процессов.
    """
    active: dict[int, subprocess.Popen] = {}
    for idx, (appid, name) in enumerate(games):
        if idx > 0:
            time.sleep(stagger)
        log.info("[%d] Запускаю: %s", appid, name)
        active[appid] = launch_game(sam_game_exe, appid)
    return active


def idle_and_split_survivors(
    active: dict[int, subprocess.Popen],
    idle_duration: float,
    poll_interval: float = _IDLE_POLL_INTERVAL,
    on_failed: Callable[[int], None] | None = None,
) -> tuple[list[int], list[int]]:
    """Идлит активные игры до idle_duration, отделяя выживших от провалившихся.

    Игра ПРОВАЛИЛАСЬ, если её процесс завершился сам (`poll()` != None) или
    показал окно 'Error' — значит не подключилась к Steam, playtime не идёт.
    Окно ошибки транзиентное (процесс показывает 'Error' и умирает за секунды),
    поэтому единственная ранняя проверка ненадёжна — опрашиваем весь idle.

    ВЫЖИВШИЕ — процесс жив весь idle и ни разу не показал ошибку (реально
    набивают время). Провалившиеся убиваются сразу, выжившие — в конце. Если
    все провалились раньше idle_duration, выходим досрочно (не ждём впустую).
    Каждый процесс проверяется хотя бы раз даже при idle_duration <= 0.

    on_failed (если задан) вызывается с appid в момент детекции провала — чтобы
    skip фиксировался сразу (переживает Ctrl+C во время idle).

    Returns:
        (survivors, failed) — списки appid. Все процессы к возврату завершены.
    """
    # Положительный шаг гарантирует прогресс к deadline (иначе busy-loop/hang).
    poll_interval = max(poll_interval, 0.1)
    failed: list[int] = []
    deadline = time.time() + idle_duration
    checked_once = False
    while active and (not checked_once or time.time() < deadline):
        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))
        checked_once = True
        for appid, proc in list(active.items()):
            if proc.poll() is not None or _has_error_window(proc.pid):
                log.info("[%d] Не подключился к Steam — пропуск (skip)", appid)
                kill_process(proc)
                del active[appid]
                failed.append(appid)
                if on_failed is not None:
                    on_failed(appid)
    survivors = list(active.keys())
    for proc in active.values():
        kill_process(proc)
    return survivors, failed


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
