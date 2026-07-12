"""Тесты управления сессиями Steam CM (app/auth/credentials.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.auth.credentials as cred


def test_clear_session_removes_jwt_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # После стирания сессии на достоверно-неверном пароле JWT-кэши тоже должны
    # уйти: иначе short-circuit _jwt_web_cookies (игнорирует username)
    # переиспользовал бы старый client-scope токен для другого аккаунта на
    # ре-промпте.
    client_cache = tmp_path / "jwt_refresh_client.json"
    web_cache = tmp_path / "jwt_refresh.json"
    client_cache.write_text("{}", encoding="utf-8")
    web_cache.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        cred, "_JWT_REFRESH_CLIENT_FILE", client_cache, raising=False
    )
    monkeypatch.setattr(cred, "_JWT_REFRESH_FILE", web_cache, raising=False)
    # Нет username-файла → keyring-ветка пропускается (без реального keyring).
    monkeypatch.setattr(cred, "_USERNAME_FILE", tmp_path / "absent.txt")

    cred._clear_session()

    assert not client_cache.exists()
    assert not web_cache.exists()
