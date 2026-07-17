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
                             — ретрай каждые 30с БЕЗ ограничения по числу
                             попыток (точный cooldown Steam нигде не
                             документирован); Ctrl+C прерывает как обычно.
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

# Живая находка (не поймать юнит-тестом на фейковом клиенте): 50 давало
# систематический Timeout под реальной нагрузкой CM — 50 лицензий не
# укладывались в жёсткие 10с send_job_and_wait библиотеки, appid ложно уходил
# в error, хотя сервер их всё равно грантил (owned рос между прогонами).
# Контрольный A/B на РЕАЛЬНОМ аккаунте в одну и ту же сессию: batch_size=50 —
# Timeout за ровно 10.2с; batch_size=20 — успех за 0.3с. 20 — с большим
# запасом (33x) от границы отказа, не гадание.
BATCH_SIZE = 20

# Живая находка: RateLimitExceeded под реальной нагрузкой держится штормом
# на протяжении МИНУТ (наблюдалось ~4.5 минуты подряд), а не секунд — точное
# время cooldown нигде не документировано (ни в самом protobuf-ответе, ни у
# Valve, ни в комьюнити ValvePython/steam) и явно варьируется. Экспоненциальный
# backoff с ограниченным числом попыток гадал бы число вслепую и сдавался
# ДО конца шторма, хотя окно всё-таки открывается (один батч посреди того же
# шторма прошёл успешно). RateLimitExceeded — по формулировке самой Valve
# ("different from k_EResultLimitExceeded which may be permanent") ВСЕГДА
# временный, поэтому ретраим каждые 30с БЕЗ ограничения по числу попыток —
# пока не пройдёт или пользователь не прервёт Ctrl+C (INT долетает как
# KeyboardInterrupt, честный отчёт "прервано" уже обрабатывает это на
# уровне run()). LimitExceeded (потолок лицензий, МОЖЕТ быть перманентным) —
# отдельная, не ретраящаяся стена, останавливает батч немедленно.
_RATE_LIMIT_RETRY_DELAY = 30.0
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
    """Один батч; RateLimitExceeded ретраится каждые 30с БЕЗ ограничения по
    числу попыток — точный cooldown Steam нигде не документирован, а
    RateLimitExceeded по определению временный (в отличие от LimitExceeded).
    """
    while True:
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
            log.warning(
                "Steam CM: rate limit — жду %.0fс и пробую снова",
                _RATE_LIMIT_RETRY_DELAY,
            )
            time.sleep(_RATE_LIMIT_RETRY_DELAY)
            continue

        if granted_appids is None:
            # granted_appids=None означает, что API не сообщил исход (напр.
            # EResult.Timeout — CM не ответил за 10с; это ЗНАЧЕНИЕ ВОЗВРАТА,
            # не исключение, поэтому except-ветка выше его не ловит).
            # Трактовать "неизвестно" как "все отказаны" похоронило бы весь
            # батч в терминальном refused.txt на транзиентном сбое —
            # классифицируем как error (восстановим --retry-errors).
            log.warning(
                "Steam CM: request_free_license не сообщил исход (%s) — "
                "батч в error",
                getattr(eresult, "name", eresult),
            )
            return _BatchOutcome(error=list(batch))

        granted = {int(a) for a in granted_appids}
        refused = [a for a in batch if a not in granted]
        if refused:
            log.info(
                "Steam CM: отказано в лицензии (%s): %s",
                getattr(eresult, "name", eresult),
                refused,
            )
        return _BatchOutcome(added=sorted(granted), refused=refused)


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
