"""Тесты устойчивой пагинации badges (card_checker.fetch_games_with_card_drops).

Баг: штатный пагинатор делал break при ПЕРВОЙ SSL-ошибке страницы, теряя
игры с поздних страниц. Фикс: ретрай каждой страницы + пропуск при стойком
отказе, обрыв только после N подряд неудачных страниц.

Фейки: _fetch_page мокается (без реального HTTP), time.sleep — no-op.
"""

from __future__ import annotations

import re

import pytest

from app.cards import card_checker


def _page_with_game(appid: int, drops: int, filler: str = "") -> str:
    """Минимальный HTML badge_row с одной игрой с дропами."""
    return (
        f'<div class="badge_row">{filler}'
        '<div class="badge_title_stats_drops">'
        f'<span class="progress_info_bold">{drops} card drops remaining</span>'
        '<div class="card_drop_info_dialog" '
        f'id="card_drop_info_gamebadge_{appid}_1_0"></div>'
        "</div></div>"
    )


_PAGE_END = '<div id="responsive_page_template_content">no badges</div>'


def _page_num(url: str) -> int:
    m = re.search(r"[?&]p=(\d+)", url)
    return int(m.group(1)) if m else 1


def _install(monkeypatch, pages, fail_counts) -> dict[int, int]:
    """Мок _fetch_page: pages[p] -> html; fail_counts[p] раз кидает RuntimeError.

    Возвращает счётчик вызовов по номеру страницы.
    """
    remaining_fails = dict(fail_counts)
    calls: dict[int, int] = {}

    def fake_fetch(opener, url):
        p = _page_num(url)
        calls[p] = calls.get(p, 0) + 1
        if remaining_fails.get(p, 0) > 0:
            remaining_fails[p] -= 1
            raise RuntimeError(f"SSL boom page {p}")
        return pages.get(p, _PAGE_END)

    monkeypatch.setattr(card_checker, "_make_opener", lambda cookies: object())
    monkeypatch.setattr(card_checker, "_fetch_page", fake_fetch)
    monkeypatch.setattr(card_checker.time, "sleep", lambda *_: None)
    return calls


def test_retries_transient_page_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Страница 2 падает один раз, затем читается — её игра НЕ теряется."""
    pages = {
        1: _page_with_game(111, 2),
        2: _page_with_game(222, 3, filler="x"),
        3: _PAGE_END,
    }
    _install(monkeypatch, pages, fail_counts={2: 1})

    result = card_checker.fetch_games_with_card_drops({}, "76561190000000000")

    assert (111, 2) in result
    assert (222, 3) in result


def test_persistent_page_failure_skipped_not_aborted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Стойкий отказ стр.2 не обрывает скрейп — игра со стр.3 собрана."""
    pages = {
        1: _page_with_game(111, 2),
        3: _page_with_game(333, 4, filler="yy"),
        4: _PAGE_END,
    }
    _install(monkeypatch, pages, fail_counts={2: 99})

    result = card_checker.fetch_games_with_card_drops({}, "76561190000000000")

    assert (111, 2) in result
    assert (333, 4) in result


def test_aborts_after_consecutive_page_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 страницы подряд не читаются -> обрыв, без бесконечного цикла."""
    pages = {1: _page_with_game(111, 2)}
    calls = _install(monkeypatch, pages, fail_counts={2: 99, 3: 99, 4: 99})

    result = card_checker.fetch_games_with_card_drops({}, "76561190000000000")

    assert result == [(111, 2)]
    # не должен дойти до 5-й страницы (оборвался на 3 подряд провалах)
    assert 5 not in calls
