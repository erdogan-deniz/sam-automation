"""Честный итоговый отчёт авто-добавления в Wishlist Steam (toast + Telegram).

status="ok" с hit_wall=True НИКОГДА не даёт ✅ — упор в rate-limit-стену не
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
    hit_wall: bool,
    cfg: Any,
) -> None:
    """Честный финальный отчёт (лог + toast + Telegram).

    status: "ok" | "interrupted" | "error" | "dry_run".
    """
    if status == "dry_run":
        head, ok = "dry-run (ничего не добавлено)", True
    elif status == "interrupted":
        head, ok = "прервано (Ctrl+C)", False
    elif status == "error":
        head, ok = "прервано ошибкой", False
    elif hit_wall:
        head, ok = "упор в стену (rate-limit)", False
    elif refused or error:
        head, ok = "готово с оговорками", False
    else:
        head, ok = "готово", True

    detail = f"добавлено {added}, отказано {refused}, ошибок {error}"
    if hit_wall:
        detail += " — дальше стена"

    log.info(SEPARATOR)
    log.info("Добавление в Wishlist — %s. %s", head, detail)
    log.info(SEPARATOR)
    toast("SAM Automation — Wishlist", f"{head}: {detail}")
    mark = "✅" if ok else "⚠️"
    send_telegram(f"{mark} Wishlist — {head}: {detail}", cfg)
