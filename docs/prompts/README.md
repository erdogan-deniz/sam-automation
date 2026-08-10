# Handoff-промпты

Заземлённые промпты для новых чатов, посвящённых отдельной фиче/задаче.
Каждый собран из реального кода (workflow: параллельные читатели → синтез →
адверсариальная сверка) и рассчитан на копипаст целиком в новую сессию.

| Файл | Назначение |
| --- | --- |
| [project-auditor.md](project-auditor.md) | Аудитор-чистильщик: мусор, dead-код, дрейф доков/версий, пробелы в тестах, нарушения архитектуры. Работает аудит-сначала (репорт → верификация → правки по согласию). |
| [scan.md](scan.md) | Фича `scripts/scan.py`: сбор App ID библиотеки из трёх источников (VDF + Steam API + CM) → `all.txt`. |
| [achievements-farm.md](achievements-farm.md) | Фича `scripts/achievements/farm.py`: разблокировка достижений через SAM (money-path; UIA-детект, run-lock, терминальный `without.txt`). |
| [cards-farm.md](cards-farm.md) | Фича `scripts/cards/farm.py`: фарм Steam trading cards (скрейп badges/gamecards, `_farm_loop`, run-lock). |
| [playtime-boost.md](playtime-boost.md) | Фича `scripts/playtime/boost.py`: набивка playtime батчами (источник правды — Steam API `playtime_forever`). |
| [add-free.md](add-free.md) | Фича `scripts/library/add_free.py`: авто-добавление бесплатных Steam-игр/app в библиотеку (CM `request_free_license`, потолок лицензий). Не проходила формальный аудит. |
| [wishlist-add.md](wishlist-add.md) | Фича `scripts/library/wishlist_add.py`: авто-добавление каталога Steam в вишлист (`IWishlistService`, rate-limit-стена). Не проходила формальный аудит. |

Перед стартом заполни в промпте секцию задачи/симптома. Примеры-зацепки внутри
промптов датированы моментом сборки — проверяй актуальность на месте (код
меняется).
