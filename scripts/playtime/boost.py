"""Boost Playtime — добивает playtime до playtime_target_minutes в каждой игре.

Запускает SAM.Game.exe для каждой игры (фейковая сессия → Steam считает playtime).
Batch-модель: N игр одновременно → ждём playtime_idle_duration сек → закрываем всех → следующий батч.

Источник правды — Steam API (`playtime_forever`), локальный прогресс не хранится.

Использование:
    python scripts/playtime/boost.py              # добить недостающие игры
    python scripts/playtime/boost.py --list       # показать недобранные игры и выйти
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import atexit
import logging
import subprocess
import time
from typing import Any

from app.cache import (
    ALL_IDS_FILE,
    clear_playtime_progress,
    clear_playtime_skip,
    load_game_names,
    load_playtime_done_ids,
    load_playtime_skip_ids,
    mark_playtime_done,
    mark_playtime_skip,
)
from app.config import load_config
from app.id_file import read_ids_ordered
from app.logging_setup import SEPARATOR, setup_logging
from app.notify import send_telegram, toast
from app.run_lock import acquire_run_lock, release_run_lock
from app.sam import (
    check_steam_running,
    ensure_sam,
    idle_and_split_survivors,
    kill_all_sam_games,
    kill_process,
    launch_games_staggered,
)
from app.steam import fetch_owned_games, resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")

# Пауза после убийства батча перед стартом следующего (сек). Даёт Steam
# освободить global user от закрытых сессий — иначе первая игра нового
# батча ловит 'failed to connect to global user'.
_PAUSE_AFTER_KILL = 5.0


def _build_parser() -> argparse.ArgumentParser:
    """CLI-флаги boost."""
    parser = argparse.ArgumentParser(
        description="Boost Playtime — набивает время во всех играх из all.txt"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать игры к набивке и выйти",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить прогресс (playtime/done.txt) и набить время заново",
    )
    parser.add_argument(
        "--retry-skips",
        action="store_true",
        help="Очистить playtime/skip.txt — заново попробовать не подключившиеся",
    )
    return parser


def _prepare_progress(args: argparse.Namespace) -> None:
    """Применяет флаги сброса прогресса до сбора списка игр."""
    if args.reset:
        clear_playtime_progress()
        log.info("Сброшен прогресс playtime (--reset)")
    if args.retry_skips:
        clear_playtime_skip()
        log.info("Очищен skip playtime (--retry-skips)")


def _select_targets(
    all_ids: list[int],
    played: dict[int, int],
    skip: set[int],
    done: set[int],
    target: int,
    names: dict[int, str],
) -> list[dict]:
    """Игры из all_ids, которым нужно набить время (порядок сохранён).

    skip (exclude_ids ∪ skip.txt) — жёсткий пропуск для любых игр. done (done.txt)
    — resume-маркер, писанный ТОЛЬКО для unknown-игр, поэтому глушит ТОЛЬКО пока
    игра всё ещё unknown: как только Steam API снова отдаёт по ней playtime (стала
    known), гейтим её по played/target и игнорируем устаревший done. Это чинит
    переход unknown→known и делает самоисцеляющимся транзиентно-пустой owned
    (RA-A: иначе весь набитый вслепую в слепом прогоне список глушился навсегда).
    Для игр без известного playtime (нет в `played`) считаем 0 — их идлим.
    """
    out: list[dict] = []
    for appid in all_ids:
        if appid in skip:
            continue
        known = appid in played
        pt = played.get(appid, 0)
        if known:
            if pt >= target:
                continue  # known & набрана — истина по API
        elif appid in done:
            continue  # unknown & уже набивали вслепую — resume-пропуск
        out.append(
            {
                "appid": appid,
                "name": names.get(appid, str(appid)),
                "playtime_forever": pt,
                # known=True → Steam API отдаёт playtime, факт проверяется по API
                # (в done.txt не пишем); False → проверить нельзя, пишем в done.
                "known": known,
            }
        )
    return out


def _fetch_targets(cfg: Any, steam_id: str) -> tuple[list[dict], bool]:
    """Игры из all.txt к набивке + признак «слепого» прогона (blind).

    Вселенная — `all.txt` (полная библиотека). Steam Web API даёт playtime
    только для части игр; известные с playtime >= target пропускаем, остальные
    (в т.ч. free/демо/лицензии без данных API) идлим вслепую один раз.
    exclude_ids и playtime/skip.txt — жёсткий пропуск; playtime/done.txt —
    resume только для игр, всё ещё unknown (см. _select_targets).

    Returns:
        (games, blind) — blind=True, если owned-games API вернул пусто: тогда
        проверить нельзя НИЧЕГО, и вызывающий не персистит done (RA-A).
    """
    all_ids = read_ids_ordered(ALL_IDS_FILE)
    played = {
        g["appid"]: g.get("playtime_forever", 0)
        for g in fetch_owned_games(cfg.steam_api_key, steam_id)
    }
    blind = not played
    if all_ids and blind:
        # Owned-games API пуст при непустой библиотеке — приватные Game details
        # ЛИБО транзиентно-битый ответ (validate дёргает GetPlayerSummaries, не
        # GetOwnedGames, и это пропускает). Тогда ВСЕ игры считаются unknown.
        # Не абортим (аккаунт может быть полностью на Family Share), но громко
        # предупреждаем И не персистим done (blind=True) — иначе один слепой
        # прогон навсегда пометил бы done всю библиотеку (RA-A).
        log.warning(
            "Steam API не вернул owned-games при непустой all.txt — ВСЕ игры "
            "считаются unknown и набиваются вслепую (прогресс НЕ сохраняется). "
            "Проверь приватность профиля (Game details должны быть публичны)."
        )
    skip = set(cfg.exclude_ids) | load_playtime_skip_ids()
    done = load_playtime_done_ids()
    games = _select_targets(
        all_ids,
        played,
        skip,
        done,
        cfg.playtime_target_minutes,
        load_game_names(),
    )
    return games, blind


def _report_result(
    status: str, boosted: int, failed: int, total: int, cfg: Any
) -> None:
    """Честный финальный отчёт (лог + toast + Telegram).

    success-✅ только когда прогон дошёл до конца без провалов. Ctrl+C
    (`interrupted`), ошибка (`error`) и наличие провалов дают ⚠️ и честный
    текст, а не «✅ обработано» — инвариант честного отчёта.
    """
    processed = boosted + failed
    if status == "interrupted":
        head, ok = "прервано (Ctrl+C)", False
    elif status == "error":
        head, ok = "прервано ошибкой", False
    elif failed:
        head, ok = "готово с оговорками", False
    else:
        head, ok = "готово", True
    detail = (
        f"набито {boosted}, не подключились {failed}, "
        f"обработано {processed} / {total}"
    )
    log.info(SEPARATOR)
    log.info("Boost Playtime — %s. %s", head, detail)
    log.info(SEPARATOR)
    toast("SAM Automation — Playtime", f"{head}: {detail}")
    mark = "✅" if ok else "⚠️"
    send_telegram(f"{mark} Playtime boost — {head}: {detail}", cfg)


def _boost_loop(games: list[dict], cfg: Any, persist_done: bool = True) -> None:
    """Batch-цикл: запустить N игр → ждать playtime_idle_duration → убить всех → следующий батч.

    persist_done=False (слепой прогон, owned-games пуст) → unknown-выжившие НЕ
    пишутся в done.txt: проверить нечем, а один слепой прогон иначе навсегда
    пометил бы done всю библиотеку (RA-A, инвариант «unverified → НЕ done»).
    """
    total = len(games)
    boosted_count = 0
    failed_count = 0
    active: dict[int, subprocess.Popen] = {}
    # Известные игры (есть в Steam API) в done.txt не пишем — их «готовность»
    # определяется по реальному playtime через API при следующем скане.
    known_ids = {g["appid"] for g in games if g.get("known")}

    def _skip_if_unknown(appid: int) -> None:
        # known-игры гейтятся по Steam API: разовый (часто транзиентный) провал
        # НЕ хороним в skip навсегда — их перепроверит API на следующем прогоне.
        # skip только для unknown (по ним playtime не проверить).
        if appid not in known_ids:
            mark_playtime_skip(appid)

    log.info(SEPARATOR)
    log.info("Boost Playtime — начало работы")
    log.info(
        "Игр к обработке: %d | Параллельно: %d | Время айдла: %d сек",
        total,
        cfg.playtime_concurrent_games,
        cfg.playtime_idle_duration,
    )
    log.info(SEPARATOR)

    status = "ok"
    try:
        for i in range(0, total, cfg.playtime_concurrent_games):
            batch = games[i : i + cfg.playtime_concurrent_games]
            games_with_names = [
                (g["appid"], g.get("name", str(g["appid"]))) for g in batch
            ]
            active = launch_games_staggered(
                cfg.sam_game_exe_path,
                games_with_names,
                stagger=cfg.launch_stagger,
            )

            log.info(
                "Батч %d игр запущен, жду до %d сек...",
                len(active),
                cfg.playtime_idle_duration,
            )
            # Выжившие (процесс жив весь idle, без окна ошибки) реально набили
            # время; провалившиеся (умерли/окно 'Error') — нет. on_failed пишет
            # skip сразу при детекции — переживает Ctrl+C во время idle.
            survivors, failed = idle_and_split_survivors(
                active,
                cfg.playtime_idle_duration,
                on_failed=_skip_if_unknown,
            )

            failed_skip = [a for a in failed if a not in known_ids]
            failed_retry = [a for a in failed if a in known_ids]
            if failed_skip:
                log.info(
                    "Не подключились к Steam (в skip): %d", len(failed_skip)
                )
            if failed_retry:
                log.info(
                    "known-игры не подключились — ретрай по API: %d",
                    len(failed_retry),
                )
            for appid in survivors:
                # known гейтятся по реальному playtime_forever через API —
                # в done.txt их не пишем; unknown проверить нельзя → resume
                # (но только в НЕслепом прогоне: persist_done, RA-A).
                if persist_done and appid not in known_ids:
                    mark_playtime_done(appid)
                log.info("[%d] Закрыт", appid)

            boosted_count += len(survivors)
            failed_count += len(failed)
            log.info("Прогресс: %d / %d", boosted_count + failed_count, total)

            # Пауза перед следующим батчем — даём Steam освободить сессии
            if i + cfg.playtime_concurrent_games < total:
                time.sleep(_PAUSE_AFTER_KILL)

    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C).")
    except Exception:
        status = "error"
        log.exception("Boost прерван ошибкой.")
    finally:
        # Гарантированно добить активные + сироты недозапущенного батча на ЛЮБОМ
        # выходе (норма/Ctrl+C/ошибка) — иначе SAM.Game.exe осиротеют и займут
        # global user. Ctrl+C/ошибка НЕ пишут done (survivors помечаются только в
        # норме, внутри цикла). Второй Ctrl+C прямо во время уборки не должен её
        # оборвать — повторяем свип до 3 раз, глотая повторные прерывания.
        for _ in range(3):
            try:
                for proc in active.values():
                    kill_process(proc)
                kill_all_sam_games()
                break
            except KeyboardInterrupt:
                continue

    _report_result(status, boosted_count, failed_count, total, cfg)


def main() -> None:
    """Точка входа: парсит аргументы CLI и запускает цикл набивки playtime."""
    args = _build_parser().parse_args()

    setup_logging(name="boost_playtime", category="playtime/boost")
    cfg = load_config()
    validate(cfg)

    if not check_steam_running():
        log.error("Steam не запущен! Запусти Steam и попробуй снова.")
        sys.exit(1)
    log.info("Steam запущен")

    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    try:
        steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
    except RuntimeError as e:
        log.error("Не удалось определить Steam ID: %s", e)
        sys.exit(1)
    log.info("Steam ID: %s", steam_id)

    if args.list and (args.reset or args.retry_skips):
        log.warning(
            "--list только показывает цели; --reset/--retry-skips игнорируются"
        )
    if not args.list:
        # Run-lock берём ДО деструктивного --reset/--retry-skips: иначе второй
        # инстанс сотрёт done.txt работающего (его resume) ещё ДО того, как сам
        # упрётся в лок. --list read-only — без лока и без сброса прогресса.
        try:
            acquire_run_lock("playtime/boost")
        except RuntimeError as e:
            log.error(str(e))
            sys.exit(1)
        atexit.register(release_run_lock)
        _prepare_progress(args)

    log.info("Собираю игры для набивки из all.txt (вся библиотека)...")
    try:
        games, blind = _fetch_targets(cfg, steam_id)
    except RuntimeError as e:
        log.error("Не удалось собрать список игр: %s", e)
        sys.exit(1)
    log.info("Игр к набивке (без уже набитых и наигранных): %d", len(games))

    if not games:
        log.info("Нет игр для обработки!")
        sys.exit(0)

    batches = (len(games) + cfg.playtime_concurrent_games - 1) // (
        cfg.playtime_concurrent_games
    )
    est_min = batches * (cfg.playtime_idle_duration + _PAUSE_AFTER_KILL) / 60
    log.info(
        "Оценка: ~%.0f мин (%d батчей). Прерывание безопасно — resume по "
        "playtime/done.txt",
        est_min,
        batches,
    )

    if args.list:
        for g in games:
            pt = g.get("playtime_forever", 0)
            print(f"{g['appid']:>10}  [{pt:>3} мин]  —  {g.get('name', '?')}")
        sys.exit(0)

    _boost_loop(games, cfg, persist_done=not blind)


if __name__ == "__main__":
    main()
