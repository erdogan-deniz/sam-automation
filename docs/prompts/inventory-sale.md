<!--
Handoff-промпт: распродажа инвентаря Steam (scripts/library/sell_inventory.py,
B-16). Скопируй всё ниже в новый чат и заполни секцию «ЗАДАЧА/СИМПТОМ». Собран
из реального кода app/inventory/ и живых проб 19.10.2026.
-->

# РОЛЬ
Ты — мейнтейнер репозитория sam-automation. Сессия — работа с распродажей
инвентаря Steam (продать на маркете или разобрать на самоцветы). Только
Windows, Python 3.12, venv в `.venv`. Отвечай коротко. Перед фиксами — корень
по доказательствам (systematic-debugging). TDD обязателен (тест ПЕРЕД кодом).
Гейты перед каждым коммитом: `ruff check .`, `ruff format --check .`,
`mypy app`, `pytest tests/unit -q`. git-flow: `feature/*` от develop через
`merge --no-ff`. Коммиты conventional, тело на русском, без футеров-атрибуций.

**Любой запуск, который выставляет лоты или разбирает предметы, — только
после «да» владельца в чате, с числом предметов и суммой.** Разбор необратим.
Подтверждения лотов в мобильном Steam Guard владелец нажимает сам.

# ЗАДАЧА/СИМПТОМ (заполни перед стартом)
<<ОПИШИ: фича/баг/вопрос. Для бага приложи вывод `python scripts/library/
sell_inventory.py --list`, строки из `logs/library/sell_inventory/` и файлы
`data/games/ids/inventory_sale/{listed,pending,ground,refused}.txt`.>>

# ЧТО ДЕЛАЕТ СКРИПТ
`python scripts/library/sell_inventory.py` — dry-run: план и суммы. Флаги
(регистр не важен): `--sell` (выставить лоты), `--grind` (разобрать),
`--list` (таблица по предметам), `--limit N`, `--interval SEC` (по умолчанию 3),
`--reset` (забыть сделанное, например после снятия лотов).

Правила выбора (`app/inventory/plan.py`, решения владельца 18–19.10.2026):
- не `marketable` и бустер-паки — пропуск; карточки — только когда значок игры
  собран (обычный — 5-й уровень, металлический — 1-й), нет данных о значке — пропуск;
- есть лучшая заявка: на руки по заявке против `самоцветов × заявка на мешок /
  1000`; самоцветы дороже — `grind`, иначе `sell_bid` (лот по заявке — купят сразу);
- заявок нет — `sell_ask`: лот по самой низкой цене продажи, висит;
- нет данных, другая валюта, нет ни заявок, ни цен — пропуск.

# ФАКТЫ STEAM (сняты живьём 19.10.2026 — не передерживать)
- Инвентарь: `GET /inventory/{id64}/753/6?l=english&count=2000` с одной кукой
  `steamLoginSecure`. Бывает единичный HTTP 500 — чтение ретраится.
- **Цены и заявки — `GET /market/orderbook?q=Load&qp=[753,"<market_hash_name>"]`**
  (`amtMaxBuyOrder`, `amtMinSellOrder`, `eCurrency`). Старые `market/listings`,
  `priceoverview` из Python давали 429 вразнобой и не используются.
- Самоцветы: `auction/ajaxgetgoovalueforitemtype/?appid&item_type&border_color`
  (параметры из `owner_actions` → `GetGooValue(...)`), `goo_value` — строка.
- `POST market/sellitem/`: `price` — на руки в копейках; ответ
  `requires_confirmation`/`needs_mobile_confirmation` → состояние `pending`.
- `POST profiles/{id}/ajaxgrindintogoo/`: в ответе ключ `"goo_value_received "`
  **с пробелом на конце**.
- `sessionid` Steam выдаёт в `Set-Cookie` любого GET и принимает в POST.
- **Комиссия** (проверена на 101 лоте): `покупатель = на_руки + max(m, ⌊5%⌋) +
  max(m, ⌊10%⌋)`, `m` — минимум комиссии валюты (**рубли — 84 коп.**, не 1).
  Валюта вне таблицы `app/inventory/fees.py` — скрипт останавливается.

# КЛЮЧЕВЫЕ ФАЙЛЫ
`app/inventory/`: `fees.py` (комиссия, целые), `plan.py` (правила), `items.py`
(разбор инвентаря), `badges.py` (GetBadges), `market.py` (orderbook, sell,
grind), `http.py` (транспорт, ретраи чтения), `state.py`, `run.py`
(оркестровка; циклы `sell`/`grind` идут через `wishlist_api.add_pending` — тот же
backoff на 429 и стена после 5 подряд). Спека:
`docs/superpowers/specs/2026-10-19-inventory-sale-design.md`.

# ИНВАРИАНТЫ
- Состояние пишется после каждого предмета (`listed`/`pending`/`ground`/
  `refused`); ошибка не записывается — повтор в следующем прогоне.
- `pending` (ждёт подтверждения) — не «продано».
- Run-lock не берётся: SAM не спавнится, уровень значка только растёт.
- Чужие 571 активных лота скрипт не трогает.
- Секреты (куки, sessionid, ключ API) не попадают в логи и тексты ошибок.

# НЕ ПРОВЕРЕНО
`sell_bid` (лот по цене не выше заявки покупают сразу, снять нельзя) на живом
аккаунте не гонялся: первый боевой прогон — с `--limit 1`.
