# Handoff-промпты

Заземлённые промпты для новых чатов, посвящённых отдельной фиче/задаче.
Каждый собран из реального кода (workflow: параллельные читатели → синтез →
адверсариальная сверка) и рассчитан на копипаст целиком в новую сессию.

| Файл | Назначение |
| --- | --- |
| [project-auditor.md](project-auditor.md) | Аудитор-чистильщик: мусор, dead-код, дрейф доков/версий, пробелы в тестах, нарушения архитектуры. Работает аудит-сначала (репорт → верификация → правки по согласию). |
| [scan.md](scan.md) | Фича `scripts/scan_library.py`: сбор App ID библиотеки из трёх источников (VDF + Steam API + CM) → `all.txt`. |
| [achievements-farm.md](achievements-farm.md) | Фича `scripts/achievements/farm_achievements.py`: разблокировка достижений через SAM (money-path; UIA-детект, run-lock, терминальный `without.txt`). |
| [cards-farm.md](cards-farm.md) | Фича `scripts/cards/farm_cards.py`: фарм Steam trading cards (скрейп badges/gamecards, `_farm_loop`, run-lock). |
| [playtime-boost.md](playtime-boost.md) | Фича `scripts/playtime/boost_playtime.py`: набивка playtime батчами (источник правды — Steam API `playtime_forever`). |
| [add-free.md](add-free.md) | Фича `scripts/library/add_free_games.py`: авто-добавление бесплатных Steam-игр/app в библиотеку (CM `request_free_license`, потолок лицензий). Не проходила формальный аудит. |
| [add-demos.md](add-demos.md) | Фича `scripts/library/add_demos.py`: авто-добавление demo-версий игр в библиотеку. Отделена от add_free_games.py 2026-09-12 (B-11) — переиспользует его `licenses.py` и общий `app.steam.store_search`. Не проходила формальный аудит. |
| [wishlist-add.md](wishlist-add.md) | Фича `scripts/library/fill_wishlist.py`: авто-добавление платного вышедшего контента в вишлист (`IWishlistService`, rate-limit-стена), и чистка вишлиста `clean_wishlist.py`. Не проходила формальный аудит. |
| [inventory-sale.md](inventory-sale.md) | Фича `scripts/library/sell_inventory.py` (B-16): распродажа инвентаря Steam — продать на маркете или разобрать на самоцветы (`market/orderbook`, `sellitem`, `ajaxgrindintogoo`, формула комиссии с минимумом 84 коп.). Не проходила формальный аудит. |
| [add-dlc.md](add-dlc.md) | RESEARCH-сессия (R-6 в backlog): работает ли `request_free_license` для DLC уже имеющихся игр и как его обнаруживать. Ничего не реализовано — скрипта/ветки ещё нет. |
| [core-auth-cookies.md](core-auth-cookies.md) | Общая инфраструктура Steam-логина `app/auth/` + `app/cookies/` (CM-логин, web-cookie fallback-цепочка) — без своего скрипта, используется scan_library/add_free_games (cm_session) и farm_cards/fill_wishlist (get_web_cookies). Заведён 2026-08-10 из находок full-project-аудита. |

Перед стартом заполни в промпте секцию задачи/симптома. Примеры-зацепки внутри
промптов датированы моментом сборки — проверяй актуальность на месте (код
меняется).

**2026-08-10**: полный проектный аудит (46 агентов) нашёл конкретные баги по
нескольким скриптам — каждый вписан прямо в соответствующий плейбук выше
(секция «НАЙДЕНО АУДИТОМ 2026-08-10»), так что открытие сессии по плейбуку
сразу подхватывает и его. Полная сводка — память `project_full_audit_2026_08_10`.
