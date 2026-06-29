"""ДИАГНОСТИКА (временный): воспроизводит путь boost и проверяет детект ошибки.

Реальный баг проявляется ТОЛЬКО в батче: boost запускает N игр staggered, затем
`drop_failed_launches` ОДИН раз (через 3с после последнего старта) проверяет окно
ошибки. Этот скрипт повторяет тот же запуск и вызывает НАСТОЯЩУЮ
`_has_error_window` по таймлайну — чтобы увидеть:

  * срабатывает ли функция вообще в боевом процессе (детект-баг?),
  * во сколько РЕАЛЬНО появляется окно ошибки у каждой игры (тайминг-баг?).

Игры НЕ убиваются до конца наблюдения и НЕ помечаются done/skip — только смотрим.

Запускать ОТДЕЛЬНО (Steam запущен, boost/farm НЕ запущены):
    python scripts/diag/dump_boost_batch_detect.py
    python scripts/diag/dump_boost_batch_detect.py 2021390 2063480 466160 --idle 40
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import time

from app.config import load_config
from app.logging_setup import setup_logging
from app.sam import check_steam_running, ensure_sam, kill_process
from app.sam.launcher import launch_games_staggered
from app.sam.win32_utils import _has_error_window
from app.validator import validate

log = logging.getLogger("sam_automation")

_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "diag"

# Несколько «сломанных» из реального батча + одна рабочая для контраста.
_DEFAULT_APPIDS = [2021390, 2063480, 2466790, 2593740, 466160]

# Точно как в boost: drop_failed_launches ждёт 3с после последнего старта.
_DROP_CHECK_DELAY = 3.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Воспроизводит batch-запуск boost и таймлайн детекта ошибки"
    )
    parser.add_argument(
        "appids",
        type=int,
        nargs="*",
        default=_DEFAULT_APPIDS,
        help="appid игр (по умолчанию набор из реального батча)",
    )
    parser.add_argument(
        "--idle",
        type=float,
        default=40.0,
        help="секунд наблюдать за детектом после запуска (по умолчанию 40)",
    )
    args = parser.parse_args()

    setup_logging(verbose=True, name="diag_batch_detect", category="diag")
    cfg = load_config()
    validate(cfg)

    if not check_steam_running():
        log.error("Steam не запущен")
        sys.exit(1)
    try:
        cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
    except RuntimeError as e:
        log.error(str(e))
        sys.exit(1)

    appids: list[int] = args.appids
    log.info(
        "Запускаю батч %d игр (stagger=%.1f), как boost...",
        len(appids),
        cfg.launch_stagger,
    )
    games = [(appid, str(appid)) for appid in appids]
    active = launch_games_staggered(
        cfg.sam_game_exe_path, games, stagger=cfg.launch_stagger
    )

    report: list[str] = [
        f"# Воспроизведение batch-детекта boost: {len(appids)} игр",
        f"# stagger={cfg.launch_stagger}s, drop_check_delay={_DROP_CHECK_DELAY}s, "
        f"idle={args.idle}s",
        f"# appid→pid: {[(a, p.pid) for a, p in active.items()]}",
        "",
    ]
    first_detect: dict[int, float] = {}
    detected_at_drop: dict[int, bool] = {}
    t0 = time.time()
    try:
        # Точка реальной проверки boost: один снимок через 3с после старта батча.
        time.sleep(_DROP_CHECK_DELAY)
        report.append(
            f"=== Момент drop_failed_launches (t={_DROP_CHECK_DELAY}s "
            "после батча) — РЕАЛЬНАЯ проверка boost ==="
        )
        for appid, proc in active.items():
            hit = _has_error_window(proc.pid)
            detected_at_drop[appid] = hit
            if hit:
                first_detect[appid] = round(time.time() - t0, 1)
            report.append(f"  [{appid}] pid={proc.pid} _has_error_window={hit}")
        report.append("")

        # Дальше — таймлайн: когда у каждой игры РЕАЛЬНО появляется окно ошибки.
        report.append("=== Таймлайн детекта (poll каждые 2с) ===")
        deadline = time.time() + args.idle
        while time.time() < deadline:
            elapsed = round(time.time() - t0, 1)
            row = []
            for appid, proc in active.items():
                alive = proc.poll() is None
                hit = _has_error_window(proc.pid)
                if hit and appid not in first_detect:
                    first_detect[appid] = elapsed
                row.append(
                    f"{appid}:{'ERR' if hit else ('ok' if alive else 'dead')}"
                )
            report.append(f"  [t={elapsed:>5}s] " + "  ".join(row))
            time.sleep(2.0)

        report.append("")
        report.append("=== ИТОГ ===")
        for appid in appids:
            at_drop = detected_at_drop.get(appid, False)
            first = first_detect.get(appid)
            report.append(
                f"  [{appid}] detected@drop(3s)={at_drop}  "
                f"first_error_seen={first if first is not None else 'НИКОГДА'}s"
            )
    finally:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = _OUT_DIR / "boost_batch_detect.txt"
        out.write_text("\n".join(report), encoding="utf-8")
        log.info("Отчёт записан: %s", out)
        for proc in active.values():
            kill_process(proc)
        log.info("Все процессы убиты.")


if __name__ == "__main__":
    main()
