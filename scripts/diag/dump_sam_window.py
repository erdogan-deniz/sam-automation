"""ДИАГНОСТИКА (временный скрипт): дамп UIA-дерева окна SAM.Game.

Открывает указанную игру через SAM.Picker, ждёт загрузки достижений и
записывает всё дерево контролов окна Manager в data/sam_dump_<appid>.txt.
Нужно, чтобы увидеть реальный контрол списка достижений и состояние строк
(locked/unlocked) — для замены чтения статус-бара проверкой «по факту».

Запускать ОТДЕЛЬНО (не во время farm — конфликт за SAM):
    python scripts/diag/dump_sam_window.py 493180
    python scripts/diag/dump_sam_window.py 493180 --wait 20
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
from app.sam import (
    check_steam_running,
    close_game,
    ensure_sam,
    kill_process,
    launch_picker,
)
from app.validator import validate

log = logging.getLogger("sam_automation")

_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _walk(ctrl, depth: int, lines: list[str], counts: dict[str, int]) -> None:
    """Рекурсивно обходит контролы, пишет тип/класс/id/текст/состояние."""
    try:
        ei = ctrl.element_info
        ctype = getattr(ei, "control_type", "") or ""
        counts[ctype] = counts.get(ctype, 0) + 1
        try:
            aid = ctrl.automation_id()
        except Exception:
            aid = ""
        try:
            cls = ctrl.friendly_class_name()
        except Exception:
            cls = ""
        try:
            txt = ctrl.window_text()
        except Exception:
            txt = ""
        # Состояния (для ListItem: выбран / отмечен) — что доступно у элемента
        state = ""
        for attr in ("is_checked", "is_selected"):
            try:
                fn = getattr(ctrl, attr, None)
                if callable(fn):
                    state += f" {attr}={fn()}"
            except Exception:
                pass
        lines.append(
            f"{'  ' * depth}[{ctype}] cls={cls!r} id={aid!r} "
            f"text={txt!r}{state}"
        )
    except Exception as e:  # noqa: BLE001
        lines.append(f"{'  ' * depth}<ошибка чтения контрола: {e}>")
        return

    try:
        for child in ctrl.children():
            _walk(child, depth + 1, lines, counts)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Дамп UIA-дерева окна SAM.Game для одной игры"
    )
    parser.add_argument("appid", type=int, help="App ID игры")
    parser.add_argument(
        "--wait",
        type=float,
        default=15.0,
        help="секунд ждать загрузки достижений перед дампом (по умолчанию 15)",
    )
    args = parser.parse_args()

    setup_logging(verbose=True, name="diag_dump", category="diag")
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

    proc, session = launch_picker(
        cfg.sam_game_exe_path, launch_delay=cfg.launch_delay
    )
    game_app = None
    try:
        game_app = session.add_and_open_game(
            args.appid, timeout=cfg.load_timeout
        )
        log.info("Окно открыто. Жду %.0fс загрузки достижений...", args.wait)
        time.sleep(args.wait)

        wins = game_app.windows()
        if not wins:
            log.error("Окно SAM.Game исчезло за время ожидания")
            sys.exit(1)
        game_window = wins[0]
        lines: list[str] = []
        counts: dict[str, int] = {}
        _walk(game_window, 0, lines, counts)

        out = _OUT_DIR / f"sam_dump_{args.appid}.txt"
        out.parent.mkdir(exist_ok=True)
        header = [
            f"# Дамп окна SAM.Game для appid={args.appid} (wait={args.wait}s)",
            f"# Сводка по типам контролов: {counts}",
            "",
        ]
        out.write_text("\n".join(header + lines), encoding="utf-8")
        log.info("Дерево записано: %s (%d контролов)", out, len(lines))
        log.info("Сводка по типам: %s", counts)
    finally:
        if game_app is not None:
            close_game(game_app)
        kill_process(proc)


if __name__ == "__main__":
    main()
