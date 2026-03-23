"""Тип результата разблокировки достижений одной игры."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UnlockResult:
    """Результат обработки одной игры."""

    game_id: int
    total: int = 0
    already_unlocked: int = 0
    newly_unlocked: int = 0
    skipped: bool = False
    skip_reason: str = ""
