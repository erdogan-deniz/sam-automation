"""Тесты CLI-флагов scripts/achievements/farm.py.

Скрипт импортируется напрямую по пути (он не пакет). Проверяем разбор
аргументов и применение сброса прогресса — то, что чинит мёртвые кнопки
GUI «Retry errors» / «Reset».
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_FARM_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "achievements" / "farm.py"
)


def _load_farm() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "farm_ach_under_test", _FARM_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


farm = _load_farm()


# ── разбор аргументов ───────────────────────────────────────────────────────


def test_parser_defaults_all_false() -> None:
    args = farm._build_parser().parse_args([])
    assert not args.retry_errors
    assert not args.reset
    assert not args.no_resume


def test_parser_retry_errors() -> None:
    assert farm._build_parser().parse_args(["--retry-errors"]).retry_errors


def test_parser_reset() -> None:
    assert farm._build_parser().parse_args(["--reset"]).reset


def test_parser_no_resume() -> None:
    assert farm._build_parser().parse_args(["--no-resume"]).no_resume


# ── применение сброса ───────────────────────────────────────────────────────


def test_prepare_progress_reset_clears_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(farm, "clear_progress", lambda: called.append("all"))
    monkeypatch.setattr(farm, "clear_error_ids", lambda: called.append("err"))
    farm._prepare_progress(farm._build_parser().parse_args(["--reset"]))
    assert called == ["all"]


def test_prepare_progress_retry_errors_clears_only_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(farm, "clear_progress", lambda: called.append("all"))
    monkeypatch.setattr(farm, "clear_error_ids", lambda: called.append("err"))
    farm._prepare_progress(farm._build_parser().parse_args(["--retry-errors"]))
    assert called == ["err"]


def test_prepare_progress_noop_without_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(farm, "clear_progress", lambda: called.append("all"))
    monkeypatch.setattr(farm, "clear_error_ids", lambda: called.append("err"))
    farm._prepare_progress(farm._build_parser().parse_args([]))
    assert called == []


# ── честный финальный отчёт ─────────────────────────────────────────────────
# Инвариант: прерванный (Ctrl+C) или аварийный (слишком много ошибок) прогон
# НЕ должен давать success-«✅ Готово» — только честный ⚠️ с оговоркой.


def _capture_report(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    unlocked: int,
    errors: int,
    total: int,
) -> tuple[str, str]:
    """Гоняет farm._report_result с перехватом toast/Telegram."""
    toast_msgs: list[str] = []
    tg_msgs: list[str] = []
    monkeypatch.setattr(
        farm, "toast", lambda title, msg: toast_msgs.append(f"{title}: {msg}")
    )
    monkeypatch.setattr(
        farm, "send_telegram", lambda text, cfg: tg_msgs.append(text)
    )
    farm._report_result(status, unlocked, errors, total, cfg=object())
    return toast_msgs[0], tg_msgs[0]


def test_report_clean_run_is_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "ok", 10, 0, 10)
    assert "✅" in tg_msg
    assert "⚠️" not in tg_msg
    assert "готово" in toast_msg.lower()


def test_report_errors_downgrade_to_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "ok", 7, 3, 10)
    assert "✅" not in tg_msg
    assert "⚠️" in tg_msg
    assert "оговорк" in toast_msg.lower()


def test_report_interrupted_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "interrupted", 5, 0, 10)
    assert "✅" not in tg_msg
    assert "⚠️" in tg_msg
    assert "прерв" in toast_msg.lower()


def test_report_aborted_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "aborted", 2, 5, 10)
    assert "✅" not in tg_msg
    assert "⚠️" in tg_msg
    assert "прерв" in toast_msg.lower()
