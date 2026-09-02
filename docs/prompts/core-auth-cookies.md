<!--
Handoff-промпт: инфраструктура Steam-логина (app/auth/ + app/cookies/).
Скопируй всё ниже в новый чат и заполни секцию «ЗАДАЧА/СИМПТОМ». Заведён
2026-08-10 из находок 46-агентного full-project-аудита (см. память
project_full_audit_2026_08_10) — у этих двух подпакетов нет своего скрипта
(в отличие от остальных плейбуков в этой папке), их использует несколько
скриптов, поэтому раньше они не имели ни одной выделенной сессии.
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Сессия — работа с общей
инфраструктурой Steam-логина: `app/auth/` (CM-логин по паролю/TOTP/JWT,
интерактивные промпты, хранение кредов в Windows keyring) и `app/cookies/`
(добыча web-сессионных куки через fallback-цепочку). Только Windows,
Python 3.12, venv в `.venv`. Отвечай коротко. Перед фиксами — корень по
доказательствам (systematic-debugging). TDD обязателен (тест ПЕРЕД кодом,
RED→GREEN). Гейты перед каждым коммитом: `ruff check .`, `ruff format
--check .`, `mypy app`, `pytest tests/unit -q` (line-length 80, target
py312; mypy scoped ТОЛЬКО на `app/`). git-flow: `feature/*` от develop через
`merge --no-ff`. Коммиты conventional, тело на русском, БЕЗ футеров-атрибуций
(ни `Co-Authored-By`, ни «Generated with …») — ни в коммитах, ни в PR-боди.

ВАЖНО (общий файл, не один владелец): эти модули дёргают scan.py, cards/
farm.py, add_free.py, wishlist_add.py — прежде чем чинить, `git log --oneline
-5 -- app/auth/ app/cookies/` и `git status`, чтобы не столкнуться с правкой
из другой параллельной сессии по одному из тех скриптов.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: фича/баг/вопрос. Если баг — из какого скрипта воспроизведён (scan.py
/ add_free.py — через cm_session; cards/farm.py / wishlist_add.py — через
get_web_cookies), реальный лог, что наблюдаешь vs ожидаешь.>>

