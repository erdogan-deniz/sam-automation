"""Тесты _playwright_login — гарантированное закрытие браузера (без утечки окна).

Fake-playwright: подменяем playwright.sync_api.sync_playwright, чтобы проверить
control-flow _playwright_login без реального Chromium/Steam-входа. Ассертим
реальный контракт продакшена (browser.close вызван), а не внутренности мока.
"""

from __future__ import annotations

import playwright.sync_api as pw_api

from app.cookies import playwright as pw_mod


class _FakePage:
    def __init__(self, *, goto_error: bool):
        self._goto_error = goto_error

    def goto(self, *a, **k):
        if self._goto_error:
            raise RuntimeError("goto упал после launch")


class _FakeCtx:
    def __init__(self, *, goto_error: bool, cookies: list[dict]):
        self._goto_error = goto_error
        self._cookies = cookies

    def new_page(self):
        return _FakePage(goto_error=self._goto_error)

    def cookies(self, _url):
        return self._cookies


class _FakeBrowser:
    def __init__(
        self, *, goto_error: bool, cookies: list[dict], closed: list[int]
    ):
        self._goto_error = goto_error
        self._cookies = cookies
        self._closed = closed

    def new_context(self, **k):
        return _FakeCtx(goto_error=self._goto_error, cookies=self._cookies)

    def close(self):
        self._closed.append(1)


class _FakeChromium:
    def __init__(self, *, goto_error, cookies, closed):
        self._kw = dict(goto_error=goto_error, cookies=cookies, closed=closed)

    def launch(self, **k):
        return _FakeBrowser(**self._kw)


class _FakePW:
    def __init__(self, *, goto_error, cookies, closed):
        self.chromium = _FakeChromium(
            goto_error=goto_error, cookies=cookies, closed=closed
        )


class _FakeCM:
    def __init__(self, **kw):
        self._pw = _FakePW(**kw)

    def __enter__(self):
        return self._pw

    def __exit__(self, *a):
        return False


def _install_fake(monkeypatch, *, goto_error=False, cookies=None, closed=None):
    closed = [] if closed is None else closed
    monkeypatch.setattr(
        pw_api,
        "sync_playwright",
        lambda: _FakeCM(
            goto_error=goto_error, cookies=cookies or [], closed=closed
        ),
    )
    return closed


def test_playwright_login_closes_browser_on_error(monkeypatch):
    # Исключение в goto ПОСЛЕ launch не должно оставить видимое окно Chromium
    # висеть: browser.close() обязан выполниться (finally), не только на выходе
    # из sync_playwright.
    closed = _install_fake(monkeypatch, goto_error=True)
    assert pw_mod._playwright_login() is None
    assert closed  # браузер закрыт несмотря на исключение


def test_playwright_login_returns_cookies_and_closes_on_success(monkeypatch):
    closed = _install_fake(
        monkeypatch,
        cookies=[{"name": "steamLoginSecure", "value": "76561||tok"}],
    )
    monkeypatch.setattr(pw_mod, "_save_manual_cookie", lambda _v: None)
    monkeypatch.setattr(pw_mod, "_save_remember_login", lambda _v: None)
    monkeypatch.setattr(pw_mod, "_try_save_cm_refresh_token", lambda: None)

    result = pw_mod._playwright_login()

    assert result == {"steamLoginSecure": "76561||tok"}
    assert closed  # браузер закрыт на успешном пути


def test_try_save_cm_refresh_token_uses_client_scope(tmp_path, monkeypatch):
    # _cm_login (steam_cm.py) читает ТОЛЬКО _JWT_REFRESH_CLIENT_FILE (CM-scope,
    # for_steam_client=True). Токен, сохранённый без этого флага, попадает в
    # _JWT_REFRESH_FILE (web-scope) и физически никогда не используется —
    # проверяем guard (ориентируется на client-файл) и сам вызов сохранения.
    web_file = tmp_path / "jwt_refresh.json"
    web_file.write_text("{}", encoding="utf-8")  # web-токен уже есть
    client_file = tmp_path / "jwt_refresh_client.json"  # client-токена нет
    monkeypatch.setattr(pw_mod, "_JWT_REFRESH_FILE", web_file, raising=False)
    monkeypatch.setattr(
        pw_mod, "_JWT_REFRESH_CLIENT_FILE", client_file, raising=False
    )
    monkeypatch.setattr(pw_mod, "_load_session", lambda: ("u", "p"))
    monkeypatch.setattr("builtins.input", lambda *_a: "y")
    calls = []
    monkeypatch.setattr(
        pw_mod,
        "_jwt_web_cookies",
        lambda u, p, **kw: calls.append((u, p, kw)),
    )

    pw_mod._try_save_cm_refresh_token()

    assert calls, "guard не должен считать client-токен готовым по web-файлу"
    assert calls[0][2].get("for_steam_client") is True


def test_try_save_cm_refresh_token_skips_if_client_token_exists(
    tmp_path, monkeypatch
):
    client_file = tmp_path / "jwt_refresh_client.json"
    client_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        pw_mod, "_JWT_REFRESH_CLIENT_FILE", client_file, raising=False
    )
    monkeypatch.setattr(
        pw_mod, "_JWT_REFRESH_FILE", tmp_path / "absent.json", raising=False
    )

    def _fail():
        raise AssertionError("не должно вызываться — токен уже готов")

    monkeypatch.setattr(pw_mod, "_load_session", _fail)

    pw_mod._try_save_cm_refresh_token()
