"""Тесты хелперов логирования: SEPARATOR и centered()."""

from __future__ import annotations

from app.logging_setup import SEPARATOR, centered


def test_separator_is_80_box_chars():
    assert SEPARATOR == "═" * 80
    assert len(SEPARATOR) == 80


def test_centered_matches_legacy_farm_format():
    # Воспроизводит прежний inline-код achievements/farm.py:
    #   side = (70 - len(header) - 2) // 2
    #   "═"*side + " " + header + " " + "═"*side
    header = "[1/10]"
    side = (70 - len(header) - 2) // 2
    expected = f"{'═' * side} {header} {'═' * side}"
    assert centered(header) == expected


def test_centered_custom_width_and_char():
    # side = (10 - 1 - 2) // 2 = 3  →  "---" + " X " + "---"
    assert centered("X", width=10, char="-") == "--- X ---"


def test_centered_long_text_collapses_sides():
    # Текст шире доступной ширины → отрицательный side, char-полос нет
    text = "X" * 80
    assert centered(text, width=70) == f" {text} "


# ── B-3: 5 последних логов на скрипт, один файл не больше 20 МБ ──────────────
# Решение владельца 19.10.2026: старше пяти — удалять; дорос до предела —
# продолжать в следующем файле, он тоже входит в пятёрку.

import logging  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

import app.logging_setup as ls  # noqa: E402


def _make_logs(d: Path, stems: list[str]) -> None:
    for stem in stems:
        (d / f"{stem}.log").write_text("x", encoding="utf-8")


def test_defaults_match_owner_decision() -> None:
    assert ls.LOG_KEEP_FILES == 5
    assert ls.LOG_MAX_BYTES == 20 * 1024 * 1024


def test_prune_keeps_newest_files(tmp_path: Path) -> None:
    stems = [f"2026-10-0{i}_10-00-00" for i in range(1, 8)]  # 7 файлов
    _make_logs(tmp_path, stems)
    ls._prune_logs(tmp_path, keep=5, current=tmp_path / f"{stems[-1]}.log")
    left = sorted(p.stem for p in tmp_path.glob("*.log"))
    assert left == stems[2:]  # два самых старых удалены


def test_prune_never_deletes_current_file(tmp_path: Path) -> None:
    _make_logs(tmp_path, ["2026-10-01_10-00-00", "2026-10-02_10-00-00"])
    current = tmp_path / "2026-10-01_10-00-00.log"  # самый «старый» по имени
    ls._prune_logs(tmp_path, keep=1, current=current)
    assert current.exists()


def test_prune_ignores_non_log_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")
    _make_logs(tmp_path, ["2026-10-01_10-00-00", "2026-10-02_10-00-00"])
    ls._prune_logs(
        tmp_path, keep=1, current=tmp_path / "2026-10-02_10-00-00.log"
    )
    assert (tmp_path / "notes.txt").exists()


def _logger_with(handler: logging.Handler) -> logging.Logger:
    log = logging.getLogger(f"b3_test_{id(handler)}")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    log.addHandler(handler)
    return log


def test_handler_rolls_over_without_losing_lines(tmp_path: Path) -> None:
    h = ls._RollingFileHandler(
        tmp_path, "2026-10-19_00-00-00", max_bytes=300, keep=100
    )
    log = _logger_with(h)
    for i in range(50):
        log.info("строка %03d", i)
    h.close()
    files = sorted(tmp_path.glob("*.log"))
    assert len(files) > 1  # был переход на следующий файл
    assert files[0].name == "2026-10-19_00-00-00.log"
    assert files[1].name == "2026-10-19_00-00-00_part02.log"
    lines = [
        ln for f in files for ln in f.read_text(encoding="utf-8").splitlines()
    ]
    assert lines == [f"строка {i:03d}" for i in range(50)]
    assert all(f.stat().st_size <= 300 for f in files)


def test_rollover_parts_count_toward_keep(tmp_path: Path) -> None:
    _make_logs(tmp_path, ["2026-10-01_10-00-00", "2026-10-02_10-00-00"])
    h = ls._RollingFileHandler(
        tmp_path, "2026-10-19_00-00-00", max_bytes=300, keep=2
    )
    log = _logger_with(h)
    for i in range(50):
        log.info("строка %03d", i)
    h.close()
    files = sorted(p.name for p in tmp_path.glob("*.log"))
    assert len(files) == 2
    assert all(n.startswith("2026-10-19_00-00-00") for n in files)


def test_setup_logging_prunes_script_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    folder = tmp_path / "library" / "add_free"
    folder.mkdir(parents=True)
    _make_logs(folder, [f"2026-10-0{i}_10-00-00" for i in range(1, 8)])
    logger = logging.getLogger("sam_automation")
    saved = logger.handlers[:]
    logger.handlers.clear()
    try:
        ls.setup_logging(name="add_free", category="library/add_free")
        assert len(list(folder.glob("*.log"))) == ls.LOG_KEEP_FILES
    finally:
        for h in logger.handlers:
            h.close()
        logger.handlers[:] = saved
