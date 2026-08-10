<!--
Handoff-промпт: фича auto-add Wishlist (scripts/library/wishlist_add.py).
Скопируй всё ниже в новый чат и заполни секцию «ЗАДАЧА/СИМПТОМ». Собран из
реального кода app/wishlist/ + scripts/library/wishlist_add.py (прямое
чтение, 2026-08-10) — фича никогда не проходила формальный многоосевой аудит
(в отличие от scan.py/boost.py/cards-farm.py), это кандидат №2 после add-free.
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Сессия — работа с auto-add
Wishlist (авто-добавление каталога Steam в вишлист аккаунта через WebAPI).
Только Windows, Python 3.12, venv в `.venv`. Отвечай коротко. Перед фиксами —
корень по доказательствам (systematic-debugging). TDD обязателен (тест ПЕРЕД
кодом, RED→GREEN). Гейты перед каждым коммитом: `ruff check .`,
`ruff format --check .`, `mypy app`, `pytest tests/unit -q` (line-length 80,
target py312; mypy scoped ТОЛЬКО на `app/`, `scripts/` не типизируется).
git-flow: `feature/*` от develop через `merge --no-ff`. Коммиты conventional,
тело на русском, заканчивать `Co-Authored-By: Claude Opus 4.8
<noreply@anthropic.com>`.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: фича/баг/вопрос. Если баг — приложи реальный вывод
`python scripts/library/wishlist_add.py [--add]`, что наблюдаешь vs
ожидаешь, строки из `logs/library/wishlist_add/`, состояние
`data/games/ids/wishlist/{candidates,added,refused,error}.txt` ДО/ПОСЛЕ.>>

# ЧТО ДЕЛАЕТ ФУНКЦИЯ
Две фазы. **Discover**: вселенная через `IStoreService/GetAppList/v1`
(пагинация по `last_appid`, все типы контента — games/dlc/software/videos/
hardware) минус owned (`GetOwnedGames` Web API) минус уже-в-вишлисте
(`IWishlistService/GetWishlist/v1`, keyless) минус added/refused →
`candidates.txt`. **Add**: по одному appid (batch-эндпоинта у Steam нет)
через `POST IWishlistService/AddToWishlist/v1` с community-JWT. Дефолт —
dry-run (только discover + отчёт); реальное добавление — только по `--add`.

**Write-путь выбран ЖИВОЙ проверкой, вопреки исходному ресёрчу** — держи в
голове при любой правке `wishlist_api.py`: adversarial-research указывал на
легаси `store.steampowered.com/api/addtowishlist` (store-куки), но на
реальном аккаунте он не подошёл (нужен токен с `aud=web:store`, которого
`get_web_cookies` не даёт). Рабочий путь — `IWishlistService/AddToWishlist`
с community-JWT (см. `wishlist_api.py:1-18`).

# ТОЧКА ВХОДА: scripts/library/wishlist_add.py
`main()`: `_build_parser().parse_args()` → `setup_logging(category="library/
wishlist_add")` → `load_config()` → если `cfg.steam_id` непусто:
`resolve_steam_id` ДО `validate` (RA-B-паттерн, уже сделано правильно, см.
wishlist_add.py:86-95) → `validate(cfg)` → guard `--list` vs `--reset`/
`--retry-errors` → применяет флаги к state → `app.wishlist.run(do_add=
args.add, list_only=args.list, limit=args.limit, interval=args.interval,
api_key=cfg.steam_api_key, steam_id=cfg.steam_id, cfg=cfg)`.

`app/wishlist/orchestrate.py`:
- `discover(*, api_key, steam_id) -> list[int]` — `discovery.discover_candidates`
  (universe минус owned минус wishlisted, оба через Web API — см. КЛЮЧЕВЫЕ
  ФАЙЛЫ) минус added/refused → `state.save_candidates`.
- `add(*, limit=None, interval=1.0) -> wishlist_api.AddResult` — pending =
  candidates минус added/refused/error (срез по `limit`); пустой pending →
  `AddResult()`; `cookies = get_web_cookies("", interactive=False)` — `None`
  → `AddResult(auth_fail=True)` БЕЗ пометки appid в error (сбой СЕССИИ, не
  appid — пользователь просто перезапустит `--add`, без `--retry-errors`;
  ОТЛИЧИЕ от `free_games`, где CM-login-failure метит ВСЕ pending как error
  — там сессия внутри `cm_session()` per-run, тут сессия хранится между
  запусками). `access_token = cookies["steamLoginSecure"].split("||",1)[1]`
  → `wishlist_api.add_pending(access_token, pending, interval, persist=
  _persist)` — `_persist` пишет `state.mark_added/refused/error`
  ИНКРЕМЕНТАЛЬНО по каждому решённому appid (живая находка: батчевый персист
  терял прогресс при жёстком килле — см. ПРОБЕЛЫ у add-free.md, тот же риск
  там НЕ закрыт). На `auth_fail` — ОДНА попытка обновить токен и повторить
  на remaining, иначе остаётся `auth_fail=True` (remaining НЕ помечен error —
  resume подхватит).
