<!--
Handoff-промпт: фича playtime boost. Скопируй всё ниже в новый чат и заполни
секцию «ЗАДАЧА/СИМПТОМ». Собран из реального кода scripts/playtime/boost.py + app/.
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Задача сессии — работа с функцией
boost playtime (набивка времени в играх). Только Windows, Python 3.12, venv в
.venv. Отвечай коротко. Перед фиксами — корень по доказательствам
(systematic-debugging). TDD обязателен (тест ПЕРЕД кодом, RED→GREEN). Гейты
перед каждым коммитом: pytest, ruff check, ruff format, mypy app (line-length 80,
target py312). git-flow: feature/* от develop через merge --no-ff. Коммиты
conventional, тело на русском, заканчивать Co-Authored-By.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: что нужно — фича/баг/вопрос. Если баг — приложи реальный вывод
прогона `python scripts/playtime/boost.py` (или `--list`), что наблюдаешь vs
ожидаешь, и относящиеся строки из logs/playtime/boost/.>>

# ЧТО ДЕЛАЕТ ФУНКЦИЯ
Набивает playtime до target в каждой игре, запуская SAM.Game.exe (фейковая
сессия → Steam засчитывает время). Batch-модель: N игр одновременно → ждём
idle_duration сек → убиваем всех → следующий батч. ИСТОЧНИК ПРАВДЫ — Steam Web
API (`playtime_forever`); локальный прогресс для «известных» игр НЕ хранится
(перепроверяется по API каждый прогон).

# ТОЧКА ВХОДА: scripts/playtime/boost.py
- main(): args → setup_logging → load_config → validate → check_steam_running →
  ensure_sam → resolve_steam_id → (не --list: acquire_run_lock ДО
  _prepare_progress — --reset/--retry-skips деструктивны, лок защищает resume
  работающего инстанса) → _fetch_targets → (--list: read-only печать и выход,
  без лока и без сброса) → _boost_loop. atexit release.
- _prepare_progress: --reset → clear_playtime_progress (только done.txt);
  --retry-skips → clear_playtime_skip (только skip.txt).
- _fetch_targets(cfg, steam_id): вселенная — all.txt (вся библиотека);
  played = {appid: playtime_forever} из fetch_owned_games (Steam API);
  skip = exclude_ids ∪ playtime/skip.txt ∪ playtime/done.txt → _select_targets.
- _select_targets(...): пропускает skip и игры с известным playtime >= target;
  у каждой цели флаг known = (appid in played). known=True → готовность по API
  (в done.txt НЕ пишем); known=False (API не отдаёт playtime: free/демо/
  лицензии) → идлим вслепую один раз и пишем в done.txt (resume).
- _boost_loop(games, cfg): по батчам concurrent_games:
  launch_games_staggered(stagger) → idle_and_split_survivors (поллинг весь idle,
  on_failed → skip ТОЛЬКО для unknown; known-провал НЕ хоронится — перепроверит
  API) → known НЕ в done, unknown → mark_playtime_done → пауза _PAUSE_AFTER_KILL
  =5с между батчами. try/except/finally: ЛЮБОЙ выход (норма/Ctrl+C/ошибка) →
  добить active + kill_all_sam_games (не осиротить SAM.Game.exe); done пишется
  только в норме. Итог через _report_result: ✅ только при полном прогоне без
  провалов, иначе ⚠️ (прервано/ошибка/с оговорками).
  Ctrl+C: активные убиваются, но НЕ помечаются done (могли не добрать время).

# КЛЮЧЕВЫЕ ФАЙЛЫ
- scripts/playtime/boost.py — точка входа (_build_parser/_fetch_targets/
  _select_targets/_boost_loop).
- app/cache.py — пути и хелперы: PLAYTIME_DONE_FILE (data/games/ids/playtime/
  done.txt), PLAYTIME_SKIP_FILE (skip.txt), load/mark_playtime_done,
  load/mark_playtime_skip, clear_playtime_progress (done.txt),
  clear_playtime_skip (skip.txt).
- app/steam/steam_api.py — fetch_owned_games (playtime_forever); resolve_steam_id.
- app/sam/launcher.py — launch_games_staggered, idle_and_split_survivors
  (on_failed→skip, гарды idle≤0/poll≤0/neg-sleep), kill_process,
  kill_all_sam_games (win32-свип сирот).
- app/sam/ — check_steam_running, ensure_sam.
- app/run_lock.py — acquire_run_lock/release_run_lock (data/.sam_run.lock).
- app/config.py — конфиг; app/notify.py — toast + send_telegram;
  app/validator.py — validate (в т.ч. playtime idle≥1/target≥1/stagger≥0).
- Тесты: tests/unit/ (test_boost_loop, test_boost_targets, test_launcher —
  фейки subprocess/SAM, БЕЗ реального запуска).

# КОНФИГ (config.yaml, дефолты в app/config.py)
- playtime_idle_duration = 120   # сек идлить каждую игру
- playtime_target_minutes = 3    # минимум минут playtime
- playtime_concurrent_games     # размер батча (параллельные игры)
- launch_stagger = 3.0           # сек между стартами игр внутри батча
- exclude_ids — список appid пропустить.

# ЗНАЧИМЫЕ ПОВЕДЕНИЯ / РИСКИ
- farm и boost НЕЛЬЗЯ запускать параллельно: конфликт за SAM/Steam-сессию,
  ложные ERROR и потеря игры. Защищено run-lock (data/.sam_run.lock):
  acquire_run_lock бросает RuntimeError, если другой активен.
- _PAUSE_AFTER_KILL после убийства батча обязателен: даёт Steam освободить
  global user, иначе первая игра следующего батча ловит «failed to connect to
  global user».
- done.txt — ТОЛЬКО для unknown-игр (API не видит playtime). known-игры
  гейтятся по реальному playtime_forever, поэтому набитые отсеиваются на
  _fetch_targets, а не флагом. --reset чистит done.txt; --retry-skips чистит
  skip.txt. skip пишется ТОЛЬКО для unknown — known-провал (часто транзиентный)
  не хоронится навсегда, его перепроверит API (инвариант «known-истина=API»).
- Детект провалившихся запусков — idle_and_split_survivors (поллинг весь idle):
  успех = процесс пережил весь idle без окна ошибки; провал → on_failed→skip
  (unknown). (Старый гоночный drop_failed_launches заменён.)
- Пустой owned-games API при непустой all.txt (приватные Game details) → warning:
  ВСЕ игры считаются unknown и набиваются вслепую — не абортим, но предупреждаем.
- Честный отчёт: ✅-тост/Telegram только при полном прогоне без провалов; Ctrl+C,
  ошибка и наличие провалов → ⚠️ и честный текст (не «✅ обработано»).
- Ctrl+C безопасен (resume по done.txt), но текущий батч не зачтётся.
- Логи: logs/playtime/boost/<timestamp>.log (UTF-8).

# МЕТОД
1. По симптому выбери цель. Если баг — воспроизведи, сними лог, проверь
   состояние done.txt/skip.txt и ответ Steam API ДО/ПОСЛЕ.
2. Падающий тест на плоских фейках (subprocess/SAM-лаунчер БЕЗ реального
   запуска SAM/Steam). RED → фикс → GREEN.
3. Прогони 4 гейта. feature-ветка от develop, conventional-коммит, merge --no-ff.

# ОГРАНИЧЕНИЯ
- Только Windows; реальный прогон требует запущенного Steam и SAM.Game.exe.
- boost и farm параллельно не запускать.
- Не ломать инвариант «источник правды для known-игр — Steam API, не done.txt».