# ЧТО ДЕЛАЮТ ЭТИ ПОДПАКЕТЫ
Нет своего CLI-скрипта — чистая инфраструктура, вызываемая другими фичами:
- **app/auth/** — Steam CM (client) логин: пароль → (RSA-fallback на ложный
  `InvalidPassword` у аккаунтов на современном Steam auth — см. память
  `project_legacy_cm_login_invalidpassword`) → TOTP/2FA/email-код →
  сохранение сессии/кредов в Windows Credential Manager через `keyring`.
  Потребители: `app/steam/steam_cm.py::cm_session()` (scan.py,
  app/free_games/orchestrate.py → add_free.py).
- **app/cookies/** — добыча `steamLoginSecure`-куки (`{steamid64}||{jwt}`,
  вторая половина — community-JWT) 4-шаговой fallback-цепочкой:
  1. ранее сохранённая ручная кука (`storage.py`);
  2. `_web_refresh` — рефреш через `http.cookiejar` без полного логина;
  3. `_jwt_from_refresh_token` — обмен закэшированного refresh-токена;
  4. `_playwright_login` — полный интерактивный вход через headless-браузер
     (последний резерв, самый медленный).
  Потребители: `app/cookies/__init__.py::get_web_cookies()` →
  scripts/cards/farm.py (`app.steam.get_web_cookies`), app/wishlist/
  orchestrate.py (`add()`, `interactive=False`).

# КЛЮЧЕВЫЕ ФАЙЛЫ
- `app/auth/credentials.py` — `_load_shared_secret` (keyring + SDA maFile
  fallback), `_save_session`/`_load_session` (legacy plaintext-JSON→keyring
  миграция, один раз), `_clear_session`, `_ask_keep_credentials`.
- `app/auth/interactive.py` — `_do_interactive_login(client, username)`:
  ветки TryAnotherCM (транзиент-ретрай) / ServiceUnavailable (да/нет-гейт) /
  InvalidPassword (RSA-ретрай) / AccountLogonDenied+InvalidLoginAuthCode
  (email-код) / AccountLoginDeniedNeedTwoFactor+TwoFactorCodeMismatch
  (авто-TOTP через `_load_shared_secret` либо ручной ввод).
- `app/auth/iauth_service.py`, `jwt.py`, `totp.py`, `_constants.py` —
  IAuthService RPC, JWT refresh-кэш (`_JWT_REFRESH_FILE` — web-scope,
  `_JWT_REFRESH_CLIENT_FILE` — CM/SteamClient-scope, различаются
  `for_steam_client` в `_jwt_web_cookies`/`_rsa_jwt_login`), TOTP-код.
- `app/cookies/__init__.py` — `get_web_cookies(username, *,
  interactive=True)`: сама fallback-цепочка (НЕ чистый фасад — вся логика
  здесь, в отличие от auth/cards/sam).
- `app/cookies/playwright.py` — `_playwright_login`,
  `_try_save_cm_refresh_token` (готовит CM-scoped токен на будущее).
- `app/cookies/storage.py` — `_load_manual_cookie`/`_save_manual_cookie`
  (URL-decode `%7C%7C`→`||` документирован и сделан здесь).
- `app/cookies/web_refresh.py` — `_web_refresh` (шаг 2 цепочки).
- `app/steam/steam_cm.py::cm_session()` — потребитель app/auth (реальный
  `client.login()` + `_do_interactive_login`), `_cm_login` читает
  `_JWT_REFRESH_CLIENT_FILE`.

# НАЙДЕНО АУДИТОМ 2026-08-10 (4 находки, все CONFIRMED адверсариальной
верификацией по коду — полные evidence в памяти project_full_audit_2026_08_10)

1. **[High] Данные — `app/auth/credentials.py:71-86`.** Легаси-миграция
   plaintext-JSON→keyring: `_save_session(u, p)` может кинуть (keyring/DPAPI
   недоступен — реальный транзиентный сценарий на Windows), исключение
   глотается `except Exception: pass`, а СЛЕДУЮЩЕЙ строкой безусловно
   `_LEGACY_SESSION_FILE.unlink(missing_ok=True)` — единственная сохранённая
   копия пароля удаляется, даже если миграция в keyring провалилась.
   Фикс: удалять legacy-файл ТОЛЬКО после подтверждённого успеха
   `_save_session` (например, переместить unlink внутрь `if u and p:` после
   успешного возврата, не в общий fallthrough).
2. **[High] `app/cookies/playwright.py:15` — `_try_save_cm_refresh_token`.**
   Зовёт `_jwt_web_cookies(username, password)` БЕЗ `for_steam_client=True`
   → кэширует в `_JWT_REFRESH_FILE` (web-scope), а `_cm_login`
   (steam_cm.py:268) читает ТОЛЬКО `_JWT_REFRESH_CLIENT_FILE`. Токен,
   который эта функция готовит для CM-логина, физически никогда не
   используется. Фикс: добавить `for_steam_client=True` к вызову.
3. **[Medium] `app/cookies/web_refresh.py:64` — `_web_refresh`.** Не делает
   `unquote()` над `steamLoginSecure` перед проверкой `"||" in c.value` (в
   отличие от `storage.py::_save_manual_cookie`, которая документирует и
   декодирует `%7C%7C`→`||`). Если Steam отдаёт этот cookie
   URL-encoded и через `http.cookiejar` (не только через Playwright) — шаг 2
   fallback-цепочки тихо ВСЕГДА возвращает `None`. Фикс: `unquote(c.value)`
   перед проверкой/возвратом.
4. **[Medium] Пробелы в тестах.** `app/auth/credentials.py`
   (`_load_shared_secret`/`_save_session`/`_load_session`/
   `_ask_keep_credentials` — 0% покрытия, только `_clear_session`
   протестирован); `app/auth/interactive.py` (email-код и
   TOTP-vs-manual-ввод ветки `_do_interactive_login` — 0% покрытия);
   `app/cookies/__init__.py::get_web_cookies` (ни один тест не импортирует
   `app.cookies` напрямую — везде монки-патчится как чёрный ящик).

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
- **Legacy CM InvalidPassword-ловушка** (см. память
  `project_legacy_cm_login_invalidpassword`): `client.login()` отдаёт
  `InvalidPassword` на ВЕРНЫХ кредах для аккаунтов на современном Steam
  auth — это НЕ реально неверный пароль. Фикс — RSA-fallback через
  `_jwt_web_cookies`. Не «чинить» это как настоящую ошибку пароля.
- Два РАЗНЫХ JWT-кэша с разным scope: `_JWT_REFRESH_FILE` (web,
  `for_steam_client=False`) vs `_JWT_REFRESH_CLIENT_FILE` (CM,
  `for_steam_client=True`) — путать их даёт находку №2 выше.
- `get_web_cookies` fallback НЕ откатывается назад: если шаг 2 (web_refresh)
  сломан находкой №3, каждый вызов доходит до шага 4 (playwright,
  самый медленный) вместо быстрого шага 2 — с точки зрения пользователя это
  не сбой, а просто «всегда медленно».
- Креды хранятся в Windows Credential Manager через `keyring` (SECURITY.md);
  единственное исключение — одноразовая миграция legacy plaintext-JSON,
  которую и ломает находка №1.

# ПРОБЕЛЫ В ТЕСТАХ (если правишь — закрой TDD)
См. пункт 4 находок выше — это и есть актуальный список пробелов на
2026-08-10 (сверено живым grep по tests/unit/*.py).

# МЕТОД
1. Определи, из какого потребителя (cm_session vs get_web_cookies)
   воспроизведён симптом — это разные пути кода.
2. Падающий тест на фейках (фейковый `client`/`keyring`/`http.cookiejar` —
   БЕЗ реального Steam-логина, БЕЗ реального браузера). RED → фикс → GREEN.
3. 4 гейта. feature от develop, conventional-коммит, merge --no-ff.

# ОГРАНИЧЕНИЯ
- Только Windows; реальный прогон интерактивного логина требует настоящих
  Steam-кредов + возможно 2FA/email-кода — не гоняй его без явного запроса.
- Общий код для 4 скриптов (scan/add_free через cm_session; cards-farm/
  wishlist_add через get_web_cookies) — перед правкой сверься с их
  плейбуками (`scan.md`, `add-free.md`, `cards-farm.md`, `wishlist-add.md`),
  не regressни то, что там задокументировано как ожидаемое поведение.
- Не путай `_JWT_REFRESH_FILE` (web-scope) и `_JWT_REFRESH_CLIENT_FILE`
  (CM-scope) — это разные файлы с разным назначением, не один и тот же кэш.
