"""Максимумы значков для правила «карточки уходят в распродажу» (B-16).

Источник — IPlayerService/GetBadges/v1 с steam_api_key (снято живьём 19.10.2026:
поля appid, level, border_color; у системных значков appid нет). Обычный значок
максимален на 5-м уровне, металлический (border_color=1) — на 1-м.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MAX_LEVEL = {0: 5, 1: 1}  # border_color -> уровень, дальше карточки не нужны


def badge_levels(raw: list[dict[str, Any]]) -> dict[tuple[int, int], int]:
    """GetBadges → {(appid, border_color): лучший уровень}."""
    result: dict[tuple[int, int], int] = {}
    for b in raw:
        appid = b.get("appid")
        if not appid:
            continue
        key = (int(appid), int(b.get("border_color", 0)))
        result[key] = max(result.get(key, 0), int(b.get("level", 0)))
    return result


def is_maxed(border: int, level: int) -> bool:
    need = MAX_LEVEL.get(border)
    return need is not None and level >= need


def fetch_badge_levels(
    api_key: str,
    steamid64: str,
    get_json: Callable[[str], dict[str, Any]],
) -> dict[tuple[int, int], int]:
    url = (
        "https://api.steampowered.com/IPlayerService/GetBadges/v1/"
        f"?key={api_key}&steamid={steamid64}"
    )
    body = get_json(url)
    return badge_levels(body.get("response", {}).get("badges", []) or [])
