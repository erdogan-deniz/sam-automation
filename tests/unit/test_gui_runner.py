"""Тесты остановки gui.runner.ScriptRunner через Win32 Job Object.

Прошлый graceful-фикс (CTRL_BREAK) на Windows жёстко убивал скрипт до
finally/atexit → внуки SAM.Game.exe оставались сиротами. Job Object с
KILL_ON_JOB_CLOSE убивает всё дерево разом, без зависимости от сигналов.

Юнит-тесты проверяют проводку (job создан/назначен/терминейтнут), а
Windows-only интеграционный тест доказывает реальную смерть внука.
"""

from __future__ import annotations

import subprocess
import sys
import time

import psutil
import pytest

from gui import win_job
from gui.runner import ScriptRunner


class _FakeProc:
    stdout = iter(())

    def __init__(self) -> None:
        self.pid = 4242
        self.returncode = 0
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int | None:
        return None


def test_run_wraps_child_in_job(monkeypatch: pytest.MonkeyPatch) -> None:
    assigned: list[tuple[object, int]] = []
    monkeypatch.setattr(win_job, "create_kill_on_close_job", lambda: 777)
    monkeypatch.setattr(
        win_job,
        "assign_process",
        lambda job, pid: assigned.append((job, pid)) or True,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc())

    runner = ScriptRunner()
    runner.run("scripts/cards/farm.py", [])

    assert assigned == [(777, 4242)]  # процесс помещён в созданный job


def test_stop_terminates_job(monkeypatch: pytest.MonkeyPatch) -> None:
    terminated: list[object] = []
    monkeypatch.setattr(
        win_job, "terminate_job", lambda job: terminated.append(job)
    )

    runner = ScriptRunner()
    runner._proc = _FakeProc()  # type: ignore[assignment]
    runner._running = True
    runner._job = 777

    runner.stop()

    assert terminated == [777]  # убито всё дерево через job


def test_stop_without_job_falls_back_to_terminate() -> None:
    runner = ScriptRunner()
    proc = _FakeProc()
    runner._proc = proc  # type: ignore[assignment]
    runner._running = True
    runner._job = None  # не-Windows / job не создался

    runner.stop()

    assert proc.terminated is True


@pytest.mark.skipif(
    sys.platform != "win32", reason="Job Object — только Windows"
)
def test_job_terminate_kills_grandchild(tmp_path) -> None:
    """E2E: stop() убивает ВНУКА (не только сам скрипт) через job."""
    grandchild = tmp_path / "grandchild.py"
    grandchild.write_text(
        "import os, sys, time\n"
        "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    child = tmp_path / "child.py"
    child.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    pidfile = tmp_path / "gc.pid"

    runner = ScriptRunner()
    runner.run(str(child), [str(grandchild), str(pidfile)])
    try:
        for _ in range(100):
            if pidfile.exists():
                break
            time.sleep(0.1)
        assert pidfile.exists(), "внук не успел стартовать"
        gc_pid = int(pidfile.read_text())
        assert psutil.pid_exists(gc_pid)

        runner.stop()

        for _ in range(100):
            if not psutil.pid_exists(gc_pid):
                break
            time.sleep(0.1)
        assert not psutil.pid_exists(gc_pid), "внук осиротел после stop()"
    finally:
        runner.stop()
