"""Тесты app/wishlist/clean_state.py (кандидаты на удаление, удалённое)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.wishlist.clean_state as cs


def _patch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cs, "CANDIDATES_FILE", tmp_path / "candidates.txt")
    monkeypatch.setattr(cs, "REMOVED_FILE", tmp_path / "removed.txt")


def test_candidates_roundtrip(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    assert cs.load_candidates() == []
    cs.save_candidates([30, 10, 30])
    assert cs.load_candidates() == [10, 30]


def test_mark_removed(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path)
    cs.mark_removed(5)
    cs.mark_removed(5)
    assert cs.load_removed_ids() == {5}
