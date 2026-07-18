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
