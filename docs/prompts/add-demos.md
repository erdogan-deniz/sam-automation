<!--
Handoff-промпт: фича auto-add Demos (scripts/library/add_demos.py).
Скопируй всё ниже в новый чат и заполни секцию «ЗАДАЧА/СИМПТОМ». Отделена
от add_free.py 2026-09-12 (B-11, TDD) — раньше демо были побочным эффектом
того скрипта (category1=10 внутри общей discovery, include_demos=True).
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Сессия — работа с auto-add
Demos (авто-добавление demo-версий Steam-игр в библиотеку аккаунта через
CM). Только Windows, Python 3.12, venv в `.venv`. Отвечай коротко. Перед
фиксами — корень по доказательствам (systematic-debugging). TDD обязателен
(тест ПЕРЕД кодом, RED→GREEN). Гейты перед каждым коммитом: `ruff check .`,
`ruff format --check .`, `mypy app`, `pytest tests/unit -q` (line-length 80,
target py312; mypy scoped ТОЛЬКО на `app/`, `scripts/` не типизируется).
git-flow: `feature/*` от develop через `merge --no-ff`. Коммиты conventional,
тело на русском, БЕЗ футеров-атрибуций (ни `Co-Authored-By`, ни
«Generated with …») — ни в коммитах, ни в PR-боди.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: фича/баг/вопрос. Если баг — приложи реальный вывод
`python scripts/library/add_demos.py [--add]`, что наблюдаешь vs ожидаешь,
строки из `logs/library/add_demos/`, состояние
`data/games/ids/demos/{candidates,added,refused,error}.txt` ДО/ПОСЛЕ.>>

# ЧТО ДЕЛАЕТ ФУНКЦИЯ
Две фазы. **Discover**: неофициальный store-search API
(`store.steampowered.com/search/results/`) собирает кандидатов из ЕДИНСТВЕННОЙ
категории (Demos `category1=10`, без `maxprice` — демо всегда бесплатны),
минус owned (развёрнутые через `packageinfo.vdf` пакеты живой CM-сессии),
минус уже added/refused → `candidates.txt`. **Add**:
`client.request_free_license` батчами по 20 поверх переиспользуемого
`cm_session()` (та же функция, что и у add_free.py — `app.free_games.licenses`
переиспользуется напрямую, это generic CM-механизм, не free_games-специфика).
Дефолт — dry-run (только discover + отчёт); реальное добавление лицензий
необратимо на аккаунте (штатными средствами Steam не убрать) — только по
`--add`.

> **Не путай с add-free.md**: до 2026-09-12 демо были частью того скрипта
> (`include_demos=True`). Теперь полностью отделены — свой discovery, свой
> `data/games/ids/demos/`, свой CLI. Общее с add_free.py — только пагинация
> store search (`app.steam.store_search`) и выдача лицензий
> (`app.free_games.licenses`), оба переиспользуются напрямую, не дублируются.

# ТОЧКА ВХОДА: scripts/library/add_demos.py
`main()`: `_build_parser().parse_args()` → `setup_logging(category="library/
add_demos")` → `load_config()` → если `cfg.steam_id` непусто:
`resolve_steam_id` (vanity/URL → ID64) ДО `validate` (тот же RA-B-паттерн,
что в scan.py/boost.py/add_free.py) → `validate(cfg)` → guard `--list` vs
`--reset`/`--retry-errors` (варнинг, не ошибка) → применяет
`--reset`/`--retry-errors` к state → `app.demos.run(do_add, list_only,
limit, cfg)`.

`app/demos/orchestrate.py`:
- `discover() -> list[int]` — `discovery.discover_candidates` →
  `with cm_session() as client:` (None при неуспехе логина — WARNING, owned
  НЕ вычитается, discover НЕ падает) → `expand_packages_to_apps(steam_path,
  client.licenses.keys())` → кандидаты минус owned/added/refused →
  `state.save_candidates`.
