"""Загрузка и валидация конфигурации из config.yaml."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("sam_automation")


def _num(raw: dict, key: str, cast: Callable[..., Any], current: Any) -> Any:
    """cast(raw[key]) с фолбэком: отсутствует → current; не-число → warning + current.

    Ручной config.yaml с опечаткой (напр. load_timeout: xyz) больше не роняет
    load_config сырым ValueError до валидации — берётся значение по умолчанию.
    """
    if key not in raw:
        return current
    try:
        return cast(raw[key])
    except (ValueError, TypeError):
        log.warning(
            "config.yaml: %s=%r не число — использую значение по умолчанию %r",
            key,
            raw[key],
            current,
        )
        return current


def _parse_int_list(raw_list: list, field: str) -> list[int]:
    """int() каждого элемента; нечисловые пропускает с warning (без трейсбека)."""
    out: list[int] = []
    for elem in raw_list:
        try:
            out.append(int(elem))
        except (ValueError, TypeError):
            log.warning(
                "config.yaml: %s содержит нечисловой элемент %r — пропущен",
                field,
                elem,
            )
    return out


@dataclass
class Config:
    """Конфигурация SAM Automation, загружаемая из config.yaml."""

    sam_game_exe_path: str = ""

    # Steam API
    steam_api_key: str = ""
    steam_id: str = ""

    game_ids: list[int] = field(default_factory=list)
    game_ids_file: str | None = None
    exclude_ids: list[int] = field(default_factory=list)

    # Таймауты (секунды)
    launch_delay: float = 3.0
    load_timeout: float = 20.0  # медленным играм нужно ~15-20с на загрузку
    post_commit_delay: float = 0.2
    between_games_delay: float = 0.1
    launch_stagger: float = 3.0  # пауза между стартами игр в батче (playtime)

    # Пути
    steam_path: str = ""  # путь к папке Steam (автоопределяется если пусто)

    # Поведение
    max_consecutive_errors: int = 100

    # Card farming
    max_concurrent_games: int = 1  # сколько игр идлить одновременно
    card_check_interval: int = 10  # минут между проверками card drops

    # Playtime boosting
    playtime_idle_duration: int = 120  # секунд идлить каждую игру
    playtime_target_minutes: int = 3  # минимум минут playtime для каждой игры
    playtime_concurrent_games: int = (
        10  # сколько игр идлить параллельно (boost)
    )

    # Telegram уведомления (опционально; пусто → уведомления отключены)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


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

    if "game_ids" in raw:
        if isinstance(raw["game_ids"], list):
            cfg.game_ids = _parse_int_list(raw["game_ids"], "game_ids")
        else:
            log.warning(
                "config.yaml: game_ids не список — игнорирую (ожидается [id, ...])"
            )

    cfg.game_ids_file = raw.get("game_ids_file")

    if "exclude_ids" in raw:
        if isinstance(raw["exclude_ids"], list):
            cfg.exclude_ids = _parse_int_list(raw["exclude_ids"], "exclude_ids")
        else:
            log.warning(
                "config.yaml: exclude_ids не список — игнорирую; эти игры НЕ "
                "будут исключены (ожидается [id, ...])"
            )

    for float_key in (
        "launch_delay",
        "load_timeout",
        "post_commit_delay",
        "between_games_delay",
        "launch_stagger",
    ):
        setattr(
            cfg, float_key, _num(raw, float_key, float, getattr(cfg, float_key))
        )

    for int_key in (
        "max_consecutive_errors",
        "max_concurrent_games",
        "card_check_interval",
        "playtime_idle_duration",
        "playtime_target_minutes",
        "playtime_concurrent_games",
    ):
        setattr(cfg, int_key, _num(raw, int_key, int, getattr(cfg, int_key)))

    cfg.telegram_bot_token = raw.get("telegram_bot_token", "")
    cfg.telegram_chat_id = str(raw.get("telegram_chat_id", ""))

    # Резолвим относительный путь к exe от директории конфига
    if cfg.sam_game_exe_path and not os.path.isabs(cfg.sam_game_exe_path):
        cfg.sam_game_exe_path = str(path.parent / cfg.sam_game_exe_path)

    return cfg
