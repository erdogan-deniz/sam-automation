"""Тесты для app/cache.py.

Модульные константы (*_FILE) перехватываются через monkeypatch,
чтобы перенаправить операции с файлами в tmp_path.
"""

from __future__ import annotations

import app.cache as cache_mod


# ── Вспомогательная функция ────────────────────────────────────────────────


def _patch_all(monkeypatch, tmp_path):
    """Перенаправляет все пути cache в tmp_path."""
    monkeypatch.setattr(cache_mod, "DONE_IDS_FILE", tmp_path / "done_ids.txt")
    monkeypatch.setattr(cache_mod, "ERROR_IDS_FILE", tmp_path / "error_ids.txt")
    monkeypatch.setattr(cache_mod, "NO_ACHIEVEMENTS_FILE", tmp_path / "no_ach.txt")


# ── load/mark done ─────────────────────────────────────────────────────────


def test_load_done_ids_empty(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)
    assert cache_mod.load_done_ids() == set()


def test_mark_done_and_load(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)
    cache_mod.mark_done(730)
    cache_mod.mark_done(440)
    assert cache_mod.load_done_ids() == {730, 440}


# ── load/mark error ────────────────────────────────────────────────────────


def test_load_error_ids_empty(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)
    assert cache_mod.load_error_ids() == set()


def test_mark_error_and_load(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)
    cache_mod.mark_error_id(10)
    assert cache_mod.load_error_ids() == {10}


# ── load/mark no_achievements ──────────────────────────────────────────────


def test_load_no_achievements_empty(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)
    assert cache_mod.load_no_achievements_ids() == set()


def test_mark_no_achievements_and_load(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)
    cache_mod.mark_no_achievements(440)
    assert 440 in cache_mod.load_no_achievements_ids()


# ── clear_progress ─────────────────────────────────────────────────────────


def test_clear_progress_removes_files(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)
    cache_mod.mark_done(730)
    cache_mod.mark_error_id(440)
    cache_mod.mark_no_achievements(10)

    cache_mod.clear_progress()

    assert not (tmp_path / "done_ids.txt").exists()
    assert not (tmp_path / "error_ids.txt").exists()
    assert not (tmp_path / "no_ach.txt").exists()


def test_clear_progress_idempotent(monkeypatch, tmp_path):
    """clear_progress не падает, если файлы уже удалены."""
    _patch_all(monkeypatch, tmp_path)
    cache_mod.clear_progress()
    cache_mod.clear_progress()  # повторный вызов — не должно быть исключения