- `add(*, limit=None) -> licenses.AddResult` (`licenses` = `app.free_games.
  licenses`) — pending = candidates минус added/refused/error (срез по
  `limit`); пустой pending → `AddResult()` без захода в CM; иначе
  `with cm_session() as client:` (None → ВСЕ pending сразу в `error.txt`,
  восстановимо `--retry-errors`) → `licenses.add_licenses(client, pending)`
  → персист батчем ПОСЛЕ полного возврата (тот же паттерн и тот же класс
  риска, что в add_free.py — см. ЗНАЧИМЫЕ ПОВЕДЕНИЯ).
- `run(...)` — `discover()`+`add()` под ОБЩИМ try/except (KeyboardInterrupt→
  interrupted, Exception→error); dry-run (`not do_add`) печатает статус
  `dry_run` с `added=len(candidates)`; иначе `report.report_result(status,
  added=len(result.added), refused, error, hit_cap, cfg)`, обёрнуто в
  `try/except BaseException` (третий Ctrl+C на этапе отчёта не роняет run()).

# CLI-ФЛАГИ
`--add` (реально добавить, иначе dry-run) · `--list` (показать
`candidates.txt` и выйти) · `--reset` (стереть весь state) ·
`--retry-errors` (стереть только `error.txt` — `refused.txt` терминален,
не трогается) · `--limit N` (потолок добавлений за прогон).

# КЛЮЧЕВЫЕ ФАЙЛЫ
- `scripts/library/add_demos.py` — CLI, разбор флагов, resolve→validate,
  wiring в `app.demos.run`.
- `app/demos/discovery.py` — `discover_candidates(*, target_count=3000,
  page_size=100, max_pages=200) -> list[int]`. Единственный источник —
  `app.steam.store_search.collect_category(category1=10, maxprice_free=False,
  ...)`. Пагинация/ретрай на 429/сеть — ОБЩИЙ с `app/free_games/discovery.py`
  модуль `app.steam.store_search` (вынесен 2026-09-12) — сетевой баг чинится
  в одном месте для обоих скриптов, не дублируется.
- `app/free_games/licenses.py` (ПЕРЕИСПОЛЬЗУЕТСЯ, не свой модуль) —
  `add_licenses(client, appids, *, batch_size=BATCH_SIZE=20) -> AddResult`.
  Классификация `EResult`: `LimitExceeded(25)` → `hit_cap=True`, СТЕНА,
  немедленный стоп; `RateLimitExceeded(84)` ИЛИ `granted_appids is None` →
  ретрай через `_TRANSIENT_RETRY_DELAY=30.0`с БЕЗ ограничения попыток; прочее
  → `refused`; исключение → `error`. Подробности констант — `add-free.md`
  (та же реализация, тот же баг-фикс закрывает оба скрипта разом).
- `app/demos/orchestrate.py` — `discover`/`add`/`run` (см. выше).
- `app/demos/state.py` — `load_candidates/save_candidates/load_added_ids/
  load_refused_ids/load_error_ids/mark_added/mark_refused/mark_error/
  clear_error_ids/clear_state`, на примитивах `app.id_file`. Каталог
  `data/games/ids/demos/` — НЕ пересекается с `data/games/ids/free/`.
- `app/demos/report.py` — `report_result(*, status, added, refused, error,
  hit_cap, cfg)`. `hit_cap=True` НИКОГДА не даёт ✅ (тот же инвариант, что
  везде в проекте).
- `app/steam/steam_cm.py::cm_session()` — переиспользуется, как в add_free.py.
- `app/steam/packageinfo.py::expand_packages_to_apps` — переиспользуется.

# STATE-ФАЙЛЫ (data/games/ids/demos/)
- `candidates.txt` — обнаруженные кандидаты, вход фазы add.
- `added.txt` — выданные лицензии (`granted_appids`).
- `refused.txt` — CM отказал — ТЕРМИНАЛЬНО, skip-on-resume, `--reset` — ЕДИНСТВЕННЫЙ способ вернуть.
- `error.txt` — транзиентная ошибка (исключение при вызове CM) — восстановимо `--retry-errors`.

