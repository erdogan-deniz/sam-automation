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


def test_prev_html_size_reset_after_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пропуск страницы не должен ломать size-эвристику конца пагинации.

    Стр.1 и стр.3 имеют одинаковую байт-длину (одинаковые шаблоны).
    Стр.2 стойко падает и пропускается. Если prev_html_size не сброшен,
    стр.3 ложно примется за «повтор последней» → её игра потеряется.
    """
    # 111 и 333 — по 3 цифры, 2 и 4 — по 1 цифре: длины строк совпадают.
    pages = {
        1: _page_with_game(111, 2),
        3: _page_with_game(333, 4),
        4: _PAGE_END,
    }
    assert len(pages[1]) == len(pages[3])  # предпосылка теста
    _install(monkeypatch, pages, fail_counts={2: 99})

    result = card_checker.fetch_games_with_card_drops({}, "76561190000000000")

    assert (111, 2) in result
    assert (333, 4) in result


def test_absolute_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без content-стопа пагинация обрывается по абсолютному капу страниц."""
    # Каждая страница уникальна (свой appid и длина) → ни size-повтор,
    # ни badge_row==0 не сработают; остановить должен только кап.
    pages = {
        p: _page_with_game(1000 + p, 1, filler="z" * p) for p in range(1, 100)
    }
    calls = _install(monkeypatch, pages, fail_counts={})

    result = card_checker.fetch_games_with_card_drops({}, "76561190000000000")

    assert len(result) == card_checker._MAX_BADGE_PAGES
    assert (card_checker._MAX_BADGE_PAGES + 1) not in calls


def _gamecards_html(drops: int) -> str:
    return (
        f'<span class="progress_info_bold">{drops} card drops remaining</span>'
    )


def test_check_cards_remaining_retries_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Одиночный SSL-блип в перечитке не даёт -1 — читается с ретраем."""
    calls = {"n": 0}

    def fake_fetch(opener: object, url: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("SSL boom")
        return _gamecards_html(2)

    monkeypatch.setattr(card_checker, "_make_opener", lambda cookies: object())
    monkeypatch.setattr(card_checker, "_fetch_page", fake_fetch)
    monkeypatch.setattr(card_checker.time, "sleep", lambda *_: None)

    result = card_checker.check_cards_remaining({}, "76561190000000000", 774241)

    assert result == 2  # не -1: транзиентный отказ пережит ретраем


def test_fetch_page_wraps_remote_disconnected() -> None:
    """RemoteDisconnected (редирект) → RuntimeError, чтобы ретрай его поймал.

    Реальный краш A/B-прогона: при 302 на страницу логина getresponse кидал
    http.client.RemoteDisconnected — подкласс OSError, но НЕ urllib URLError →
    проходил мимо except и рушил весь прогон вместо штатного ретрая.
    """
    import http.client

    class _BoomOpener:
        def open(self, url: str, timeout: int = 15) -> object:
            raise http.client.RemoteDisconnected(
                "Remote end closed connection without response"
            )

    with pytest.raises(RuntimeError):
        card_checker._fetch_page(
            _BoomOpener(), f"{card_checker._COMMUNITY_BASE}/x"
        )


def test_fetch_page_wraps_os_error() -> None:
    """Любой OSError (сброс соединения / SSL-таймаут) тоже → RuntimeError."""

    class _BoomOpener:
        def open(self, url: str, timeout: int = 15) -> object:
            raise ConnectionResetError("connection reset by peer")

    with pytest.raises(RuntimeError):
        card_checker._fetch_page(
            _BoomOpener(), f"{card_checker._COMMUNITY_BASE}/x"
        )


def _http_error_opener(code: int, retry_after: str | None = None) -> object:
    """Opener, чей .open() кидает urllib HTTPError с заданным кодом."""
    import email.message
    import urllib.error

    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = retry_after

    class _Boom:
        def open(self, url: str, timeout: int = 15) -> object:
            raise urllib.error.HTTPError(url, code, "boom", hdrs, None)

    return _Boom()


def test_fetch_page_429_is_rate_limit_with_retry_after() -> None:
    """429 → _RateLimitError с распарсенным Retry-After (умный бэкофф)."""
    with pytest.raises(card_checker._RateLimitError) as exc:
        card_checker._fetch_page(
            _http_error_opener(429, "7"), f"{card_checker._COMMUNITY_BASE}/x"
        )
    assert exc.value.retry_after == 7.0


def test_fetch_page_403_is_auth_error() -> None:
    """403 (истёкшие куки / нет доступа) → _AuthError, а не транзиент."""
    with pytest.raises(card_checker._AuthError):
        card_checker._fetch_page(
            _http_error_opener(403), f"{card_checker._COMMUNITY_BASE}/x"
        )


def test_retry_does_not_retry_auth_error() -> None:
    """_AuthError НЕ ретраится (куки ретраем не чинятся) — ровно 1 попытка."""
    import urllib.error

    calls = {"n": 0}

    class _Boom:
        def open(self, url: str, timeout: int = 15) -> object:
            calls["n"] += 1
            raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)

    with pytest.raises(card_checker._AuthError):
        card_checker._fetch_page_with_retry(
            _Boom(), f"{card_checker._COMMUNITY_BASE}/x"
        )
    assert calls["n"] == 1


def test_retry_honors_rate_limit_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 ретраится с бэкоффом по Retry-After, затем страница читается."""
    import email.message
    import urllib.error

    slept: list[float] = []
    monkeypatch.setattr(card_checker.time, "sleep", lambda s: slept.append(s))
    hdrs = email.message.Message()
    hdrs["Retry-After"] = "3"
    calls = {"n": 0}

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_: object) -> bool:
            return False

        def read(self) -> bytes:
            return b"<html>ok</html>"

    class _Flaky:
        def open(self, url: str, timeout: int = 15) -> object:
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(url, 429, "rate", hdrs, None)
            return _Resp()

    result = card_checker._fetch_page_with_retry(
        _Flaky(), f"{card_checker._COMMUNITY_BASE}/x"
    )
    assert "ok" in result
    assert 3.0 in slept


def test_cap_warning_signals_incompleteness(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Упор в _MAX_BADGE_PAGES честно предупреждает о НЕПОЛНОТЕ списка игр.

    Иначе (terse «обрываю пагинацию») тихая потеря игр на стр. 41+ выглядит
    штатным концом — нарушение инварианта «не терять игры».
    """
    import logging

    pages = {
        p: _page_with_game(1000 + p, 1, filler="z" * p) for p in range(1, 100)
    }
    _install(monkeypatch, pages, fail_counts={})
    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        card_checker.fetch_games_with_card_drops({}, "76561190000000000")

    assert any("неполн" in r.getMessage().lower() for r in caplog.records), (
        "warning на упоре должен сигналить о неполноте списка"
    )
