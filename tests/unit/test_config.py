"""Тесты для app/config.py."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.config import Config, load_config

# ── load_config — файл не существует ──────────────────────────────────────


def test_load_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(str(tmp_path / "nonexistent.yaml"))
    assert isinstance(cfg, Config)
    assert cfg.steam_api_key == ""
    assert cfg.steam_id == ""
    assert cfg.launch_delay == 3.0
    assert cfg.load_timeout == 20.0
    assert cfg.max_consecutive_errors == 100
    assert cfg.launch_stagger == 3.0


def test_load_config_launch_stagger(write_config: Callable[..., str]) -> None:
    path = write_config(launch_stagger=1.5)
    cfg = load_config(path)
    assert cfg.launch_stagger == 1.5


def test_load_config_playtime_concurrent_games(
    write_config: Callable[..., str],
) -> None:
    path = write_config(playtime_concurrent_games=20)
    cfg = load_config(path)
    assert cfg.playtime_concurrent_games == 20


def test_playtime_concurrent_games_default() -> None:
    assert Config().playtime_concurrent_games == 10


# ── load_config — базовые поля ────────────────────────────────────────────


def test_load_config_required_fields(write_config: Callable[..., str]) -> None:
    path = write_config(steam_api_key="mykey", steam_id="76561198000000000")
    cfg = load_config(path)
    assert cfg.steam_api_key == "mykey"
    assert cfg.steam_id == "76561198000000000"


def test_load_config_numeric_steam_id_becomes_string(
    write_config: Callable[..., str],
) -> None:
    # YAML может загрузить steam_id как int, если не в кавычках
    path = write_config(steam_id=76561198000000000)
    cfg = load_config(path)
    assert cfg.steam_id == "76561198000000000"


def test_load_config_game_ids(write_config: Callable[..., str]) -> None:
    path = write_config(game_ids=[10, 440, 730])
    cfg = load_config(path)
    assert cfg.game_ids == [10, 440, 730]


def test_load_config_exclude_ids(write_config: Callable[..., str]) -> None:
    path = write_config(exclude_ids=[730, 440])
    cfg = load_config(path)
    assert set(cfg.exclude_ids) == {730, 440}


# ── load_config — числовые поля ───────────────────────────────────────────


def test_load_config_float_fields(write_config: Callable[..., str]) -> None:
    path = write_config(
        launch_delay=5.0, load_timeout=15, post_commit_delay=0.5
    )
    cfg = load_config(path)
    assert cfg.launch_delay == 5.0
    assert cfg.load_timeout == 15.0
    assert cfg.post_commit_delay == 0.5


def test_load_config_int_fields(write_config: Callable[..., str]) -> None:
    path = write_config(
        max_consecutive_errors=50,
        max_concurrent_games=3,
        card_check_interval=60,
    )
    cfg = load_config(path)
    assert cfg.max_consecutive_errors == 50
    assert cfg.max_concurrent_games == 3
    assert cfg.card_check_interval == 60


# ── load_config — путь к SAM.exe ──────────────────────────────────────────


def test_load_config_relative_sam_exe_resolved(
    write_config: Callable[..., str], tmp_path: Path
) -> None:
    path = write_config(sam_game_exe_path="external/SAM/SAM.Game.exe")
    cfg = load_config(path)
    expected = str(tmp_path / "external" / "SAM" / "SAM.Game.exe")
    assert cfg.sam_game_exe_path == expected


def test_load_config_absolute_sam_exe_unchanged(
    write_config: Callable[..., str],
) -> None:
    abs_path = r"C:\Tools\SAM\SAM.Game.exe"
    path = write_config(sam_game_exe_path=abs_path)
    cfg = load_config(path)
    assert cfg.sam_game_exe_path == abs_path