# КОНФИГ (config.yaml)
`steam_api_key`/`steam_id` — как везде. Специфичных для фичи ключей в
`Config` НЕТ — пагинация/батчинг/бэкофф захардкожены константами в коде
(общие с add_free.py — см. `app/steam/store_search.py`/
`app/free_games/licenses.py`).

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
- **Необратимость**: добавленную бесплатную лицензию нельзя убрать штатными
  средствами Steam. `--add` — единственное действие, мутирующее аккаунт;
  dry-run — дефолт.
- run-lock НЕ нужен: фича не спавнит `SAM.Game.exe`.
- `discover()` УСТОЙЧИВ к отсутствию Steam/неуспеху CM-логина (просто не
  вычитает owned — WARNING, не сбой); `add()` НЕ устойчив: неуспех логина →
  ВСЕ pending разом в `error.txt` (per-appid `--retry-errors` их вернёт).
- Персист `add()` — БАТЧЕМ после полного возврата `add_licenses()`, НЕ
  инкрементально по appid — ТОТ ЖЕ класс риска, что открытая находка B-1 в
  `docs/backlog.md` для free_games (Ctrl+C/исключение посреди
  многоминутного retry-шторма теряет уже выданные лицензии из `added.txt`).
  Если/когда B-1 будет закрыт (persist-callback в `app.free_games.licenses.
  add_licenses`), `app/demos/orchestrate.py::add()` унаследует фикс
  автоматически — модуль переиспользуется, не дублирован.
- `ground_truth.py::_check_demos` сверяет `added.txt` (demos) с
  `GetOwnedGames` тем же способом, что `_check_free_games` — тот же слепой
  участок B-6 (неоднозначный пустой ответ Steam API) относится и сюда.

# ПРОБЕЛЫ В ТЕСТАХ (если правишь — закрой TDD)
> Построена через TDD 2026-09-12 (34 теста в
> test_demos_{discovery,orchestrate,report,state}.py + 7 в
> test_add_demos_main.py + test_store_search.py для вынесенной пагинации),
> но НИКОГДА не проходила формальный многоосевой аудит после релиза.
- Реальный сетевой путь (store-search HTML-парсинг, CM
  `request_free_license`) не тестируется — ожидаемо, фейки покрывают только
  логику (то же ограничение, что у add_free.py).
- Батчевый (не инкрементальный) персист в `add()` не проверен на «жёсткий
  килл посреди многочасового прогона» — см. B-1 в backlog, тот же риск.
- Живой e2e-прогон (сколько demo реально находится/добавляется на реальном
  аккаунте) НЕ проводился — discovery только юнит-тестирован на фейковом
  HTTP.

# МЕТОД
1. По симптому воспроизведи, сними лог, сверь 4 файла state ДО/ПОСЛЕ.
2. Падающий тест на фейках (client с `.licenses`/`request_free_license` без
   реального CM; HTTP-моки для discovery — см. test_store_search.py для
   образца). RED → фикс → GREEN.
3. 4 гейта. feature от develop, conventional-коммит, merge --no-ff.

# ОГРАНИЧЕНИЯ
- Только Windows; реальный прогон `--add` требует живого Steam-логина
  (CM-сессия) и МУТИРУЕТ аккаунт необратимо — не гоняй `--add` без явного
  запроса пользователя.
- farm/boost/cards нельзя запускать параллельно с этим скриптом ТОЛЬКО если
  что-то из них уже держит run-lock — сам add_demos.py лок не берёт и не
  проверяет (не спавнит SAM).
- Не выдумывай ключи config.yaml для этой фичи — их нет, всё в константах кода.
- Правя `app.steam.store_search` или `app.free_games.licenses` — это ОБЩИЙ
  код с add_free.py, изменения затрагивают оба скрипта. Прогоняй тесты
  ОБОИХ (`test_store_search.py`, `test_free_games_*`, `test_demos_*`).
