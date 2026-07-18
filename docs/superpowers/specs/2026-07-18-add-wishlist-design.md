# Дизайн: авто-добавление каталога Steam в WISHLIST (v1)

- **Дата:** 2026-07-18
- **Статус:** согласован владельцем, готов к writing-plans
- **Ветка:** `feature/add-wishlist` (от `develop`)
- **Сиблинг:** зеркалит `app/free_games/` (см.
  `2026-07-17-add-free-games-design.md`), но добавляет в **вишлист**, не в
  библиотеку. Механизм принципиально другой (web `access_token`, не CM).

## Цель

Запускаемый скрипт сам добавляет позиции каталога Steam в **вишлист** аккаунта.
Вселенная кандидатов = весь `GetAppList` − owned − уже-в-вишлисте. Резюмируемость
и честный отчёт — обязательны (инвариант проекта). Фича по сути **инкрементальная
и многозапусковая**: rate-limit ~50/час делает весь каталог (сотни тысяч)
недостижимым за один прогон — это заложено в дизайн, не баг.

## Зафиксированные решения владельца (2026-07-18 — НЕ переоткрывать)

- **Scope:** абсолютно всё — любой appid, который вишлист примет (игры, DLC,
  софт, саундтреки, видео).
- **Порядок:** последовательно, без приоритизации.
- **Механизм:** только web (`access_token`), CM-сообщения для вишлиста нет.
- **Архитектура:** Approach A — сиблинг-пакет `app/wishlist/`. Минимальное
  дублирование каркаса с (незамёрженным) `feature/add-free-games` принято;
  общий type-agnostic core — поздний рефактор, не сейчас.
- **Дефолт запуска:** dry-run (только счёт кандидатов). Мутация аккаунта —
  только по явному `--add`.
- **owned-вычитание:** v1 — Web API `GetOwnedGames`; CM-вычитание owned-DLC —
  задокументированный будущий шаг (см. «Trade-offs»).
- **run_lock не нужен** — фича не спавнит `SAM.Game.exe` (как `scan.py`).

## Live-verified факты Steam (сняты вживую 2026-07-18 на реальном аккаунте — НЕ передеривать)

Ключевой результат live-probe (браузерный вход + add/remove на реальном
аккаунте, аккаунт возвращён к исходным 24 253 позициям):

### Write-путь — МОДЕРН, не legacy (РАЗВОРОТ рекомендации брифа)

- **Активный эндпоинт:**
  `POST https://api.steampowered.com/IWishlistService/AddToWishlist/v1/?access_token=<JWT>`
  форма `appid=<id>` (`application/x-www-form-urlencoded`).
- **`access_token` = JWT** — часть после `||` из `steamLoginSecure`, которую
  отдаёт `app.cookies.get_web_cookies()`. Токен `aud=["web:community"]` —
  и его **достаточно** (модерн-эндпоинт принимает community-токен).
- **Legacy `store.steampowered.com/api/addtowishlist/` отклонён:** снят вживую —
  store-домен требует `web:store`-aud токен, которого `get_web_cookies()` не
  даёт; community-токен на store даёт `dynamicstore/userdata` с
  `rgOwnedApps:0/rgWishlist:0` (не аутентифицирован) и add → `success:false,
  wishlistCount:0`. **Следствие: sessionid/CSRF/store-cookie НЕ нужны** — их
  обработки в проекте нет и не потребуется.
- **RemoveFromWishlist** (для тестов/отката): симметрично,
  `IWishlistService/RemoveFromWishlist/v1/?access_token=<JWT>` форма `appid`.

### Классификатор ответа — по HTTP-заголовку `x-eresult` (авторитетный сигнал WebAPI)

| HTTP | `x-eresult` | Тело | Значение | State |
|---|---|---|---|---|
| 200 | **1** (OK) | `{"response":{"wishlist_count":N}}` | добавлено | `added.txt` |
| 200 | **2** (Fail) | `{"response":{}}` | owned / уже в вишлисте | `refused.txt` (терминал) |
| 200 | **8** (InvalidParam) | `{"response":{}}` | delisted / несуществующий appid | `refused.txt` (терминал) |
| 429 | — / **84** (RateLimitExceeded) | — | троттл | **backoff** (state не пишем) |
| 401 | — (HTML `Unauthorized`) | — | токен невалиден/истёк | **auth-fail → стоп** |

