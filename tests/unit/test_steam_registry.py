"""Тесты для app/steam/steam_registry.py.

Тестируем только steamid64_to_id3 — чистую арифметическую функцию.
find_steam_path использует winreg и файловую систему,
поэтому остаётся без тестов (интеграционный уровень).
"""

from __future__ import annotations

import pytest

from app.exceptions import SAMError
from app.steam import steam_registry
from app.steam.steam_registry import (
    STEAM_ID64_BASE,
    find_steam_path,
    steamid64_to_id3,
)


def test_base_value_converts_to_zero() -> None:
    assert steamid64_to_id3(str(STEAM_ID64_BASE)) == 0


def test_unicode_digit_raises_samerror_not_valueerror() -> None:
    # '²'.isdigit()==True, но int('²') бросает ValueError → раньше сырой краш
    # читателя всей библиотеки. Гвард должен дать SAMError (isdecimal, не isdigit).
    with pytest.raises(SAMError):
        steamid64_to_id3("²")


def test_known_conversion() -> None:
    # 76561198000000000 — просто известное значение
    steam_id64 = 76561198000000000
    result = steamid64_to_id3(str(steam_id64))
    assert result == steam_id64 - STEAM_ID64_BASE


def test_gabe_newell() -> None:
    # Gabe Newell: https://steamcommunity.com/id/gabelogannewell
    # Steam ID64: 76561197960287930
    result = steamid64_to_id3("76561197960287930")
    assert result == 76561197960287930 - STEAM_ID64_BASE
    assert result == 22202


def test_result_is_positive_for_valid_id64() -> None:
    # Любой валидный Steam ID64 >= STEAM_ID64_BASE
    result = steamid64_to_id3(str(STEAM_ID64_BASE + 1))
    assert result == 1


def test_consistency_with_base() -> None:
    for offset in (0, 1, 100, 39734272, 123456789):
        assert steamid64_to_id3(str(STEAM_ID64_BASE + offset)) == offset


# ── B1: steamid64_to_id3 валидация → SAMError ──────────────────────────────


def test_steamid64_to_id3_rejects_empty() -> None:
    with pytest.raises(SAMError):
        steamid64_to_id3("")


def test_steamid64_to_id3_rejects_whitespace() -> None:
    with pytest.raises(SAMError):
        steamid64_to_id3("   ")


def test_steamid64_to_id3_rejects_non_numeric() -> None:
    with pytest.raises(SAMError):
        steamid64_to_id3("not-a-number")


def test_steamid64_to_id3_rejects_below_base() -> None:
    # < STEAM_ID64_BASE → не породит отрицательный id3-путь, а SAMError.
    with pytest.raises(SAMError):
        steamid64_to_id3(str(STEAM_ID64_BASE - 1))


def test_steamid64_to_id3_accepts_base_boundary() -> None:
    assert steamid64_to_id3(str(STEAM_ID64_BASE)) == 0


# ── B2/B3: find_steam_path (реестр) ────────────────────────────────────────


def _fake_path_cls(existing: set[str]) -> type:
    """Fake Path: exists() True только для путей из `existing`."""

    class _FakePath:
        def __init__(self, p: object) -> None:
            self.p = str(p)

        def exists(self) -> bool:
            return self.p in existing

    return _FakePath


class _FakeKey:
    def __enter__(self) -> _FakeKey:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def test_find_steam_path_empty_install_path_is_not_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой InstallPath из реестра НЕ валиден (Path('').exists()==True)."""
    import winreg

    # Реестр всегда отдаёт пустую строку — все хайвы «есть», но путь пустой.
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: _FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda *a, **k: ("", 1))
    # "" и "." «существуют» (как на реальной ФС), стандартные пути — нет.
    monkeypatch.setattr(steam_registry, "Path", _fake_path_cls({"", "."}))

    assert find_steam_path() is None


def test_find_steam_path_continues_past_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PermissionError (⊂OSError) на первом хайве → поиск продолжается."""
    import winreg

    real = r"C:\Games\Steam"
    calls: list[int] = []

    def fake_openkey(*_a: object, **_k: object) -> _FakeKey:
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("access denied")
        return _FakeKey()

    monkeypatch.setattr(winreg, "OpenKey", fake_openkey)
    monkeypatch.setattr(winreg, "QueryValueEx", lambda *a, **k: (real, 1))
    monkeypatch.setattr(steam_registry, "Path", _fake_path_cls({real}))

    assert find_steam_path() == real
    assert len(calls) >= 2  # не упал на первом хайве, дошёл до второго
