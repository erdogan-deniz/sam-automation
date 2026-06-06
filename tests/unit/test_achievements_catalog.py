"""Тесты для app/achievements_catalog.py — раскладка игр по with/without."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.cache as cache_mod
from app import achievements_catalog as cat


def _patch_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cache_mod, "DONE_IDS_FILE", tmp_path / "unlocked.txt")
    monkeypatch.setattr(
        cache_mod, "NO_ACHIEVEMENTS_FILE", tmp_path / "without.txt"
    )
    monkeypatch.setattr(
        cache_mod, "WITH_ACHIEVEMENTS_FILE", tmp_path / "with.txt"
    )


# ── classify_count ─────────────────────────────────────────────────────────


def test_classify_count_with() -> None:
    assert cat.classify_count(3) == "with"


def test_classify_count_without() -> None:
    assert cat.classify_count(0) == "without"


def test_classify_count_unresolved() -> None:
    assert cat.classify_count(None) is None


# ── select_unclassified ────────────────────────────────────────────────────


def test_select_unclassified_filters_known() -> None:
    todo = cat.select_unclassified(
        [10, 20, 30, 40], known_with={10}, known_without={20}
    )
    assert todo == [30, 40]


# ── catalog ────────────────────────────────────────────────────────────────


def test_catalog_distributes_and_skips_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_cache(monkeypatch, tmp_path)
    cache_mod.mark_with_achievements(10)  # уже классифицирована
    cache_mod.mark_no_achievements(20)  # уже классифицирована

    counts_map = {30: 5, 40: 0, 50: None}
    queried: list[int] = []

    def fake_fetch(appid: int) -> int | None:
        queried.append(appid)
        return counts_map[appid]

    sleeps: list[float] = []
    result = cat.catalog(
        [10, 20, 30, 40, 50],
        fake_fetch,
        delay=1.0,
        sleep=lambda s: sleeps.append(s),
    )

    # Уже классифицированные не опрашиваются повторно
    assert queried == [30, 40, 50]
    # Раскладка по файлам
    assert cache_mod.load_with_achievements_ids() == {10, 30}
    assert cache_mod.load_no_achievements_ids() == {20, 40}
    # 50 (None) нигде не записана — перепроверится при следующем скане
    assert result == {"with": 1, "without": 1, "unresolved": 1}
    # Пауза между запросами: 3 ID → 2 паузы
    assert sleeps == [1.0, 1.0]


def test_catalog_counts_done_as_known_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Игра из unlocked.txt (farm уже выбил) точно с достижениями — не опрашиваем."""
    _patch_cache(monkeypatch, tmp_path)
    cache_mod.mark_done(70)

    def fake_fetch(appid: int) -> int | None:
        raise AssertionError(f"не должны опрашивать {appid}")

    result = cat.catalog([70], fake_fetch, delay=0.0, sleep=lambda _s: None)
    assert result == {"with": 0, "without": 0, "unresolved": 0}
