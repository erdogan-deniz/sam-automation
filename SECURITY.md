# Security

## Где живут секреты (и куда их НЕ коммитить)

- **Пароль Steam и TOTP `shared_secret`** — в Windows Credential Manager через
  `keyring` (`app/auth/credentials.py`). Никогда в открытом виде на диске.
- **Refresh-токены** (`jwt_refresh*.json`) — в `%APPDATA%/steamctl`, вне репозитория.
- **`config.yaml`** (содержит `steam_api_key`, `steam_id`) — в `.gitignore`,
  **никогда не коммитить**. Трекается только `config.example.yaml`. Не обходить
  через `git add -f`: pre-commit-хук `forbid-config-yaml` блокирует его попадание
  в индекс.
- **`.maFile` / `shared_secret` / `jwt_refresh*.json`** — чувствительные,
  обращаться как с паролями.

## Дисклеймер

Инструмент создан в образовательных целях; использование может нарушать Steam
ToS. На свой риск.

## Сообщить об уязвимости

Открой приватный security-advisory на GitHub или свяжись с мейнтейнером напрямую.
Пожалуйста, не публикуй детали в открытом issue до исправления.
