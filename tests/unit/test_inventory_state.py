"""Тесты app/inventory/state.py: что уже сделано с предметами (B-16)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.inventory.state as st


@pytest.fixture(autouse=True)
def _dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(st, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(st, "LISTED_FILE", tmp_path / "listed.txt")
    monkeypatch.setattr(st, "PENDING_FILE", tmp_path / "pending.txt")
    monkeypatch.setattr(st, "GROUND_FILE", tmp_path / "ground.txt")
    monkeypatch.setattr(st, "REFUSED_FILE", tmp_path / "refused.txt")


def test_nothing_handled_initially() -> None:
    assert st.load_handled() == set()


def test_each_outcome_lands_in_its_own_file(tmp_path: Path) -> None:
    st.mark_listed(1)
    st.mark_pending(2)
    st.mark_ground(3)
    st.mark_refused(4)
    assert (tmp_path / "listed.txt").read_text().split() == ["1"]
    assert (tmp_path / "pending.txt").read_text().split() == ["2"]
    assert (tmp_path / "ground.txt").read_text().split() == ["3"]
    assert (tmp_path / "refused.txt").read_text().split() == ["4"]


def test_load_handled_unions_all_outcomes() -> None:
    st.mark_listed(19292374134)
    st.mark_pending(5)
    st.mark_ground(7)
    st.mark_refused(9)
    assert st.load_handled() == {19292374134, 5, 7, 9}


def test_pending_is_not_counted_as_listed() -> None:
    st.mark_pending(2)
    assert st.load_listed() == set()
    assert st.load_pending() == {2}


def test_reset_clears_everything() -> None:
    st.mark_listed(1)
    st.mark_pending(2)
    st.mark_ground(3)
    st.mark_refused(4)
    st.reset()
    assert st.load_handled() == set()