- `run(...)` — `discover()`+`add()` под общим try/except; `result.auth_fail
  and status=="ok"` → `status="error"`; dry-run печатает `dry_run` с
  `added=len(candidates)`; иначе `report.report_result(status, added,
  refused, error, hit_wall=result.hit_wall, cfg)`.

# CLI-ФЛАГИ
`--add` (реально добавить, иначе dry-run) · `--list` (показать
`candidates.txt` и выйти) · `--reset` (стереть весь state) ·
`--retry-errors` (стереть только `error.txt`) · `--limit N` (потолок
добавлений за прогон) · `--interval SEC` (пауза между добавлениями, дефолт
1.0; 0 = максимальная скорость).

# КЛЮЧЕВЫЕ ФАЙЛЫ
- `scripts/library/wishlist_add.py` — CLI, разбор флагов, resolve→validate,
  wiring в `app.wishlist.run`.
- `app/wishlist/discovery.py` — `discover_universe(api_key, *, max_pages=200)
  -> list[int]`: пагинация `IStoreService/GetAppList/v1` (`_MAX_RESULTS=
  50000`/страница, все `include_*` флаги включены) через `last_appid`-курсор
  до `have_more_results=False` или пустой страницы. `fetch_wishlist_ids(
  steam_id) -> set[int]`: `IWishlistService/GetWishlist/v1` (keyless), снято
  вживую на 24 253 позициях ОДНИМ ответом — пагинация читателю НЕ нужна.
  `discover_candidates(*, api_key, steam_id) -> list[int]`: universe минус
  owned (`fetch_owned_games`) минус wishlisted; ОБА сбоя owned/wishlisted
  ПРОГЛАТЫВАЮТСЯ (WARNING, не вычитается — самоисцеление: лишнее появление
  отсеется как refused при add); сбой САМОГО universe (`GetAppList`) НЕ
  проглатывается — пробрасывается (живая находка: тихий проглот тут стирал
  реальный `candidates.txt` из 211 032 записей пустым списком).
  Использует `app.steam.steam_api._api_get` (тот же хост/JSON-форма, что и
  api.steampowered.com, в отличие от `free_games/discovery.py` на
  store.steampowered.com — там свой ретрай, тут переиспользован чужой).
- `app/wishlist/wishlist_api.py` — `add_to_wishlist(appid, access_token) ->
  Classification`; `_classify(http_status, eresult) -> Literal["added",
  "refused","rate_limit","auth_fail"]` по заголовку `x-eresult` (`1`→added;
  `2`(owned/уже-в-вишлисте) и `8`(delisted) → refused ТЕРМИНАЛЬНО; `84` либо
  голый HTTP 429 → rate_limit; HTTP 401 → auth_fail). `_call` ретраит
  ТРАНСПОРТНЫЙ сбой (SSL-обрыв/таймаут — `_NETWORK_RETRY_ATTEMPTS=2`,
  `_NETWORK_RETRY_DELAY=1.0`), НЕ ретраит валидный HTTP-ответ сервера.
  `add_pending(access_token, appids, *, interval=1.0, sleep=time.sleep,
  persist=None) -> AddResult` — по одному (batch-эндпоинта нет);
  `_BACKOFF_SCHEDULE=(60,120,240,300)` на растущий streak rate_limit,
  `_WALL_STREAK=5` подряд → `hit_wall=True`, стоп; streak сбрасывается ЛЮБЫМ
  иным исходом ИЛИ исключением; `persist` вызывается сразу по решённому
  appid (см. orchestrate `_persist`).
- `app/wishlist/orchestrate.py` — `discover`/`add`/`run` (см. выше).
- `app/wishlist/state.py` — идентично `app/free_games/state.py` по форме,
  свой каталог `data/games/ids/wishlist/`.
- `app/wishlist/report.py` — `report_result(*, status, added, refused,
  error, hit_wall, cfg)`. `hit_wall=True` НИКОГДА не даёт ✅ — заголовок
  «упор в стену (rate-limit)».
- `app/steam/steam_api.py::_api_get`/`fetch_owned_games` — переиспользованы
  discovery.py для GetAppList/GetWishlist/GetOwnedGames.
