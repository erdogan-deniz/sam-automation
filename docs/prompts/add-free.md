<!--
Handoff-промпт: фича auto-add Free Games (scripts/library/add_free.py).
Скопируй всё ниже в новый чат и заполни секцию «ЗАДАЧА/СИМПТОМ». Собран из
реального кода app/free_games/ + scripts/library/add_free.py (прямое чтение,
2026-08-10) — фича никогда не проходила формальный многоосевой аудит
(в отличие от scan.py/boost.py/cards-farm.py), это первый кандидат.
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Сессия — работа с auto-add Free
Games (авто-добавление бесплатных Steam-игр/app в библиотеку аккаунта через
CM). Только Windows, Python 3.12, venv в `.venv`. Отвечай коротко. Перед
фиксами — корень по доказательствам (systematic-debugging). TDD обязателен
(тест ПЕРЕД кодом, RED→GREEN). Гейты перед каждым коммитом: `ruff check .`,
`ruff format --check .`, `mypy app`, `pytest tests/unit -q` (line-length 80,
target py312; mypy scoped ТОЛЬКО на `app/`, `scripts/` не типизируется).
git-flow: `feature/*` от develop через `merge --no-ff`. Коммиты conventional,
тело на русском, заканчивать `Co-Authored-By: Claude Opus 4.8
<noreply@anthropic.com>`.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: фича/баг/вопрос. Если баг — приложи реальный вывод
`python scripts/library/add_free.py [--add]`, что наблюдаешь vs ожидаешь,
строки из `logs/library/add_free/`, состояние
`data/games/ids/free/{candidates,added,refused,error}.txt` ДО/ПОСЛЕ.>>

# ЧТО ДЕЛАЕТ ФУНКЦИЯ
Две фазы. **Discover**: неофициальный store-search API
(`store.steampowered.com/search/results/`) собирает кандидатов из трёх
категорий (F2P-игры `category1=998`+`maxprice=free`, бесплатный софт
`994`+`maxprice=free`, демо `10` — без `maxprice`, всегда бесплатны), минус
owned (развёрнутые через `packageinfo.vdf` пакеты живой CM-сессии), минус
уже added/refused → `candidates.txt`. **Add**: `client.request_free_license`
батчами по 20 поверх переиспользуемого `cm_session()`. Дефолт — dry-run
(только discover + отчёт); реальное добавление лицензий необратимо на
аккаунте (штатными средствами Steam не убрать) — только по `--add`.

# ТОЧКА ВХОДА: scripts/library/add_free.py
`main()`: `_build_parser().parse_args()` → `setup_logging(category="library/
add_free")` → `load_config()` → если `cfg.steam_id` непусто:
`resolve_steam_id` (vanity/URL → ID64) ДО `validate` (тот же RA-B-паттерн,
что в scan.py/boost.py/achievements-farm.py/cards-farm.py — уже сделано
правильно с самого начала, см. add_free.py:88-97) → `validate(cfg)` → guard
`--list` vs `--reset`/`--retry-errors` (варнинг, не ошибка) → применяет
`--reset`/`--retry-errors` к state → `app.free_games.run(do_add, list_only,
limit, include_demos, cfg)`.

`app/free_games/orchestrate.py`:
- `discover(*, include_demos=True) -> list[int]` — `discovery.discover_candidates`
  → `with cm_session() as client:` (None при неуспехе логина — WARNING, owned
  НЕ вычитается, discover НЕ падает) → `expand_packages_to_apps(steam_path,
  client.licenses.keys())` → кандидаты минус owned/added/refused →
  `state.save_candidates`.
- `add(*, limit=None) -> licenses.AddResult` — pending = candidates минус
  added/refused/error (срез по `limit`); пустой pending → `AddResult()` без
  захода в CM; иначе `with cm_session() as client:` (None → ВСЕ pending сразу
  в `error.txt`, НЕ retryable-тихо — восстановимо `--retry-errors`) →
  `licenses.add_licenses(client, pending)` → персист батчем ПОСЛЕ полного
  возврата (НЕ инкрементально по appid, в отличие от `app/wishlist/`
  — см. ПРОБЕЛЫ).
- `run(...)` — `discover()`+`add()` под ОБЩИМ try/except (KeyboardInterrupt→
  interrupted, Exception→error); dry-run (`not do_add`) печатает статус
  `dry_run` с `added=len(candidates)`; иначе `report.report_result(status,
  added=len(result.added), refused, error, hit_cap, cfg)`.

# CLI-ФЛАГИ
`--add` (реально добавить, иначе dry-run) · `--list` (показать
`candidates.txt` и выйти) · `--reset` (стереть весь state) ·
`--retry-errors` (стереть только `error.txt` — `refused.txt` терминален,
не трогается) · `--limit N` (потолок добавлений за прогон) · `--no-demos`
(пропустить демо-подфазу discovery).

# КЛЮЧЕВЫЕ ФАЙЛЫ
- `scripts/library/add_free.py` — CLI, разбор флагов, resolve→validate,
  wiring в `app.free_games.run`.
