"""Пакет аутентификации Steam: TOTP, credentials, JWT, интерактивный вход.

Субмодули:
  _constants      — пути и имена сервисов
  totp            — Steam Guard TOTP
  credentials     — keyring, shared_secret, управление сессиями
  jwt             — JWT refresh-токен, CM-логин через access_token
  interactive     — интерактивный ввод пароля/2FA
  iauth_service   — IAuthenticationService (BeginAuth, 2FA, Poll)
"""

# re-export всех констант и функций для backward compat (from app.auth import ...)
from ._constants import (
    _CRED_DIR,
    _JWT_REFRESH_FILE,
    _KEYRING_2FA_SERVICE,
    _KEYRING_SERVICE,
    _LEGACY_SESSION_FILE,
    _USERNAME_FILE,
)
from .credentials import (
    _ask_keep_credentials,
    _clear_credentials,
    _clear_session,
    _load_session,
    _load_shared_secret,
    _save_session,
    _save_shared_secret,
)
from .iauth_service import _jwt_web_cookies
from .interactive import _do_interactive_login
from .jwt import _cm_login_with_jwt, _jwt_from_refresh_token, _save_jwt_refresh
from .totp import _compute_steam_totp

__all__ = [
    "_CRED_DIR",
    "_USERNAME_FILE",
    "_LEGACY_SESSION_FILE",
    "_KEYRING_SERVICE",
    "_KEYRING_2FA_SERVICE",
    "_JWT_REFRESH_FILE",
    "_compute_steam_totp",
    "_load_shared_secret",
    "_save_shared_secret",
    "_load_session",
    "_save_session",
    "_clear_session",
    "_clear_credentials",
    "_ask_keep_credentials",
    "_save_jwt_refresh",
    "_jwt_from_refresh_token",
    "_cm_login_with_jwt",
    "_do_interactive_login",
    "_jwt_web_cookies",
]
