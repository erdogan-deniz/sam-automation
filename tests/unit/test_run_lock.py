"""Тесты run-lock — защита от одновременного запуска farm и boost.

Формат лока: PID:create_time:name. Сверка create_time отсекает PID-reuse.
"""

from __future__ import annotations

import os

import pytest

import app.run_lock as rl


def test_acquire_creates_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "LOCK_FILE", tmp_path / "run.lock")
    rl.acquire_run_lock("farm")
    content = (tmp_path / "run.lock").read_text(encoding="utf-8")
    assert str(os.getpid()) in content and "farm" in content


def test_acquire_raises_if_live_owner(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("99999:111.000:boost", encoding="utf-8")
    # Владелец 99999 жив И его create_time совпадает с записанным.
    monkeypatch.setattr(
        rl, "_proc_create_time", lambda pid: "111.000" if pid == 99999 else "me"
    )
    with pytest.raises(RuntimeError, match="boost"):
        rl.acquire_run_lock("farm")


def test_acquire_overwrites_on_pid_reuse(tmp_path, monkeypatch):
    # PID 99999 существует, но create_time ДРУГОЙ → другой процесс (reuse),
    # лок устарел — перезаписываем без ошибки.
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("99999:111.000:boost", encoding="utf-8")
    monkeypatch.setattr(
        rl, "_proc_create_time", lambda pid: "999.999" if pid == 99999 else "me"
    )
    rl.acquire_run_lock("farm")
    assert "farm" in lock.read_text(encoding="utf-8")


def test_acquire_overwrites_dead_owner(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("99999:111.000:boost", encoding="utf-8")
    monkeypatch.setattr(
        rl, "_proc_create_time", lambda pid: None if pid == 99999 else "me"
    )
    rl.acquire_run_lock("farm")
    assert "farm" in lock.read_text(encoding="utf-8")


def test_acquire_overwrites_corrupt_lock(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("мусор", encoding="utf-8")  # битый формат
    rl.acquire_run_lock("farm")
    assert "farm" in lock.read_text(encoding="utf-8")


def test_release_removes_own_lock(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    monkeypatch.setattr(rl, "_proc_create_time", lambda pid: "mine")
    lock.write_text(f"{os.getpid()}:mine:farm", encoding="utf-8")
    rl.release_run_lock()
    assert not lock.exists()


def test_release_keeps_foreign_lock(tmp_path, monkeypatch):
    # Чужой лок (другой PID) release не трогает.
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    monkeypatch.setattr(rl, "_proc_create_time", lambda pid: "mine")
    lock.write_text("99999:other:boost", encoding="utf-8")
    rl.release_run_lock()
    assert lock.exists()


def test_release_no_lock_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "LOCK_FILE", tmp_path / "absent.lock")
    rl.release_run_lock()  # не должно бросить
