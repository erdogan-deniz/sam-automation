"""Предстартовая валидация config.yaml.

Использование в скриптах:
    from app.validator import validate
    cfg = load_config()
    validate(cfg)   # завершает процесс с sys.exit(1) при любой ошибке
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from app.config import Config

log = logging.getLogger("sam_automation")


# ── Phase 1: local checks ─────────────────────────────────────────────────


def _check_required_fields(cfg: Config) -> list[str]:
    """Проверяет наличие обязательных полей конфига."""
    errors: list[str] = []
    if not cfg.steam_api_key:
        errors.append("steam_api_key is missing")
    if not cfg.steam_id:
        errors.append("steam_id is missing")
    return errors


def _check_file_paths(cfg: Config) -> list[str]:
    """Проверяет существование путей к файлам, указанных в конфиге."""
    errors: list[str] = []
    if cfg.game_ids_file and not Path(cfg.game_ids_file).exists():
        errors.append(f"game_ids_file not found: {cfg.game_ids_file}")
    if cfg.steam_path and not Path(cfg.steam_path).exists():
        errors.append(f"steam_path not found: {cfg.steam_path}")
    if cfg.sam_game_exe_path and not Path(cfg.sam_game_exe_path).exists():
        errors.append(f"sam_game_exe_path not found: {cfg.sam_game_exe_path}")
    return errors


# ── Phase 2: external checks ──────────────────────────────────────────────


def _check_steam_process() -> list[str]:
    """Проверяет, запущен ли процесс steam.exe."""
    try:
        # Use p.name() (method) rather than p.info["name"] (attrs accessor);
        # the attrs pattern requires process_iter to be called with attrs=["name"],
        # but method access works regardless of which attrs were requested.
        names = {p.name().lower() for p in psutil.process_iter(["name"])}
        if "steam.exe" not in names:
            return ["Steam is not running — start Steam and try again"]
        return []
    except Exception as exc:
        return [f"Could not check Steam process: {exc}"]


def _check_steam_api(cfg: Config) -> list[str]:
    """Делает тестовый запрос к Steam API, проверяет ключ и Steam ID."""
    url = (
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
        f"?key={cfg.steam_api_key}&steamids={cfg.steam_id}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            # urlopen only returns here on HTTP 200; non-2xx raises HTTPError
            data = json.loads(resp.read())
            players = data.get("response", {}).get("players", [])
            if not players:
                return ["Steam API key is invalid or Steam ID not found"]
            return []
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return ["Steam API rate limited (HTTP 429) — try again in a moment"]
        return [f"Steam API returned unexpected status: HTTP {exc.code}"]
    except urllib.error.URLError as exc:
        return [f"Could not reach Steam API: {exc.reason}"]
    except OSError as exc:
        return [f"Could not reach Steam API: {exc}"]


# ── Orchestrator ──────────────────────────────────────────────────────────


def _report_and_exit(errors: list[str]) -> None:
    """Логирует все ошибки и завершает процесс с кодом 1."""
    for err in errors:
        log.error("[CONFIG ERROR] %s", err)
    count = len(errors)
    noun = "error" if count == 1 else "errors"
    log.error("%d config %s found. Fix config.yaml and try again.", count, noun)
    sys.exit(1)


def validate(cfg: Config) -> None:
    """Запускает все pre-flight проверки. Вызывает sys.exit(1) при ошибке. Никогда не бросает исключений."""
    # Phase 1 — local (fast, no network)
    errors: list[str] = []
    errors.extend(_check_required_fields(cfg))
    errors.extend(_check_file_paths(cfg))
    if errors:
        _report_and_exit(errors)

    # Phase 2 — external (process + network)
    errors.extend(_check_steam_process())
    errors.extend(_check_steam_api(cfg))
    if errors:
        _report_and_exit(errors)