Классификатор переиспользует `from steam.enums import EResult` (как
`free_games/licenses.py`). Числа `x-eresult` = значения `EResult`
(`OK=1, Fail=2, InvalidParam=8, RateLimitExceeded=84, LimitExceeded=25`).
`LimitExceeded` вишлиста в природе не наблюдался (капа нет — см. ниже), но
обрабатывается защитно как стена.

### Чтение вишлиста (дедуп) — пагинация НЕ нужна

- `GET https://api.steampowered.com/IWishlistService/GetWishlist/v1/?steamid=<id64>`
  — **keyless** (публичный метод; работает при публичном вишлисте). Ответ
  `{"response":{"items":[{appid,priority,date_added},…]}}`.
- Снято вживую: **все 24 253 позиции пришли одним ответом**, без курсора/
  `have_more` — пагинация читателя не требуется. `GetWishlistItemCount/v1` —
  дешёвый размер.
- `steamid64` берётся прямо из cookie: `steamLoginSecure = "{steamid64}||{jwt}"`.

### Вселенная кандидатов — `GetAppList`

- `GET https://api.steampowered.com/IStoreService/GetAppList/v1/` — **key
  обязателен**. По умолчанию отдаёт только `type=Game` → под scope «всё»
  ставим `include_games=1&include_dlc=1&include_software=1&include_videos=1&include_hardware=1`.
- Пагинация: курсор `last_appid` + `have_more_results` (bool), `max_results`
  (дефолт 10000, макс 50000). Ответ `{"response":{"apps":[{appid,name,
  last_modified,price_change_number},…],"have_more_results":bool,"last_appid":int}}`.
  Снято вживую.

### Кап и rate-limit

- **Жёсткого капа вишлиста НЕТ** — на аккаунте уже 24 253 позиции (живое
  доказательство). «250/2000/5000» из фолклора — following/UI-фильтр/сторонний
  инструмент, не add-лимит. `«wishlist full»` per-add ошибки не существует.
- **Реальная стена = rate-limit** ≈ 50 добавлений/час (тот же soft-cap, что
  free-game adds). `429`/`x-eresult=84` = сигнал троттла; при долбёжке 429 →
  IP soft-ban ~6ч, авто-продлевается. **Отсюда backoff-then-stop, НЕ бесконечный
  ретрай** (отличие от free_games — см. ниже).
- Web API rate-limit ключа: ~100k вызовов/день (GetAppList дешёвый: ~200k
  каталог / 50k `max_results` ≈ 4–5 вызовов).

## Архитектура

Полностью на **Web API + cookie**. CM и run_lock не нужны. Каркас (state/report/
orchestrate/CLI) — дословное зеркало `free_games`; отличается только
add-механизм (`wishlist_api.py` вместо `licenses.py`).

```text
app/wishlist/__init__.py       # реэкспорт: run, AddResult
app/wishlist/discovery.py      # вселенная GetAppList(all types) − owned − wishlisted → candidates.txt
app/wishlist/state.py          # data/games/ids/wishlist/ (зеркало free_games/state.py)
app/wishlist/wishlist_api.py   # НОВЫЙ: модерн POST AddToWishlist + x-eresult классиф. + throttle/backoff/wall loop
app/wishlist/report.py         # честный отчёт (строки «Wishlist»)
app/wishlist/orchestrate.py    # discover→add→report; dry-run дефолт; честные статусы
scripts/library/wishlist_add.py# CLI (копия add_free.py), НЕ типизируется mypy
```

## Фаза discover (`discovery.py`)

Пишет `data/games/ids/wishlist/candidates.txt`.

1. **Вселенная:** пагинация `GetAppList/v1` со всеми `include_*` типами по
   курсору `last_appid`/`have_more_results` до конца каталога. 429-backoff
   переиспользует паттерн `app/steam/steam_api.py::_api_get`. Результат
   кэшируется в candidates.txt.
