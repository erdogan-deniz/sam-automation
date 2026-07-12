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


def test_launch_stagger_negative_is_error() -> None:
    # time.sleep(negative) → ValueError крашит батч.
    assert validator._check_numeric_bounds(_cfg(launch_stagger=-1.0))


def test_launch_stagger_nan_is_error() -> None:
    # RA-6: nan < 0 == False → проскакивал guard >= 0 → time.sleep(nan)
    # ValueError крашит батч. Отбраковываем не-конечные явно.
    assert validator._check_numeric_bounds(_cfg(launch_stagger=float("nan")))


def test_launch_stagger_inf_is_error() -> None:
    # RA-6: inf проходит guard и уводит time.sleep(inf) в вечный сон.
    assert validator._check_numeric_bounds(_cfg(launch_stagger=float("inf")))


def test_playtime_idle_duration_too_high_is_error() -> None:
    # INFO: абсурдная длительность (опечатка 10^9с ≈ 31 год idle) типо-валидна,
    # но вешает boost без диагностики. Разумный потолок ловит опечатку.
    assert validator._check_numeric_bounds(_cfg(playtime_idle_duration=10**9))


def test_launch_stagger_too_high_is_error() -> None:
    assert validator._check_numeric_bounds(_cfg(launch_stagger=10**9))


def test_generous_durations_still_valid() -> None:
    # Потолки щедрые — реальные конфиги не задевают.
    assert (
        validator._check_numeric_bounds(
            _cfg(playtime_idle_duration=3600, launch_stagger=60)
        )
        == []
    )


def test_valid_bounds_no_error() -> None:
    errs = validator._check_numeric_bounds(
        _cfg(
            max_concurrent_games=1,
            playtime_concurrent_games=1,
            card_check_interval=10,
        )
    )
    assert errs == []
