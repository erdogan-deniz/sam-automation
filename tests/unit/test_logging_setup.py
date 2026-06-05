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
