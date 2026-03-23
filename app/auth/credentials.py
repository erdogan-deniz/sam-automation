"""Управление сессиями Steam: keyring (DPAPI), shared_secret, SDA maFiles."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import keyring
import keyring.errors

from ._constants import (
    _CRED_DIR,
    _KEYRING_2FA_SERVICE,
    _KEYRING_SERVICE,
    _LEGACY_SESSION_FILE,
    _USERNAME_FILE,
)

log = logging.getLogger("sam_automation")


def _load_shared_secret(username: str) -> str | None:
    """Загружает Steam Guard shared_secret из keyring или SDA maFile."""
    # 1. Keyring (Windows Credential Manager — DPAPI-шифрование)
    try:
        secret = keyring.get_password(_KEYRING_2FA_SERVICE, username)
        if secret:
            return secret
    except Exception:
        pass

    # 2. SteamDesktopAuthenticator maFiles (если SDA установлен)
    sda_dir = (
        Path.home()
        / "AppData"
        / "Roaming"
        / "SteamDesktopAuthenticator"
        / "maFiles"
    )
    if sda_dir.exists():
        for maf in sda_dir.glob("*.maFile"):
            try:
                data = json.loads(maf.read_text(encoding="utf-8"))
                if data.get("account_name", "").lower() != username.lower():
                    continue
                secret = data.get("shared_secret", "")
                if secret:
                    log.info("Найден SDA maFile: %s", maf.name)
                    return secret
            except Exception:
                pass

    return None


def _save_shared_secret(username: str, secret: str) -> None:
    """Сохраняет shared_secret в Windows Credential Manager."""
    keyring.set_password(_KEYRING_2FA_SERVICE, username, secret)
    log.info("shared_secret сохранён в Credential Manager")


def _save_session(username: str, password: str) -> None:
    """Сохраняет username на диск, пароль — в Windows Credential Manager."""
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _USERNAME_FILE.write_text(username, encoding="utf-8")
    keyring.set_password(_KEYRING_SERVICE, username, password)


def _load_session() -> tuple[str, str] | None:
    """Загружает сохранённые данные входа. Возвращает (username, password) или None.

    При наличии старого JSON-файла автоматически мигрирует в Credential Manager.
    """
    # Однократная миграция: старый plaintext JSON → keyring
    if _LEGACY_SESSION_FILE.exists():
        try:
            data = json.loads(_LEGACY_SESSION_FILE.read_text(encoding="utf-8"))
            u = data.get("username", "")
            p = data.get("password", "")
            if u and p:
                _save_session(u, p)
                _LEGACY_SESSION_FILE.unlink()
                log.info(
                    "Steam CM: учётные данные перенесены в Credential Manager"
                )
                return u, p
        except Exception:
            pass
        _LEGACY_SESSION_FILE.unlink(missing_ok=True)

    if not _USERNAME_FILE.exists():
        return None
    username = _USERNAME_FILE.read_text(encoding="utf-8").strip()
    if not username:
        return None
    try:
        password = keyring.get_password(_KEYRING_SERVICE, username)
    except Exception:
        return None
    return (username, password) if password else None


def _clear_session() -> None:
    """Удаляет пароль из Credential Manager и username-файл. Sentry сохраняется."""
    if _USERNAME_FILE.exists():
        username = _USERNAME_FILE.read_text(encoding="utf-8").strip()
        if username:
            try:
                keyring.delete_password(_KEYRING_SERVICE, username)
            except keyring.errors.PasswordDeleteError:
                pass
        _USERNAME_FILE.unlink()
        log.info("Steam CM: учётные данные удалены из Credential Manager")


def _clear_credentials() -> None:
    """Удаляет все данные Steam CM (сессия + sentry)."""
    import shutil

    _clear_session()
    if _CRED_DIR.exists():
        shutil.rmtree(_CRED_DIR, ignore_errors=True)
        log.info("Steam CM: все данные удалены (%s)", _CRED_DIR)


def _ask_keep_credentials() -> bool:
    """Спрашивает пользователя, сохранить ли данные для следующих запусков."""
    print()
    answer = (
        input(
            "[Steam Client Master] Сохранить логин и пароль учётной записи "
            "Steam локально для автоматической авторизации? [YES/NO]: "
        )
        .strip()
        .lower()
    )
    return answer in ("y", "yes", "д", "да")
