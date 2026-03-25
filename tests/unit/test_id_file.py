"""Тесты для app/id_file.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.id_file import _append_id, load_ids_file, read_ids_ordered


# ── load_ids_file ──────────────────────────────────────────────────────────


def test_load_ids_file_missing(tmp_path: Path) -> None:
    assert load_ids_file(tmp_path / "nonexistent.txt") == set()


def test_load_ids_file_basic(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n440\n730\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440, 730}


def test_load_ids_file_skips_comments(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n# skip this\n440\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440}


def test_load_ids_file_skips_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n\n  \n440\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440}


def test_load_ids_file_ignores_invalid(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\nnot_a_number\n440\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440}


# ── read_ids_ordered ───────────────────────────────────────────────────────


def test_read_ids_ordered_missing(tmp_path: Path) -> None:
    assert read_ids_ordered(tmp_path / "nonexistent.txt") == []


def test_read_ids_ordered_preserves_order(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("730\n440\n10\n", encoding="utf-8")
    assert read_ids_ordered(f) == [730, 440, 10]


def test_read_ids_ordered_skips_comments(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("730\n# comment\n440\n", encoding="utf-8")
    assert read_ids_ordered(f) == [730, 440]


# ── _append_id ─────────────────────────────────────────────────────────────


def test_append_id_creates_file(tmp_path: Path) -> None:
    f = tmp_path / "out.txt"
    _append_id(f, 730)
    assert f.read_text(encoding="utf-8") == "730\n"


def test_append_id_creates_parent_dir(tmp_path: Path) -> None:
    f = tmp_path / "subdir" / "out.txt"
    _append_id(f, 440)
    assert f.exists()
    assert f.read_text(encoding="utf-8") == "440\n"


def test_append_id_appends(tmp_path: Path) -> None:
    f = tmp_path / "out.txt"
    _append_id(f, 10)
    _append_id(f, 440)
    assert read_ids_ordered(f) == [10, 440]
