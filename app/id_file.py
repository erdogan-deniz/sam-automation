"""Чтение и запись текстовых файлов с целочисленными ID.

Примитивы без доменной семантики — используются в cache.py, card_cache.py,
card_store.py, game_list.py.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger("sam_automation")


def _iter_ids(path: Path) -> Iterator[int]:
    """Итерирует валидные int-ID из текстового файла (строки с # — комментарии)."""
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    yield int(line)
                except ValueError:
                    log.warning("Невалидная строка в %s: %r", path, line)
    except Exception as e:
        log.warning("Не удалось прочитать %s: %s", path, e)


def load_ids_file(path: Path) -> set[int]:
    """Читает текстовый файл с ID (по одному на строку) → set[int]."""
    return set(_iter_ids(path))


def read_ids_ordered(path: Path) -> list[int]:
    """Читает текстовый файл с ID, сохраняя порядок; строки с # — комментарии."""
    return list(_iter_ids(path))


def _append_id(path: Path, game_id: int) -> None:
    """Добавляет ID в файл, сохраняя числовую сортировку."""
    path.parent.mkdir(exist_ok=True)
    ids = set(_iter_ids(path))
    ids.add(game_id)
    path.write_text(
        "\n".join(str(i) for i in sorted(ids)) + "\n", encoding="utf-8"
    )
