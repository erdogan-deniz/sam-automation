"""Тесты для app/validator.py."""

from __future__ import annotations

from app.config import Config
from app.validator import _check_file_paths, _check_required_fields


# ── _check_required_fields ────────────────────────────────────────────────


def test_required_fields_both_missing():
    cfg = Config()
    errors = _check_required_fields(cfg)
    assert "steam_api_key is missing" in errors
    assert "steam_id is missing" in errors


def test_required_fields_api_key_missing():
    cfg = Config(steam_id="76561198000000000")
    errors = _check_required_fields(cfg)
    assert "steam_api_key is missing" in errors
    assert len(errors) == 1


def test_required_fields_steam_id_missing():
    cfg = Config(steam_api_key="mykey")
    errors = _check_required_fields(cfg)
    assert "steam_id is missing" in errors
    assert len(errors) == 1


def test_required_fields_both_present():
    cfg = Config(steam_api_key="mykey", steam_id="76561198000000000")
    assert _check_required_fields(cfg) == []


# ── _check_file_paths ─────────────────────────────────────────────────────


def test_file_paths_game_ids_file_missing(tmp_path):
    cfg = Config(game_ids_file=str(tmp_path / "nonexistent.txt"))
    errors = _check_file_paths(cfg)
    assert any("game_ids_file not found" in e for e in errors)


def test_file_paths_game_ids_file_exists(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("440\n", encoding="utf-8")
    cfg = Config(game_ids_file=str(f))
    assert _check_file_paths(cfg) == []


def test_file_paths_steam_path_missing(tmp_path):
    cfg = Config(steam_path=str(tmp_path / "nosteam"))
    errors = _check_file_paths(cfg)
    assert any("steam_path not found" in e for e in errors)


def test_file_paths_steam_path_exists(tmp_path):
    cfg = Config(steam_path=str(tmp_path))
    assert _check_file_paths(cfg) == []


def test_file_paths_steam_path_empty_string_skipped():
    # Empty string = auto-detect, must not be checked
    cfg = Config(steam_path="")
    assert _check_file_paths(cfg) == []


def test_file_paths_sam_exe_missing(tmp_path):
    cfg = Config(sam_game_exe_path=str(tmp_path / "SAM.Game.exe"))
    errors = _check_file_paths(cfg)
    assert any("sam_game_exe_path not found" in e for e in errors)


def test_file_paths_sam_exe_exists(tmp_path):
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"")
    cfg = Config(sam_game_exe_path=str(exe))
    assert _check_file_paths(cfg) == []


def test_file_paths_sam_exe_empty_string_skipped():
    # Empty string = auto-download, must not be checked
    cfg = Config(sam_game_exe_path="")
    assert _check_file_paths(cfg) == []


def test_file_paths_all_unset():
    # Nothing set = nothing to check
    cfg = Config()
    assert _check_file_paths(cfg) == []
