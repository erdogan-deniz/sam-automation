"""Механизмы безопасности: отслеживание ошибок, задержки."""

from __future__ import annotations

import logging

from .exceptions import SAMTooManyErrors

log = logging.getLogger("sam_automation")


class ErrorTracker:
    """Отслеживает последовательные ошибки и останавливает выполнение при превышении лимита."""

    def __init__(self, max_consecutive: int = 3) -> None:
        self.max_consecutive = max_consecutive
        self._consecutive = 0
        self._total_errors = 0

    def record_success(self) -> None:
        """Сбрасывает счётчик последовательных ошибок."""
        self._consecutive = 0

    def record_error(self, game_id: int, error: Exception) -> None:
        """Фиксирует ошибку. Бросает SAMTooManyErrors при превышении лимита."""
        self._consecutive += 1
        self._total_errors += 1
        log.warning(
            "[%d] Ошибка (%d подряд / %d всего): %s",
            game_id, self._consecutive, self._total_errors, error,
        )

        if self._consecutive >= self.max_consecutive:
            raise SAMTooManyErrors(
                f"Аварийная остановка: {self._consecutive} ошибок подряд. "
                f"Последняя: {error}"
            )

    @property
    def total_errors(self) -> int:
        return self._total_errors
