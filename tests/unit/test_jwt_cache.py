"""Тесты чтения сырого refresh_token из кэша для логона в CM.

CM ClientLogon принимает в поле access_token именно refresh_token (SteamClient-
scope, aud содержит 'client'); короткоживущий access_token (только web/derive)
отвергается с AccessDenied. Деривация через GenerateAccessTokenForApp для
client-scope даёт пустой токен — поэтому берём refresh_token из кэша напрямую.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from steam.enums import EResult  # noqa: E402

from app.auth.jwt import _load_refresh_token, _refresh_token_dead  # noqa: E402


def test_dead_on_explicit_invalidation():
    # Явные сигналы протухания/отзыва → кэш удалять.
    for r in (
        EResult.Expired,
        EResult.AccessDenied,
        EResult.Revoked,
        EResult.InvalidParam,
    ):
        assert _refresh_token_dead(r) is True, r


def test_not_dead_on_transient_none():
    # Нет ответа (таймаут/сеть) — НЕ удалять валидный кэш (подозр. корень #1).
    assert _refresh_token_dead(None) is False


def test_not_dead_on_transient_eresults():
    for r in (EResult.Timeout, EResult.TryAnotherCM, EResult.Fail, EResult.OK):
        assert _refresh_token_dead(r) is False, r


def test_load_refresh_token_reads_raw(tmp_path):
    f = tmp_path / "jwt_refresh_client.json"
    f.write_text(
        json.dumps({"steamid": "76561198190468628", "refresh_token": "RT123"}),
        encoding="utf-8",
    )
    assert _load_refresh_token(f) == "RT123"


def test_load_refresh_token_missing_file(tmp_path):
    assert _load_refresh_token(tmp_path / "nope.json") is None


def test_load_refresh_token_malformed(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not json", encoding="utf-8")
    assert _load_refresh_token(f) is None


def test_load_refresh_token_missing_field(tmp_path):
    f = tmp_path / "partial.json"
    f.write_text(json.dumps({"steamid": "123"}), encoding="utf-8")
    assert _load_refresh_token(f) is None


# ── _cm_login_with_jwt: чистка протухшего client-scope refresh_token ────────

import app.auth.jwt as jwtmod  # noqa: E402


class _FakeCMClient:
    """Двойник CM-клиента: _pre_login OK, wait_msg отдаёт заданный eresult."""

    def __init__(self, eresult_value: int) -> None:
        self._eresult = eresult_value
        self.connected = False
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def sleep(self, _s) -> None:
        pass

    def _pre_login(self):
        return EResult.OK

    def send(self, _msg) -> None:
        pass

    def wait_msg(self, _emsg, timeout=None):
        body = type("_Body", (), {"eresult": self._eresult})()
        return type("_Resp", (), {"body": body})()


def test_cm_jwt_dead_token_unlinks_client_cache(tmp_path, monkeypatch):
    # AccessDenied/Expired/Revoked → протухший client-scope кэш удаляется
    # (иначе вечно-мёртвый CM: тот же битый токен предъявляется каждый раз).
    f = tmp_path / "jwt_refresh_client.json"
    f.write_text(json.dumps({"steamid": "1", "refresh_token": "RT"}), "utf-8")
    monkeypatch.setattr(jwtmod, "_JWT_REFRESH_CLIENT_FILE", f)

    client = _FakeCMClient(int(EResult.AccessDenied))
    result = jwtmod._cm_login_with_jwt(client, "user", "RT", 5)

    assert result == EResult.AccessDenied
    assert not f.exists()


def test_cm_jwt_transient_keeps_client_cache(tmp_path, monkeypatch):
    # Транзиентная ошибка (TryAnotherCM) НЕ трогает валидный кэш.
    f = tmp_path / "jwt_refresh_client.json"
    f.write_text(json.dumps({"steamid": "1", "refresh_token": "RT"}), "utf-8")
    monkeypatch.setattr(jwtmod, "_JWT_REFRESH_CLIENT_FILE", f)

    client = _FakeCMClient(int(EResult.TryAnotherCM))
    result = jwtmod._cm_login_with_jwt(client, "user", "RT", 5)

    assert result == EResult.TryAnotherCM
    assert f.exists()
