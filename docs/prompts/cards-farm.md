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
- `_farm_loop(games_with_drops, cfg, cookies, steam_id)` — главный цикл (farm.py:78-162)
- `_build_parser()` (farm.py:165-176)
- `_prepare_progress(args)` (farm.py:179-183)
- `main()` (farm.py:186-241)

CLI-флаги (argparse в `_build_parser`, farm.py:165-176) — существуют ТОЛЬКО эти два:
- `--reset` (store_true) — сбросить прогресс (удалить `cards/done.txt`) и начать заново (farm.py:170-174)
- `-v` / `--verbose` (store_true) — verbose logging (farm.py:175)
НЕТ флагов `--retry-errors` / `--no-*` / интервала / concurrency.

# КЛЮЧЕВЫЕ ФАЙЛЫ
- `scripts/cards/farm.py` — точка входа фарма; `main` (186-241), `_farm_loop` (78-162), `_open_next` (57-75), `_kill_game` (52-54), `_build_parser` (165-176), `_prepare_progress` (179-183). Локальные имена игр берёт через `load_game_names()` из `app.cache` (farm.py:26,88).
- `scripts/cards/scan.py` — печать таблицы игр с дропами; список строит `fetch_games_with_card_drops(cookies, steam_id)` (scan.py:57), enrich имён через `fetch_owned_games` (scan.py:59-62, best-effort → `?`), сортировка вывода DESC по дропам `-x[1]` (scan.py:71). Без CLI-флагов.
- `app/cards/card_checker.py` — живой скрейп Steam Community:
  - `fetch_games_with_card_drops(cookies, steam_id) -> list[tuple[int,int]]` (card_checker.py:65-154): пагинация GET `https://steamcommunity.com/profiles/{steam_id}/badges/?l=english&p={page}`, парсер `_BadgesPageParser`, возвращает `(appid, cards_remaining)` СОРТ. ASC по остатку (line 149); стоп-условия пагинации: HTTP/URL error (break, 90-94), повтор страницы по равной байт-длине html (99-103), приватный профиль `profile_private`/`This profile is private` (107-115), `parser.badge_row_count==0` (134-136); пауза `_REQUEST_DELAY=1.0s` между страницами (147).
  - `check_cards_remaining(cookies, steam_id, appid) -> int` (card_checker.py:157-184): одиночная проверка GET `https://steamcommunity.com/profiles/{steam_id}/gamecards/{appid}/?l=english`, парсер `_GameCardsParser`; `>0` = осталось, `0` = закончились, `-1` = не удалось определить (fetch RuntimeError ИЛИ парсер не совпал).
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
- Модель работы = параллельный батч с reopen-on-interval. `_open_next` запускает игры пока очередь непуста И `len(active) < cfg.max_concurrent_games` (farm.py:64). Stagger: `time.sleep(_PAUSE_BETWEEN_GAMES=3s)` перед каждым `launch_game` (farm.py:49,66-67). Idle: главный цикл спит `cfg.card_check_interval*60` сек (farm.py:110). Reopen: при remaining>0 игра убивается и перезапускается после `_PAUSE_AFTER_KILL=10s` (farm.py:46-48,122-125).
- Пер-проверка в `_farm_loop` (farm.py:112-151), для каждого активного appid, `time.sleep(1.0)` между запросами по играм (farm.py:114):
  - `remaining==0` → лог, kill + active.pop, check_failures.pop, `mark_card_done(appid)`, `_open_next` (116-121).
  - `remaining>0` → kill, sleep 10s, relaunch, лог, `check_failures[appid]=0` (122-133).
  - `remaining<0` (=-1) → инкремент `check_failures[appid]`; если `>= _MAX_CHECK_FAILURES`(5) → считать done: kill+pop, `mark_card_done`, `_open_next`; иначе kill, sleep 10s, relaunch (134-151).
- Резюм-фильтра НЕТ: `cards/done.txt` пишется (`mark_card_done`), но НИКОГДА не читается для пропуска игр. Дедуп при рестарте — Steam просто перестаёт отдавать завершённые игры в badges-скрейпе. Имена игр из кэша через `load_game_names()`.
- Источник истины «сколько карт» — живой HTML (badges + gamecards), НЕ inventory/badge API и НЕ локальный кэш. Любое изменение HTML-структуры Steam молча ломает парсинг (card_checker.py:116-123 только warn).
- `check_cards_remaining` возвращает `-1` и на сетевую ошибку, И на нераспарсенную страницу — трактовать `-1` как «неизвестно», НЕ «0». `-1` считается «done» только после 5 подряд провалов.
- KeyboardInterrupt ловится ТОЛЬКО внутри `_farm_loop` (try/except → лог, farm.py:153-154); `finally` убивает все оставшиеся active через `_kill_game` (155-157). Ctrl+C во время setup-фазы специально НЕ обрабатывается; очистка опирается на `finally` + atexit-релиз лока.
- Run-lock один общий (`data/.sam_run.lock`): farm/boost/cards нельзя запускать параллельно.
- Константы: `_MAX_CHECK_FAILURES=5`, `_PAUSE_AFTER_KILL=10s`, `_PAUSE_BETWEEN_GAMES=3s`. Тост «Card farming завершён» в конце `_farm_loop`.
- Приватный профиль даёт пустой результат с одним warning-логом, НЕ error. Требуется 17-значный steamid64 + валидные web-cookies.
- Пагинация badges полагается на хрупкую эвристику: стоп при равной байт-длине html соседних страниц.

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
