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


def test_load_session_migration_failure_keeps_legacy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Если _save_session (keyring/DPAPI недоступен) кидает при однократной
    # миграции legacy plaintext-JSON → Credential Manager, legacy-файл с
    # паролем НЕ должен удаляться — иначе единственная сохранённая копия
    # пароля теряется безвозвратно, хотя миграция не удалась.
    legacy = tmp_path / "credentials.json"
    legacy.write_text('{"username": "u", "password": "p"}', encoding="utf-8")
    monkeypatch.setattr(cred, "_LEGACY_SESSION_FILE", legacy, raising=False)
    monkeypatch.setattr(cred, "_USERNAME_FILE", tmp_path / "absent.txt")

    def _boom(username: str, password: str) -> None:
        raise RuntimeError("keyring недоступен")

    monkeypatch.setattr(cred, "_save_session", _boom)

    result = cred._load_session()

    assert result is None
    assert legacy.exists()


def test_load_session_migration_success_removes_legacy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "credentials.json"
    legacy.write_text('{"username": "u", "password": "p"}', encoding="utf-8")
    monkeypatch.setattr(cred, "_LEGACY_SESSION_FILE", legacy, raising=False)
    monkeypatch.setattr(cred, "_USERNAME_FILE", tmp_path / "absent.txt")
    monkeypatch.setattr(cred, "_save_session", lambda u, p: None)

    result = cred._load_session()

    assert result == ("u", "p")
    assert not legacy.exists()


def test_load_session_corrupted_legacy_file_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "credentials.json"
    legacy.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(cred, "_LEGACY_SESSION_FILE", legacy, raising=False)
    monkeypatch.setattr(cred, "_USERNAME_FILE", tmp_path / "absent.txt")

    result = cred._load_session()

    assert result is None
    assert not legacy.exists()
