"""Батчевый запрос бесплатных лицензий через живой Steam CM клиент.

client.request_free_license(app_ids) -> (EResult, granted_appids,
granted_packageids) — реальная сигнатура из steam/client/builtins/apps.py
установленной библиотеки (send_job_and_wait на ClientRequestFreeLicense,
таймаут 10с внутри библиотеки). Вызывается на живом клиенте из
app.steam.steam_cm.cm_session().

Классификация EResult (см. steam/enums/common.py):
  LimitExceeded (25)      — потолок лицензий аккаунта, МОЖЕТ быть
                             перманентным (комментарий в самой библиотеке) —
                             СТЕНА, стоп немедленно.
  RateLimitExceeded (84)  — временный (комментарий: "different from
                             k_EResultLimitExceeded which may be permanent")
                             — экспоненциальный backoff, продолжаем.
  всё остальное           — granted_appids авторитетен независимо от
                             точного eresult (напр. DuplicateRequest на
                             частично уже выданном батче всё равно granted'ит
                             новые): appid из батча, которого нет в granted,
                             считается refused.
  исключение при вызове   — error (appid из батча, транзиент — восстановим
                             --retry-errors).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("sam_automation")

BATCH_SIZE = 50
_RATE_LIMIT_ATTEMPTS = 3
_RATE_LIMIT_BASE_DELAY = 2.0
_RATE_LIMIT_DELAY_CAP = 60.0
_BATCH_PAUSE = 1.0  # пауза между батчами — не долбить CM без нужды


@dataclass
class AddResult:
    """Итог одного прогона добавления лицензий."""

    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False


@dataclass
class _BatchOutcome:
    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False


def _batches(appids: list[int], size: int) -> list[list[int]]:
    return [appids[i : i + size] for i in range(0, len(appids), size)]


def _request_batch_with_backoff(
    client: Any, batch: list[int], eresult_cls: Any
) -> _BatchOutcome:
    """Один батч с ретраем на RateLimitExceeded (экспоненциальный backoff)."""
    delay = _RATE_LIMIT_BASE_DELAY
    for attempt in range(_RATE_LIMIT_ATTEMPTS):
        try:
            eresult, granted_appids, _granted_packageids = (
                client.request_free_license(batch)
            )
        except Exception as e:
            log.warning("Steam CM: request_free_license упал: %s", e)
            return _BatchOutcome(error=list(batch))

        if eresult == eresult_cls.LimitExceeded:
            return _BatchOutcome(hit_cap=True)

        if eresult == eresult_cls.RateLimitExceeded:
            if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                log.warning("Steam CM: rate limit не отступил — батч в error")
                return _BatchOutcome(error=list(batch))
            log.warning(
                "Steam CM: rate limit (попытка %d/%d) — жду %.0fс",
                attempt + 1,
                _RATE_LIMIT_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, _RATE_LIMIT_DELAY_CAP)
            continue

        granted = {int(a) for a in (granted_appids or [])}
        refused = [a for a in batch if a not in granted]
        if refused:
            log.info(
                "Steam CM: отказано в лицензии (%s): %s",
                getattr(eresult, "name", eresult),
                refused,
            )
        return _BatchOutcome(added=sorted(granted), refused=refused)

    return _BatchOutcome(error=list(batch))  # недостижимо — для mypy


def add_licenses(
    client: Any, appids: list[int], *, batch_size: int = BATCH_SIZE
) -> AddResult:
    """Запрашивает бесплатные лицензии батчами на живом CM-клиенте.

    Останавливается немедленно при EResult.LimitExceeded (потолок аккаунта —
    hit_cap=True, оставшиеся батчи НЕ запрашиваются). RateLimitExceeded —
    backoff, продолжает после восстановления. Прочие неуспехи — refused
    (appid из батча, которого нет в granted_appids). Исключение при вызове —
    error (appid из батча, транзиент — восстановим --retry-errors).
    """
    from steam.enums import EResult

    result = AddResult()
    batches = _batches(appids, batch_size)

    for i, batch in enumerate(batches):
        outcome = _request_batch_with_backoff(client, batch, EResult)
        if outcome.hit_cap:
            result.hit_cap = True
            log.warning(
                "Steam CM: потолок free-лицензий аккаунта (LimitExceeded) — "
                "стоп. Добавлено в этом прогоне: %d",
                len(result.added),
            )
            break
        result.added.extend(outcome.added)
        result.refused.extend(outcome.refused)
        result.error.extend(outcome.error)
        if i < len(batches) - 1:
            time.sleep(_BATCH_PAUSE)

    return result
