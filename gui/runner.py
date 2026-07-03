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
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from gui import win_job


class ScriptRunner:
    """Запускает Python-скрипт как subprocess, стримит вывод через очередь.

    Дочерний процесс помещается в Win32 Job Object (KILL_ON_JOB_CLOSE), так
    что stop() убивает ВСЁ дерево — сам скрипт И его внуков SAM.Game.exe.
    Это надёжнее сигналов: не зависит от обработчиков и прерываемости
    time.sleep, поэтому Stop/Esc/закрытие окна не оставляют сирот.
    """

    def __init__(self) -> None:
        self.on_output: Callable[[str], None] | None = None
        self.on_finish: Callable[[int], None] | None = None

        self._proc: subprocess.Popen | None = None
        self._job: int | None = None
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

        # Создаём job ДО запуска и помещаем в него процесс сразу после старта.
        # Скрипт делает многосекундный setup до первого SAM.Game.exe, так что
        # к моменту появления внуков он уже в job → внуки наследуют членство.
        self._job = win_job.create_kill_on_close_job()
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        win_job.assign_process(self._job, self._proc.pid)

        thread = threading.Thread(target=self._read_output, daemon=True)
        thread.start()

    def stop(self) -> None:
        """Убивает всё дерево процессов (скрипт + внуки SAM.Game.exe).

        Через Job Object — надёжно, без зависимости от сигналов/сна. Фолбэк
        на terminate() самого процесса, если job недоступен (не-Windows).
        """
        if not (self._proc and self._running):
            return
        if self._job is not None:
            win_job.terminate_job(self._job)
            self._job = None
        else:
            try:
                self._proc.terminate()
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
                    # Закрываем job-хендл завершившегося прогона (процессов
                    # в нём уже нет — просто освобождаем ресурс).
                    win_job.terminate_job(self._job)
                    self._job = None
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
