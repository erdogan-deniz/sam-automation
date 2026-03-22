"""SAM Card Farming — автоматический фарм Steam trading card drops.

Открывает игры через SAM.Game.exe (создаёт фейковую игровую сессию),
периодически проверяет через Steam Community, остались ли card drops.
Закрывает игру как только drops заканчиваются, открывает следующую.

Использование:
    python scripts/card_farming.py              # начать/продолжить фарм
    python scripts/card_farming.py --list       # показать игры с card drops
    python scripts/card_farming.py --reset      # сбросить прогресс и начать заново
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import subprocess
import time
import logging
from collections import deque

from app.cache import mark_card_done, clear_card_progress
from app.card_checker import fetch_games_with_card_drops, check_cards_remaining
from app.config import load_config
from app.logging_setup import setup_logging
from app.setup import check_steam_running, ensure_sam
from app.steam_api import fetch_owned_games, resolve_steam_id
from app.steam_cm import get_web_cookies


def _launch_game(sam_game_exe: str, appid: int) -> subprocess.Popen:
    """Запускает SAM.Game.exe для указанного AppID."""
    exe = Path(sam_game_exe)
    log = logging.getLogger("sam_automation")
    try:
        proc = subprocess.Popen(
            [str(exe), str(appid)],
            cwd=str(exe.parent),
        )
    except OSError as e:
        raise RuntimeError(f"Не удалось запустить SAM.Game.exe для {appid}: {e}") from e
    log.info("[%d] SAM.Game.exe запущен (PID=%d)", appid, proc.pid)
    return proc


def _kill_game(appid: int, proc: subprocess.Popen) -> None:
    """Завершает процесс SAM.Game.exe."""
    log = logging.getLogger("sam_automation")
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    log.info("[%d] SAM.Game.exe закрыт", appid)


def main() -> None:
    parser = argparse.ArgumentParser(description="SAM Card Farming")
    parser.add_argument("--list", action="store_true",
                        help="Показать игры с оставшимися card drops и выйти")
    parser.add_argument("--reset", action="store_true",
                        help="Сбросить прогресс card farming и начать заново")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log = setup_logging(verbose=args.verbose, name="card_farming", category="cards/farming")
    cfg = load_config()

    # Валидация
    if not cfg.steam_api_key or not cfg.steam_id:
        log.error("Заполни steam_api_key и steam_id в config.yaml")
        sys.exit(1)

    if args.reset:
        clear_card_progress()
        log.info("Прогресс card farming сброшен")

    # Steam должен быть запущен
    if not check_steam_running():
        log.error("Steam не запущен! Запусти Steam и попробуй снова.")
        sys.exit(1)
    log.info("Steam запущен")

    # Авто-скачивание SAM если нет
    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    # Резолвим Steam ID
    try:
        steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
    except RuntimeError as e:
        log.error("Не удалось определить Steam ID: %s", e)
        sys.exit(1)
    log.info("Steam ID: %s", steam_id)

    # Получаем owned игры — нужны только для отображения имён в --list
    log.info("Получаю список owned игр...")
    try:
        owned = fetch_owned_games(cfg.steam_api_key, steam_id)
    except Exception as e:
        log.warning("Не удалось получить список игр (имена не будут отображены): %s", e)
        owned = []

    # ── Фаза 1: badges page (только игры с реально оставшимися дропами) ──────
    log.info("Фаза 1: получаю список игр с оставшимися card drops через badges page...")
    cookies = get_web_cookies(cfg.steam_id)
    if cookies:
        phase1 = fetch_games_with_card_drops(cookies, steam_id)
        log.info("Фаза 1: найдено %d игр с оставшимися дропами", len(phase1))
    else:
        log.error(
            "Фаза 1: нет авторизации Steam. Запусти скрипт вручную один раз:\n"
            "  python scripts/card_farming.py\n"
            "и введи 2FA код при запросе '[Steam JWT] Введи 2FA код'."
        )
        sys.exit(1)

    games_with_drops = phase1

    if not games_with_drops:
        log.info("Нет игр с оставшимися card drops — всё уже получено!")
        sys.exit(0)

    if args.list:
        log.info("Игр с trading cards к обработке: %d", len(games_with_drops))
        for appid, _ in games_with_drops:
            name = next((g.get("name", "?") for g in owned if g["appid"] == appid), "?")
            print(f"{appid:>10}  —  {name}")
        sys.exit(0)

    # ── Farming loop ────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("SAM Card Farming — начало работы")
    log.info("Игр к обработке: %d | Параллельно: %d | Интервал проверки: %d мин",
             len(games_with_drops), cfg.max_concurrent_games, cfg.card_check_interval)
    log.info("=" * 60)

    queue: deque[tuple[int, int]] = deque(games_with_drops)
    active: dict[int, subprocess.Popen] = {}  # appid → процесс

    def _open_next() -> None:
        """Открывает следующую игру из очереди если есть место."""
        while queue and len(active) < cfg.max_concurrent_games:
            appid, cnt = queue.popleft()
            drops_str = str(cnt) if cnt >= 0 else "?"
            log.info("[%d] Открываю для idle (%s drops remaining)", appid, drops_str)
            active[appid] = _launch_game(cfg.sam_game_exe_path, appid)

    _open_next()

    try:
        while active:
            log.info(
                "Idle: %s | Ожидаю %d мин до следующей проверки...",
                list(active.keys()),
                cfg.card_check_interval,
            )
            time.sleep(cfg.card_check_interval * 60)

            for appid in list(active):
                remaining = check_cards_remaining(cookies, steam_id, appid)
                time.sleep(1.0)  # пауза между запросами

                if remaining == 0:
                    log.info("[%d] Card drops закончились — закрываю игру", appid)
                    _kill_game(appid, active.pop(appid))
                    mark_card_done(appid)
                    _open_next()
                elif remaining > 0:
                    log.info("[%d] Ещё %d card drop(s) — продолжаю idle", appid, remaining)
                else:
                    log.warning("[%d] Не удалось определить card drops — продолжаю idle", appid)

    except KeyboardInterrupt:
        log.info("Прервано (Ctrl+C). Закрываю все активные игры...")
    finally:
        for appid, proc in active.items():
            _kill_game(appid, proc)

    log.info("=" * 60)
    log.info("Card farming завершён")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