- `app/cookies/__init__.py::get_web_cookies(username, *, interactive) ->
  dict|None` — даёт `steamLoginSecure` (`"{steamid64}||{jwt}"`); вторая
  половина после `||` — community-JWT, он же `access_token` для
  `IWishlistService`.

# STATE-ФАЙЛЫ (data/games/ids/wishlist/)
- `candidates.txt` — universe минус owned/wishlisted/added/refused.
- `added.txt` — успешно добавлено (x-eresult=1).
- `refused.txt` — терминально (owned/уже-в-вишлисте/delisted) — только `--reset` вернёт.
- `error.txt` — транзиентная сетевая ошибка — восстановимо `--retry-errors`.

# КОНФИГ (config.yaml)
`steam_api_key` (нужен для `GetAppList`/`GetOwnedGames`), `steam_id`.
Специфичных для фичи ключей в `Config` НЕТ — пагинация/backoff/интервал
захардкожены константами (`interval` пробрасывается флагом `--interval`,
не из config.yaml).

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
- run-lock НЕ нужен: не спавнит `SAM.Game.exe`.
- **Auth-fail ≠ appid-error**: сбой веб-сессии не хоронит pending в
  `error.txt` (в отличие от free_games) — architected так специально
  (сессия хранится между запусками, не per-run как CM). Если рефакторишь
  `add()` — не regressни это различие.
- Персист УЖЕ инкрементальный (в отличие от `add_free.py`) — живая находка
  2026-07-19: жёсткий килл посреди 10k-прогона терял прогресс при батчевом
  персисте, исправлено callback'ом `persist` в `add_pending`.
- `_WALL_STREAK=5`/`_BACKOFF_SCHEDULE` — живые константы (снято на реальном
  аккаунте: ~2 добавления/сек без единого троттла на 40 подряд), но
  устойчивый предел за ТЫСЯЧИ adds намеренно НЕ измерялся (IP soft-ban ~6ч
  продлевается при долбёжке) — governor адаптивный, не хардкод-троттл.
  Не меняй магические числа без нового живого замера.
- Классификатор читает `x-eresult` — числа совпадают с `steam.enums.EResult`,
  но enum-класс НЕ импортируется намеренно (другой транспорт — HTTP-заголовок
  WebAPI, не CM-протокол; `steam`-пакет тяжёлый, тянуть его сюда не
  оправдано). Не «исправляй» это на импорт enum без веской причины.

# ПРОБЕЛЫ В ТЕСТАХ (если правишь — закрой TDD)
> Проверено 2026-08-10: фича построена через TDD (75 тестов в
> test_wishlist_{api,discovery,orchestrate,report,state}.py) и живьём
> e2e-верифицирована (234 955 кандидатов dry-run, 24 281 добавлено за
> несколько прогонов), но НИКОГДА не проходила формальный многоосевой аудит
> после релиза (в отличие от scan.py/boost.py).
- `scripts/library/wishlist_add.py::main()` — ЦЕЛИКОМ без покрытия: нет
  `test_wishlist_add.py`/`test_wishlist_add_main.py`. Разбор флагов
  (включая `--interval`), порядок resolve→validate, guard `--list` vs
  `--reset`/`--retry-errors`, wiring в `run()` не тестируются напрямую (в
  отличие от `test_boost_main.py`/`test_farm_main.py`/
  `test_cards_farm_main.py`).
- Реальный сетевой путь (`IWishlistService`, `GetAppList` пагинация) не
  тестируется — ожидаемо, фейки покрывают только логику классификации/backoff.
- Долгий (многочасовой/многодневный) реальный прогон против устойчивого
  IP soft-ban НЕ воспроизведён — 429-поведение проверено только логически
  (моки), не живым долблением до реального бана.

# МЕТОД
1. По симптому воспроизведи, сними лог, сверь 4 файла state ДО/ПОСЛЕ.
2. Падающий тест на фейках (мок HTTP-ответа с `x-eresult`-заголовком; фейк
   cookies). RED → фикс → GREEN.
3. 4 гейта. feature от develop, conventional-коммит, merge --no-ff.

# ОГРАНИЧЕНИЯ
- Только Windows; реальный прогон `--add` требует действующей веб-сессии
  (`steamLoginSecure`) и МУТИРУЕТ аккаунт — не гоняй `--add` без явного
  запроса пользователя.
- Не выдумывай batch-эндпоинт для Wishlist — его нет, только по одному appid.
- Не путай эту фичу с `add-free.md` (CM-лицензии, необратимо) — здесь другой
  транспорт (Web API, JWT), другой домен риска (rate-limit, не потолок).
