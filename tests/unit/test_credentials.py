"""Тесты управления сессиями Steam CM (app/auth/credentials.py)."""

from __future__ import annotations

from pathlib import Path

import keyring.errors
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


def test_save_session_keyring_failure_leaves_no_orphan_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # _save_session пишет _USERNAME_FILE ДО keyring.set_password. Если keyring
    # бросит (DPAPI/Credential Manager недоступен), username-файл без
    # соответствующего пароля — рассинхрон, вводящий в заблуждение _load_session
    # (найдёт username, но не найдёт пароль). Не должен оставаться.
    username_file = tmp_path / "username.txt"
    monkeypatch.setattr(cred, "_USERNAME_FILE", username_file, raising=False)
    monkeypatch.setattr(cred, "_CRED_DIR", tmp_path, raising=False)
    monkeypatch.setattr(
        keyring,
        "set_password",
        lambda *_a: (_ for _ in ()).throw(
            keyring.errors.PasswordSetError("недоступен")
        ),
    )

    with pytest.raises(keyring.errors.PasswordSetError):
        cred._save_session("u", "p")

    assert not username_file.exists()


def test_save_session_keyboard_interrupt_leaves_no_orphan_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Тот же контракт должен держаться и на BaseException (Ctrl+C), не только
    # на Exception — иначе регрессия на "except Exception" тихо это сломает.
    username_file = tmp_path / "username.txt"
    monkeypatch.setattr(cred, "_USERNAME_FILE", username_file, raising=False)
    monkeypatch.setattr(cred, "_CRED_DIR", tmp_path, raising=False)
    monkeypatch.setattr(
        keyring,
        "set_password",
        lambda *_a: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        cred._save_session("u", "p")

    assert not username_file.exists()


def test_load_session_logs_on_keyring_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Keyring-сбой (KeyringLocked/NoKeyringError/DPAPI) должен ЛОГИРОВАТЬСЯ, а
    # не молча трактоваться как «пароль не сохранён» — иначе non-interactive
    # вызов (steam_cm._cm_login) залогирует ложное «нет сохранённых данных» и
    # пропустит CM-логин, хотя реальная причина — недоступность keyring.
    username_file = tmp_path / "username.txt"
    username_file.write_text("user1", encoding="utf-8")
    monkeypatch.setattr(cred, "_USERNAME_FILE", username_file, raising=False)
    monkeypatch.setattr(
        cred, "_LEGACY_SESSION_FILE", tmp_path / "absent.json", raising=False
    )
    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda *_a: (_ for _ in ()).throw(
            keyring.errors.KeyringLocked("locked")
        ),
    )

    with caplog.at_level("WARNING"):
        result = cred._load_session()

    assert result is None
    assert any("keyring" in r.message.lower() for r in caplog.records)


def test_clear_session_survives_non_password_delete_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # except keyring.errors.PasswordDeleteError ловит только один подкласс
    # KeyringError. KeyringLocked/NoKeyringError/InitError — сиблинги, не
    # подклассы PasswordDeleteError — раньше пролетали НЕПОЙМАННЫМИ, роняя
    # _clear_session до удаления username-файла/JWT-кэшей.
    username_file = tmp_path / "username.txt"
    username_file.write_text("u", encoding="utf-8")
    monkeypatch.setattr(cred, "_USERNAME_FILE", username_file, raising=False)
    monkeypatch.setattr(
        cred, "_JWT_REFRESH_CLIENT_FILE", tmp_path / "absent1", raising=False
    )
    monkeypatch.setattr(
        cred, "_JWT_REFRESH_FILE", tmp_path / "absent2", raising=False
    )
    monkeypatch.setattr(
        keyring,
        "delete_password",
        lambda *_a: (_ for _ in ()).throw(
            keyring.errors.KeyringLocked("locked")
        ),
    )

    cred._clear_session()  # не должно бросить

    assert not username_file.exists()
