"""Тесты app/wishlist/wishlist_api.py: HTTP-вызов + x-eresult классификатор.

x-eresult и коды сняты вживую на реальном аккаунте 2026-07-18 (см.
docs/superpowers/specs/2026-07-18-add-wishlist-design.md): 1=added,
2/8=refused (owned/уже-в-вишлисте/invalid), 429 или eresult=84=rate_limit,
HTTP 401=auth_fail.
"""

from __future__ import annotations

import email.message
import json
import urllib.error
from collections.abc import Callable

import pytest

import app.wishlist.wishlist_api as wishlist_api


class _FakeResp:
    """Контекст-менеджер успешного ответа urlopen (status + headers + JSON body)."""

    def __init__(self, status: int, eresult: str | None, body: dict) -> None:
        self.status = status
        self.headers = {"x-eresult": eresult} if eresult is not None else {}
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _http_error(
    code: int, eresult: str | None = None
) -> urllib.error.HTTPError:
    hdrs = email.message.Message()
    if eresult is not None:
        hdrs["x-eresult"] = eresult
    return urllib.error.HTTPError(
        "https://api.steampowered.com/x", code, "err", hdrs, None
    )


# ── _classify: чистая функция, таблица из живого снятия ─────────────────────


def test_classify_ok_is_added() -> None:
    assert wishlist_api._classify(200, "1") == "added"


def test_classify_fail_is_refused() -> None:
    assert wishlist_api._classify(200, "2") == "refused"


def test_classify_invalid_param_is_refused() -> None:
    assert wishlist_api._classify(200, "8") == "refused"


def test_classify_rate_limit_by_eresult_header() -> None:
    assert wishlist_api._classify(200, "84") == "rate_limit"


def test_classify_rate_limit_by_bare_http_429() -> None:
    assert wishlist_api._classify(429, None) == "rate_limit"


def test_classify_auth_fail_by_http_401() -> None:
    assert wishlist_api._classify(401, None) == "auth_fail"


# ── _call: реальный HTTP-слой (замокан) ──────────────────────────────────────


def test_call_success_returns_status_eresult_and_body(monkeypatch) -> None:
    monkeypatch.setattr(
        wishlist_api.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(
            200, "1", {"response": {"wishlist_count": 5}}
        ),
    )
    status, eresult, body = wishlist_api._call("AddToWishlist", 730, "tok")
    assert status == 200
    assert eresult == "1"
    assert body == {"response": {"wishlist_count": 5}}


def test_call_http_error_returns_status_and_eresult(monkeypatch) -> None:
    def fake_urlopen(req, timeout=15):
        raise _http_error(429, "84")

    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    status, eresult, body = wishlist_api._call("AddToWishlist", 730, "tok")
    assert status == 429
    assert eresult == "84"
    assert body == {}


def test_call_http_error_without_eresult_header(monkeypatch) -> None:
    def fake_urlopen(req, timeout=15):
        raise _http_error(401)

    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    status, eresult, body = wishlist_api._call("AddToWishlist", 730, "tok")
    assert status == 401
    assert eresult is None


# ── _call: ретрай на транзиентный сетевой сбой (SSL-обрыв, не HTTP-ответ) ───
# Живая находка 2026-07-19 (10k-прогон): единичные SSL-таймауты/EOF на
# AddToWishlist уходили прямиком в error.txt без единой попытки повтора —
# в отличие от app/steam/steam_api._api_get, у _call ретрая не было вовсе.


def test_call_retries_transient_network_error_then_succeeds(
    monkeypatch,
) -> None:
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("EOF occurred in violation of protocol")
        return _FakeResp(200, "1", {"response": {"wishlist_count": 5}})

    sleeps: list[float] = []
    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    status, eresult, body = wishlist_api._call("AddToWishlist", 730, "tok")

    assert status == 200
    assert eresult == "1"
    assert calls["n"] == 2
    assert sleeps == [wishlist_api._NETWORK_RETRY_DELAY]


def test_call_retries_on_remote_disconnected_then_succeeds(
    monkeypatch,
) -> None:
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError("reset")
        return _FakeResp(200, "1", {"response": {}})

    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    status, eresult, _body = wishlist_api._call("AddToWishlist", 730, "tok")
    assert status == 200
    assert calls["n"] == 2


