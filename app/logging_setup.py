"""Настройка логирования: консоль + файл."""

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"

SEPARATOR = "═" * 80


def centered(text: str, width: int = 70, char: str = "═") -> str:
    """Центрирует text между полосами из char до заданной ширины.

    Воспроизводит прежний inline-формат заголовков в скриптах:
    «═══ [1/10] ═══». При тексте шире width полосы исчезают (side ≤ 0).
    """
    side = (width - len(text) - 2) // 2
    bar = char * side  # при отрицательном side Python даёт "" — полос нет
    return f"{bar} {text} {bar}"


def setup_logging(
    verbose: bool = False, name: str = "sam", category: str = ""
) -> logging.Logger:
    """Настраивает корневой логгер с выводом в консоль и файл.

    Файл создаётся в logs/<category>/<name>_TIMESTAMP.log.
    """
    log_dir = LOG_DIR / category if category else LOG_DIR / name
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("sam_automation")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    # Формат
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Консоль — UTF-8 + errors='replace' для не-Unicode терминалов (cp1251 и т.п.).
    # encoding="utf-8" переключает кодировку (нужно для ═, ✗ и пр.); errors страхует.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Файл
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_handler = logging.FileHandler(
        log_dir / f"{timestamp}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
