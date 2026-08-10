"""Тесты resume-состояния app/free_games/state.py (candidates/added/refused/error)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.free_games.state as state_mod


def _patch_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        state_mod, "CANDIDATES_FILE", tmp_path / "candidates.txt"
    )
    monkeypatch.setattr(state_mod, "ADDED_FILE", tmp_path / "added.txt")
    monkeypatch.setattr(state_mod, "REFUSED_FILE", tmp_path / "refused.txt")
    monkeypatch.setattr(state_mod, "ERROR_FILE", tmp_path / "error.txt")


def test_load_candidates_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    assert state_mod.load_candidates() == []


def test_save_and_load_candidates_deduped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.save_candidates([730, 10, 730, 440])
    assert state_mod.load_candidates() == [730, 10, 440]  # дедуп, не сортировка


def test_save_candidates_preserves_priority_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Баг (Medium, аудит 2026-08-10): save_candidates писала
    # sorted(set(appids)) — числовая сортировка стирала порядок приоритета
    # (games>software>demos), который discovery.discover_candidates строит
    # специально, а orchestrate.add()'s --limit срезает по этому порядку
    # (pending[:limit]). Числовая сортировка превращала --limit в "N игр с
    # наименьшим appid" вместо "N по приоритету".
    _patch_all(monkeypatch, tmp_path)
    # Не по возрастанию appid — если бы save_candidates сортировала численно,
    # порядок ниже не сохранился бы.
    state_mod.save_candidates([500, 10, 999])
    assert state_mod.load_candidates() == [500, 10, 999]


def test_mark_added_and_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_added(730)
    state_mod.mark_added(10)
    assert state_mod.load_added_ids() == {730, 10}


def test_mark_refused_and_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_refused(440)
    assert state_mod.load_refused_ids() == {440}


def test_mark_error_and_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_error(20)
    assert state_mod.load_error_ids() == {20}


def test_clear_error_ids_removes_only_error_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_added(730)
    state_mod.mark_error(20)
    state_mod.clear_error_ids()
    assert state_mod.load_error_ids() == set()
    assert state_mod.load_added_ids() == {730}  # added не тронут


def test_clear_state_removes_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.save_candidates([730])
    state_mod.mark_added(730)
    state_mod.mark_refused(10)
    state_mod.mark_error(20)
    state_mod.clear_state()
    assert state_mod.load_candidates() == []
    assert state_mod.load_added_ids() == set()
    assert state_mod.load_refused_ids() == set()
    assert state_mod.load_error_ids() == set()