def test_call_network_error_bounded_retry_then_raises(monkeypatch) -> None:
    """Постоянный сетевой сбой — ограниченный ретрай, затем пробрасывается
    (add_pending ловит его как error для этого appid, как и раньше)."""
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        calls["n"] += 1
        raise urllib.error.URLError("connection reset")

    sleeps: list[float] = []
    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    with pytest.raises(urllib.error.URLError):
        wishlist_api._call("AddToWishlist", 730, "tok")

    assert calls["n"] == wishlist_api._NETWORK_RETRY_ATTEMPTS
    assert len(sleeps) == wishlist_api._NETWORK_RETRY_ATTEMPTS - 1


def test_call_posts_appid_and_access_token_in_url(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return _FakeResp(200, "1", {"response": {}})

    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    wishlist_api._call("AddToWishlist", 1600020, "the.jwt.token")
    assert "access_token=the.jwt.token" in captured["url"]
    assert "IWishlistService/AddToWishlist/v1/" in captured["url"]
    assert captured["data"] == b"appid=1600020"


# ── add_to_wishlist: _classify(_call(...)) ───────────────────────────────────


def test_add_to_wishlist_added(monkeypatch) -> None:
    monkeypatch.setattr(
        wishlist_api,
        "_call",
        lambda *_a: (200, "1", {"response": {"wishlist_count": 1}}),
    )
    assert wishlist_api.add_to_wishlist(730, "tok") == "added"


def test_add_to_wishlist_refused(monkeypatch) -> None:
    monkeypatch.setattr(wishlist_api, "_call", lambda *_a: (200, "2", {}))
    assert wishlist_api.add_to_wishlist(730, "tok") == "refused"


def test_add_to_wishlist_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(wishlist_api, "_call", lambda *_a: (429, None, {}))
    assert wishlist_api.add_to_wishlist(730, "tok") == "rate_limit"


def test_add_to_wishlist_auth_fail(monkeypatch) -> None:
    monkeypatch.setattr(wishlist_api, "_call", lambda *_a: (401, None, {}))
    assert wishlist_api.add_to_wishlist(730, "tok") == "auth_fail"


# ── add_pending: адаптивный backoff + стена (K=5 подряд rate_limit) ─────────


def _sequence(outcomes: list[str]) -> Callable[[int, str], str]:
    """Возвращает фейковый add_to_wishlist, отдающий outcomes по порядку."""
    it = iter(outcomes)

    def _fake(appid: int, access_token: str) -> str:
        return next(it)

    return _fake


def test_add_pending_added_then_refused(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["added", "refused"])
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2], interval=0.5, sleep=sleeps.append
    )
    assert result.added == [1]
    assert result.refused == [2]
    assert sleeps == [0.5, 0.5]


def test_add_pending_rate_limit_then_success_retries_same_appid(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["rate_limit", "added"])
    )
    result = wishlist_api.add_pending(
        "tok", [1], interval=1.0, sleep=sleeps.append
    )
    assert result.added == [1]
    # backoff(streak=1)=60, затем вежливая пауза 1.0 после успеха
    assert sleeps == [60.0, 1.0]


def test_add_pending_hits_wall_after_five_consecutive_rate_limits(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["rate_limit"] * 5)
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2, 3], interval=1.0, sleep=sleeps.append
    )
    assert result.hit_wall is True
    assert result.added == []
    # 4 backoff-ожидания (streak 1..4), на 5-м — стена без ожидания
    assert sleeps == [60.0, 120.0, 240.0, 300.0]


def test_add_pending_streak_resets_after_success_between_appids(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        wishlist_api,
        "add_to_wishlist",
        _sequence(
            ["rate_limit", "rate_limit", "added"]
            + ["rate_limit"] * 4  # appid=2 не наследует streak от appid=1
            + ["added"]
        ),
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2], interval=1.0, sleep=lambda *_a: None
    )
    assert result.added == [1, 2]  # Оба добавились
    assert result.hit_wall is False  # Стена НЕ сработала (4 < 5)


def test_add_pending_auth_fail_stops_immediately(monkeypatch) -> None:
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["auth_fail"])
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2, 3], interval=1.0, sleep=lambda *_a: None
    )
    assert result.auth_fail is True
    assert result.added == []
    assert result.refused == []


