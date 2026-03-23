"""Тесты для app/cards/card_parsers.py."""

from __future__ import annotations

from app.cards.card_parsers import _BadgesPageParser, _GameCardsParser


# ── Хелперы ────────────────────────────────────────────────────────────────


def _badges_html(appid: int, drops: int) -> str:
    """Минимальный HTML блока badge_title_stats_drops с заданными значениями."""
    plural = "s" if drops != 1 else ""
    return (
        '<div class="badge_title_stats_drops">'
        f'<span class="progress_info_bold">{drops} card drop{plural} remaining</span>'
        f'<div class="card_drop_info_dialog" '
        f'id="card_drop_info_gamebadge_{appid}_1_0" style="display: none;"></div>'
        "</div>"
    )


def _game_cards_html(drops: int | None) -> str:
    """HTML span для страницы /gamecards/."""
    if drops is None:
        text = "No card drops remaining"
    else:
        plural = "s" if drops != 1 else ""
        text = f"{drops} card drop{plural} remaining"
    return f'<span class="progress_info_bold">{text}</span>'


# ── _BadgesPageParser ──────────────────────────────────────────────────────


def test_badges_parser_single_game():
    parser = _BadgesPageParser()
    parser.feed(_badges_html(730, 3))
    assert (730, 3) in parser.games


def test_badges_parser_multiple_games():
    parser = _BadgesPageParser()
    parser.feed(_badges_html(730, 3))
    parser.feed(_badges_html(440, 1))
    parser.feed(_badges_html(10, 5))
    assert set(parser.games) == {(730, 3), (440, 1), (10, 5)}


def test_badges_parser_one_drop():
    parser = _BadgesPageParser()
    parser.feed(_badges_html(440, 1))
    assert (440, 1) in parser.games


def test_badges_parser_no_drops_text_skipped():
    """Span без паттерна 'N card drop' не должен добавлять запись."""
    html = (
        '<div class="badge_title_stats_drops">'
        '<span class="progress_info_bold">No card drops remaining</span>'
        '<div class="card_drop_info_dialog" '
        'id="card_drop_info_gamebadge_730_1_0" style="display: none;"></div>'
        "</div>"
    )
    parser = _BadgesPageParser()
    parser.feed(html)
    # "No card drops" не матчит r"(\d+)\s+card\s+drop", запись не добавляется
    assert parser.games == []


def test_badges_parser_empty_html():
    parser = _BadgesPageParser()
    parser.feed("<html><body></body></html>")
    assert parser.games == []


def test_badges_parser_counts_badge_rows():
    html = (
        '<div class="badge_row">' + _badges_html(730, 2) + "</div>"
        '<div class="badge_row">' + _badges_html(440, 1) + "</div>"
    )
    parser = _BadgesPageParser()
    parser.feed(html)
    assert parser.badge_row_count == 2


# ── _GameCardsParser ───────────────────────────────────────────────────────


def test_game_cards_parser_n_drops():
    parser = _GameCardsParser()
    parser.feed(_game_cards_html(5))
    assert parser.cards_remaining == 5


def test_game_cards_parser_one_drop():
    parser = _GameCardsParser()
    parser.feed(_game_cards_html(1))
    assert parser.cards_remaining == 1


def test_game_cards_parser_no_drops():
    parser = _GameCardsParser()
    parser.feed(_game_cards_html(None))
    assert parser.cards_remaining == 0


def test_game_cards_parser_default_when_no_span():
    parser = _GameCardsParser()
    parser.feed("<p>nothing relevant</p>")
    assert parser.cards_remaining == -1


def test_game_cards_parser_case_insensitive():
    """Парсер должен распознавать 'Card Drop' с любым регистром."""
    html = '<span class="progress_info_bold">3 Card Drops Remaining</span>'
    parser = _GameCardsParser()
    parser.feed(html)
    assert parser.cards_remaining == 3
