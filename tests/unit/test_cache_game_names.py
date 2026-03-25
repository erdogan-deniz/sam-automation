"""Тесты для load_game_names / save_game_names в app/cache.py."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.cache as cache_mod


def _patch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cache_mod, "GAME_NAMES_FILE", tmp_path / "game_names.json")


# ── load_game_names ─────────────────────────────────────────────────────────


def test_load_game_names_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, tmp_path)
    assert cache_mod.load_game_names() == {}


def test_load_game_names_corrupted_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, tmp_path)
    (tmp_path / "game_names.json").write_text("not json", encoding="utf-8")
    assert cache_mod.load_game_names() == {}


# ── save_game_names ─────────────────────────────────────────────────────────


def test_save_and_load_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, tmp_path)
    names = {570: "Dota 2", 440: "Team Fortress 2"}
    cache_mod.save_game_names(names)
    assert cache_mod.load_game_names() == names


def test_save_merges_with_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, tmp_path)
    cache_mod.save_game_names({570: "Dota 2"})
    cache_mod.save_game_names({440: "TF2"})
    result = cache_mod.load_game_names()
    assert result[570] == "Dota 2"
    assert result[440] == "TF2"


def test_save_overwrites_existing_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, tmp_path)
    cache_mod.save_game_names({570: "Old Name"})
    cache_mod.save_game_names({570: "Dota 2"})
    assert cache_mod.load_game_names()[570] == "Dota 2"


def test_save_creates_parent_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "game_names.json"
    monkeypatch.setattr(cache_mod, "GAME_NAMES_FILE", deep)
    cache_mod.save_game_names({1: "Game"})
    assert deep.exists()


def test_keys_are_integers_after_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, tmp_path)
    cache_mod.save_game_names({12345: "Portal"})
    result = cache_mod.load_game_names()
    assert all(isinstance(k, int) for k in result)


def test_save_empty_dict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, tmp_path)
    cache_mod.save_game_names({570: "Dota 2"})
    cache_mod.save_game_names({})
    # Empty save should not erase existing data
    assert cache_mod.load_game_names()[570] == "Dota 2"
