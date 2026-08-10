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
                             k_EResultLimitExceeded which may be permanent").
  granted_appids is None  — API не сообщил исход (напр. EResult.Timeout — CM
                             не ответил за 10с; ЗНАЧЕНИЕ ВОЗВРАТА, не
                             исключение). Живая находка: appid с таким
                             исходом потом реально появлялись owned — сервер
                             их всё равно обрабатывал, просто не уложился в
                             ответ.
  оба выше                — не окончательный отказ ("неизвестно"/"позже", не
                             "нет") — ретрай каждые 30с БЕЗ ограничения по
                             числу попыток (точный cooldown Steam нигде не
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

# Живая находка: RateLimitExceeded и Timeout (granted_appids=None) под
# реальной нагрузкой держатся штормом на протяжении МИНУТ (наблюдалось ~4.5
# минуты подряд), а не секунд — точное время cooldown нигде не
# документировано (ни в самом protobuf-ответе, ни у Valve, ни в комьюнити
# ValvePython/steam) и явно варьируется. Ни один из двух исходов — НЕ
# окончательный отказ: RateLimitExceeded по формулировке самой Valve
# ("different from k_EResultLimitExceeded which may be permanent") ВСЕГДА
# временный; appid с Timeout потом реально появлялись owned (сервер их
# всё равно обрабатывал, просто не уложился в 10с ответа). Экспоненциальный
# backoff с ограниченным числом попыток гадал бы число вслепую и сдавался
# ДО конца шторма — поэтому ретраим ОБА исхода каждые 30с БЕЗ ограничения по
# числу попыток, пока не пройдёт или пользователь не прервёт Ctrl+C (INT
# долетает как KeyboardInterrupt, честный отчёт "прервано" уже обрабатывает
# это на уровне run()). LimitExceeded (потолок лицензий, МОЖЕТ быть
# перманентным) — отдельная, не ретраящаяся стена, останавливает батч
# немедленно.
_TRANSIENT_RETRY_DELAY = 30.0
_BATCH_PAUSE = 1.0  # пауза между батчами — не долбить CM без нужды


@dataclass
class AddResult:
    """Итог одного прогона добавления лицензий."""

    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False
    session_dead: bool = False


@dataclass
class _BatchOutcome:
    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False
    session_dead: bool = False


def _batches(appids: list[int], size: int) -> list[list[int]]:
    return [appids[i : i + size] for i in range(0, len(appids), size)]


def _request_batch_with_backoff(
    client: Any, batch: list[int], eresult_cls: Any
) -> _BatchOutcome:
    """Один батч; RateLimitExceeded и Timeout (granted_appids=None) ретраятся
    каждые 30с БЕЗ ограничения по числу попыток — ни один не окончательный
    отказ ("неизвестно"/"позже", не "нет"), в отличие от LimitExceeded
    (потолок, МОЖЕТ быть перманентным — стена немедленно).
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

        if eresult == eresult_cls.RateLimitExceeded or granted_appids is None:
            # RateLimitExceeded — временный (комментарий Valve: "different
            # from k_EResultLimitExceeded which may be permanent").
            # granted_appids=None — API не сообщил исход (напр. Timeout: CM
            # не ответил за 10с — ЗНАЧЕНИЕ ВОЗВРАТА, не исключение); appid с
            # таким исходом потом реально появлялись owned. Ни то ни другое
            # не повод сдаваться — ретраим одинаково.
            #
            # ИСКЛЮЧЕНИЕ: если сама CM-сессия умерла (сон ноутбука, роуминг
            # WiFi, вход с другого устройства), client.send() тихо отбрасывает
            # сообщение — КАЖДЫЙ следующий вызов даст тот же Timeout, неотличимый
            # по EResult от штатного шторма. "Ретрай без ограничения по числу
            # попыток" на мёртвой сессии — навсегда, а не временно. Честный
            # abort вместо бесконечного hang.
            if not getattr(client, "connected", True):
                log.error(
                    "Steam CM: сессия умерла (client.connected=False) — "
                    "дальнейшие попытки бессмысленны, стоп"
                )
                return _BatchOutcome(session_dead=True)
            log.warning(
                "Steam CM: %s — жду %.0fс и пробую снова",
                getattr(eresult, "name", eresult),
                _TRANSIENT_RETRY_DELAY,
            )
            time.sleep(_TRANSIENT_RETRY_DELAY)
            continue

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
    hit_cap=True, оставшиеся батчи НЕ запрашиваются) и при обнаруженной
    мёртвой CM-сессии (session_dead=True, тот же немедленный стоп — см.
    _request_batch_with_backoff). RateLimitExceeded и Timeout
    (granted_appids=None) на ЖИВОЙ сессии — ретрай каждые 30с без ограничения
    по числу попыток. Прочие неуспехи — refused (appid из батча, которого нет
    в granted_appids). Исключение при вызове — error (appid из батча,
    транзиент — восстановим --retry-errors).
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
        if outcome.session_dead:
            result.session_dead = True
            log.error(
                "Steam CM: сессия умерла посреди прогона — стоп. "
                "Добавлено в этом прогоне: %d",
                len(result.added),
            )
            break
        result.added.extend(outcome.added)
        result.refused.extend(outcome.refused)
        result.error.extend(outcome.error)
        if i < len(batches) - 1:
            time.sleep(_BATCH_PAUSE)

    return result
