"""Список игр с оставшимися card drops.

Парсит /profiles/{steamid}/badges/ через JWT steamLoginSecure cookie.
Показывает точно: '2 card drops remaining' для каждой игры.

Использование:
    python scripts/cards/scan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Принудительный UTF-8 на Windows
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )

from app.cards import fetch_games_with_card_drops
from app.config import load_config
from app.logging_setup import setup_logging
from app.validator import validate
from app.steam import (
    fetch_owned_games,
    get_web_cookies,
    resolve_steam_id,
)


def main() -> None:
    log = setup_logging(
        verbose=False, name="scan_cards", category="cards/scan"
    )
    cfg = load_config()
    validate(cfg)

    try:
        steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
    except RuntimeError as e:
        log.error("Steam ID: %s", e)
        sys.exit(1)

    cookies = get_web_cookies(cfg.steam_id)

    if not cookies:
        print("✗  JWT авторизация не удалась.")
        print()
        print("Что делать:")
        print("  1. Запусти этот скрипт в реальном терминале (не IDE):")
        print("     python scripts/cards/scan.py")
        print("  2. Введи 2FA код когда появится запрос '[Steam JWT]'")
        print(
            "  3. После первого запуска авторизация кэшируется — 2FA больше не нужна"
        )
        sys.exit(1)

    games = fetch_games_with_card_drops(cookies, steam_id)

    try:
        owned = fetch_owned_games(cfg.steam_api_key, steam_id)
    except Exception:
        owned = []

    print(f"Игр с оставшимися card drops: {len(games)}")
    print()

    if games:
        owned_map = {g["appid"]: g.get("name", "?") for g in owned}
        print(f"{'AppID':>10}  {'Drops':>5}  Название")
        print("═" * 80)
        for appid, drops in sorted(games, key=lambda x: -x[1]):
            name = owned_map.get(appid, "?")
            print(f"{appid:>10}  {drops:>5}  {name}")
    else:
        print("Нет игр с оставшимися card drops.")


if __name__ == "__main__":
    main()
