"""Предстартовая валидация config.yaml.

Использование в скриптах:
    from app.validator import validate
    cfg = load_config()
    validate(cfg)   # завершает процесс с sys.exit(1) при любой ошибке
"""

from __future__ import annotations

import http.client
import json
import logging
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

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


_MAX_CONCURRENT_LIMIT = 20  # разумный потолок; выше — почти наверняка опечатка


def _check_numeric_bounds(cfg: Config) -> list[str]:
    """Проверяет числовые параметры (руками отредактированный config.yaml).

    Ловит max_concurrent_games:0 (тихий no-op «успех»), отрицательный
    card_check_interval (busy-loop/крэш) и абсурдно большую конкурентность
    (шторм запусков SAM.Game.exe).
    """
    errors: list[str] = []
    for field in ("max_concurrent_games", "playtime_concurrent_games"):
        val = getattr(cfg, field)
        if val < 1:
            # 0 → ZeroDivisionError/range-error в boost; <0 → тихий no-op.
            errors.append(f"{field} must be >= 1 (got {val})")
        elif val > _MAX_CONCURRENT_LIMIT:
            errors.append(
                f"{field} too high: {val} (max {_MAX_CONCURRENT_LIMIT})"
            )
    if cfg.card_check_interval < 1:
        errors.append(
            f"card_check_interval must be >= 1 minute "
            f"(got {cfg.card_check_interval})"
        )
    # Playtime boost: idle<=0 не идлит (unknown-выжившие ложно done);
    # target<=0 пропускает ВСЕ игры (тихий no-op); stagger<0 → time.sleep()
    # ValueError крашит батч и осиротляет уже запущенные SAM.Game.exe.
    if cfg.playtime_idle_duration < 1:
        errors.append(
            f"playtime_idle_duration must be >= 1 second "
            f"(got {cfg.playtime_idle_duration})"
        )
    if cfg.playtime_target_minutes < 1:
        errors.append(
            f"playtime_target_minutes must be >= 1 "
            f"(got {cfg.playtime_target_minutes})"
        )
    # not isfinite → nan/inf: `nan < 0` и `inf < 0` == False проскакивали бы guard
    # >= 0, а time.sleep(nan) бросает ValueError / time.sleep(inf) спит вечно.
    if not math.isfinite(cfg.launch_stagger) or cfg.launch_stagger < 0:
        errors.append(
            f"launch_stagger must be a finite number >= 0 "
            f"(got {cfg.launch_stagger})"
        )
    return errors


# ── Phase 2: external checks ──────────────────────────────────────────────


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
    except (OSError, http.client.HTTPException) as exc:
        return [f"Could not reach Steam API: {exc}"]
    except ValueError as exc:
        # HTTP 200 с не-JSON телом (Cloudflare/captive-portal HTML) →
        # JSONDecodeError (подкласс ValueError). validate() обещает «никогда
        # не бросает» — возвращаем ошибку, а не сырой трейсбек.
        return [f"Steam API вернул не-JSON ответ: {exc}"]


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
    errors.extend(_check_numeric_bounds(cfg))
    if errors:
        _report_and_exit(errors)

    # Phase 2 — external (network only; Steam process check is each script's responsibility)
    errors.extend(_check_steam_api(cfg))
    if errors:
        _report_and_exit(errors)
