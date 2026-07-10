"""Тесты числовых границ конфига (app.validator._check_numeric_bounds).

Руками отредактированный config.yaml с max_concurrent_games:0 давал тихий
no-op «успех», а card_check_interval:0/отрицательный — busy-loop/крэш.
"""

from __future__ import annotations

from app import validator
from app.config import Config


def _cfg(**kw: object) -> Config:
    cfg = Config()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_max_concurrent_zero_is_error() -> None:
    assert validator._check_numeric_bounds(_cfg(max_concurrent_games=0))


def test_max_concurrent_negative_is_error() -> None:
    assert validator._check_numeric_bounds(_cfg(max_concurrent_games=-1))


def test_max_concurrent_too_high_is_error() -> None:
    assert validator._check_numeric_bounds(_cfg(max_concurrent_games=999))


def test_interval_zero_is_error() -> None:
    assert validator._check_numeric_bounds(_cfg(card_check_interval=0))


def test_interval_negative_is_error() -> None:
    assert validator._check_numeric_bounds(_cfg(card_check_interval=-5))


def test_playtime_concurrent_zero_is_error() -> None:
    # 0 → ZeroDivisionError/range-error в boost.py
    assert validator._check_numeric_bounds(_cfg(playtime_concurrent_games=0))


def test_valid_bounds_no_error() -> None:
    errs = validator._check_numeric_bounds(
        _cfg(
            max_concurrent_games=1,
            playtime_concurrent_games=1,
            card_check_interval=10,
        )
    )
    assert errs == []
