"""Резолвинг Steam ID — числовые ID64, vanity URL, полные ссылки на профиль."""

from __future__ import annotations

import re

from .steam_api import _api_get

BASE_URL = "https://api.steampowered.com"


def resolve_vanity_url(api_key: str, vanity_name: str) -> str:
    """Резолвит vanity URL (кастомное имя профиля) в Steam ID 64.

    Пример: 'gabelogannewell' → '76561197960287930'
    """
    url = (
        f"{BASE_URL}/ISteamUser/ResolveVanityURL/v1/"
        f"?key={api_key}&vanityurl={vanity_name}"
    )
    data = _api_get(url)
    resp = data.get("response", {})

    if resp.get("success") != 1:
        raise RuntimeError(
            f"Не удалось резолвить vanity URL '{vanity_name}': "
            f"{resp.get('message', 'unknown error')}"
        )

    return resp["steamid"]


def resolve_steam_id(api_key: str, steam_id_or_url: str) -> str:
    """Принимает Steam ID 64, vanity name или полный URL профиля → возвращает Steam ID 64."""
    # Уже числовой Steam ID 64
    if re.fullmatch(r"\d{17}", steam_id_or_url):
        return steam_id_or_url

    # URL вида steamcommunity.com/id/vanityname или /profiles/76561...
    m = re.search(r"steamcommunity\.com/id/([^/?\s]+)", steam_id_or_url)
    if m:
        return resolve_vanity_url(api_key, m.group(1))

    m = re.search(r"steamcommunity\.com/profiles/(\d{17})", steam_id_or_url)
    if m:
        return m.group(1)

    # Считаем vanity name
    return resolve_vanity_url(api_key, steam_id_or_url)
