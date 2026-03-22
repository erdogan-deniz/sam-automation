"""Загрузка и валидация конфигурации из config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class Config:
    sam_game_exe_path: str = ""

    # Steam API
    steam_api_key: str = ""
    steam_id: str = ""

    game_ids: list[int] = field(default_factory=list)
    game_ids_file: str | None = None
    exclude_ids: list[int] = field(default_factory=list)

    # Таймауты (секунды)
    launch_delay: float = 3.0
    load_timeout: float = 45.0
    post_commit_delay: float = 0.2
    between_games_delay: float = 0.1

    # Пути
    steam_path: str = ""  # путь к папке Steam (автоопределяется если пусто)

    # Поведение
    max_consecutive_errors: int = 100

    # Card farming
    max_concurrent_games: int = 1   # сколько игр идлить одновременно
    card_check_interval: int = 10   # минут между проверками card drops


def load_config(config_path: str = "config.yaml") -> Config:
    """Загружает конфигурацию из YAML-файла.

    Если файл не найден — возвращает конфигурацию по умолчанию.
    """
    path = Path(config_path)
    if not path.exists():
        return Config()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = Config()

    if "sam_game_exe_path" in raw:
        cfg.sam_game_exe_path = raw["sam_game_exe_path"]

    cfg.steam_api_key = raw.get("steam_api_key", "")
    cfg.steam_id = str(raw.get("steam_id", ""))
    cfg.steam_path = raw.get("steam_path", "")

    if "game_ids" in raw and isinstance(raw["game_ids"], list):
        cfg.game_ids = [int(gid) for gid in raw["game_ids"]]

    cfg.game_ids_file = raw.get("game_ids_file")

    if "exclude_ids" in raw and isinstance(raw["exclude_ids"], list):
        cfg.exclude_ids = [int(gid) for gid in raw["exclude_ids"]]

    for float_key in ("launch_delay", "load_timeout", "post_commit_delay", "between_games_delay"):
        if float_key in raw:
            setattr(cfg, float_key, float(raw[float_key]))

    if "max_consecutive_errors" in raw:
        cfg.max_consecutive_errors = int(raw["max_consecutive_errors"])

    if "max_concurrent_games" in raw:
        cfg.max_concurrent_games = int(raw["max_concurrent_games"])

    if "card_check_interval" in raw:
        cfg.card_check_interval = int(raw["card_check_interval"])

    # Резолвим относительный путь к exe от директории конфига
    if cfg.sam_game_exe_path and not os.path.isabs(cfg.sam_game_exe_path):
        cfg.sam_game_exe_path = str(path.parent / cfg.sam_game_exe_path)

    return cfg
