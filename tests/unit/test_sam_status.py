"""Тесты _check_game_status — различение loading-timeout, error, retrieved."""

from __future__ import annotations

from unittest.mock import patch

from app.sam.sam_status import _check_game_status


def _with_status(text: str):
    return patch("app.sam.sam_status._wait_for_status", return_value=text)


def test_loading_timeout_returns_retry():
    # Статистика не загрузилась (только 'retrieving' весь timeout) → пусто.
    # Это НЕ постоянная ошибка — игру нужно повторить, а не помечать error.
    with _with_status(""):
        assert _check_game_status(None) == ("retry", 0)


def test_error_status_returns_no_achievements():
    with _with_status("error: no stats"):
        assert _check_game_status(None) == ("no achievements", 0)


def test_retrieved_returns_count():
    with _with_status("12 achievements retrieved"):
        assert _check_game_status(None) == (None, 12)