def test_add_pending_network_exception_marks_error_and_continues(
    monkeypatch,
) -> None:
    def _fake(appid: int, access_token: str) -> str:
        if appid == 1:
            raise ConnectionResetError("нет связи")
        return "added"

    monkeypatch.setattr(wishlist_api, "add_to_wishlist", _fake)
    result = wishlist_api.add_pending(
        "tok", [1, 2], interval=0, sleep=lambda *_a: None
    )
    assert result.error == [1]
    assert result.added == [2]


# ── add_pending: persist-callback (крэш-safety) ─────────────────────────────
# Живая находка 2026-07-19: orchestrate.add() персистил added/refused/error
# ОДНИМ батчем ПОСЛЕ полного возврата add_pending() — жёсткий килл процесса
# посреди многочасового прогона (harness teardown, не KeyboardInterrupt)
# терял ВСЕ локальные записи added.txt/refused.txt для уже реально
# состоявшихся на стороне Steam добавлений (wishlist_count там не откатывался).
# persist вызывается инкрементально по каждому appid — переживает жёсткий килл.


def test_add_pending_calls_persist_for_added_and_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["added", "refused"])
    )
    calls: list[tuple[int, str]] = []
    wishlist_api.add_pending(
        "tok",
        [1, 2],
        interval=0,
        sleep=lambda *_a: None,
        persist=lambda appid, outcome: calls.append((appid, outcome)),
    )
    assert calls == [(1, "added"), (2, "refused")]


def test_add_pending_calls_persist_for_network_exception(monkeypatch) -> None:
    def _fake(appid: int, access_token: str) -> str:
        if appid == 1:
            raise ConnectionResetError("нет связи")
        return "added"

    monkeypatch.setattr(wishlist_api, "add_to_wishlist", _fake)
    calls: list[tuple[int, str]] = []
    wishlist_api.add_pending(
        "tok",
        [1, 2],
        interval=0,
        sleep=lambda *_a: None,
        persist=lambda appid, outcome: calls.append((appid, outcome)),
    )
    assert calls == [(1, "error"), (2, "added")]


def test_add_pending_without_persist_still_works(monkeypatch) -> None:
    """persist опционален (default None) — обратная совместимость с caller'ами,
    не передающими его (напр. существующие тесты orchestrate.add())."""
    monkeypatch.setattr(wishlist_api, "add_to_wishlist", _sequence(["added"]))
    result = wishlist_api.add_pending(
        "tok", [1], interval=0, sleep=lambda *_a: None
    )
    assert result.added == [1]


def test_add_pending_empty_input_no_calls(monkeypatch) -> None:
    def _boom(appid: int, access_token: str) -> str:
        raise AssertionError("add_to_wishlist не должен вызываться")

    monkeypatch.setattr(wishlist_api, "add_to_wishlist", _boom)
    result = wishlist_api.add_pending("tok", [], interval=1.0)
    assert result == wishlist_api.AddResult()


def test_add_pending_exception_resets_streak(monkeypatch) -> None:
    """Exception на appid должна сбросить streak перед переходом на следующий appid."""
    call_counts: dict[int, int] = {}

    def _fake(appid: int, access_token: str) -> str:
        call_counts[appid] = call_counts.get(appid, 0) + 1
        if appid == 1:
            if call_counts[appid] <= 2:
                return "rate_limit"  # Два rate_limit для appid=1
            else:
                raise ConnectionResetError("сеть сломана")  # Затем исключение
        elif appid == 2:
            # appid=2 получает 4 rate_limit, затем успех
            if call_counts[appid] <= 4:
                return "rate_limit"
            else:
                return "added"
        raise StopIteration()

    monkeypatch.setattr(wishlist_api, "add_to_wishlist", _fake)
    result = wishlist_api.add_pending(
        "tok", [1, 2], interval=1.0, sleep=lambda *_a: None
    )
    # Если streak СБРОШЕН при исключении (правильно):
    #   appid=2 начинает с streak=0, получает 4 rate_limit → streak=[1,2,3,4]
    #   затем added → успех, результат: added=[2], hit_wall=False
    # Если streak НЕ сброшен (баг):
    #   appid=2 наследует streak=2 от appid=1, добавляет 4 → streak=[2,3,4,5]
    #   на 5-м стена срабатывает раньше → hit_wall=True, added=[]
    assert result.error == [1]
    assert result.added == [2]
    assert result.hit_wall is False
