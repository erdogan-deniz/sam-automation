"""Чтение и запись текстовых файлов с целочисленными ID.

Примитивы без доменной семантики — используются в cache.py, card_cache.py,
game_list.py.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger("sam_automation")

# Ретрай os.replace на транзиентный Windows sharing-violation/access-denied —
# антивирус/индексатор миллисекунды держат только что созданный tmp-файл.
# Симметрично _read_ids_strict, которая уже переживает тот же класс сбоя на
# чтении; здесь — защита на записи (живой краш: PermissionError WinError 5 на
# os.replace в проде во время batch-записи error.txt при активном --add).
_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY = 0.1  # секунд между попытками


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
        for attempt in range(_REPLACE_RETRY_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == _REPLACE_RETRY_ATTEMPTS - 1:
                    raise
                log.debug(
                    "os.replace(%s): транзиентный PermissionError, "
                    "повтор %d/%d",
                    path,
                    attempt + 1,
                    _REPLACE_RETRY_ATTEMPTS,
                )
                time.sleep(_REPLACE_RETRY_DELAY)
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
    """Читает текстовый файл с ID, сохраняя порядок первых вхождений (дедуп).

    Дедуп важен для boost — единственного потребителя, полагающегося на порядок:
    дубль appid (напр. из вручную-правленного all.txt) иначе дал бы двойной
    запуск игры (два SAM.Game.exe на один appid дерутся за Steam global user).
    """
    return list(dict.fromkeys(_iter_ids(path)))


def _read_ids_strict(path: Path) -> set[int]:
    """Читает id-файл в set; при СБОЕ чтения существующего файла бросает.

    Бросает OSError (сбой ввода-вывода) либо UnicodeDecodeError (файл не в
    UTF-8: оборванная запись, ручная правка в другой кодировке) — оба означают
    «содержимое неизвестно», и оба обязан ловить писатель.

    Для писателей (_append_id), в отличие от _iter_ids: тот глушит любую ошибку
    чтения в пустой результат — уместно для читателей, но для писателя
    катастрофично (транзиентный сбой чтения → перезапись файла одним новым id,
    потеря всего накопленного). Отсутствие файла — не ошибка (пустой set); сбой
    чтения существующего — пробрасывается, чтобы writer НЕ перезаписал усечённым.
    """
    if not path.exists():
        return set()
    out: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                out.add(int(line))
            except ValueError:
                log.warning("Невалидная строка в %s: %r", path, line)
    return out


def _append_id(path: Path, game_id: int) -> None:
    """Добавляет ID в файл, сохраняя числовую сортировку (атомарно).

    Если чтение СУЩЕСТВУЮЩЕГО файла упало (не «файла нет», а транзиентный сбой —
    напр. Windows sharing-violation от AV/OneDrive на только что перезаписанном
    файле, либо битый не-UTF-8 байт), НЕ перезаписываем: иначе усечём весь
    накопленный список до одного нового id. Пропускаем дозапись (файл цел; для
    resume-файлов недобавленный id безвреден — обработается следующим прогоном),
    а не теряем данные и не роняем прогон сырым трейсбеком.
    """
    try:
        ids = _read_ids_strict(path)
    except (OSError, UnicodeDecodeError) as e:
        log.warning(
            "Не удалось прочитать %s для дозаписи (%s) — пропускаю, "
            "файл не перезаписан",
            path,
            e,
        )
        return
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
