"""Настройка логирования: консоль + файл."""

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")


def setup_logging(verbose: bool = False, name: str = "sam") -> logging.Logger:
    """Настраивает корневой логгер с выводом в консоль и файл.

    Файл создаётся в logs/<name>_YYYYMMDD_HHMMSS.log. Консоль получает INFO (или DEBUG при verbose).
    """
    LOG_DIR.mkdir(exist_ok=True)

    logger = logging.getLogger("sam_automation")
    logger.setLevel(logging.DEBUG)

    # Формат
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Консоль
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Файл
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_handler = logging.FileHandler(
        LOG_DIR / f"{name}_{timestamp}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