- `app/free_games/discovery.py` — `discover_candidates(*, include_demos=True,
  target_count=3000, page_size=100, max_pages=200) -> list[int]`. Свой
  ретрай на 429/сеть (`_RETRY_ATTEMPTS=3`, `_RETRY_DELAY=2.0`,
  `_PAGE_DELAY=0.5`) — НЕ через `app.steam.steam_api._api_get` (другой хост
  и форма ответа: `results_html`, не типизированный JSON). Не гарантирует
  полноту каталога (Games+free даёт ~20k по `total_count`) — набирает
  кандидатов с запасом относительно потолка лицензий (~1000-2000).
- `app/free_games/licenses.py` — `add_licenses(client, appids, *,
  batch_size=BATCH_SIZE=20) -> AddResult`. `BATCH_SIZE=20` — живой A/B на
  реальном аккаунте: 50 давало систематический `Timeout` за 10.2с (жёсткий
  `send_job_and_wait`-таймаут библиотеки), 20 — успех за 0.3с (33x запас).
  Классификация `EResult`: `LimitExceeded(25)` → `hit_cap=True`, СТЕНА,
  немедленный стоп остатка батчей; `RateLimitExceeded(84)` ИЛИ
  `granted_appids is None` (напр. `Timeout` — appid потом реально появлялись
  owned) → ретрай ЧЕРЕЗ `_TRANSIENT_RETRY_DELAY=30.0`с БЕЗ ограничения числа
  попыток (наблюдался шторм ~4.5 мин); прочее → `granted_appids` авторитетен,
  appid вне него → `refused`; исключение при вызове → `error` (батч целиком).
- `app/free_games/orchestrate.py` — `discover`/`add`/`run` (см. выше).
- `app/free_games/state.py` — `load_candidates/save_candidates/
  load_added_ids/load_refused_ids/load_error_ids/mark_added/mark_refused/
  mark_error/clear_error_ids/clear_state`, на примитивах `app.id_file`
  (атомарная запись, числовая сортировка). Каталог `data/games/ids/free/`.
- `app/free_games/report.py` — `report_result(*, status, added, refused,
  error, hit_cap, cfg)`. `hit_cap=True` НИКОГДА не даёт ✅ (инвариант
  честного отчёта) — заголовок «упор в стену (потолок лицензий)».
- `app/steam/steam_cm.py::cm_session()` — контекст-менеджер, yield живой
  авторизованный `SteamClient` (`.licenses`) или `None` при неуспехе логина;
  гарантированный disconnect. Переиспользуется `discover`/`add`.
- `app/steam/packageinfo.py::expand_packages_to_apps` — packageids→appids
  через локальный `packageinfo.vdf` (нужен `steam_path`).

# STATE-ФАЙЛЫ (data/games/ids/free/)
- `candidates.txt` — обнаруженные кандидаты, вход фазы add.
- `added.txt` — выданные лицензии (`granted_appids`).
- `refused.txt` — CM отказал — ТЕРМИНАЛЬНО, skip-on-resume, `--reset` — ЕДИНСТВЕННЫЙ способ вернуть.
- `error.txt` — транзиентная ошибка (исключение при вызове CM) — восстановимо `--retry-errors`.

# КОНФИГ (config.yaml)
`steam_api_key`/`steam_id` — как везде (steam_id опционален для этой фичи,
т.к. discovery не читает owned через Web API, а через CM `.licenses`; нужен
только для sanity-check внутри `validate()`). Специфичных для фичи ключей в
`Config` НЕТ — пагинация/батчинг/бэкофф захардкожены константами в
`discovery.py`/`licenses.py`.

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
- **Необратимость**: добавленную бесплатную лицензию нельзя убрать штатными
  средствами Steam. `--add` — единственное действие, мутирующее аккаунт;
  dry-run — дефолт.
- run-lock НЕ нужен: фича не спавнит `SAM.Game.exe` (как `scan.py`).
- `discover()` УСТОЙЧИВ к отсутствию Steam/неуспеху CM-логина (просто не
  вычитает owned — WARNING, не сбой); `add()` НЕ устойчив: неуспех логина →
  ВСЕ pending разом в `error.txt` (per-appid `--retry-errors` их вернёт).
- `run()` оборачивает `discover()+add()` ОДНИМ try/except — Ctrl+C/исключение
  внутри `discover()` (включая сам CM-логин) даёт честный `interrupted`/
  `error`, не сырой трейсбек мимо отчёта.
- Персист `add()` — БАТЧЕМ после полного возврата `add_licenses()`, НЕ
  инкрементально по appid (сравни с `app/wishlist/orchestrate.add()`, где
  инкрементальный персист был добавлен именно из-за живой находки о потере
  прогресса при жёстком килле). **ПОДТВЕРЖДЕНО аудитом 2026-08-10** (было
  теоретическим риском, теперь CONFIRMED статическим анализом — см. находку
  №1 ниже): это реальный, воспроизводимый баг, не гипотеза.
- `BATCH_SIZE=20` и `_TRANSIENT_RETRY_DELAY=30.0` — живые, не гаданные
  константы (см. licenses.py docstring), но снятые на ОДНОМ конкретном
  аккаунте в ОДНОЙ сессии — не исключено, что для другого аккаунта/момента
  граница отказа иная.

