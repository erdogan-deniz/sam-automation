"""Запуск скриптов как subprocess с потоковым чтением вывода.

Использование:
    runner = ScriptRunner()
    runner.on_output = lambda line: print(line)
    runner.on_finish = lambda code: print(f"exit {code}")
    runner.run("scripts/scan.py", [])
    # ...
    runner.stop()
"""

from __future__ import annotations

import queue
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

# Мягкий сигнал остановки: на Windows CTRL_BREAK_EVENT, иначе SIGINT.
# Скрипт ловит его как KeyboardInterrupt и сам закрывает своих детей
# (SAM.Game.exe) через finally/atexit — жёсткий terminate() это ломает.
_GRACEFUL_SIGNAL = getattr(signal, "CTRL_BREAK_EVENT", signal.SIGINT)
# Флаг нужен, чтобы CTRL_BREAK доставлялся ТОЛЬКО дочернему процессу,
# а не задел саму GUI. На не-Windows платформах = 0 (no-op).
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_STOP_GRACE_SECONDS = 8.0  # сколько ждём самоочистки перед жёстким добиванием


class ScriptRunner:
    """Запускает Python-скрипт как subprocess, стримит вывод через очередь."""

    def __init__(self) -> None:
        self.on_output: Callable[[str], None] | None = None
        self.on_finish: Callable[[int], None] | None = None

        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def run(
        self, script_path: str | Path, args: list[str] | None = None
    ) -> None:
        """Запускает скрипт в subprocess. Вывод стримится через on_output."""
        if self._running:
            return

        self._running = True
        cmd = [sys.executable, str(script_path), *(args or [])]

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NEW_GROUP,
        )

        thread = threading.Thread(target=self._read_output, daemon=True)
        thread.start()

    def stop(self) -> None:
        """Мягко останавливает subprocess, добивая только если завис.

        Шлёт CTRL_BREAK/SIGINT — скрипт ловит его как KeyboardInterrupt и
        сам закрывает своих детей (SAM.Game.exe) + освобождает run-lock.
        Если за _STOP_GRACE_SECONDS не завершился — жёсткий terminate().
        """
        if not (self._proc and self._running):
            return
        proc = self._proc
        try:
            proc.send_signal(_GRACEFUL_SIGNAL)
        except (OSError, ValueError):
            # Не удалось послать сигнал (нет группы/процесс мёртв) — жёстко.
            try:
                proc.terminate()
            except OSError:
                pass
            return
        threading.Thread(
            target=self._terminate_after_grace, args=(proc,), daemon=True
        ).start()

    @staticmethod
    def _terminate_after_grace(proc: subprocess.Popen) -> None:
        """Добивает процесс, если он не завершился сам за grace-период."""
        try:
            proc.wait(timeout=_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
            except OSError:
                pass

    def poll_output(self) -> None:
        """Вызывается из главного потока (через widget.after).

        Забирает все строки из очереди и вызывает on_output/on_finish.
        """
        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    # sentinel — скрипт завершился
                    returncode = self._proc.returncode if self._proc else -1
                    self._running = False
                    self._proc = None
                    if self.on_finish:
                        self.on_finish(returncode)
                    break
                if self.on_output:
                    self.on_output(item)
        except queue.Empty:
            pass

    # ------------------------------------------------------------------
    # Internal

    def _read_output(self) -> None:
        """Daemon thread: читает stdout и кладёт строки в очередь."""
        assert self._proc is not None
        assert self._proc.stdout is not None

        for line in self._proc.stdout:
            self._queue.put(line.rstrip("\n"))

        self._proc.wait()
        self._queue.put(None)  # sentinel