2. **Вычитание wishlisted:** `GetWishlist/v1` (один запрос, keyless) → set
   appid. Авторитетный дедуп — вишлист растёт от наших же adds.
3. **Вычитание owned:** `fetch_owned_games(api_key, steam_id)` (GetOwnedGames) →
   set appid. Кандидаты = `universe − owned − wishlisted − added − refused`.

Устойчивость: падение отдельного источника логируется WARNING, не роняет прогон.
Сбой GetWishlist/owned → дедуп не полный, лишнее отсеется на add как
`x-eresult=2` refused (самозалечивание). Сбой GetAppList (пустая вселенная) →
discover честно сообщает 0 кандидатов.

## Фаза add (`wishlist_api.py`, только по `--add`)

1. `access_token` из `get_web_cookies("", interactive=…)` (JWT-часть).
   Нет валидной сессии → честный стоп (`error`, не ✅).
2. pending = `candidates − added − refused − error` (resume).
   `--limit N` усекает pending.
3. По одному appid (batch-эндпоинта нет):
   `POST AddToWishlist?access_token=… appid=…`. Между add — **самотроттл 72с**
   (`3600/50` → ≤50/час; `--interval` override).
4. Классификация по `x-eresult` (таблица выше):
   - `OK(1)` → `added.txt` (`_append_id`), лог `wishlist_count`.
   - `Fail(2)`/`InvalidParam(8)` → `refused.txt` (терминал).
   - `RateLimitExceeded(84)`/HTTP 429 → backoff (см. ниже), НЕ пишем state,
     повторяем ТОТ ЖЕ appid.
   - HTTP 401 → одна попытка refresh токена (`get_web_cookies` заново); не помог
     → стоп, статус `auth-fail`.
   - Сетевое исключение → `error.txt` (транзиент, `--retry-errors`).

### Backoff-then-stop + детект стены (инвариант честной остановки)

Отличие от `free_games` (тот ретраит RateLimitExceeded **бесконечно** — там
единственная стена это license-cap). Для вишлиста бесконечный ретрай **опасен**:
долбёжка 429 продлевает IP soft-ban. Поэтому:

- 429/`eresult=84` → экспоненциальный backoff **60→120→240→300с (кап)**,
  учитывая `Retry-After` если пришёл. Счётчик подряд идущих rate-limit-ответов
  растёт; успешный add (или иной не-rate-limit исход) его сбрасывает.
- **K=5** подряд rate-limit-ответов (backoff доходит до капа) → **стена**:
  `hit_wall=True`, стоп, оставшийся pending не трогаем. Отчёт «добавлено N,
  дальше стена (rate-limit)» — **не ✅**. Пользователь дорезюмит позже (state
  сохранён). Точные K и тайминги — тюнинг на integration-прогоне; инвариант:
  **не долбить 429 бесконечно**.

## Resume-состояние (`data/games/ids/wishlist/`, `.gitignore`)

| Файл | Смысл | На resume |
|---|---|---|
| `candidates.txt` | universe − owned − wishlisted − added − refused | вход фазы add |
| `added.txt` | успешно добавленные (`x-eresult=1`) | skip |
| `refused.txt` | терминал (`x-eresult=2/8`) | skip |
| `error.txt` | транзиент (сеть) | skip, восстановим `--retry-errors` |

Все записи — через `app.id_file` (`_atomic_write_text`/`_append_id`: атомарно,
числ-сорт, strict-read guard). id-файлы хранят только int; причины — в лог.

## Честный отчёт (`report.py`)

`toast()` + `send_telegram()`. Матрица (зеркало free_games, строки «Wishlist»):

| status | Условие | Тост |
|---|---|---|
| `dry_run` | нет `--add` | ✅ «dry-run: найдено N кандидатов» |
| `ok` | чисто, refused=0 | ✅ «готово: добавлено N» |
| `hit_wall` | упор в rate-limit | ⚠️ «стена (rate-limit): добавлено N, дальше стена» |
| `interrupted` | Ctrl+C | ⚠️ «прервано» |
| `error` | auth-fail / исключение | ⚠️ «прервано ошибкой» |
| refused>0 | иначе | ⚠️ «готово с оговорками: добавлено N, отказано M» |

