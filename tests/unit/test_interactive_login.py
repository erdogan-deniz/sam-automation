"""Тесты интерактивного входа в Steam CM (app/auth/interactive.py).

Критично: транзиентные ошибки (TryAnotherCM/ServiceUnavailable) РАНЬШЕ давали
бесконечный цикл — тело ветки кончалось `_reconnect_timed(); continue`, минуя
ре-логин, поэтому `result` навсегда оставался транзиентным (login больше не
звался, gevent-таймаут на этот путь не действовал). Плюс битый yes/no-гейт
(подстрочная проверка): «no»/пустой ввод неверно трактовались.

Тесты гоняют ФЕЙКОВЫЙ SteamClient (последовательности EResult), без сети и
реального логина. Страховка от зависания: fake.sleep поднимает исключение после
абсурдного числа вызовов — на баге (бесконечный цикл) тест падает детерминированно,
а не висит.
"""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from steam.enums import EResult  # noqa: E402

import app.auth.interactive as interactive  # noqa: E402


class _FakeClient:
    """Двойник SteamClient: login отдаёт заранее заданную очередь EResult."""

    def __init__(self, login_results, *, connected: bool = True) -> None:
        self._results = list(login_results)
        self._idx = 0
        self.connected = connected
        self.login_calls: list[tuple] = []
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.sleep_calls = 0

    def login(self, *args, **kwargs):
        self.login_calls.append((args, kwargs))
        if self._idx < len(self._results):
            r = self._results[self._idx]
            self._idx += 1
            return r
        return self._results[-1]  # последний результат повторяется

    def sleep(self, _s):
        # Страховка: бесконечный цикл (баг) → детерминированный отказ, не зависание.
        self.sleep_calls += 1
        if self.sleep_calls > 100:
            raise RuntimeError("infinite-loop guard: sleep вызван >100 раз")

    def connect(self):
        self.connect_calls += 1
        self.connected = True
        return True

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False


def _feed_inputs(monkeypatch, answers):
    """Подменяет builtins.input очередью ответов."""
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(it))


def _patch_password(monkeypatch, pw="pw"):
    monkeypatch.setattr(interactive, "_getpass_stars", lambda _prompt: pw)


# ── Транзиентные ошибки: ре-логин, а не вечный цикл ────────────────────────


def test_transient_retries_then_ok(monkeypatch):
    # TryAnotherCM дважды, затем OK → функция делает ре-логины и выходит с OK.
    _patch_password(monkeypatch)
    client = _FakeClient(
        [EResult.TryAnotherCM, EResult.TryAnotherCM, EResult.OK]
    )

    result, user, pw = interactive._do_interactive_login(client, "user")

    assert result == EResult.OK
    assert user == "user"
    assert pw == "pw"
    # начальный login + 2 ре-логина = 3 вызова
    assert len(client.login_calls) == 3


def test_always_transient_terminates(monkeypatch):
    # login всегда TryAnotherCM → НЕ виснет: счётчик исчерпывается, возврат result.
    _patch_password(monkeypatch)
    client = _FakeClient([EResult.TryAnotherCM])

    result, _user, _pw = interactive._do_interactive_login(client, "user")

    assert result == EResult.TryAnotherCM
    # ограничено счётчиком (cap), а не бесконечно
    assert len(client.login_calls) <= 6


# ── ServiceUnavailable + yes/no-гейт ───────────────────────────────────────


def test_service_unavailable_no_exits(monkeypatch):
    # Ответ «no» реально выходит (раньше подстрока → не выходил).
    _patch_password(monkeypatch)
    _feed_inputs(monkeypatch, ["no"])
    client = _FakeClient([EResult.ServiceUnavailable])

    result, _user, _pw = interactive._do_interactive_login(client, "user")

    assert result == EResult.ServiceUnavailable
    # после «no» ре-логина нет — только начальный вызов
    assert len(client.login_calls) == 1


def test_service_unavailable_yes_retries_then_ok(monkeypatch):
    # «yes» → ре-логин; следующий OK → выход с OK.
    _patch_password(monkeypatch)
    _feed_inputs(monkeypatch, ["yes"])
    client = _FakeClient([EResult.ServiceUnavailable, EResult.OK])

    result, _user, _pw = interactive._do_interactive_login(client, "user")

    assert result == EResult.OK
    assert len(client.login_calls) == 2


def test_yesno_gate_rejects_invalid_and_empty(monkeypatch):
    # Пустой ввод и мусор НЕ принимаются (раньше «» — подстрока → ложный выход);
    # цикл ждёт валидного ответа, затем «нет» выходит.
    _patch_password(monkeypatch)
    _feed_inputs(monkeypatch, ["", "maybe", "нет"])
    client = _FakeClient([EResult.ServiceUnavailable])

    result, _user, _pw = interactive._do_interactive_login(client, "user")

    assert result == EResult.ServiceUnavailable
    assert len(client.login_calls) == 1


def test_yes_russian_da_retries(monkeypatch):
    # Русское «да» тоже принимается как yes.
    _patch_password(monkeypatch)
    _feed_inputs(monkeypatch, ["да"])
    client = _FakeClient([EResult.ServiceUnavailable, EResult.OK])

    result, _user, _pw = interactive._do_interactive_login(client, "user")

    assert result == EResult.OK
    assert len(client.login_calls) == 2
