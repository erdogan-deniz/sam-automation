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


def test_remove_stale_lock_deletes_matching(tmp_path, monkeypatch):
    # Содержимое на диске == прочитанный мёртвый токен → безопасно снести.
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("999:bbb:boost", encoding="utf-8")
    rl._remove_stale_lock("999:bbb:boost")
    assert not lock.exists()


def test_remove_stale_lock_keeps_lock_when_content_changed(
    tmp_path, monkeypatch
):
    # TOCTOU: между read мёртвого токена и unlink другой инстанс успел взять
    # СВОЙ живой лок. Безусловный unlink снёс бы чужой живой лок → оба решили бы,
    # что владеют → параллельный farm+boost. Изменившееся содержимое НЕ трогаем.
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text(
        "111:aaa:farm", encoding="utf-8"
    )  # уже живой лок инстанса A
    rl._remove_stale_lock("999:bbb:boost")  # B сносит СТАРЫЙ мёртвый токен
    assert lock.exists()
    assert lock.read_text(encoding="utf-8") == "111:aaa:farm"


def test_acquire_does_not_clobber_live_lock_taken_during_removal(
    tmp_path, monkeypatch
):
    # Сквозной сценарий гонки: на диске мёртвый лок; в момент снятия появляется
    # живой чужой лок. acquire не должен его снести и захватить второй раз —
    # обязан упасть RuntimeError (владелец жив).
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(rl, "LOCK_FILE", lock)
    lock.write_text("99999:dead:boost", encoding="utf-8")  # мёртвый владелец

    live_ctime = {"99999": None}  # изначально владелец мёртв

    def fake_ctime(pid):
        if pid == 99999:
            return live_ctime["99999"]
        return "me"

    monkeypatch.setattr(rl, "_proc_create_time", fake_ctime)

    real_remove = rl._remove_stale_lock

    def racing_remove(expected):
        # Инстанс A перехватил лок живым токеном ровно перед нашим unlink.
        lock.write_text("99999:aaa:farm", encoding="utf-8")
        live_ctime["99999"] = "aaa"  # теперь владелец жив
        real_remove(expected)

    monkeypatch.setattr(rl, "_remove_stale_lock", racing_remove)

    with pytest.raises(RuntimeError, match="farm"):
        rl.acquire_run_lock("boost")
    assert lock.read_text(encoding="utf-8") == "99999:aaa:farm"  # чужой лок цел


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
