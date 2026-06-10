"""Тесты skip-списка playtime — игры, которые не подключаются к Steam."""

from __future__ import annotations

import app.cache as cache


def test_playtime_skip_roundtrip(tmp_path, monkeypatch):
    skip_file = tmp_path / "skip.txt"
    monkeypatch.setattr(cache, "PLAYTIME_SKIP_FILE", skip_file)

    assert cache.load_playtime_skip_ids() == set()
    cache.mark_playtime_skip(111)
    cache.mark_playtime_skip(222)
    assert cache.load_playtime_skip_ids() == {111, 222}


def test_playtime_skip_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PLAYTIME_SKIP_FILE", tmp_path / "nope.txt")
    assert cache.load_playtime_skip_ids() == set()


def test_playtime_done_roundtrip(tmp_path, monkeypatch):
    done_file = tmp_path / "done.txt"
    monkeypatch.setattr(cache, "PLAYTIME_DONE_FILE", done_file)

    assert cache.load_playtime_done_ids() == set()
    cache.mark_playtime_done(616390)
    cache.mark_playtime_done(633360)
    assert cache.load_playtime_done_ids() == {616390, 633360}


def test_playtime_done_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PLAYTIME_DONE_FILE", tmp_path / "nope.txt")
    assert cache.load_playtime_done_ids() == set()


def test_clear_playtime_progress_removes_done(tmp_path, monkeypatch):
    done = tmp_path / "done.txt"
    monkeypatch.setattr(cache, "PLAYTIME_DONE_FILE", done)
    cache.mark_playtime_done(1)
    cache.clear_playtime_progress()
    assert not done.exists()
    assert cache.load_playtime_done_ids() == set()


def test_clear_playtime_progress_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PLAYTIME_DONE_FILE", tmp_path / "nope.txt")
    cache.clear_playtime_progress()  # не должно падать на отсутствующем файле
