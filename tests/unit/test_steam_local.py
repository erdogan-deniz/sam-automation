"""Тесты для app/steam/steam_local.py.

Тестируем _extract_app_ids_from_vdf — чистую функцию парсинга VDF-текста.
read_library_app_ids читает файловую систему и остаётся без тестов.
"""

from __future__ import annotations

import pytest

from app.steam.steam_local import _extract_app_ids_from_vdf


# ── Хелперы ────────────────────────────────────────────────────────────────


def _make_vdf(*app_ids: int) -> str:
    """Строит минимальный localconfig.vdf с заданными App ID для тестирования парсера."""
    inner = ""
    for appid in app_ids:
        inner += f'\t\t\t\t\t\t"{appid}"\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t}}\n'
    return (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        f"{inner}"
        "\t\t\t\t}\n"
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )


# ── Тесты ──────────────────────────────────────────────────────────────────


def test_extract_single_app() -> None:
    ids = _extract_app_ids_from_vdf(_make_vdf(730))
    assert ids == [730]


def test_extract_multiple_apps() -> None:
    ids = _extract_app_ids_from_vdf(_make_vdf(10, 440, 730))
    assert set(ids) == {10, 440, 730}


def test_extract_empty_apps_section() -> None:
    vdf = _make_vdf()
    ids = _extract_app_ids_from_vdf(vdf)
    assert ids == []


def test_extract_missing_apps_section() -> None:
    ids = _extract_app_ids_from_vdf("no apps here at all")
    assert ids == []


def test_extract_preserves_large_app_ids() -> None:
    large_id = 2167760
    ids = _extract_app_ids_from_vdf(_make_vdf(large_id))
    assert large_id in ids


def test_extract_does_not_return_nested_non_app_keys() -> None:
    """Вложенные числовые ключи внутри блока приложения не должны приниматься за App ID."""
    # Создаём VDF с одним приложением и числовым подключом внутри него
    vdf = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"440"\n\t\t\t\t\t{\n'
        '\t\t\t\t\t\t"12345"\t"nested_value"\n'
        "\t\t\t\t\t}\n"
        "\t\t\t\t}\n"
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )
    ids = _extract_app_ids_from_vdf(vdf)
    # 440 — это App ID; 12345 — это строковое поле, не блок (нет {} после него)
    assert 440 in ids
    assert 12345 not in ids
