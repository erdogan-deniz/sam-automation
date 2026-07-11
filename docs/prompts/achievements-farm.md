<!--
Handoff-промпт: фича achievements farm (разблокировка достижений через SAM —
money-path). Скопируй всё ниже в новый чат и заполни секцию «ЗАДАЧА/СИМПТОМ».
Собран из реального кода scripts/achievements/farm.py + app/sam/ + app/ (workflow:
читатели по внутренностям SAM → синтез → адверсариальная сверка).
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Сессия — работа с achievements
farm (разблокировка достижений Steam через SAM — ядро проекта, money-path).
Только Windows, Python 3.12, venv в .venv. Отвечай коротко. Перед фиксами —
корень по доказательствам (systematic-debugging). TDD обязателен (тест ПЕРЕД
кодом, RED→GREEN). Гейты перед каждым коммитом: ruff check ., ruff format
--check ., mypy app, pytest tests/unit -q (line-length 80, target py312; mypy
scoped ТОЛЬКО на app/, scripts/ не типизируется). git-flow: feature/* от
develop через merge --no-ff. Коммиты conventional, тело на русском,
заканчивать Co-Authored-By.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: фича/баг/вопрос. Если баг — приложи реальный вывод
`python scripts/achievements/farm.py`, что наблюдаешь vs ожидаешь, строки из
logs/achievements/farm/, и состояние achievements/{unlocked,error,without}.txt
ДО/ПОСЛЕ. Если UIA/детект — приложи scripts/diag/dump_sam_window.py <appid>.>>

# ЧТО ДЕЛАЕТ ФУНКЦИЯ
Проходит библиотеку (all.txt), для КАЖДОЙ игры: открывает её в SAM, ждёт
загрузки списка достижений, жмёт Unlock All + Commit, закрывает, идёт дальше.
ПОСЛЕДОВАТЕЛЬНАЯ модель (по одной игре, НЕ батч — в отличие от boost/cards):
один процесс Picker на весь прогон, каждая игра открывается в своём SAM.Game.
Прогресс сохраняется после каждой игры → перезапуск продолжает с места.

# ТОЧКА ВХОДА: scripts/achievements/farm.py
main(): parse args → setup_logging(category="achievements/farm") →
acquire_run_lock("achievements/farm") [ДО сброса прогресса!] → atexit release →
load_config/validate → _prepare_progress(args) → check_steam_running →
ensure_sam → load_game_ids → выбор среза (--retry-without/--retry-done →
_select_retry_subset, иначе _apply_resume_filter) → prioritize_by_with →
launch_picker → цикл _process_one_game по каждой игре → kill_process(proc) в
finally → _report_result (честный тост+telegram по статусу ok/interrupted/aborted).

- _process_one_game(session, gid, cfg, tracker, results, name):
  session.add_and_open_game(gid, timeout=load_timeout) → process_game(...) →
  маршрут состояния: НЕ skipped → mark_done + unmark_no_achievements +
  unmark_store_advisory (сняли устаревшие «нет достижений»); skipped &
  "no achievements" → mark_no_achievements + unmark_store_advisory (SAM
  авторитетнее Store-совета); skipped & иное → mark_error_id. На
  SAMError/Exception (кроме SAMTooManyErrors) → tracker.record_error +
  mark_error_id, return True. SAMTooManyErrors проброс наверх. finally:
  close_game(game_app).
- _prepare_progress: --reset → clear_progress (все 3 файла); --retry-errors →
  clear_error_ids (ТОЛЬКО error.txt). (elif: при обоих флагах побеждает --reset.)
- _apply_resume_filter: skip = load_done_ids | load_error_ids |
  load_no_achievements_ids; исключает их из очереди.
- _select_retry_subset (при --retry-without и/или --retry-done): оставляет
  ТОЛЬКО заранее обработанные игры — --retry-without → without ∪ store_zero ∪
  store_empty; --retry-done → unlocked; оба вместе → объединение. При
  одновременном --reset игнорируются (reset и так гонит всю библиотеку).

# CLI-ФЛАГИ (scoped — не путать с другими скриптами)
--retry-errors (чистит error.txt) · --reset (сброс done+error+without) ·
--retry-without (перепроверить ТОЛЬКО without+store_zero+store_empty) ·
--retry-done (перепрогнать ТОЛЬКО unlocked).

# КЛЮЧЕВЫЕ ФАЙЛЫ
- scripts/achievements/farm.py — оркестрация + флаги + итоговый отчёт.
- app/sam/picker_session.py — PickerSession.add_and_open_game: вводит appid в
  Picker, дабл-клик, ждёт новый PID SAM.Game, connect(backend="uia") → возвращает
  pywinauto Application. Гард IsWindowEnabled (modal dialog вешает UIA). Ошибки →
  SAMGameError (игра недоступна / процесс не появился / окно Manager не появилось).
- app/sam/manager_window.py — process_game(app, gid, load_timeout,
  post_commit_delay): находит Manager-окно по automation_id=="Manager" (НЕ
  windows()[0]!), _check_game_status, при retry/error один Refresh+recheck, затем
  Unlock All + Commit + {ENTER}. Кнопки — КЭШИРОВАННЫЕ координатные клики
  (_ButtonCache.calibrate на первой игре через descendants() один раз;
  провал калибровки → SAMGameError «не удалось найти кнопки (нет достижений?)»).
- app/sam/sam_status.py — _check_game_status: ИСТОЧНИК ИСТИНЫ = число ListItem в
  _AchievementListView (структурно), статус-бар только для быстрых негативов
  ("error" / "Retrieved 0"). Обход дерева ТОЛЬКО children() через _find_child.
- app/sam/launcher.py — launch_picker, close_game (kill по PID через Win32),
  kill_process, kill_all_sam_games (страховка Ctrl+C).
- app/sam/sam_downloader.py — ensure_sam (качает SAM с gibbed/SteamAchievement
  Manager, кэш версии .sam_version через PE-метаданные), check_steam_running.
- app/cache.py — state: mark_done→unlocked.txt, mark_error_id→error.txt,
  mark_no_achievements→without.txt; load_*_ids; clear_progress/clear_error_ids.
- app/catalog.py — load_with_ids, prioritize_by_with (переставляет, НЕ фильтрует).
- app/safety.py — ErrorTracker (аварийный стоп по ПОДРЯД-ошибкам).
- app/unlock_result.py — UnlockResult(game_id, total, already_unlocked,
  newly_unlocked, skipped, skip_reason). app/notify.py — toast/send_telegram.
- Тесты: test_farm (ТОЛЬКО _build_parser + _prepare_progress), test_sam_status,
  test_manager_window (plain-фейки БЕЗ child_window), test_safety, test_catalog.

# STATE-ФАЙЛЫ (data/games/ids/achievements/)
- unlocked.txt — успешно обработанные (mark_done). ⚠️ имя unlocked.txt, НЕ done.txt
  (done.txt — это playtime).
- error.txt — ошибка/таймаут/transient, RETRYABLE (--retry-errors чистит).
- without.txt — ТЕРМИНАЛЬНО «нет достижений»; пишет ТОЛЬКО farm
  (mark_no_achievements при статус-баре "Retrieved 0"); скипается на резюме
  навсегда; чистит только --reset. Store-каталог (with/store_zero/store_empty)
  сюда НЕ пишет — это advisory, отдельные файлы.

# КОНФИГ (config.yaml)
- load_timeout=20 — ждать загрузки статов игры (окно Manager ждётся отдельно:
  max(load_timeout, 15с)).
- launch_delay=3 — после старта Picker; post_commit_delay=0.2; between_games_delay=0.1.
- max_consecutive_errors=100 — порог ПОДРЯД-ошибок для аварийного стопа.
- exclude_ids/game_ids/game_ids_file — источник и исключения (в game_list).

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
- run-lock ОБЯЗАТЕЛЕН и берётся ДО --reset: farm/boost/cards нельзя параллельно
  (дерутся за SAM/Steam global user). Второй запуск → RuntimeError → exit(1) до
  любого сброса прогресса.
- ЛОВУШКА pywinauto (стоила багов): окно из app.windows()[0] — UIAWrapper, у него
  НЕТ child_window()/wait() (только children()). Обход дерева — _find_child через
  children(). Manager ищется по automation_id, НЕ по индексу [0] (иначе ссылка на
  транзиентное/мёртвое окно → каждая игра ложный ERROR). Тесты UIA — на фейках БЕЗ
  child_window; вызов несуществующего метода ДОЛЖЕН ронять тест.
- Детект: наличие достижений = заполненность _AchievementListView (структурно),
  а НЕ текст статус-бара (он приходит с задержкой, ронял медленные игры в ERROR).
  "error"/"Retrieved 0" — только быстрые негативы. "retry" (не загрузилось) →
  Refresh → если снова retry, деградирует в error (retryable, не вечный цикл).
- ErrorTracker: SAMTooManyErrors на N-й ПОДРЯД ошибке (record_success сбрасывает
  серию; total_errors не сбрасывается). Проброс → main ловит → "продолжит с места".
- Ctrl+C безопасен (ловится в main, kill_process(proc), resume по unlocked/error).
- Честный отчёт: _report_result(status) — прерванный Ctrl+C (`interrupted`) или
  аварийный SAMTooManyErrors (`aborted`) прогон даёт ⚠️ и честный текст, НЕ
  «✅ Готово»; ✅ только при чистом завершении без ошибок. Не регрессить.
- newly_unlocked = полное число строк списка (НЕ дельта ранее-залоченных).
- Логи: logs/achievements/farm/<TIMESTAMP>.log (UTF-8).

# ПРОБЕЛЫ В ТЕСТАХ (если правишь — закрой TDD)
- _process_one_game, _apply_resume_filter, main()-цикл — БЕЗ покрытия; фейка
  session (add_and_open_game/close_game/launch_picker) нет.
- Реальный pywinauto-путь против живого SAM не тестируется (только логика на фейках).
- _report_result покрыт (test_farm: ✅ vs ⚠️ на interrupted/aborted/errors), но
  перехват Ctrl+C/SAMTooManyErrors в самом цикле main не проверяется.

# МЕТОД
1. По симптому выбери цель. Баг → воспроизведи, сними лог, сверь состояние
   3 файлов ДО/ПОСЛЕ; для UIA — дамп окна (scripts/diag/dump_sam_window.py).
2. Падающий тест на плоских фейках (session/UIA БЕЗ child_window, БЕЗ реального
   SAM). RED → фикс → GREEN. UIA-логику строй на _Ctrl-фейке из test_sam_status.
3. 4 гейта. feature от develop, conventional-коммит, merge --no-ff.

# ОГРАНИЧЕНИЯ
- Только Windows; реальный прогон требует запущенного Steam + SAM.Game.exe.
- farm/boost/cards параллельно не запускать.
- Не ломать инварианты: without.txt терминален и пишет только farm; каталог
  advisory (порядок, не скип); прогресс честный (stalled/error ≠ done).
