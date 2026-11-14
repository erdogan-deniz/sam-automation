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
  RateLimitExceeded       — ретрай каждые 30с без ограничения по числу
                             попыток (точный cooldown Steam нигде не
                             документирован); Ctrl+C прерывает как обычно.
  Timeout / пустой ответ  — не отказ: сервер часто выдаёт лицензию позже.
  Busy, ServiceUnavailable   Поздний ответ ловит слушатель
                             ClientRequestFreeLicenseResponse (библиотека
                             снимает jobid через 10с и теряет его). Пачка
                             делится пополам после 2 таких исходов подряд,
                             одиночный appid после 3 — в error; 10 подряд
                             по всему прогону без единого ответа — стоп
                             (stalled). Живьём 21.10.2026 без этого: 47
                             Timeout подряд на первой пачке DLC, выдано 0.
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
from collections.abc import Callable
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
# МИНУТАМИ (наблюдалось ~4.5 минуты подряд); точное время cooldown нигде не
# документировано. По формулировке Valve ("different from
# k_EResultLimitExceeded which may be permanent") он ВСЕГДА временный —
# ретраим каждые 30с без ограничения по числу попыток, пока не пройдёт или
# пользователь не прервёт Ctrl+C. LimitExceeded (потолок лицензий, МОЖЕТ
# быть перманентным) — отдельная стена, стоп немедленно.
_TRANSIENT_RETRY_DELAY = 30.0
_BATCH_PAUSE = 1.0  # пауза между батчами — не долбить CM без нужды

# Timeout и пустой ответ «сервер занят» — ограниченно (живьём 21.10.2026:
# 47 Timeout подряд без предела, выдано 0, прогон остановлен вручную).
_EMPTY_TRANSIENT = frozenset(
    {"Timeout", "Busy", "ServiceUnavailable", "TryAnotherCM"}
)
_SPLIT_AFTER_TIMEOUTS = 2  # пачка > 1 appid делится пополам
_SINGLE_GIVE_UP_TIMEOUTS = 3  # одиночный appid → error (--retry-errors)
_STALL_ABORT_TIMEOUTS = 10  # подряд по всему прогону без ответа → стоп


@dataclass
class AddResult:
    """Итог одного прогона добавления лицензий."""

    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False
    session_dead: bool = False
    stalled: bool = False  # Steam не ответил на _STALL_ABORT_TIMEOUTS подряд


@dataclass
class _BatchOutcome:
    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False
    session_dead: bool = False
    stalled: bool = False

    @property
    def stop(self) -> bool:
        return self.hit_cap or self.session_dead or self.stalled

    def merge(self, other: _BatchOutcome) -> None:
        self.added += other.added
        self.refused += other.refused
        self.error += other.error
        self.hit_cap |= other.hit_cap
        self.session_dead |= other.session_dead
        self.stalled |= other.stalled


def _batches(appids: list[int], size: int) -> list[list[int]]:
    return [appids[i : i + size] for i in range(0, len(appids), size)]


def _sleep(client: Any, seconds: float) -> None:
    """Пауза через client.sleep (gevent): time.sleep замораживает CM-клиент —
    входящие ответы не читаются, heartbeat не уходит."""
    sleep = getattr(client, "sleep", None)
    (sleep or time.sleep)(seconds)


