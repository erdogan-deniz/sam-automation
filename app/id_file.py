"""Чтение и запись текстовых файлов с целочисленными ID.

Примитивы без доменной семантики — используются в cache.py, card_cache.py,
game_list.py.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger("sam_automation")


def _atomic_write_text(path: Path, text: str) -> None:
    """Атомарно пишет text в path: tmp-файл рядом + os.replace.

    Прямой write_text открывает файл на запись (truncate) ПЕРЕД записью: краш
    или Ctrl+C между усечением и записью оставляет пустой/битый файл. Для
    id-файлов и names.json это потеря ВСЕГО накопленного (каждая дозапись
    переписывает файл целиком), а не только добавляемого элемента. Пишем во
    временный файл в том же каталоге и os.replace — атомарный rename на одном
    томе: path в любой момент либо старый целиком, либо новый целиком.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        # Сбой на любом шаге: исходный path не тронут, tmp-мусор убираем.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    """Добавляет ID в файл, сохраняя числовую сортировку (атомарно)."""
    ids = set(_iter_ids(path))
    ids.add(game_id)
    _atomic_write_text(path, "\n".join(str(i) for i in sorted(ids)) + "\n")


def _remove_id(path: Path, game_id: int) -> None:
    """Удаляет ID из файла, сохраняя числовую сортировку (атомарно).

    No-op, если файла нет или ID в нём отсутствует (файл не переписывается).
    Если после удаления не осталось ID — файл удаляется целиком, чтобы не
    плодить пустые id-файлы.
    """
    if not path.exists():
        return
    ids = set(_iter_ids(path))
    if game_id not in ids:
        return
    ids.discard(game_id)
    if ids:
        _atomic_write_text(path, "\n".join(str(i) for i in sorted(ids)) + "\n")
    else:
        path.unlink()
