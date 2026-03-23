"""Константы пакета auth — пути хранения и имена сервисов Credential Manager."""

import os
from pathlib import Path

# steam использует protobuf 3.x API; при наличии protobuf 4.x нужен python-режим
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

_CRED_DIR = Path.home() / "AppData" / "Roaming" / "steamctl"
# Хранит только имя пользователя — пароль идёт в Credential Manager
_USERNAME_FILE = _CRED_DIR / "username.txt"
# Старый файл — нужен для однократной миграции из plaintext JSON
_LEGACY_SESSION_FILE = _CRED_DIR / "steam_helper_session.json"
_KEYRING_SERVICE = "sam-automation"
_KEYRING_2FA_SERVICE = "sam-automation-2fa"
# Кэш JWT refresh-токена для повторного получения access_token без 2FA
_JWT_REFRESH_FILE = _CRED_DIR / "jwt_refresh.json"
