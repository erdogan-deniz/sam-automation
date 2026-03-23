"""Тесты для app/steam/steam_registry.py.

Тестируем только steamid64_to_id3 — чистую арифметическую функцию.
find_steam_path / read_steam_username используют winreg и файловую систему,
поэтому остаются без тестов (интеграционный уровень).
"""

from __future__ import annotations

from app.steam.steam_registry import STEAM_ID64_BASE, steamid64_to_id3


def test_base_value_converts_to_zero():
    assert steamid64_to_id3(str(STEAM_ID64_BASE)) == 0


def test_known_conversion():
    # 76561198000000000 — просто известное значение
    steam_id64 = 76561198000000000
    result = steamid64_to_id3(str(steam_id64))
    assert result == steam_id64 - STEAM_ID64_BASE


def test_gabe_newell():
    # Gabe Newell: https://steamcommunity.com/id/gabelogannewell
    # Steam ID64: 76561197960287930
    result = steamid64_to_id3("76561197960287930")
    assert result == 76561197960287930 - STEAM_ID64_BASE
    assert result == 22202


def test_result_is_positive_for_valid_id64():
    # Любой валидный Steam ID64 >= STEAM_ID64_BASE
    result = steamid64_to_id3(str(STEAM_ID64_BASE + 1))
    assert result == 1


def test_consistency_with_base():
    for offset in (0, 1, 100, 39734272, 123456789):
        assert steamid64_to_id3(str(STEAM_ID64_BASE + offset)) == offset
