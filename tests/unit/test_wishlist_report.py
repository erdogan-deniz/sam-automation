"""Тесты честного отчёта app/wishlist/report.py."""

from __future__ import annotations

from types import SimpleNamespace

import app.wishlist.report as report_mod


def _cfg() -> SimpleNamespace:
    return SimpleNamespace()


def _capture(monkeypatch) -> dict:
    calls: dict = {}
    monkeypatch.setattr(
        report_mod, "toast", lambda t, m: calls.setdefault("toast", (t, m))
    )
    monkeypatch.setattr(
        report_mod,
        "send_telegram",
        lambda text, cfg: calls.setdefault("tg", text),
    )
    return calls


def test_report_ok_status_marks_success(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=5, refused=0, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "готово" in calls["toast"][1]
    assert "✅" in calls["tg"]


def test_report_hit_wall_never_says_all_added(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=40, refused=0, error=0, hit_wall=True, cfg=_cfg()
    )
    assert "стена" in calls["toast"][1]
    assert "⚠️" in calls["tg"]  # НЕ ✅ — упор в rate-limit не чистый успех


def test_report_interrupted_never_marks_success(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="interrupted",
        added=3,
        refused=0,
        error=0,
        hit_wall=False,
        cfg=_cfg(),
    )
    assert "прервано" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_error_status_marks_qualified(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="error", added=1, refused=0, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "прервано ошибкой" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_refused_or_error_marks_qualified(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=5, refused=2, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "оговорками" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_dry_run_marks_success_without_adding(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="dry_run",
        added=0,
        refused=0,
        error=0,
        hit_wall=False,
        cfg=_cfg(),
    )
    assert "dry-run" in calls["toast"][1]
    assert "✅" in calls["tg"]
