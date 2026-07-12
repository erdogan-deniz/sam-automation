"""Тесты для app/steam/steam_local.py.

Тестируем _extract_app_ids_from_vdf — чистую функцию парсинга VDF-текста.
read_library_app_ids читает файловую систему и остаётся без тестов.
"""

from __future__ import annotations

import logging

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


# ── A3: tolerant anchor (скалярные ключи до apps) ──────────────────────────


def test_extract_tolerant_of_scalar_keys_before_apps() -> None:
    """apps не обязана быть ПЕРВЫМ ребёнком Steam — до неё бывают скаляры."""
    vdf = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"SurveyDate"\t"2026-01-01"\n'
        '\t\t\t\t"SurveyDateRC"\t"7"\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"730"\n\t\t\t\t\t{\n\t\t\t\t\t}\n'
        "\t\t\t\t}\n"
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )
    assert _extract_app_ids_from_vdf(vdf) == [730]


# ── A2: quote-awareness (скобки внутри строковых значений) ─────────────────


def test_extract_ignores_braces_inside_string_values() -> None:
    """}/{ внутри значения (LaunchOptions и т.п.) не рвут/не растягивают блок."""
    vdf = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"440"\n\t\t\t\t\t{\n'
        '\t\t\t\t\t\t"LaunchOptions"\t"gamemoderun %command% }"\n'
        '\t\t\t\t\t\t"cloud"\t"{enabled}"\n'
        "\t\t\t\t\t}\n"
        '\t\t\t\t\t"730"\n\t\t\t\t\t{\n\t\t\t\t\t}\n'
        "\t\t\t\t}\n"
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )
    assert _extract_app_ids_from_vdf(vdf) == [440, 730]


def test_extract_ignores_escaped_quote_in_value() -> None:
    """Экранированная \\\" внутри значения не завершает строку раньше времени."""
    vdf = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"440"\n\t\t\t\t\t{\n'
        '\t\t\t\t\t\t"LaunchOptions"\t"say \\"hi\\" }"\n'
        "\t\t\t\t\t}\n"
        '\t\t\t\t\t"730"\n\t\t\t\t\t{\n\t\t\t\t\t}\n'
        "\t\t\t\t}\n"
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )
    assert _extract_app_ids_from_vdf(vdf) == [440, 730]


# ── A1: depth=1 (вложенные numeric-ключи не дают фантома) ───────────────────


def test_extract_ignores_nested_numeric_block_keys() -> None:
    """Вложенные depots{ "228987"{...} } и фантомный "0" НЕ попадают в App ID."""
    vdf = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"440"\n\t\t\t\t\t{\n'
        '\t\t\t\t\t\t"depots"\n\t\t\t\t\t\t{\n'
        '\t\t\t\t\t\t\t"228987"\n\t\t\t\t\t\t\t{\n'
        '\t\t\t\t\t\t\t\t"size"\t"123"\n'
        "\t\t\t\t\t\t\t}\n"
        '\t\t\t\t\t\t\t"0"\n\t\t\t\t\t\t\t{\n\t\t\t\t\t\t\t}\n'
        "\t\t\t\t\t\t}\n"
        "\t\t\t\t\t}\n"
        "\t\t\t\t}\n"
        "\t\t\t}\n\t\t}\n\t}\n}\n"
    )
    ids = _extract_app_ids_from_vdf(vdf)
    assert ids == [440]
    assert 0 not in ids
    assert 228987 not in ids


# ── A4: dedup (сохраняя порядок) ───────────────────────────────────────────


def test_extract_dedups_preserving_order() -> None:
    ids = _extract_app_ids_from_vdf(_make_vdf(730, 440, 730, 10, 440))
    assert ids == [730, 440, 10]


# ── A5: malformed-detection (обрезанный/несбалансированный файл) ────────────


def test_extract_truncated_file_warns_and_returns_parsed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Обрезанный файл: 730 распознан, блоки не закрыты → distinct warning."""
    vdf = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"730"\n\t\t\t\t\t{\n'
        '\t\t\t\t\t\t"LastPlayed"\t"123"\n'
        # файл обрывается — блоки не закрыты
    )
    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        ids = _extract_app_ids_from_vdf(vdf)
    assert ids == [730]
    assert any(
        "обрез" in r.getMessage().lower() or "поврежд" in r.getMessage().lower()
        for r in caplog.records
    )


def test_extract_wellformed_does_not_warn_malformed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        ids = _extract_app_ids_from_vdf(_make_vdf(10, 440))
    assert ids == [10, 440]
    assert not any(
        "обрез" in r.getMessage().lower() or "поврежд" in r.getMessage().lower()
        for r in caplog.records
    )


# ── CRLF / BOM ─────────────────────────────────────────────────────────────


def test_extract_handles_crlf_and_bom() -> None:
    vdf = "\ufeff" + _make_vdf(570).replace("\n", "\r\n")
    assert _extract_app_ids_from_vdf(vdf) == [570]
