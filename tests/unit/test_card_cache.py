"""Тесты app/cards/card_cache.py — прогресс card farming.

Модуль тонкий (делегирует в _append_id), поэтому ценность теста — регресс-гард
ПУТИ: cards/done.txt — реальный прогресс собранных карт, промах константы увёл
бы записи мимо и потерял прогресс.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.cards.card_cache as cc
from app.id_file import read_ids_ordered


def test_mark_card_done_writes_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    done = tmp_path / "done.txt"
    monkeypatch.setattr(cc, "CARD_DONE_FILE", done)
    cc.mark_card_done(730)
    assert done.read_text(encoding="utf-8") == "730\n"


def test_mark_card_done_appends_sorted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Числовая сортировка id-файлов — общий инвариант (_append_id).
    done = tmp_path / "done.txt"
    monkeypatch.setattr(cc, "CARD_DONE_FILE", done)
    cc.mark_card_done(730)
    cc.mark_card_done(10)
    assert read_ids_ordered(done) == [10, 730]


def test_mark_card_done_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Повторная отметка не плодит дубли (set внутри _append_id).
    done = tmp_path / "done.txt"
    monkeypatch.setattr(cc, "CARD_DONE_FILE", done)
    cc.mark_card_done(440)
    cc.mark_card_done(440)
    assert read_ids_ordered(done) == [440]


def test_card_done_file_lives_in_cards_dir() -> None:
    # Гард пути: прогресс карт должен лежать в cards/done.txt, не где-то ещё.
    assert cc.CARD_DONE_FILE.name == "done.txt"
    assert cc.CARD_DONE_FILE.parent.name == "cards"
