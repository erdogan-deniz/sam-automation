"""Тесты для app/id_file.py."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.id_file as idf
from app.id_file import (
    _append_id,
    _remove_id,
    load_ids_file,
    read_ids_ordered,
)

# ── load_ids_file ──────────────────────────────────────────────────────────


def test_load_ids_file_missing(tmp_path: Path) -> None:
    assert load_ids_file(tmp_path / "nonexistent.txt") == set()


def test_load_ids_file_basic(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n440\n730\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440, 730}


def test_load_ids_file_skips_comments(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n# skip this\n440\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440}


def test_load_ids_file_skips_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n\n  \n440\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440}


def test_load_ids_file_ignores_invalid(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\nnot_a_number\n440\n", encoding="utf-8")
    assert load_ids_file(f) == {10, 440}


# ── read_ids_ordered ───────────────────────────────────────────────────────


def test_read_ids_ordered_missing(tmp_path: Path) -> None:
    assert read_ids_ordered(tmp_path / "nonexistent.txt") == []


def test_read_ids_ordered_preserves_order(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("730\n440\n10\n", encoding="utf-8")
    assert read_ids_ordered(f) == [730, 440, 10]


def test_read_ids_ordered_skips_comments(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("730\n# comment\n440\n", encoding="utf-8")
    assert read_ids_ordered(f) == [730, 440]


def test_read_ids_ordered_dedups_preserving_order(tmp_path: Path) -> None:
    # INFO: boost — единственный потребитель, полагающийся на порядок; дубль
    # appid из вручную-правленного all.txt дал бы двойной запуск игры (два
    # SAM.Game.exe на один appid дерутся за global user). Дедуп по первому
    # вхождению сохраняет порядок.
    f = tmp_path / "ids.txt"
    f.write_text("30\n10\n30\n20\n10\n", encoding="utf-8")
    assert read_ids_ordered(f) == [30, 10, 20]


# ── _append_id ─────────────────────────────────────────────────────────────


def test_append_id_creates_file(tmp_path: Path) -> None:
    f = tmp_path / "out.txt"
    _append_id(f, 730)
    assert f.read_text(encoding="utf-8") == "730\n"


def test_append_id_creates_parent_dir(tmp_path: Path) -> None:
    f = tmp_path / "subdir" / "out.txt"
    _append_id(f, 440)
    assert f.exists()
    assert f.read_text(encoding="utf-8") == "440\n"


def test_append_id_appends(tmp_path: Path) -> None:
    f = tmp_path / "out.txt"
    _append_id(f, 10)
    _append_id(f, 440)
    assert read_ids_ordered(f) == [10, 440]


def test_append_id_creates_deeply_nested_parent_dirs(tmp_path: Path) -> None:
    # На свежем чекауте отсутствует не только непосредственный родитель, но и
    # дед-каталог (data/games/ids/achievements). mkdir без parents=True роняет
    # первый _append_id FileNotFoundError.
    f = tmp_path / "games" / "ids" / "achievements" / "unlocked.txt"
    _append_id(f, 42)
    assert f.read_text(encoding="utf-8") == "42\n"


def test_append_id_write_failure_preserves_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Прямой write_text усекает файл ПЕРЕД записью: краш/Ctrl+C в этот момент
    # стирает НЕ добавляемый id, а ВСЕ накопленные. Атомарная запись (tmp +
    # os.replace) обязана сохранить старое содержимое при сбое финального шага
    # и не оставить tmp-мусор.
    f = tmp_path / "ids.txt"
    f.write_text("1\n2\n3\n", encoding="utf-8")

    def boom(*_a: object) -> None:
        raise OSError("crash во время замены")

    monkeypatch.setattr(idf.os, "replace", boom)

    with pytest.raises(OSError):
        _append_id(f, 4)

    assert f.read_text(encoding="utf-8") == "1\n2\n3\n"  # прогресс не потерян
    assert list(tmp_path.glob("*.tmp")) == []  # tmp-мусор убран


def test_append_id_read_failure_preserves_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RA-8: транзиентный сбой ЧТЕНИЯ существующего файла (Windows sharing-
    # violation от AV/OneDrive на только что перезаписанном файле) не должен
    # усечь накопленное до одного нового id. _iter_ids глушит ошибку чтения в
    # пустой набор → безусловная запись стёрла бы всё; _append_id обязан НЕ
    # переписывать при сбое чтения существующего файла.
    f = tmp_path / "ids.txt"
    f.write_text("10\n20\n30\n", encoding="utf-8")

    orig_read_text = Path.read_text

    def flaky_read_text(self: Path, *a: object, **k: object) -> str:
        if self == f:
            raise PermissionError(13, "sharing violation")
        return orig_read_text(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    _append_id(f, 40)  # не должно усечь (чтение существующего файла упало)

    monkeypatch.setattr(Path, "read_text", orig_read_text)
    assert load_ids_file(f) == {10, 20, 30}  # накопленное цело, 40 не дописан


# ── _remove_id ─────────────────────────────────────────────────────────────


def test_remove_id_missing_file_noop(tmp_path: Path) -> None:
    _remove_id(tmp_path / "nope.txt", 730)  # не должно падать


def test_remove_id_removes_and_keeps_sorted(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n440\n730\n", encoding="utf-8")
    _remove_id(f, 440)
    assert f.read_text(encoding="utf-8") == "10\n730\n"


def test_remove_id_absent_id_leaves_file_untouched(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("10\n440\n", encoding="utf-8")
    _remove_id(f, 999)
    assert f.read_text(encoding="utf-8") == "10\n440\n"


def test_remove_id_last_id_deletes_file(tmp_path: Path) -> None:
    # Пустой id-файл не оставляем — удаляем целиком.
    f = tmp_path / "ids.txt"
    f.write_text("730\n", encoding="utf-8")
    _remove_id(f, 730)
    assert not f.exists()