Rate-limit / auth-fail / Ctrl+C **никогда** не дают success-тост.

## CLI (`scripts/library/wishlist_add.py`, копия add_free.py)

| Флаг | Действие |
|---|---|
| *(без флагов)* | dry-run: discover + «найдено N кандидатов», НЕ добавляет |
| `--add` | реально добавлять в вишлист |
| `--list` | показать `candidates.txt` и выйти |
| `--reset` | сбросить state (candidates/added/refused/error) |
| `--retry-errors` | повторить `error.txt` (НЕ `refused` — терминален) |
| `--limit N` | потолок числа добавлений за прогон |
| `--interval SEC` | override самотроттла (дефолт 72с; для тюнинга/теста) |

Bootstrap как add_free.py: `sys.path`, `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`,
`setup_logging`, `load_config`, `resolve_steam_id` ДО `validate`, гварды флагов
(`--list` + `--reset/--retry-errors` → warning), вызов `run()`.

## Тестирование (TDD, только `tests/unit`, моки HTTP/cookies)

- `test_wishlist_api.py` — классификатор по `x-eresult` (фейковый HTTP-слой):
  `1→added`, `2/8→refused`, `429/84→backoff+повтор того же appid`,
  `401→auth-fail-stop`, сетевое искл.→error; backoff-then-wall (K подряд →
  `hit_wall`); самотроттл вызывается (мок `time.sleep`); `--limit`.
- `test_wishlist_discovery.py` — моки GetAppList(пагинация курсором)/GetWishlist/
  GetOwnedGames; дедуп `universe − owned − wishlisted`; устойчивость к сбою
  источника.
- `test_wishlist_state.py` — load/save/mark/clear, свой каталог, атомарность
  (переиспользует id_file).
- `test_wishlist_report.py` — honest-матрица (hit_wall/interrupted/error/
  refused>0 ≠ ✅).
- `test_wishlist_orchestrate.py` — dry-run vs add, проброс статусов, Ctrl+C/
  исключение в discover→`interrupted`/`error`.

Гейты перед каждым коммитом (как CI): `ruff check .`, `ruff format --check .`,
`mypy app`, `pytest tests/unit -q`.

Интеграция (реальный `--add` на живом аккаунте) — вне CI, ручной прогон
владельцем: подтверждает throttle-cadence и точный rate-limit-порог. Write-путь
и классификатор уже сняты вживую (см. «Live-verified факты»).

## Trade-offs / будущее

- **owned-DLC слепая зона (v1):** `GetOwnedGames` видит только игры (+played
  free), СЛЕП к owned DLC/софту/Family-Share. Те уйдут в `refused` по 1
  троттл-слоту (терминал, не повторяется, самозалечивается). Если на практике
  сгорит заметно слотов — добавить CM-вычитание (`cm_session` +
  `expand_packages_to_apps`, как free_games) отдельным шагом. **Согласовано
  владельцем: WebAPI сейчас, CM позже.**
- **Общий type-agnostic core** с `free_games` — поздний рефактор, не сейчас
  (LOCKED).
- **Games-first порядок** — допустим позже; дефолт последовательный (LOCKED).

## Не-цели v1 (YAGNI)

- Legacy store `addtowishlist` / модерн-фолбэк-переключатель (снят: модерн
  работает community-токеном — один путь).
- Приоритизация/сортировка кандидатов.
- Гарантия 100% полноты каталога за прогон (rate-limit → инкрементально;
  честно сообщаем в отчёте).
- Приватный чужой вишлист (дедуп только для СВОЕГО публичного — у владельца
  публичный, снято живьём).

## Git-flow

Ветка `feature/add-wishlist` от `develop`, merge `--no-ff`. Conventional
Commits, тело на русском, футер
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. PR создаёт и мержит
агент через `gh`. После — чистка веток локально и на origin.
