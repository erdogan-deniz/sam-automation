"""Тесты run-lock — защита от одновременного запуска farm и boost."""

from __future__ import annotations

import pytest

import app.run_lock as rl


def test_acquire_creates_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "LOCK_FILE", tmp_path / "run.lock")
    rl.acquire_run_lock("farm")
    assert (tmp_path / "run.lock").exists()


def test_acquire_raises_if_other_process_alive(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("99999:boost", encoding="utf-8")
    monkeypatch.setattr(rl.psutil, "pid_exists", lambda _p: True)

    with pytest.raises(RuntimeError, match="boost"):
        rl.acquire_run_lock("farm")


def test_acquire_overwrites_stale_lock(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("99999:boost", encoding="utf-8")
    monkeypatch.setattr(rl.psutil, "pid_exists", lambda _p: False)  # мёртвый

    rl.acquire_run_lock("farm")  # битый lock — перезаписываем без ошибки
    assert "farm" in lock.read_text(encoding="utf-8")


def test_release_removes_lock(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("1:farm", encoding="utf-8")
    rl.release_run_lock()
    assert not lock.exists()
