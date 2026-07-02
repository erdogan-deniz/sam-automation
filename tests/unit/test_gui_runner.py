"""Тесты graceful-остановки gui.runner.ScriptRunner.

Баг: stop() делал terminate() (жёсткий TerminateProcess) в обход finally/
atexit скрипта → farm.py не убирал своих детей SAM.Game.exe → аккаунт
застревал in-game. Фикс: слать CTRL_BREAK/SIGINT (скрипт ловит как
KeyboardInterrupt и сам чистит детей), terminate() — только фолбэк.
"""

from __future__ import annotations

import signal
import subprocess

import pytest

from gui.runner import ScriptRunner


class _FakeProc:
    stdout = iter(())

    def __init__(self) -> None:
        self.signals: list[object] = []
        self.terminated = False

    def send_signal(self, sig: object) -> None:
        self.signals.append(sig)

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0  # процесс «завершился» — фолбэк-терминейт не нужен

    def poll(self) -> int | None:
        return None


def test_stop_sends_graceful_signal_not_hard_kill() -> None:
    runner = ScriptRunner()
    proc = _FakeProc()
    runner._proc = proc  # type: ignore[assignment]
    runner._running = True

    runner.stop()

    expected = getattr(signal, "CTRL_BREAK_EVENT", signal.SIGINT)
    assert expected in proc.signals  # послан мягкий сигнал
    assert proc.terminated is False  # не жёсткий kill сразу


def test_stop_falls_back_to_terminate_when_signal_fails() -> None:
    runner = ScriptRunner()

    class _BadProc(_FakeProc):
        def send_signal(self, sig: object) -> None:
            raise OSError("no process group")

    proc = _BadProc()
    runner._proc = proc  # type: ignore[assignment]
    runner._running = True

    runner.stop()

    assert proc.terminated is True  # фолбэк на жёсткое завершение


def test_run_launches_in_new_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptRunner()
    captured: dict[str, object] = {}

    def fake_popen(cmd: list[str], **kw: object) -> _FakeProc:
        captured.update(kw)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    runner.run("scripts/cards/farm.py", [])

    expected = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert captured.get("creationflags") == expected