# ПРОБЕЛЫ В ТЕСТАХ (если правишь — закрой TDD)
> Проверено 2026-08-10: фича построена через TDD (46 тестов в
> test_free_games_{discovery,licenses,orchestrate,report,state}.py) и
> живьём e2e-верифицирована (3441 кандидат dry-run), но НИКОГДА не проходила
> формальный многоосевой аудит после релиза (в отличие от scan.py/boost.py).
- `scripts/library/add_free.py::main()` — ЦЕЛИКОМ без покрытия: нет
  `test_add_free.py`/`test_add_free_main.py`. Ни разбор флагов, ни порядок
  resolve→validate, ни guard `--list` vs `--reset`/`--retry-errors`, ни
  wiring в `run()` не тестируются напрямую (в отличие от `test_boost_main.py`/
  `test_farm_main.py`/`test_cards_farm_main.py`).
- Батчевый (не инкрементальный) персист в `add()` не проверен на
  «жёсткий килл посреди многочасового прогона» — живой сценарий, который
  ВЫЯВИЛ баг в wishlist (см. ФИЧУ wishlist — если тут есть тот же риск,
  скорее всего есть и тот же баг).
- Реальный сетевой путь (store-search HTML-парсинг, CM `request_free_license`)
  не тестируется — ожидаемо, фейки покрывают только логику.

# НАЙДЕНО АУДИТОМ 2026-08-10 (открытые баги, TDD-фикс)
> Полный проектный аудит (46 агентов), первый формальный проход. Все
> CONFIRMED адверсариальной верификацией по коду. Полные evidence — память
> `project_full_audit_2026_08_10`.

1. **[High] `app/free_games/orchestrate.py:92` — data-loss на interrupt.**
   `result = licenses.add_licenses(client, pending)` персистит в state
   (`mark_added`/`refused`/`error`) только ПОСЛЕ полного возврата.
   `add_licenses` копит `AddResult` в памяти через многоминутные retry-штормы
   (`_TRANSIENT_RETRY_DELAY=30s`, unbounded — наблюдалось ~4.5 мин подряд).
   KeyboardInterrupt/исключение ВО ВРЕМЯ шторма теряет уже выданные Steam
   лицензии из `added.txt` НАСОВСЕМ (appid реально получен, но нигде не
   записан). `cm_session()`'s finally только disconnect'ит клиента, исключение
   не глотает. Фикс: тот же паттерн, что уже в `app/wishlist/wishlist_api.py`
   — прокинуть `persist: Callable[[int, str], None] | None` в
   `add_licenses`/`_request_batch_with_backoff`, звать `state.mark_added/
   refused/error` сразу по каждому решённому appid (или хотя бы по батчу),
   не одним махом в конце.
2. **[Medium] `app/free_games/state.py:37` — `save_candidates` теряет
   приоритет.** Пишет `sorted(set(appids))` (числовой порядок), а
   `discovery.discover_candidates` специально строит порядок
   games→software→demos (демо — в конец, едят потолок лицензий). После
   круглого рейс через save/load приоритет стирается: `--limit N` режет по
   числовому appid, а не по намеренному приоритету — обесценивает саму цель
   упорядочивания. Фикс: сохранять порядок (dict.fromkeys для дедупа вместо
   sorted(set(...))), либо явно задокументировать, что порядок не сохраняется
   (и убрать ложное утверждение из докстринга `load_candidates`).
3. **[Medium] `app/free_games/orchestrate.py:151` — финальный
   `report.report_result(...)` не переживает BaseException.** В отличие от
   `scripts/playtime/boost.py` (полиш v1.14.1: `try: _report_result(...)
   except BaseException: log.exception(...)`), здесь вызов — голый
   top-level statement. Ctrl+C ровно на этапе отчёта (напр. внутри
   `toast()`/`send_telegram()`) даёт сырой трейсбек вместо уже честно
   посчитанного статуса. Фикс: обернуть тем же `try/except BaseException`.

Скрипт использует `cm_session()` (полный интерактивный CM-логин) — 2 High
находки по самому логину (credentials.py данные, playwright.py неверный
файл токена) см. в `docs/prompts/core-auth-cookies.md`.

# МЕТОД
1. По симптому воспроизведи, сними лог, сверь 4 файла state ДО/ПОСЛЕ.
2. Падающий тест на фейках (client с `.licenses`/`request_free_license` без
   реального CM; HTTP-моки для discovery). RED → фикс → GREEN.
3. 4 гейта. feature от develop, conventional-коммит, merge --no-ff.

# ОГРАНИЧЕНИЯ
- Только Windows; реальный прогон `--add` требует живого Steam-логина
  (CM-сессия) и МУТИРУЕТ аккаунт необратимо — не гоняй `--add` без явного
  запроса пользователя.
- farm/boost/cards нельзя запускать параллельно с этим скриптом ТОЛЬКО если
  что-то из них уже держит run-lock — сам add_free.py лок не берёт и не
  проверяет (не спавнит SAM).
- Не выдумывай ключи config.yaml для этой фичи — их нет, всё в константах кода.
