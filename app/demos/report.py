"""Честный итоговый отчёт авто-добавления demo-версий игр (toast + Telegram).

Зеркало app/free_games/report.py (2026-09-12, B-11) с текстом под demo.
status="ok" с hit_cap=True НИКОГДА не даёт ✅ — упор в потолок лицензий не
считается чистым успехом (инвариант честного отчёта проекта).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.logging_setup import SEPARATOR
from app.notify import send_telegram, toast

log = logging.getLogger("sam_automation")


def report_result(
    *,
    status: Literal["ok", "interrupted", "error", "dry_run"],
    added: int,
    refused: int,
    error: int,
    hit_cap: bool,
    session_dead: bool = False,
    cfg: Any,
) -> None:
    """Честный финальный отчёт (лог + toast + Telegram).

    status: "ok" | "interrupted" | "error" | "dry_run". session_dead=True
    (CM-сессия умерла посреди прогона) — тоже НЕ ✅.
    """
    if status == "dry_run":
        head, ok = "dry-run (ничего не добавлено)", True
    elif status == "interrupted":
        head, ok = "прервано (Ctrl+C)", False
    elif status == "error":
        head, ok = "прервано ошибкой", False
    elif hit_cap:
        head, ok = "упор в стену (потолок лицензий)", False
    elif session_dead:
        head, ok = "прервано: сессия Steam умерла", False
    elif refused or error:
        head, ok = "готово с оговорками", False
    else:
        head, ok = "готово", True

    detail = f"добавлено {added}, отказано {refused}, ошибок {error}"
    if hit_cap:
        detail += " — дальше стена"

    log.info(SEPARATOR)
    log.info("Добавление demo — %s. %s", head, detail)
    log.info(SEPARATOR)
    toast("SAM Automation — Demos", f"{head}: {detail}")
    mark = "✅" if ok else "⚠️"
    send_telegram(f"{mark} Demos — {head}: {detail}", cfg)
