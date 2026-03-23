"""Тесты для app/game_list.py."""

from __future__ import annotations

import app.game_list as gl_mod
from app.config import Config


# ── Источник: config.game_ids ──────────────────────────────────────────────


def test_game_ids_from_config():
    cfg = Config(game_ids=[10, 440, 730])
    assert gl_mod.load_game_ids(cfg) == [10, 440, 730]


def test_game_ids_deduplication():
    cfg = Config(game_ids=[10, 440, 10, 730, 440])
    result = gl_mod.load_game_ids(cfg)
    assert result == [10, 440, 730]


def test_game_ids_exclude():
    cfg = Config(game_ids=[10, 440, 730], exclude_ids=[440])
    result = gl_mod.load_game_ids(cfg)
    assert 440 not in result
    assert 10 in result
    assert 730 in result


def test_game_ids_exclude_all():
    cfg = Config(game_ids=[10, 440], exclude_ids=[10, 440])
    assert gl_mod.load_game_ids(cfg) == []


# ── Источник: ALL_IDS_FILE ─────────────────────────────────────────────────


def test_game_ids_from_all_ids_file(monkeypatch, tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("10\n440\n730\n", encoding="utf-8")
    monkeypatch.setattr(gl_mod, "ALL_IDS_FILE", f)
    cfg = Config()
    assert gl_mod.load_game_ids(cfg) == [10, 440, 730]


def test_all_ids_file_not_used_when_config_ids_set(monkeypatch, tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("999\n", encoding="utf-8")
    monkeypatch.setattr(gl_mod, "ALL_IDS_FILE", f)
    # config.game_ids уже задан — ALL_IDS_FILE игнорируется
    cfg = Config(game_ids=[10, 440])
    result = gl_mod.load_game_ids(cfg)
    assert 999 not in result


# ── Источник: game_ids_file ────────────────────────────────────────────────


def test_game_ids_from_ids_file(monkeypatch, tmp_path):
    # Убедимся, что ALL_IDS_FILE не мешает (несуществующий файл)
    monkeypatch.setattr(gl_mod, "ALL_IDS_FILE", tmp_path / "nonexistent.txt")
    ids_file = tmp_path / "my_ids.txt"
    ids_file.write_text("10\n440\n", encoding="utf-8")
    cfg = Config(game_ids_file=str(ids_file))
    result = gl_mod.load_game_ids(cfg)
    assert set(result) == {10, 440}


def test_game_ids_file_extends_config_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(gl_mod, "ALL_IDS_FILE", tmp_path / "nonexistent.txt")
    ids_file = tmp_path / "extra.txt"
    ids_file.write_text("730\n", encoding="utf-8")
    cfg = Config(game_ids=[10, 440], game_ids_file=str(ids_file))
    result = gl_mod.load_game_ids(cfg)
    assert set(result) == {10, 440, 730}


def test_game_ids_file_missing_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(gl_mod, "ALL_IDS_FILE", tmp_path / "nonexistent.txt")
    cfg = Config(game_ids=[10], game_ids_file=str(tmp_path / "missing.txt"))
    result = gl_mod.load_game_ids(cfg)
    assert result == [10]
