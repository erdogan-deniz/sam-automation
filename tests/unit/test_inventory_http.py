"""Тесты app/inventory/http.py: транспорт Steam Community (B-16)."""

from __future__ import annotations

import email.message
import gzip
import json
import urllib.request
from typing import Any

import pytest

from app.inventory import http as inv_http
from app.inventory.market import AuthExpired, RateLimited


def _headers(*set_cookies: str) -> email.message.Message:
    msg = email.message.Message()
    for sc in set_cookies:
        msg["Set-Cookie"] = sc
    return msg


class Script:
    """Подмена отправки: отдаёт заранее заданные ответы по очереди."""

    def __init__(self, *responses: tuple[int, email.message.Message, bytes]):
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(
        self, req: urllib.request.Request
    ) -> tuple[int, email.message.Message, bytes]:
        self.requests.append(req)
        return self.responses.pop(0)


def _ok(
    body: Any, *set_cookies: str
) -> tuple[int, email.message.Message, bytes]:
    return 200, _headers(*set_cookies), json.dumps(body).encode()


def _make(
    script: Script, sleeps: list[float] | None = None
) -> inv_http.SteamHttp:
    rec = sleeps if sleeps is not None else []
    return inv_http.SteamHttp(
        "7656||jwt", send=script, sleep=lambda s: rec.append(s)
    )


def test_get_json_parses_body_and_sends_login_cookie() -> None:
    script = Script(_ok({"a": 1}))
    assert _make(script).get_json("https://x/y") == {"a": 1}
    cookie = script.requests[0].get_header("Cookie")
    assert "steamLoginSecure=7656||jwt" in cookie
    assert script.requests[0].get_header("Accept") == "*/*"


def test_gzip_body_is_decoded() -> None:
    body = gzip.compress(json.dumps({"ok": True}).encode())
    script = Script((200, _headers(), body))
    assert _make(script).get_json("https://x/y") == {"ok": True}


def test_get_json_retries_429_with_backoff() -> None:
    sleeps: list[float] = []
    script = Script(
        (429, _headers(), b"null"),
        (429, _headers(), b"null"),
        _ok({"done": 1}),
    )
    assert _make(script, sleeps).get_json("https://x/y") == {"done": 1}
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_get_json_gives_up_after_budget_with_rate_limited() -> None:
    sleeps: list[float] = []
    script = Script(*[(429, _headers(), b"null")] * 20)
    with pytest.raises(RateLimited):
        _make(script, sleeps).get_json("https://x/y")
    assert len(script.requests) == inv_http.GET_ATTEMPTS


@pytest.mark.parametrize("status", [401, 403])
def test_get_json_auth_error(status) -> None:
    script = Script((status, _headers(), b""))
    with pytest.raises(AuthExpired):
        _make(script).get_json("https://x/y")


def test_get_json_client_error_is_not_retried() -> None:
    script = Script((404, _headers(), b"nope"))
    with pytest.raises(inv_http.HttpError):
        _make(script).get_json("https://x/y")
    assert len(script.requests) == 1


@pytest.mark.parametrize("status", [500, 502, 503])
def test_get_json_retries_server_errors(status) -> None:
    sleeps: list[float] = []
    script = Script((status, _headers(), b"oops"), _ok({"done": 1}))
    assert _make(script, sleeps).get_json("https://x/y") == {"done": 1}
    assert len(sleeps) == 1


def test_get_json_persistent_server_error_gives_http_error() -> None:
    script = Script(*[(500, _headers(), b"oops")] * 20)
    with pytest.raises(inv_http.HttpError) as exc:
        _make(script).get_json("https://x/y?key=SECRET")
    assert len(script.requests) == inv_http.GET_ATTEMPTS
    assert "SECRET" not in str(exc.value)


def test_sessionid_is_taken_from_set_cookie_and_sent_in_post() -> None:
    script = Script(
        _ok(
            {}, "sessionid=abc123def; Path=/; Secure", "steamCountry=RU; Path=/"
        ),
        _ok({"success": True}),
    )
    h = _make(script)
    h.ensure_session("7656")
    status, body = h.post_form("https://x/sell", {"a": "1"}, "https://ref")
    assert (status, body) == (200, {"success": True})
    req = script.requests[1]
    cookie = req.get_header("Cookie")
    assert "sessionid=abc123def" in cookie
    assert "steamLoginSecure=7656||jwt" in cookie
    sent = req.data.decode()  # type: ignore[union-attr]
    assert "sessionid=abc123def" in sent
    assert "a=1" in sent
    assert req.get_header("Referer") == "https://ref"
    assert req.get_header("Origin") == "https://steamcommunity.com"


def test_ensure_session_without_sessionid_cookie_fails() -> None:
    script = Script(_ok({}))
    with pytest.raises(inv_http.HttpError):
        _make(script).ensure_session("7656")


def test_post_form_429_is_returned_not_retried() -> None:
    script = Script(
        _ok({}, "sessionid=abc; Path=/"), (429, _headers(), b"null")
    )
    h = _make(script)
    h.ensure_session("7656")
    assert h.post_form("https://x", {}, "https://r") == (429, None)
    assert len(script.requests) == 2


def test_post_form_network_error_is_status_zero() -> None:
    def boom(req: urllib.request.Request) -> Any:
        if req.data is None:
            return _ok({}, "sessionid=abc; Path=/")
        raise ConnectionResetError("reset")

    h = inv_http.SteamHttp("7656||jwt", send=boom, sleep=lambda s: None)
    h.ensure_session("7656")
    assert h.post_form("https://x", {}, "https://r") == (0, None)


def test_post_form_without_session_refuses() -> None:
    h = _make(Script())
    with pytest.raises(inv_http.HttpError):
        h.post_form("https://x", {}, "https://r")