class _LateGrants:
    """Собирает granted_appids из ВСЕХ ответов ClientRequestFreeLicense.

    send_job_and_wait ждёт ответ по jobid 10с и снимает ожидание: ответ,
    пришедший позже, библиотека молча выбрасывает. Слушатель на сам EMsg
    ловит и такие.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self.granted: set[int] = set()
        self._emsg: Any = None
        if hasattr(client, "on"):
            from steam.enums.emsg import EMsg

            self._emsg = EMsg.ClientRequestFreeLicenseResponse
            client.on(self._emsg, self._on_response)

    def _on_response(self, msg: Any) -> None:
        body = getattr(msg, "body", None)
        for appid in getattr(body, "granted_appids", None) or []:
            self.granted.add(int(appid))

    def take(self, batch: list[int]) -> list[int]:
        return [a for a in batch if a in self.granted]

    def close(self) -> None:
        if self._emsg is not None:
            self._client.remove_listener(self._emsg, self._on_response)


class _Run:
    """Счётчик Timeout подряд по всему прогону (сбрасывается любым ответом)."""

    def __init__(self) -> None:
        self.silent = 0


def _is_silent(eresult: Any, granted_appids: Any) -> bool:
    """Ответа по существу нет: Timeout (None) или пустой «сервер занят»."""
    if granted_appids is None:
        return True
    return (
        not granted_appids and getattr(eresult, "name", "") in _EMPTY_TRANSIENT
    )


def _request_batch_with_backoff(
    client: Any,
    batch: list[int],
    eresult_cls: Any,
    late: _LateGrants | None = None,
    run: _Run | None = None,
) -> _BatchOutcome:
    """Один батч до окончательного исхода (см. классификацию в docstring модуля)."""
    late = late if late is not None else _LateGrants(object())
    run = run if run is not None else _Run()
    out = _BatchOutcome()
    silent = 0
    while True:
        try:
            eresult, granted_appids, _granted_packageids = (
                client.request_free_license(batch)
            )
        except Exception as e:
            log.warning("Steam CM: request_free_license упал: %s", e)
            out.error += batch
            return out

        if eresult == eresult_cls.LimitExceeded:
            out.added += late.take(batch)
            out.hit_cap = True
            return out

        rate_limited = eresult == eresult_cls.RateLimitExceeded
        if rate_limited or _is_silent(eresult, granted_appids):
            # Мёртвая CM-сессия (сон ноутбука, роуминг WiFi, вход с другого
            # устройства): client.send() тихо отбрасывает сообщение, каждый
            # вызов даёт тот же Timeout — честный abort вместо hang.
            if not getattr(client, "connected", True):
                log.error(
                    "Steam CM: сессия умерла (client.connected=False) — "
                    "дальнейшие попытки бессмысленны, стоп"
                )
                out.added += late.take(batch)
                out.session_dead = True
                return out
            log.warning(
                "Steam CM: %s — жду %.0fс и пробую снова",
                getattr(eresult, "name", eresult),
                _TRANSIENT_RETRY_DELAY,
            )
            _sleep(client, _TRANSIENT_RETRY_DELAY)
            got = late.take(batch)
            if got:
                log.info("Steam CM: поздний ответ — выдано %s", got)
                out.added += got
                batch = [a for a in batch if a not in got]
                if not batch:
                    return out
            if rate_limited:
                run.silent = 0
                continue
            silent += 1
            run.silent += 1
            if run.silent >= _STALL_ABORT_TIMEOUTS:
                log.error(
                    "Steam CM: нет ответа на %d запросов подряд — стоп",
                    run.silent,
                )
                out.stalled = True
                return out
            if len(batch) > 1 and silent >= _SPLIT_AFTER_TIMEOUTS:
                mid = len(batch) // 2
                log.info(
                    "Steam CM: делю пачку %d → %d + %d",
                    len(batch),
                    mid,
                    len(batch) - mid,
                )
                for half in (batch[:mid], batch[mid:]):
                    part = _request_batch_with_backoff(
                        client, half, eresult_cls, late, run
                    )
                    out.merge(part)
                    if part.stop:
                        break
                return out
            if len(batch) == 1 and silent >= _SINGLE_GIVE_UP_TIMEOUTS:
                log.warning("Steam CM: нет ответа по %s — в error", batch)
                out.error += batch
                return out
            continue

        run.silent = 0
        granted = {int(a) for a in granted_appids} | set(late.take(batch))
        refused = [a for a in batch if a not in granted]
        if refused:
            log.info(
                "Steam CM: отказано в лицензии (%s): %s",
                getattr(eresult, "name", eresult),
                refused,
            )
        out.added += sorted(a for a in granted if a in batch)
        out.refused += refused
        return out


def add_licenses(
    client: Any,
    appids: list[int],
    *,
    batch_size: int = BATCH_SIZE,
    persist: Callable[[int, str], None] | None = None,
) -> AddResult:
    """Запрашивает бесплатные лицензии батчами на живом CM-клиенте.

    Останавливается немедленно при EResult.LimitExceeded (потолок аккаунта —
    hit_cap=True, оставшиеся батчи НЕ запрашиваются) и при обнаруженной
    мёртвой CM-сессии (session_dead=True, тот же немедленный стоп — см.
    _request_batch_with_backoff), и когда Steam молчит
    _STALL_ABORT_TIMEOUTS запросов подряд (stalled=True). RateLimitExceeded
    на ЖИВОЙ сессии — ретрай каждые 30с без ограничения по числу попыток;
    Timeout — ограниченно, с делением пачки и сбором поздних ответов
    (см. docstring модуля). Прочие неуспехи — refused (appid из батча, которого нет
    в granted_appids). Исключение при вызове — error (appid из батча,
    транзиент — восстановим --retry-errors).

    persist (опционально) вызывается СРАЗУ по каждому решённому appid батча
    ("added"/"refused"/"error"), ДО перехода к следующему батчу. Живая
    находка (аудит 2026-08-10): AddResult копился в памяти и персистился
    ОДНИМ батчем ПОСЛЕ полного возврата этой функции — KeyboardInterrupt/
    жёсткий килл во время многоминутного retry-шторма
    (_TRANSIENT_RETRY_DELAY, без ограничения по числу попыток — наблюдался
    шторм ~4.5 мин подряд) НАСОВСЕМ терял уже выданные Steam лицензии
    предыдущих батчей. Тот же паттерн, что в
    app.wishlist.wishlist_api.add_pending.
    """
    from steam.enums import EResult

    result = AddResult()
    batches = _batches(appids, batch_size)
    late = _LateGrants(client)
    run = _Run()
    try:
        _add_batches(client, batches, EResult, late, run, result, persist)
    finally:
        late.close()
    return result


def _add_batches(
    client: Any,
    batches: list[list[int]],
    eresult_cls: Any,
    late: _LateGrants,
    run: _Run,
    result: AddResult,
    persist: Callable[[int, str], None] | None,
) -> None:
    for i, batch in enumerate(batches):
        outcome = _request_batch_with_backoff(
            client, batch, eresult_cls, late, run
        )
        # выданное до стопа (поздние ответы) тоже сохраняется
        if persist is not None:
            for appid in outcome.added:
                persist(appid, "added")
            for appid in outcome.refused:
                persist(appid, "refused")
            for appid in outcome.error:
                persist(appid, "error")
        result.added.extend(outcome.added)
        result.refused.extend(outcome.refused)
        result.error.extend(outcome.error)
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
        if outcome.stalled:
            result.stalled = True
            log.error(
                "Steam CM: Steam не отвечает — стоп. Добавлено в этом "
                "прогоне: %d",
                len(result.added),
            )
            break
        if i < len(batches) - 1:
            _sleep(client, _BATCH_PAUSE)
