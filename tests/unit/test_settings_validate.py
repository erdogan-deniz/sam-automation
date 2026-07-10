"""Тесты для логики валидации SettingsTab (_validate, _path_warnings, is_configured).

Не требует Tk/display: методы вызываются с SimpleNamespace вместо реального виджета.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gui.tabs.settings import SettingsTab, _merge_config

# ── helpers ────────────────────────────────────────────────────────────────


def _entry(value: str) -> MagicMock:
    """Mock CTkEntry.get() → value."""
    m = MagicMock()
    m.get.return_value = value
    return m


def _make_settings(**overrides: str) -> SimpleNamespace:
    """SimpleNamespace с атрибутами-записями, имитирующий SettingsTab."""
    defaults: dict[str, str] = {
        "steam_api_key": "abc123",
        "steam_id": "76561198000000000",
        "launch_delay": "3.0",
        "load_timeout": "10.0",
        "post_commit_delay": "0.2",
        "between_games_delay": "0.1",
        "max_consecutive_errors": "100",
        "max_concurrent_games": "1",
        "card_check_interval": "30",
        "playtime_idle_duration": "120",
        "sam_exe": "",
        "steam_path": "",
        "game_ids_file": "",
    }
    defaults.update(overrides)
    ns = SimpleNamespace()
    for name, val in defaults.items():
        setattr(ns, f"_{name}", _entry(val))
    return ns


def _validate(ns: SimpleNamespace) -> list[str]:
    return SettingsTab._validate(ns)  # type: ignore[arg-type]


def _path_warnings(ns: SimpleNamespace) -> list[str]:
    return SettingsTab._path_warnings(ns)  # type: ignore[arg-type]


# ── _validate — обязательные поля ──────────────────────────────────────────


def test_validate_ok_returns_empty() -> None:
    assert _validate(_make_settings()) == []


def test_validate_missing_api_key() -> None:
    errors = _validate(_make_settings(steam_api_key=""))
    assert any("steam_api_key" in e for e in errors)


def test_validate_missing_steam_id() -> None:
    errors = _validate(_make_settings(steam_id="  "))
    assert any("steam_id" in e for e in errors)


def test_validate_both_missing() -> None:
    errors = _validate(_make_settings(steam_api_key="", steam_id=""))
    fields = {e.split(":")[0] for e in errors}
    assert "steam_api_key" in fields
    assert "steam_id" in fields


# ── _validate — числовые поля ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("launch_delay", "abc"),
        ("load_timeout", "not_a_number"),
        ("post_commit_delay", ""),
        ("max_consecutive_errors", "one"),
        ("max_concurrent_games", "two"),
        ("card_check_interval", "!"),
        ("playtime_idle_duration", "?"),
    ],
)
def test_validate_non_numeric(field: str, bad_value: str) -> None:
    errors = _validate(_make_settings(**{field: bad_value}))
    assert any(field in e for e in errors), (
        f"Expected error for {field}={bad_value!r}"
    )


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("load_timeout", "0"),  # min 0.1
        ("max_consecutive_errors", "-1"),
        ("max_concurrent_games", "0"),
        ("card_check_interval", "0"),
        ("playtime_idle_duration", "0"),
    ],
)
def test_validate_below_minimum(field: str, bad_value: str) -> None:
    errors = _validate(_make_settings(**{field: bad_value}))
    assert any(field in e for e in errors), (
        f"Expected min error for {field}={bad_value!r}"
    )


@pytest.mark.parametrize(
    "field,good_value",
    [
        ("launch_delay", "0"),  # 0 is ok
        ("post_commit_delay", "0"),
        ("between_games_delay", "0"),
        ("load_timeout", "0.1"),  # exactly min
        ("max_concurrent_games", "1"),
    ],
)
def test_validate_boundary_ok(field: str, good_value: str) -> None:
    errors = _validate(_make_settings(**{field: good_value}))
    assert not any(field in e for e in errors), (
        f"Unexpected error for {field}={good_value!r}"
    )


# ── _path_warnings ──────────────────────────────────────────────────────────


def test_path_warnings_empty_paths_no_warning() -> None:
    ns = _make_settings(sam_exe="", steam_path="", game_ids_file="")
    assert _path_warnings(ns) == []


def test_path_warnings_nonexistent_file(tmp_path: Path) -> None:
    ns = _make_settings(sam_exe=str(tmp_path / "missing.exe"))
    warnings = _path_warnings(ns)
    assert any("sam_game_exe_path" in w for w in warnings)


def test_path_warnings_nonexistent_dir(tmp_path: Path) -> None:
    ns = _make_settings(steam_path=str(tmp_path / "no_such_dir"))
    warnings = _path_warnings(ns)
    assert any("steam_path" in w for w in warnings)


def test_path_warnings_existing_file_no_warning(tmp_path: Path) -> None:
    f = tmp_path / "SAM.Game.exe"
    f.touch()
    ns = _make_settings(sam_exe=str(f))
    warnings = _path_warnings(ns)
    assert not any("sam_game_exe_path" in w for w in warnings)


def test_path_warnings_existing_dir_no_warning(tmp_path: Path) -> None:
    ns = _make_settings(steam_path=str(tmp_path))
    warnings = _path_warnings(ns)
    assert not any("steam_path" in w for w in warnings)


# ── is_configured ───────────────────────────────────────────────────────────


def test_is_configured_true() -> None:
    ns = _make_settings(steam_api_key="key", steam_id="12345")
    assert SettingsTab.is_configured(ns)  # type: ignore[arg-type]


def test_is_configured_false_when_key_empty() -> None:
    ns = _make_settings(steam_api_key="", steam_id="12345")
    assert not SettingsTab.is_configured(ns)  # type: ignore[arg-type]


def test_is_configured_false_when_id_empty() -> None:
    ns = _make_settings(steam_api_key="key", steam_id="")
    assert not SettingsTab.is_configured(ns)  # type: ignore[arg-type]


# ── _merge_config (M4: сохранение не теряет ключи не из формы) ───────────────


def test_merge_config_preserves_form_absent_keys() -> None:
    existing = {
        "playtime_concurrent_games": 15,
        "launch_stagger": 2.0,
        "playtime_target_minutes": 5,
        "telegram_bot_token": "tok",
        "game_ids": [1, 2],
        "steam_id": "old",
    }
    updates = {"steam_id": "new", "playtime_idle_duration": 200}
    merged = _merge_config(existing, updates, exclude=[])
    # ключи не из формы сохранены
    assert merged["playtime_concurrent_games"] == 15
    assert merged["launch_stagger"] == 2.0
    assert merged["playtime_target_minutes"] == 5
    assert merged["telegram_bot_token"] == "tok"
    assert merged["game_ids"] == [1, 2]
    # управляемые формой обновлены
    assert merged["steam_id"] == "new"
    assert merged["playtime_idle_duration"] == 200


def test_merge_config_exclude_set_and_cleared() -> None:
    assert _merge_config({}, {}, [1, 2])["exclude_ids"] == [1, 2]
    # пустой exclude убирает ключ (форма явно очищает)
    assert "exclude_ids" not in _merge_config({"exclude_ids": [9]}, {}, [])


def test_save_preserves_unmanaged_keys_end_to_end(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    # M4 end-to-end: настоящий _save читает existing config, мержит поля формы
    # и пишет обратно — ключи не из формы (playtime_concurrent_games,
    # launch_stagger, target, telegram_*, game_ids) НЕ теряются.
    import yaml

    import gui.tabs.settings as settings_mod

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "playtime_concurrent_games: 15\n"
        "launch_stagger: 2.0\n"
        "playtime_target_minutes: 5\n"
        "telegram_bot_token: tok\n"
        "game_ids: [1, 2]\n"
        "steam_id: old_id\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_mod, "_CONFIG_PATH", cfg_path)

    ns = _make_settings(steam_api_key="newkey", steam_id="new_id")
    ns._validate = lambda: []  # type: ignore[attr-defined]
    ns._path_warnings = lambda: []  # type: ignore[attr-defined]
    ns.is_configured = lambda: False  # type: ignore[attr-defined]
    ns._lbl_saved = MagicMock()
    ns.after = MagicMock()
    ns._exclude_ids = MagicMock()
    ns._exclude_ids.get.return_value = ""

    SettingsTab._save(ns)  # type: ignore[arg-type]

    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    # ключи не из формы — сохранены
    assert saved["playtime_concurrent_games"] == 15
    assert saved["launch_stagger"] == 2.0
    assert saved["playtime_target_minutes"] == 5
    assert saved["telegram_bot_token"] == "tok"
    assert saved["game_ids"] == [1, 2]
    # поля формы — обновлены
    assert saved["steam_api_key"] == "newkey"
    assert saved["steam_id"] == "new_id"
    assert saved["playtime_idle_duration"] == 120
