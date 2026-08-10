"""Тесты app/cookies/web_refresh.py — обмен steamRememberLogin на новый cookie.

_web_refresh — второй шаг get_web_cookies (после сохранённого токена): обновляет
сессию без перелогина и 2FA. Сеть подменяется фейковым opener'ом, который кладёт
куку в тот же CookieJar, что создаёт продакшен-код.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

import app.cookies.web_refresh as wr

_VALID = "76561198000000000||jwt-token"


class _FakeOpener:
    """Фейк urllib-opener: наполняет реальный CookieJar продакшена."""

    def __init__(
        self,
        processor,
        *,
        cookie_value: str | None = None,
        raises: bool = False,
    ) -> None:
        self._jar = processor.cookiejar
        self._cookie_value = cookie_value
        self._raises = raises
        self.addheaders: list = []

    def open(self, _url, timeout=None):
        if self._raises:
            raise OSError("сеть недоступна")
        if self._cookie_value is not None:
            self._jar.set_cookie(
                wr._make_cookie(
                    "steamcommunity.com", "steamLoginSecure", self._cookie_value
                )
            )
        return None


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    remember: str | None = "remember-token",
    cookie_value: str | None = None,
    raises: bool = False,
) -> list:
    remember_file = tmp_path / "remember.txt"
    if remember is not None:
        remember_file.write_text(remember, encoding="utf-8")
    monkeypatch.setattr(wr, "_REMEMBER_LOGIN_FILE", remember_file)

    saved: list = []
    monkeypatch.setattr(wr, "_save_manual_cookie", lambda v: saved.append(v))
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda proc: _FakeOpener(
            proc, cookie_value=cookie_value, raises=raises
        ),
    )
    return saved


def test_web_refresh_none_when_no_remember_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path, remember=None)
    assert wr._web_refresh() is None


def test_web_refresh_none_when_remember_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path, remember="   \n")
    assert wr._web_refresh() is None


def test_web_refresh_returns_and_saves_new_cookie(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    saved = _setup(monkeypatch, tmp_path, cookie_value=_VALID)
    assert wr._web_refresh() == {"steamLoginSecure": _VALID}
    assert saved == [_VALID]  # обновлённая кука сохранена для след. запусков


def test_web_refresh_none_on_network_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Сетевой сбой — не падение: caller перейдёт к следующему способу входа.
    saved = _setup(monkeypatch, tmp_path, raises=True)
    assert wr._web_refresh() is None
    assert saved == []


def test_web_refresh_ignores_cookie_without_separator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Без '||' это не JWT-кука (Steam вернул что-то иное) — не сохраняем.
    saved = _setup(monkeypatch, tmp_path, cookie_value="мусор-без-разделителя")
    assert wr._web_refresh() is None
    assert saved == []


def test_web_refresh_decodes_url_encoded_separator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # http.cookiejar (в отличие от Playwright) может вернуть steamLoginSecure
    # URL-encoded (%7C%7C вместо ||) — как storage.py::_save_manual_cookie,
    # нужно unquote() ДО проверки "||", иначе шаг 2 fallback-цепочки тихо
    # ВСЕГДА проваливается на таком Steam-ответе.
    encoded = "76561198000000000%7C%7Cjwt-token"
    saved = _setup(monkeypatch, tmp_path, cookie_value=encoded)
    assert wr._web_refresh() == {"steamLoginSecure": _VALID}
    assert saved == [_VALID]
