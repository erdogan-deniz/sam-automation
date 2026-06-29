"""ДИАГНОСТИКА (временный скрипт): что показывает SAM.Game.exe при прямом запуске.

Boost запускает `SAM.Game.exe <appid>` НАПРЯМУЮ (без Picker). Для unknown-игр
окно может показывать ошибку, но `_has_error_window` её не ловит — этот скрипт
снимает РЕАЛЬНУЮ структуру окон, чтобы понять почему (заголовок/класс/PID/тайминг).

Снимает таймлайн ВСЕХ top-level окон процесса (и любых SAM.Game.exe) каждую
секунду в течение --watch сек: hwnd / PID / заголовок / класс / видимость /
enabled + дочерние контролы (текст ошибки в MessageBox лежит в Static-детях).
Окно НЕ минимизируется — чтобы ты глазами увидел ошибку.

Запускать ОТДЕЛЬНО (не во время boost/farm — конфликт за SAM):
    python scripts/diag/dump_sam_game_launch.py 2021390          # сломанная
    python scripts/diag/dump_sam_game_launch.py 466160 --watch 30  # рабочая
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import ctypes
import ctypes.wintypes
import logging
import subprocess
import time

from app.config import load_config
from app.logging_setup import setup_logging
from app.sam import check_steam_running, ensure_sam, kill_process
from app.validator import validate

log = logging.getLogger("sam_automation")

_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "diag"

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)
_TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _sam_game_pids() -> set[int]:
    """PID всех SAM.Game.exe."""
    snap = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return set()
    pe = _PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    pids: set[int] = set()
    try:
        if _kernel32.Process32First(snap, ctypes.byref(pe)):
            while True:
                if pe.szExeFile.lower() == b"sam.game.exe":
                    pids.add(pe.th32ProcessID)
                if not _kernel32.Process32Next(snap, ctypes.byref(pe)):
                    break
    finally:
        _kernel32.CloseHandle(snap)
    return pids


def _win_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _win_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _child_controls(hwnd: int) -> list[str]:
    """Текст/класс прямых и вложенных дочерних контролов (текст ошибки MessageBox)."""
    out: list[str] = []

    def _cb(child: int, _: int) -> bool:
        out.append(
            f"      child cls={_win_class(child)!r} text={_win_text(child)!r}"
        )
        return True

    _user32.EnumChildWindows(hwnd, _WNDENUMPROC(_cb), 0)
    return out


def _snapshot(pids: set[int]) -> list[str]:
    """Все видимые top-level окна, принадлежащие любому из pids."""
    lines: list[str] = []
    pid_buf = ctypes.wintypes.DWORD()

    def _cb(hwnd: int, _: int) -> bool:
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        if pid_buf.value in pids:
            visible = bool(_user32.IsWindowVisible(hwnd))
            enabled = bool(_user32.IsWindowEnabled(hwnd))
            lines.append(
                f"    hwnd={hwnd} pid={pid_buf.value} "
                f"title={_win_text(hwnd)!r} class={_win_class(hwnd)!r} "
                f"visible={visible} enabled={enabled}"
            )
            lines.extend(_child_controls(hwnd))
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Дамп окон SAM.Game.exe при прямом запуске (путь boost)"
    )
    parser.add_argument("appid", type=int, help="App ID игры")
    parser.add_argument(
        "--watch",
        type=float,
        default=25.0,
        help="секунд наблюдать за окнами (по умолчанию 25)",
    )
    args = parser.parse_args()

    setup_logging(verbose=True, name="diag_sam_game", category="diag")
    cfg = load_config()
    validate(cfg)

    if not check_steam_running():
        log.error("Steam не запущен")
        sys.exit(1)
    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    exe = Path(cfg.sam_game_exe_path)
    log.info(
        "Запускаю напрямую: %s %d (окно НЕ минимизирую)", exe.name, args.appid
    )
    proc = subprocess.Popen([str(exe), str(args.appid)], cwd=str(exe.parent))
    our_pid = proc.pid

    report: list[str] = [
        f"# SAM.Game.exe прямой запуск appid={args.appid}",
        f"# launched pid={our_pid}, watch={args.watch}s",
        "",
    ]
    seen_signatures: set[str] = set()
    try:
        deadline = time.time() + args.watch
        tick = 0
        while time.time() < deadline:
            elapsed = round(args.watch - (deadline - time.time()), 1)
            # Наблюдаем за нашим pid + всеми SAM.Game.exe (на случай дочернего процесса)
            pids = {our_pid} | _sam_game_pids()
            alive = proc.poll() is None
            snap = _snapshot(pids)
            signature = "\n".join(snap)
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                report.append(
                    f"[t={elapsed:>4}s] proc_alive={alive} pids={sorted(pids)}"
                )
                report.extend(snap or ["    <нет видимых окон у этих PID>"])
                report.append("")
                log.info("t=%ss: %d окон (новое состояние)", elapsed, len(snap))
            tick += 1
            time.sleep(1.0)
    finally:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = _OUT_DIR / f"sam_game_launch_{args.appid}.txt"
        out.write_text("\n".join(report), encoding="utf-8")
        log.info("Отчёт записан: %s", out)
        kill_process(proc)
        log.info("Процесс убит.")


if __name__ == "__main__":
    main()
