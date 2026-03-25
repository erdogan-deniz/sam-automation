"""Определяет игры с оставшимися card drops — два метода.

Метод A (быстрый, без авторизации):
  IPlayerService/GetBadges → owned игры без значка = скорее всего есть дропы.
  НЕ знает точное количество дропов. НЕ фильтрует игры без карточек.
  Даёт приблизительный список для оценки масштаба.

Метод B (точный, нужна авторизация):
  Парсит /profiles/{steamid}/badges/ через JWT steamLoginSecure cookie.
  Показывает точно: '2 card drops remaining' для каждой игры.
  Первый запуск = интерактивный ввод 2FA кода. Далее — из кэша.

Использование:
    python scripts/cards/detect_drops.py          # оба метода
    python scripts/cards/detect_drops.py --fast   # только метод A (без авторизации)
    python scripts/cards/detect_drops.py --exact  # только метод B (нужна авторизация)
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

import argparse

from app.cards import fetch_games_with_card_drops
from app.config import load_config
from app.logging_setup import setup_logging
from app.validator import validate
from app.steam import (
    fetch_badge_app_ids,
    fetch_owned_games,
    get_web_cookies,
    resolve_steam_id,
)

# ---------------------------------------------------------------------------
# Метод A — быстрый, без авторизации
# ---------------------------------------------------------------------------


def method_a(api_key: str, steam_id: str, owned: list[dict]) -> list[dict]:
    """Метод A: owned игры без значка → скорее всего есть card drops.

    Ограничения:
      - Нет фильтра «has trading cards» — много ложных срабатываний
      - Игры с badge level ≥ 1 пропускаются, хотя drops могут быть
      - Игры без значка могут не иметь карточек вовсе
    """
    badge_appids = fetch_badge_app_ids(api_key, steam_id)
    if not badge_appids:
        return []

    return [g for g in owned if g["appid"] not in badge_appids]


# ---------------------------------------------------------------------------
# Метод B — точный, нужна JWT авторизация
# ---------------------------------------------------------------------------


def method_b(cookies: dict, steam_id: str) -> list[tuple[int, int]]:
    """Метод B: badges page → точные (appid, drops_remaining)."""
    return fetch_games_with_card_drops(cookies, steam_id)


# ---------------------------------------------------------------------------
# Главная логика
# ---------------------------------------------------------------------------


def main() -> None:
    """Точка входа: определяет игры с оставшимися card drops одним или двумя методами."""
    parser = argparse.ArgumentParser(description="Обнаружение игр с card drops")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Только метод A (без авторизации, приблизительно)",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Только метод B (точный, нужна авторизация)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log = setup_logging(
        verbose=args.verbose, name="detect_card_drops", category="cards/detect"
    )
    cfg = load_config()

    validate(cfg)

    try:
        steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
    except RuntimeError as e:
        log.error("Steam ID: %s", e)
        sys.exit(1)

    log.info("Steam ID: %s", steam_id)

    log.info("Загружаю список owned игр...")
    try:
        owned = fetch_owned_games(cfg.steam_api_key, steam_id)
    except Exception as e:
        log.error("Не удалось получить список игр: %s", e)
        sys.exit(1)
    log.info("Owned игр: %d", len(owned))

    run_a = not args.exact  # по умолчанию оба
    run_b = not args.fast

    # ── Метод A ─────────────────────────────────────────────────────────────
    if run_a:
        print()
        print("=" * 60)
        print("МЕТОД A — быстрый (без авторизации, приблизительный)")
        print("=" * 60)
        print("Owned игры без значка ~ вероятно есть card drops.")
        print(
            "[!] Не учитывает: наличие карточек в игре, дропы внутри уже фармленных игр."
        )
        print()

        log.info("Метод A: запрашиваю IPlayerService/GetBadges...")
        candidates = method_a(cfg.steam_api_key, steam_id, owned)

        print(f"Owned игр без значка: {len(candidates)} из {len(owned)}")
        print("Первые 20:")
        for g in sorted(candidates, key=lambda x: x.get("name", "?"))[:20]:
            print(f"  {g['appid']:>10}  {g.get('name', '?')}")
        if len(candidates) > 20:
            print(f"  ... и ещё {len(candidates) - 20} игр")

    # ── Метод B ─────────────────────────────────────────────────────────────
    if run_b:
        print()
        print("=" * 60)
        print("МЕТОД B — точный (нужна JWT авторизация)")
        print("=" * 60)
        print("Парсит /badges/ страницу. Точные данные о дропах.")
        print()

        log.info("Метод B: получаю JWT cookies...")
        cookies = get_web_cookies(cfg.steam_id)

        if not cookies:
            print("✗  JWT авторизация не удалась.")
            print()
            print("Что делать:")
            print("  1. Запусти этот скрипт в реальном терминале (не IDE):")
            print("     python scripts/cards/detect_drops.py --exact")
            print("  2. Введи 2FA код когда появится запрос '[Steam JWT]'")
            print(
                "  3. После первого запуска авторизация кэшируется — 2FA больше не нужна"
            )
            sys.exit(1)

        log.info("Метод B: парсю badges страницу...")
        games = method_b(cookies, steam_id)

        print(f"Игр с оставшимися card drops: {len(games)}")
        print()

        if games:
            owned_map = {g["appid"]: g.get("name", "?") for g in owned}
            print(f"{'AppID':>10}  {'Drops':>5}  Название")
            print("-" * 60)
            for appid, drops in sorted(games, key=lambda x: -x[1]):
                name = owned_map.get(appid, "?")
                print(f"{appid:>10}  {drops:>5}  {name}")
        else:
            print("Нет игр с оставшимися card drops.")


if __name__ == "__main__":
    main()
