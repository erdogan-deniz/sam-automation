<!--
Handoff-промпт: фича scan (сбор App ID библиотеки → all.txt). Скопируй всё ниже
в новый чат и заполни секцию «ЗАДАЧА/СИМПТОМ». Собран из реального кода
scripts/scan.py + app/steam/ (workflow: читатели → синтез → адверсариальная сверка).
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Сессия — работа со scan.py
(сбор App ID библиотеки Steam → all.txt). Только Windows, Python 3.12, venv в
.venv. Отвечай коротко. Перед фиксами — корень по доказательствам
(systematic-debugging). TDD обязателен (тест ПЕРЕД кодом, RED→GREEN). Гейты
перед каждым коммитом: ruff check ., ruff format --check ., mypy app,
pytest tests/unit -q (line-length 80, target py312; mypy scoped ТОЛЬКО на app/,
scripts/ не типизируется). git-flow: feature/* от develop через merge --no-ff.
Коммиты conventional, тело на русском, заканчивать Co-Authored-By.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: что нужно — фича/баг/вопрос. Если баг — приложи реальный вывод
`python scripts/scan.py`, что наблюдаешь vs ожидаешь, относящиеся строки из
logs/achievements/scan/, и состояние all.txt (сколько ID было/стало).>>

# ЧТО ДЕЛАЕТ СКРИПТ
Собирает App ID всей библиотеки Steam из ТРЁХ источников, объединяет без
дублей и пишет data/games/ids/all.txt (мастер-список, от него отталкиваются
farm/boost/categorize). Источники (порядок = приоритет первого вхождения):
  1. localconfig.vdf — локальная история запусков на этой машине (базовый);
  2. Steam Web API (GetOwnedGames) — купленные + запускавшиеся F2P; ПОБОЧНО
     сохраняет имена игр в names.json;
  3. Steam CM — ВСЕ лицензии аккаунта (требует логин; самый полный).
Каждый источник best-effort: падение оборачивается в warning и даёт [],
скан НЕ прерывается. Флагов CLI НЕТ — просто `python scripts/scan.py`,
конфиг из config.yaml.

# ТОЧКА ВХОДА: scripts/scan.py
- main(): setup_logging(category="achievements/scan") → load_config → validate →
  steam_path = cfg.steam_path or find_steam_path() → читает prev_ids из all.txt
  (ТОЛЬКО для подсчёта «новых», не для слияния) → _merge каждого источника в
  combined (dedup по seen, порядок сохраняется) → если combined пуст: exit(1) →
  all.txt перезаписывается как "\n".join(sorted(combined)).
- _read_vdf_ids(steam_path, steam_id): read_library_app_ids; нет steam_path →
  warning + [].
- _read_api_ids(api_key, steam_id): нет api_key → пропуск; fetch_owned_games →
  save_game_names(names) → список appid.
- _read_cm_ids(steam_path): read_steam_cm_app_ids(steam_path, "",
  interactive=True); ловит KeyboardInterrupt отдельно (отмена пользователем).

# КЛЮЧЕВЫЕ ФАЙЛЫ
- scripts/scan.py — оркестрация трёх источников + запись all.txt.
- app/steam/steam_local.py — read_library_app_ids: парсит
  userdata/<id3>/config/localconfig.vdf, секция Software>Valve>Steam>apps
  (регэксп + ручной баланс скобок). find_steam_path/steamid64_to_id3 — реэкспорт.
- app/steam/steam_registry.py — find_steam_path (реестр Windows), steamid64_to_id3.
- app/steam/steam_api.py — fetch_owned_games (include_appinfo=1,
  include_played_free_games=1); _api_get: сетевое хардненинг (429 rate-limit,
  OSError/HTTPException → RuntimeError, не-JSON 200).
- app/steam/steam_cm.py — read_steam_cm_app_ids: JWT→пароль→2FA→RSA-fallback,
  пре-чек WebAPI, классификация EResult (_cm_login_outcome/_password_failure_action).
- app/steam/packageinfo.py — expand_packages_to_apps (лицензии → App ID).
- app/auth/, app/cookies/ — TOTP/JWT/keyring/куки (детали логина CM).
- app/cache.py — ALL_IDS_FILE (data/games/ids/all.txt), GAME_NAMES_FILE
  (names.json), save_game_names.
- app/id_file.py — read_ids_ordered; численная сортировка/дедуп.
- app/config.py / app/validator.py — конфиг и validate.
- Тесты (tests/unit/): test_steam_local (парс VDF), test_steam_cm (классификация
  логина), test_steam_registry, test_cache_game_names, test_id_file,
  test_game_list, test_network_hardening. ⚠️ ОРКЕСТРАЦИИ scan.main() (слияние
  3 источников / перезапись all.txt) unit-теста НЕТ — пробел в покрытии.

# КОНФИГ (config.yaml)
- steam_id — обязателен (17-значный / vanity / URL).
- steam_api_key — опц.: без него источник API и names.json пропускаются.
- steam_path — опц.: пусто → автоопределение через реестр.
- exclude_ids — в scan НЕ применяется: all.txt пишется целиком; исключение
  срабатывает ниже по потоку в game_list.load_game_ids (у потребителей).

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
- all.txt ПЕРЕЗАПИСЫВАЕТСЯ объединением того, что вернули источники ЭТОТ прогон
  (prev_ids на диске НЕ мержится — только для отчёта «новых»). Риск: если CM/API
  временно недоступны, all.txt может СЖАТЬСЯ до VDF-только. Инвариант проекта
  «потерянная игра переоткроется следующим скрейпом» держится ровно на
  повторных прогонах — учитывай при диагностике «пропавших» игр.
- run-lock НЕ берётся (scan не спавнит SAM.Game.exe) — безопасно параллелить с
  farm/boost по локу. НО scan может интерактивно запросить логин/2FA CM и писать
  в keyring — это отдельный побочный эффект.
- CM legacy-логин: client.login() отдаёт InvalidPassword на ВЕРНЫХ кредах для
  аккаунтов на современном Steam auth. Фикс живой: _password_failure_action →
  try_rsa (_rsa_jwt_login ДО удаления кредов). Транзиентные CM-ошибки
  (TryAnotherCM=48, Timeout, NoConnection…) — сетевые: повтор/пропуск, креды НЕ
  удалять, в интерактив НЕ падать.
- Пре-чек Steam WebAPI ПЕРЕД входом в CM: недоступен → CM пропускается (иначе
  вход виснет уже после запроса пароля/2FA).
- protobuf: os.environ PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python выставляется
  ДО импорта steam — не переносить импорты выше этой строки.
- Логи: logs/achievements/scan/<TIMESTAMP>.log (UTF-8).

# МЕТОД
1. По симптому выбери цель. Если баг — воспроизведи, сними лог, сверь ДО/ПОСЛЕ:
   all.txt (кол-во, diff), какой из 3 источников что вернул (в логе по SEPARATOR-
   блокам), ответ Steam API / состояние CM-логина.
2. Падающий тест на плоских фейках: VDF — на строковом контенте vdf; API/CM —
   мок сети/SteamClient (БЕЗ реального логина). RED → фикс → GREEN. Если правишь
   оркестрацию main() — добавь недостающий тест слияния 3 источников.
3. 4 гейта. feature-ветка от develop, conventional-коммит, merge --no-ff.

# ОГРАНИЧЕНИЯ
- Только Windows; полный прогон CM требует валидного логина Steam (keyring/2FA).
- Не ломать инварианты: all.txt — снимок текущей библиотеки; терминальные
  вердикты (without/error) пишет НЕ scan; exclude_ids применяется у потребителей.
- Сеть ненадёжна — сохраняй best-effort семантику (источник упал → warning + [],
  не abort).
