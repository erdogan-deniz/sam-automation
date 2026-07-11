# CLAUDE.md — правила проекта sam-automation

Автоматизация Steam через SAM (Steam Achievement Manager): разблокировка
достижений, фарм карточек, набивка playtime. Python 3.12, Windows-only
(pywinauto/win32), только CLI (`scripts/`; GUI удалён).

> Этот файл — единственный источник durable-правил, едущий с репозиторием.
> Глубина по каждому воркфлоу — в `docs/prompts/` (playbook'и farm/boost/scan
> и аудитор). Схема конфига — в `config.example.yaml` (авторитетна).

## Гейты перед КАЖДЫМ коммитом (все 4 обязательны)

Ровно то, что гоняет CI (`.github/workflows/ci.yml`, windows-latest). Также
стоят в `.pre-commit-config.yaml` (установи `pre-commit install`):

```
ruff check .
ruff format --check .      # НЕ E501: длину 80 держит форматтер, не линтер
mypy app                   # scoped ТОЛЬКО на app/; scripts/ НЕ типизируется
pytest tests/unit -q       # только tests/unit; интеграционных путей в CI нет
```

`ruff` в `requirements.txt` и `rev` в `.pre-commit-config.yaml` синхронятся
вручную — при бампе меняй в обоих местах.

## Git-flow (полная спека — `docs/gitflow.md`)

- `main` = последний релизный тег `vX.Y.Z`, прямых коммитов нет; `develop` —
  интеграция; `feature/<slug>` от develop, merge `--no-ff`; `release/X.Y.Z`
  бампит **VERSION + CHANGELOG** (обязательный шаг), PR в main + тег; `hotfix/X.Y.Z`
  от main.
- Агент сам создаёт И мержит PR через `gh` (`gh pr merge <n> --merge`). Прямой
  `git push origin main` заблокирован harness — не обходить, релиз закрывается
  через авторизованный `gh`.
- После релиза удаляй feature/release-ветки локально И на origin — репо чистый.
- **Инвариант версии**: VERSION-файл == верх CHANGELOG == последний тег. Сверять
  перед релизом (на v1.3.0 забытый бамп дал тег с VERSION=1.2.0 — фикс-форвардом,
  тег не двигали).
- Коммиты: Conventional Commits, тело на русском, футер
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Операционные инварианты (нарушение = потеря игр/данных)

- **Run-lock**: `farm.py` / `cards/farm.py` / `boost.py` НЕЛЬЗЯ запускать
  параллельно — все спавнят `SAM.Game.exe` и дерутся за Steam global user.
  Защита реальна и выпущена: `app/run_lock.py` (единый `data/.sam_run.lock`,
  PID-liveness → `RuntimeError`), подключена во все три скрипта + `atexit`,
  покрыта `tests/unit/test_run_lock.py`. (`scan.py`/`categorize.py` лок не берут —
  они не спавнят SAM.)
- **`data/` не трогать**: id/state-файлы (`data/games/ids/...`) — рабочее
  состояние прогонов, в `.gitignore`. `done.txt` — write-only: игра, потерянная
  в одном прогоне, переоткроется следующим скрейпом. Не помечать done то, что не
  завершено честно (stalled/unverified/failed → НЕ done).
- **Каталог достижений — advisory**: терминально пометить игру «нет достижений»
  может ТОЛЬКО SAM. Классификация scan/Store влияет лишь на порядок, не повод
  скипать. `with.txt` (есть достижения) держать отдельно от advisory Store-списков.
- **Честный отчёт**: сдача по cookie-ошибке (-1) и застревания НЕ пишут done и
  НЕ дают success-тост; тост честный («прерван» / «с оговорками: …» / чисто).

## Ловушки кода (уже стоили багов)

- **pywinauto**: окно из `app.windows()[0]` — это `UIAWrapper`, у него НЕТ
  `child_window()`/`wait()` (они только у `app.window(...)`). Обходить дерево
  только через `children()` (см. `_find_child` в `app/sam/sam_status.py`).
  Вызов `child_window()` на `UIAWrapper` → `AttributeError`, который project
  try/except глотает → функция молча вечно возвращает None → каждая игра ложно
  ERROR. Тесты UIA-логики строить на фейке БЕЗ атрибута `child_window`.
- **None vs 0** (`app/steam/store_api.py`): отсутствующий блок achievements →
  `None` (неизвестно); `0` только когда блок есть и total==0. Старый код схлопывал
  «блока нет» в 0 → игры терялись. Store API ненадёжен как источник «нет
  достижений» — не верить его нулям.
- **Legacy CM login**: `client.login()` возвращает `InvalidPassword` на ВЕРНЫХ
  кредах для аккаунтов на современном Steam auth (не опечатка, не 2FA). Детали и
  различение реально-неверного пароля — `docs/`/память.

## Конвенции

- Логи: `app/logging_setup.py` — `SEPARATOR = ═×80`; заголовки `centered()`
  центрируются по **width=70** (не 80); формат `[%H:%M:%S] LEVEL msg`; файлы
  `logs/<category>/<name>_TIMESTAMP.log`, UTF-8; логгер идемпотентный `sam_automation`.
- id-файлы всегда численно отсортированы (`app/id_file.py::_append_id`).
- Исключения: всё наследует `SAMError` (`app/exceptions.py`).
- Уведомления (`app/notify.py`): `toast()` — локальный Windows-toast;
  `send_telegram(text, cfg)` — удалённый, opt-in по `telegram_*`, best-effort.
- Line endings (`.gitattributes`): LF для всего исходника/текста, CRLF для
  `*.bat/*.cmd/*.ps1`, binary для exe/dll/zip/png/ico. UTF-8 везде.
- Декомпозиция крупных модулей: тонкий фасад `app/<name>.py` (реэкспорт,
  старые пути импорта) + реальный подпакет `app/<short>/` (сделано для
  `steam_auth→app/auth/`, `steam_cookies→app/cookies/`).

## Стиль работы

Высокая автономия: делать всё самому, разумные дефолты, без дробления вопросами;
короткие ответы (gist + действие). `AskUserQuestion` — только для реальных
развилок с разными последствиями. Необратимое/наружу (push в main, удаление
чужих веток) — через безопасный путь (PR), даже под автономией.
