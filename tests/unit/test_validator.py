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


from unittest.mock import MagicMock, patch

from app.validator import _check_steam_api, _check_steam_process


# ── _check_steam_process ──────────────────────────────────────────────────


def test_steam_process_running():
    proc = MagicMock()
    proc.name.return_value = "steam.exe"
    with patch("psutil.process_iter", return_value=[proc]):
        assert _check_steam_process() == []


def test_steam_process_not_running():
    proc = MagicMock()
    proc.name.return_value = "chrome.exe"
    with patch("psutil.process_iter", return_value=[proc]):
        errors = _check_steam_process()
        assert any("Steam is not running" in e for e in errors)


def test_steam_process_psutil_raises():
    with patch("psutil.process_iter", side_effect=RuntimeError("access denied")):
        errors = _check_steam_process()
        assert any("Could not check Steam process" in e for e in errors)


# ── _check_steam_api ──────────────────────────────────────────────────────


def _make_response(status: int, body: bytes):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_steam_api_valid():
    body = b'{"response":{"players":[{"steamid":"76561198000000000"}]}}'
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch("urllib.request.urlopen", return_value=_make_response(200, body)):
        assert _check_steam_api(cfg) == []


def test_steam_api_empty_players():
    body = b'{"response":{"players":[]}}'
    cfg = Config(steam_api_key="badkey", steam_id="76561198000000000")
    with patch("urllib.request.urlopen", return_value=_make_response(200, body)):
        errors = _check_steam_api(cfg)
        assert any("invalid or Steam ID not found" in e for e in errors)


def test_steam_api_rate_limited():
    import urllib.error
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None),
    ):
        errors = _check_steam_api(cfg)
        assert any("rate limited" in e for e in errors)


def test_steam_api_unexpected_status():
    import urllib.error
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 500, "Internal Server Error", {}, None),
    ):
        errors = _check_steam_api(cfg)
        assert any("HTTP 500" in e for e in errors)


def test_steam_api_network_error():
    import urllib.error
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        errors = _check_steam_api(cfg)
        assert any("Could not reach Steam API" in e for e in errors)
