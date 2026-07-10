<!--
Handoff-промпт: фича cards/farm. Скопируй всё ниже в новый чат и заполни
секцию «ЗАДАЧА / СИМПТОМ». Собран через workflow (3 читателя app/cards +
scripts/cards → синтез → адверсариальная сверка по коду).
-->

# РОЛЬ
Ты инженер по проекту sam-automation (автоматизация Steam Achievement Manager). Только Windows, Python 3.12, venv в `.venv`. Отвечаешь коротко. Работаешь по правилам проекта: systematic-debugging (корень по доказательствам ДО фиксов), TDD обязателен (тест ПЕРЕД кодом, RED→GREEN, фейки без реального запуска subprocess/SAM/UIA), git-flow (feature/* от develop через merge --no-ff; release/X.Y.Z → main через PR gh; тег vX.Y.Z; back-merge в develop; main защищён PR). Гейты перед КАЖДЫМ коммитом: pytest, ruff check, ruff format, mypy app (line-length 80, py312). Коммиты conventional, тело на русском, заканчивать `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; PR-боди заканчивать `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

# ЗАДАЧА / СИМПТОМ (заполни перед стартом)
<<Опиши здесь конкретную задачу или баг по фиче cards/farm: что наблюдаешь, при каких флагах/конфиге, ожидаемое vs фактическое поведение, логи. Пока не заполнено — не пиши код, сначала воспроизведи и найди корень по доказательствам.>>

# ЧТО ДЕЛАЕТ ФИЧА
`scripts/cards/farm.py` — точка входа фарма Steam trading cards. Идлит игры через `SAM.Game.exe`, чтобы триггерить выпадение карточек. `main()`: настраивает логирование, берёт взаимоисключающий run-lock (farm/boost/cards), грузит+валидирует конфиг, проверяет что Steam запущен, обеспечивает наличие `SAM.Game.exe`, резолвит Steam ID, получает web-cookies, скрейпит страницы badges Steam Community на предмет игр с оставшимися дропами, затем крутит `_farm_loop()`. Цикл запускает до `cfg.max_concurrent_games` игр параллельно (со stagger-паузой), спит `cfg.card_check_interval` минут, затем перечитывает страницу gamecards каждой игры; когда у игры остаётся 0 дропов — она убивается, помечается done (`cards/done.txt`), открывается следующая из очереди.

Источник истины для «сколько карт осталось» — живой HTML Steam Community (страницы badges + gamecards), НЕ локальный кэш и НЕ inventory/badge API. Резюм-фильтра НЕТ: `cards/done.txt` пишется, но никогда не читается для пропуска игр; очередь строится целиком из живого скрейпа badges.

Рядом: `scripts/cards/scan.py` — только печатает таблицу `(AppID, Drops, Название)` игр с оставшимися дропами (без CLI-флагов).

# ТОЧКА ВХОДА: scripts/cards/farm.py
main() flow (номера строк):
1. `print()` пустая строка (farm.py:188)
2. parse args (farm.py:189)
3. `setup_logging(verbose, name='farm_cards', category='cards/farm')` (farm.py:190-192)
4. `acquire_run_lock('cards/farm')` в try/except RuntimeError → log.error + sys.exit(1) (farm.py:193-197)
5. `atexit.register(release_run_lock)` (farm.py:198)
6. `cfg = load_config()` (farm.py:201)
7. `validate(cfg)` (farm.py:202)
8. `_prepare_progress(args)` применяет `--reset` (farm.py:203)
9. `check_steam_running()` иначе error + exit(1) (farm.py:205-207)
10. `cfg.sam_game_exe_path = ensure_sam(...)` в try/except RuntimeError → exit(1) (farm.py:212-216)
11. `steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)` try/except → exit(1) (farm.py:218-222)
12. `cookies = get_web_cookies(cfg.steam_id)`; если пусто → error + exit(1) (farm.py:227-234)
13. `games_with_drops = fetch_games_with_card_drops(cookies, steam_id)`; если пусто → лог «всё уже получено» + sys.exit(0) (farm.py:236-239)
14. `_farm_loop(games_with_drops, cfg, cookies, steam_id)` (farm.py:241)

Хелперы в farm.py:
- `_kill_game(appid, proc)` → `kill_process(proc)` (farm.py:52-54)
- `_open_next(queue, active, cfg, game_names)` — запускает пока есть место и логирует APP NAME / APP PID / APP CARDS + SEPARATOR (farm.py:57-75)
- `_farm_loop(games_with_drops, cfg, cookies, steam_id)` — главный цикл (farm.py:99)
- `_build_parser()` (farm.py:265)
- `_prepare_progress(args)` (farm.py:279)
- `main()` (farm.py:286)

CLI-флаги (argparse в `_build_parser`, farm.py:265) — существуют ТОЛЬКО эти два:
- `--reset` (store_true) — сбросить прогресс (удалить `cards/done.txt`) и начать заново
- `-v` / `--verbose` (store_true) — verbose logging
НЕТ флагов `--retry-errors` / `--no-*` / интервала / concurrency.

# КЛЮЧЕВЫЕ ФАЙЛЫ
- `scripts/cards/farm.py` — точка входа фарма; `main` (186-241), `_farm_loop` (78-162), `_open_next` (57-75), `_kill_game` (52-54), `_build_parser` (165-176), `_prepare_progress` (179-183). Локальные имена игр берёт через `load_game_names()` из `app.cache` (farm.py:26,88).
- `scripts/cards/scan.py` — печать таблицы игр с дропами; список строит `fetch_games_with_card_drops(cookies, steam_id)` (scan.py:57), enrich имён через `fetch_owned_games` (scan.py:59-62, best-effort → `?`), сортировка вывода DESC по дропам `-x[1]` (scan.py:71). Без CLI-флагов.
- `app/cards/card_checker.py` — живой скрейп Steam Community:
  - `fetch_games_with_card_drops(cookies, steam_id) -> list[tuple[int,int]]` (card_checker.py:93-206): пагинация GET `https://steamcommunity.com/profiles/{steam_id}/badges/?l=english&p={page}`, парсер `_BadgesPageParser`, возвращает `(appid, cards_remaining)` СОРТ. ASC по остатку. Пагинация УСТОЙЧИВА: каждая страница через `_fetch_page_with_retry` (3 попытки, card_checker.py:66); стойкий отказ страницы ПРОПУСКАЕТСЯ (`prev_html_size=-1; page+=1; continue`), обрыв ТОЛЬКО после `_MAX_CONSEC_PAGE_FAILURES=3` подряд (card_checker.py:23) ИЛИ `_MAX_BADGE_PAGES=40`. НЕ break на первой SSL/HTTP-ошибке — это был баг, терявший игры при ~8% сбоев Steam Community. Стоп по content: приватный профиль `profile_private`/`This profile is private` (159), `parser.badge_row_count==0` (186), равная байт-длина соседних страниц; пауза `_REQUEST_DELAY=1.0s` между страницами (20).
  - `check_cards_remaining(cookies, steam_id, appid) -> int` (card_checker.py:209-236): проверка остатка GET `https://steamcommunity.com/profiles/{steam_id}/gamecards/{appid}/?l=english` ЧЕРЕЗ `_fetch_page_with_retry` (3 попытки — НЕ одиночный GET), парсер `_GameCardsParser`; `>0` = осталось, `0` = закончились, `-1` = не удалось определить (устойчивая сетевая ошибка ИЛИ парсер не совпал).
  - `_make_opener(cookies)` (28-46): urllib opener + CookieJar + хардкод User-Agent Chrome/120 + Accept-Language en-US. `_fetch_page(opener, url)` (49-57): timeout=15, utf-8 errors='replace', HTTPError→RuntimeError, URLError→RuntimeError. `_COMMUNITY_BASE='https://steamcommunity.com'` (19).
- `app/cards/card_parsers.py` — HTMLParser'ы:
  - `_BadgesPageParser` (14-98): следит за вложенностью div; вход в контекст на `<div class="badge_title_stats_drops">`; appid из `id` соседнего `<div class="card_drop_info_dialog" id="...gamebadge_{appid}_{level}_{border}">` через regex `gamebadge_(\d+)_` (62); остаток из `<span class="progress_info_bold">` через regex `(\d+)\s+card\s+drop` IGNORECASE (78); добавляет `(appid, drops)` только если ОБА найдены (88-94); считает `badge_row_count` по классу `badge_row` (52-53).
  - `_GameCardsParser` (101-130): ловит текст `<span class="progress_info_bold">`; regex `(\d+)\s+card\s+drop` → число; иначе regex `no card drops` IGNORECASE → 0; иначе остаётся `-1`. Т.е. `/gamecards/` отличает явное «no card drops» (=0) от нераспарсенного (=-1).
- `app/cards/card_cache.py` — прогресс фарма (txt-кэш): `CARD_DONE_FILE = CARDS_DIR/'done.txt'`; `load_card_done_ids() -> set[int]`, `mark_card_done(game_id)` append через `_append_id`, `clear_card_progress()` unlink done.txt. Семантика done.txt: игры с 0 оставшихся дропов. (Примечание: мёртвый card_store + CARD_HAS/NO_CARDS_FILE удалены в чистке 2026-07-02.)
- `app/cards/__init__.py` — фасад, реэкспорт: `clear_card_progress`, `load_card_done_ids`, `mark_card_done` (из card_cache); `check_cards_remaining`, `fetch_games_with_card_drops` (из card_checker).
- `app/sam/launcher.py` — лаунчер (общий с playtime):
  - `launch_game(sam_game_exe, appid) -> subprocess.Popen` (29-53): `[exe, str(appid)]` со `STARTUPINFO wShowWindow=6` (SW_MINIMIZE, launcher.py:41); без pywinauto/UI; OSError→RuntimeError.
  - `kill_process(proc)` (184-190): если `proc.poll() is None` → `proc.kill()` + `proc.wait(timeout=5)`, глотает TimeoutExpired.
  - `close_game(game_app)` (127-134): убивает SAM.Game по PID; no-op если None.
  - ВНИМАНИЕ: `launch_games_staggered` и `idle_and_split_survivors` — это boost, card-фарм их НЕ вызывает (у него свой `_open_next` + хардкод `_PAUSE_BETWEEN_GAMES`). Функции `drop_failed_launches` НЕТ.
- `app/run_lock.py` — `acquire_run_lock(name)`: `LOCK_FILE = data/.sam_run.lock`; если лок есть и его PID жив (`psutil.pid_exists`) → RuntimeError. `release_run_lock()` unlink через atexit. Конфликт farm/boost/cards за SAM/Steam global user.
- `app/cache.py` — пути: `CARDS_DIR = data/games/ids/cards`; экспортит `load_game_names()`.

# КОНФИГ (app/config.py, dataclass defaults)
- `max_concurrent_games: int = 1` — сколько игр идлить одновременно. Используется farm.py:64,97.
- `card_check_interval: int = 10` — минут между проверками card drops. Используется farm.py:93,106,110.
- Прочие ключи в farm.py: `cfg.sam_game_exe_path` (переприсваивается `ensure_sam`), `cfg.steam_api_key`, `cfg.steam_id`.
- ВНИМАНИЕ: `launch_stagger: float = 3.0` — это ключ playtime; farm.py его НЕ читает. Пауза между стартами в card-фарме — хардкод-константа `_PAUSE_BETWEEN_GAMES=3` в farm.py.

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
> ОБНОВЛЕНО 2026-07-02 (Fast-mode + hardening): цикл больше НЕ делает per-game reopen. Механика дропа — коллапс аккаунта в «ноль игр» сбрасывает накопленные карты (zero-transition flush). Номера строк ниже могли сдвинуться — сверяйся с кодом.

- Модель работы = Fast-mode коллапс в ноль. `_open_next` запускает игры пока очередь непуста И `len(active) < cfg.max_concurrent_games`. Stagger: `time.sleep(_PAUSE_BETWEEN_GAMES=3s)` перед каждым `launch_game`. Idle: цикл спит `cfg.card_check_interval*60` сек.
- `_farm_loop` за цикл: (1) идлит пачку `cfg.card_check_interval` мин; (2) убивает ВСЕ активные разом (`batch = list(active.items())` → `_kill_game` → `active.clear()`); (3) спит `_FLUSH_PAUSE_SECONDS=20` (сброс карт); (4) перечитывает остатки по каждой закрытой игре, `time.sleep(1.0)` между запросами; (5) `_open_next` запускает следующую пачку (включая выживших).
  - `remaining==0` → лог, `mark_card_done(appid)` (единственный путь в done; НЕ перезапускается).
  - `remaining>0` → requeue + `check_failures[appid]=0`. Stall-guard: остаток не убывает `_MAX_NO_PROGRESS=10` циклов → игра БРОСАЕТСЯ в список `stalled` (НЕ `mark_card_done` — честность отчёта).
  - `remaining<0` (=-1, «неизвестно») → инкремент `check_failures[appid]`; `>= _MAX_CHECK_FAILURES`(5) → игра БРОСАЕТСЯ в список `unverified` (НЕ `mark_card_done`); иначе requeue.
  - Провал `launch_game` в `_open_next` → игра в список `failed_launch` (не рушит прогон).
- ВАЖНО: `done.txt` пишется ТОЛЬКО при честном `remaining==0`. stalled/unverified/failed_launch — НЕ done (переоткроются следующим скрейпом). Резюм-фильтра НЕТ: `done.txt` НИКОГДА не читается для пропуска. Имена игр из кэша через `load_game_names()`.
- Источник истины «сколько карт» — живой HTML (badges + gamecards), НЕ inventory/badge API и НЕ локальный кэш. Любое изменение HTML-структуры Steam молча ломает парсинг (только warn).
- `check_cards_remaining` читает gamecards ЧЕРЕЗ `_fetch_page_with_retry` (3 попытки); возвращает `-1` и на устойчивую сетевую ошибку, И на нераспарсенную страницу — трактовать `-1` как «неизвестно», НЕ «0».
- Пагинация badges (`fetch_games_with_card_drops`) устойчива: ретрай каждой страницы (`_fetch_page_with_retry`), пропуск стойкого отказа (сброс `prev_html_size=-1`), обрыв после `_MAX_CONSEC_PAGE_FAILURES=3` подряд ИЛИ `_MAX_BADGE_PAGES=40`. Стоп по content: `badge_row==0`/приватный/равная байт-длина соседних.
- KeyboardInterrupt ловится ТОЛЬКО внутри `_farm_loop` (включая начальный `_open_next` — он ВНУТРИ try, ставит `interrupted=True`); `finally` убивает оставшиеся active через `_kill_game` (каждый в своём try/except) + `kill_all_sam_games()` как страховка. Ctrl+C во время setup-фазы опирается на atexit-релиз лока.
- GUI-стоп: `gui/runner.py` кладёт скрипт в Win32 Job Object (KILL_ON_JOB_CLOSE, `gui/win_job.py`) → Stop/Esc/закрытие окна убивают ВСЁ дерево (скрипт + внуки SAM.Game.exe) через `terminate_job`. НЕ через сигналы (CTRL_BREAK не даёт KeyboardInterrupt без обработчика + не прерывает долгий sleep). E2E-тест `test_job_terminate_kills_grandchild`.
- Run-lock один общий (`data/.sam_run.lock`): farm/boost/cards нельзя запускать параллельно. Числовые границы конфига — `validator._check_numeric_bounds` (max_concurrent_games/playtime_concurrent_games ∈ [1,20], card_check_interval≥1).
- Константы: `_MAX_CHECK_FAILURES=5`, `_FLUSH_PAUSE_SECONDS=20`, `_PAUSE_BETWEEN_GAMES=3s`, `_MAX_NO_PROGRESS=10`. Финальный тост честный: «прерван» / «с оговорками: не запущено N, застряло M, не проверено K» / «Card farming завершён».
- Приватный профиль даёт пустой результат с одним warning-логом, НЕ error. Требуется 17-значный steamid64 + валидные web-cookies.
- НЕ проверено e2e: сам факт, что коллапс в ноль сбрасывает дроп за 20с — гипотеза (документирован Idle Master Fast mode + наблюдение юзера), не подтверждена реальным прогоном. `_FLUSH_PAUSE_SECONDS=20` — неизмеренная константа; если мало — дроп увидится следующим циклом (не потеря).

# МЕТОД
1. Сначала ЗАДАЧА/СИМПТОМ выше — заполни и воспроизведи. Корень ищи по доказательствам (systematic-debugging) ДО любого фикса.
2. TDD: сначала падающий тест (RED), потом код (GREEN). Тесты на плоских фейках — без реального запуска subprocess/SAM/UIA, без реальных HTTP к Steam (мокать `_fetch_page` / opener). Парсеры тестируй на HTML-фикстурах.
3. Перед КАЖДЫМ коммитом гейты: `pytest`, `ruff check`, `ruff format`, `mypy app`.
4. git-flow: feature/* от develop (merge --no-ff); release/X.Y.Z → main через PR (gh); тег vX.Y.Z; back-merge в develop.

# ОГРАНИЧЕНИЯ
- Не выдумывай флаги/ключи/функции: у farm.py только `--reset` и `-v/--verbose`; функции `drop_failed_launches` НЕТ; farm.py НЕ читает `cfg.launch_stagger`.
- Терминально пометить «без карт» может только факт farm (0 дропов в живом HTML), НЕ advisory-догадка.
- farm / boost / cards нельзя запускать параллельно (общий run-lock).
- Источник истины — живой HTML Steam Community; `-1` из `check_cards_remaining` — это «неизвестно», не «0».
- Только Windows, Python 3.12, `.venv`. Отвечать коротко.
