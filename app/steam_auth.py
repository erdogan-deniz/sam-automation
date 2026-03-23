"""Аутентификация Steam: CM протокол, управление сессиями, TOTP, JWT.

Backward-compat фасад — весь код перенесён в app/auth/.
"""

from app.auth import (  # noqa: F401
    _CRED_DIR,
    _JWT_REFRESH_FILE,
    _KEYRING_2FA_SERVICE,
    _KEYRING_SERVICE,
    _LEGACY_SESSION_FILE,
    _USERNAME_FILE,
    _ask_keep_credentials,
    _clear_credentials,
    _clear_session,
    _cm_login_with_jwt,
    _compute_steam_totp,
    _do_interactive_login,
    _jwt_from_refresh_token,
    _jwt_web_cookies,
    _load_session,
    _load_shared_secret,
    _save_jwt_refresh,
    _save_session,
    _save_shared_secret,
)
