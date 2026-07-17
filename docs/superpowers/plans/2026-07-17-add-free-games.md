# Auto-add Free Games Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Одна команда сканирует витрину Steam (F2P-игры, бесплатные app, демо), вычитает уже имеющееся в библиотеке и добавляет недостающее через `request_free_license` — резюмируемо, с честным отчётом об упоре в потолок лицензий аккаунта.

**Architecture:** Новый пакет `app/free_games/` (discovery через неофициальный store-search API, resume-состояние на id-файлах, батчевое добавление лицензий с cap/rate-limit-детектом, честный отчёт) поверх нового переиспользуемого примитива `cm_session()` в `app/steam/steam_cm.py` (живой залогиненный CM-клиент — раньше логин был заперт внутри `read_steam_cm_app_ids` и сразу отключался). Тонкий CLI `scripts/library/add_free.py` — dry-run по умолчанию.

**Tech Stack:** Python 3.12, `steam` (ValvePython CM protocol), stdlib `urllib`/`json`/`re` (без новых зависимостей), pytest + monkeypatch.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-17-add-free-games-design.md` — все решения владельца оттуда обязательны (discovery = витрина free + демо-подфаза; dry-run по умолчанию, `--add` для реального добавления; resume-состояние candidates/added/refused/error; честный отчёт; cap-детект не абстрактный — см. ниже).
- 4 гейта перед КАЖДЫМ коммитом: `ruff check .` / `ruff format --check .` / `mypy app` / `pytest tests/unit -q`. `scripts/` НЕ типизируется mypy — вся логика в `app/free_games/`, скрипт только парсит CLI и вызывает `app.free_games.run`.
- ruff: line-length 80 (держит форматтер, не линтер — E501 в ignore), py312, select `E,F,W,I`.
- Ветка `feature/add-free-games` (уже создана от `develop`), merge `--no-ff`. Conventional Commits, тело на русском, футер `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- `data/*` уже в `.gitignore` — `data/games/ids/free/` ничего дополнительно не требует.
- **Cap-сигнал закрыт, не «уточняется на интеграции»** (спека была не уверена): `steam.enums.EResult.LimitExceeded = 25` (комментарий в самой библиотеке: "Too much of a good thing" / "may be permanent") — это и есть потолок лицензий аккаунта. `EResult.RateLimitExceeded = 84` — временный (комментарий: "different from k_EResultLimitExceeded which may be permanent") — backoff, не стена. Оба значения проверены напрямую в исходнике `steam` (site-packages), см. Task 4.
- **Run-lock не нужен, без оговорок**: `scan.py` уже делает полный CM-логин через `read_steam_cm_app_ids` БЕЗ run-lock (не спавнит `SAM.Game.exe` → не конфликтует с farm/boost за Steam global user). Новая фича использует тот же CM-протокол (тот же `SteamClient` из библиотеки `steam`, тот же неблокирующий gevent-логин) тем же образом — по тому же обоснованию конфликта с farm/boost нет. Прецедент `scan.py` закрывает вопрос, отдельной проверки на интеграции не требуется.
- **Discovery-эндпоинт проверен вживую** (не из документации — Store search — неофициальный API): `GET https://store.steampowered.com/search/results/?query&start={N}&count={N}&category1={ID}&maxprice=free&supportedlang=english&json=1&infinite=1`. Ответ: `{"success":1,"results_html":"...","total_count":N,"start":N}`. AppID извлекается regex'ом `data-ds-appid="(\d+)"` из `results_html`. `category1`: `998`=Games (дефолт витрины), `994`=Software, `10`=Demos (демо не нуждаются в `maxprice=free` — все демо бесплатны по определению). Проверено `count=100` (макс. страница) и пагинация `start=100` — оба работают, возвращают разные ID.

---

## Task 1: `cm_session()` — переиспользуемый живой CM-клиент

**Files:**
- Modify: `app/steam/steam_cm.py:19-30` (импорты), `app/steam/steam_cm.py:195-466` (тело `read_steam_cm_app_ids` — рефакторинг)
- Modify: `app/steam/__init__.py` (реэкспорт `cm_session`)
- Test: `tests/unit/test_steam_cm.py` (добавить тесты, СУЩЕСТВУЮЩИЕ 27 тестов должны остаться зелёными без изменений — это regression-сеть на auth-код, который уже стоил серии 6-слойных багов)

**Interfaces:**
- Consumes: ничего нового — рефакторинг существующего кода.
- Produces:
  - `_cm_login(username: str, *, interactive: bool = True) -> Any` — приватная. Логинится (JWT→сохранённый пароль→RSA→интерактив→2FA), возвращает ЖИВОЙ подключённый `SteamClient` с заполненным `.licenses` при успехе (НЕ отключает), либо `None` при любом неуспехе (уже отключён и залогирован внутри). На исключении — отключает и пробрасывает.
  - `cm_session(username: str = "", *, interactive: bool = True) -> Iterator[Any]` — публичный контекст-менеджер. `with cm_session() as client:` — `client` либо живой `SteamClient`, либо `None` (caller обязан проверить). Гарантированно отключает на выходе из `with` (успех/неуспех/исключение внутри блока).
  - `read_steam_cm_app_ids(steam_path, username, *, interactive=True) -> list[int]` — публичная, сигнатура НЕ меняется (обратная совместимость), теперь тонкая обёртка над `cm_session`.

### Разбор рефакторинга (обязательно прочитать перед кодом)

Текущая `read_steam_cm_app_ids` создаёт `SteamClient`, логинится, читает `client.licenses`, **тут же вызывает `client.disconnect()`**, и только потом `expand_packages_to_apps(...)`. Это не даёт вызывающему коду живой клиент — а `request_free_license` (Task 4) нужно звать именно на живом клиенте.

Извлекаем: всё тело логина (создание клиента → JWT/пароль/RSA/2FA/интерактив-стейт-машина → ожидание `ClientLicenseList`) переезжает в `_cm_login`, которая возвращает **живой** клиент вместо `list[int]`. `cm_session` оборачивает это контекст-менеджером с гарантированным disconnect. `read_steam_cm_app_ids` становится тонким потребителем: `owned_packages = set(client.licenses.keys())` → `expand_packages_to_apps(...)`.

Критичный нюанс (иначе живой клиент никогда не долетит до caller'а): нельзя оставлять blanket `finally: client.disconnect()`, оборачивающий ВЕСЬ try-блок, как было — `finally` сработал бы и на успешном `return client`, отключив клиента ДО того, как он попадёт к вызывающему. Меняем `finally` на `except BaseException: client.disconnect(); raise` — идентично на исключении (диск-коннект + проброс), но НЕ срабатывает на нормальном `return` (ни ранний `return None`, ни финальный `return client`).

Это обнажает: в оригинале ДВА пути возврата (`interactive=False` без сохранённых кредов; таймаут `connect()` при первом логине) полагались ИСКЛЮЧИТЕЛЬНО на этот теперь-удаляемый `finally` для disconnect — сами явного `client.disconnect()` не делали. Добавляем им явный `client.disconnect()` (см. код ниже, помечено `# FIX:`) — это не поведенческий регресс, а закрытие скрытой дыры, которая раньше маскировалась implicit-finally. Существующие тесты этих двух путей не покрывают (проверено — ни один test_steam_cm.py тест не передаёт `interactive=False` без сохранённых кредов, ни один не бьёт `connect()`-таймаут в first-login ветке), так что это безопасно и добавляет тестовое покрытие, а не ломает его.

Каждый ДРУГОЙ путь возврата (`transient timeout`, `2FA timeout`, `2FA неверный код`, `RSA-провал`, `transient/skip не-пароль`, финальный catch-all) уже вызывает `client.disconnect()` явно перед `return []` — просто меняем `return []` → `return None`, сам disconnect не трогаем.

- [ ] **Step 1: Прочитать текущий полный текст файла (уже сделано в этой сессии) — зафиксировать базовую линию тестов**

Run: `pytest tests/unit/test_steam_cm.py -v`
Expected: `27 passed` (ровно столько тестов сейчас в файле — это baseline ДО рефакторинга)

- [ ] **Step 2: Дописать НОВЫЕ тесты в `tests/unit/test_steam_cm.py` (в конец файла) — красная фаза для `cm_session`/`_cm_login`**

```python
# ── cm_session / _cm_login: живой клиент переживает успешный вход ──────────


def test_cm_login_success_returns_live_client_without_disconnect(monkeypatch):
    # _cm_login должен вернуть КЛИЕНТА, а не отключить его — иначе
    # request_free_license (потребитель из app/free_games) не сможет им
    # воспользоваться.
    fake = _FakeCMFlow([EResult.OK])
    _patch_cm_flow(monkeypatch, fake, refresh="RT")
    monkeypatch.setattr(
        steam_cm, "_cm_login_with_jwt", lambda *a, **k: EResult.OK
    )

    client = steam_cm._cm_login("user")

    assert client is fake
    assert fake.disconnect_calls == 0


def test_cm_session_disconnects_after_with_block(monkeypatch):
    fake = _FakeCMFlow([EResult.OK])
    _patch_cm_flow(monkeypatch, fake, refresh="RT")
    monkeypatch.setattr(
        steam_cm, "_cm_login_with_jwt", lambda *a, **k: EResult.OK
    )

    with steam_cm.cm_session("user") as client:
        assert client is fake
        assert fake.disconnect_calls == 0

    assert fake.disconnect_calls == 1


def test_cm_session_yields_none_on_login_failure(monkeypatch):
    # Транзиент (TryAnotherCM) на всех попытках → login не удался.
    fake = _FakeCMFlow([EResult.TryAnotherCM])
    _patch_cm_flow(monkeypatch, fake, refresh=None)

    with steam_cm.cm_session("user") as client:
        assert client is None


def test_cm_session_no_double_disconnect_on_login_failure(
    monkeypatch, tmp_path
):
    # _cm_login САМ отключает на неуспехе (как раньше) — cm_session's finally
    # не должен звать disconnect ВТОРОЙ раз (client is None → guard).
    # Сценарий "не interactive, нет сохранённых кредов" даёт РОВНО один
    # disconnect() внутри _cm_login (без ветвления/ретраев) — предсказуемое
    # число для проверки, что cm_session не добавляет второй вызов поверх.
    # (Транзиент-ретрай сценарий НЕ годится для этой проверки: у него САМОГО
    # несколько disconnect() внутри retry-цикла — это его собственная логика,
    # не связанная с cm_session, и число дизайн-корректно, но нестабильно
    # проверять именно тут.)
    fake = _FakeCMFlow([])
    monkeypatch.setattr("steam.client.SteamClient", lambda: fake)
    monkeypatch.setattr(steam_cm, "_steam_api_reachable", lambda *a, **k: True)
    monkeypatch.setattr(steam_cm, "_load_session", lambda: None)
    monkeypatch.setattr(
        steam_cm, "_USERNAME_FILE", tmp_path / "no_such_username.txt"
    )

    with steam_cm.cm_session("user", interactive=False):
        pass

    assert fake.disconnect_calls == 1  # ровно один раз (внутри _cm_login), не 2


def test_cm_login_not_interactive_no_saved_disconnects(monkeypatch, tmp_path):
    # FIX: путь "interactive=False, нет сохранённых кредов" раньше полагался
    # ТОЛЬКО на удаляемый blanket finally для disconnect — теперь явный вызов.
    fake = _FakeCMFlow([])
    monkeypatch.setattr("steam.client.SteamClient", lambda: fake)
    monkeypatch.setattr(steam_cm, "_steam_api_reachable", lambda *a, **k: True)
    monkeypatch.setattr(steam_cm, "_load_session", lambda: None)
    monkeypatch.setattr(
        steam_cm, "_USERNAME_FILE", tmp_path / "no_such_username.txt"
    )

    client = steam_cm._cm_login("user", interactive=False)

    assert client is None
    assert fake.disconnect_calls == 1


# ── read_steam_cm_app_ids поверх cm_session: поведение не изменилось ───────


def test_read_cm_app_ids_still_works_via_cm_session(monkeypatch):
    # Регрессия по сути дублирует test_flow_jwt_first_success_returns_apps,
    # но явно фиксирует, что публичная функция пережила рефакторинг на
    # cm_session — оставлена рядом как явный regression-маркер задачи.
    fake = _FakeCMFlow([EResult.OK])
    _patch_cm_flow(monkeypatch, fake, refresh="RT")
    monkeypatch.setattr(
        steam_cm, "_cm_login_with_jwt", lambda *a, **k: EResult.OK
    )
    assert steam_cm.read_steam_cm_app_ids("C:/steam", "user") == [10, 20]
    assert fake.disconnect_calls == 1
```

- [ ] **Step 3: Запустить новые тесты — убедиться, что падают (cm_session/_cm_login ещё не существуют)**

Run: `pytest tests/unit/test_steam_cm.py -k "cm_login or cm_session or still_works" -v`
Expected: `FAIL` — `AttributeError: module 'app.steam.steam_cm' has no attribute '_cm_login'` (и аналогично для `cm_session`)

- [ ] **Step 4: Обновить импорты в начале `app/steam/steam_cm.py`**

Замени блок импортов (строки 19-30):

```python
from __future__ import annotations

import logging
import os
import urllib.request
from collections.abc import Callable
from typing import Any
```

на:

```python
from __future__ import annotations

import contextlib
import logging
import os
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any
```

- [ ] **Step 5: Заменить `read_steam_cm_app_ids` (строки 195-466) на `_cm_login` + `cm_session` + новую тонкую `read_steam_cm_app_ids`**

Полностью заменить старую функцию (от `def read_steam_cm_app_ids(` до конца файла) на:

```python
def _cm_login(username: str, *, interactive: bool = True) -> Any:
    """Логинится в Steam CM (JWT → сохранённый пароль → RSA → интерактив).

    Возвращает живой ПОДКЛЮЧЁННЫЙ SteamClient с заполненным `.licenses` при
    успехе (caller сам обязан отключить — см. `cm_session`), либо None при
    любом неуспехе (причина уже залогирована, соединение уже закрыто здесь).
    На исключении (напр. EOFError из input() в cron без stdin) — соединение
    закрывается и исключение пробрасывается дальше.

    Args:
        username:    логин Steam аккаунта (используется только при первом
                      интерактивном входе без сохранённых данных — сам вход
                      всё равно переспрашивает).
        interactive: разрешить интерактивный ввод пароля/2FA.
                     При False возвращает None если нет сохранённых данных.
    """
    try:
        import gevent
        from gevent.event import Event as GEvent
        from steam.client import SteamClient
        from steam.enums import EResult
        from steam.enums.emsg import EMsg
    except ImportError:
        log.warning("Библиотека steam не установлена: pip install steam")
        return None

    # Пре-чек ДО запроса логина/пароля/2FA: если Steam WebAPI недоступен —
    # вход в CM всё равно зависнет. Пропускаем CM (ID уже собраны из
    # localconfig + Steam API), ничего не спрашивая.
    if not _steam_api_reachable():
        log.warning(
            "Steam WebAPI недоступен — пропускаю Steam CM. ID собраны из "
            "localconfig + Steam API; повтори scan позже для лицензий CM."
        )
        return None

    client = SteamClient()
    client.set_credential_location(str(_CRED_DIR))
    try:
        # Регистрируем слушатель ДО login — иначе race condition
        licenses_event = GEvent()
        client.once(EMsg.ClientLicenseList, lambda _msg: licenses_event.set())

        captured_password: str | None = None
        first_login = False
        want_to_save = False

        _CONNECT_TIMEOUT = 30  # секунд на TCP-подключение к CM-серверу

        def _login_with_timeout(*args, **kwargs):
            """Обёртка над client.login() с таймаутом на фазу подключения."""
            with gevent.Timeout(_CONNECT_TIMEOUT, False):
                return client.login(*args, **kwargs)
            return None  # таймаут истёк

        # Пробуем загрузить сохранённые данные с диска
        saved = _load_session()
        saved_username = (
            saved[0]
            if saved
            else (
                _USERNAME_FILE.read_text(encoding="utf-8").strip()
                if _USERNAME_FILE.exists()
                else None
            )
        )

        # Сначала JWT (без пароля и 2FA) — СЫРОЙ SteamClient-scope refresh_token из
        # клиентского кэша (его кладут в ClientLogon.access_token; деривация
        # access_token дала бы пустой/web-токен → AccessDenied).
        result = None
        if saved_username:
            refresh_token = _load_refresh_token(_JWT_REFRESH_CLIENT_FILE)
            if refresh_token:
                result = _cm_login_with_jwt(
                    client, saved_username, refresh_token, _CONNECT_TIMEOUT
                )
                if result == EResult.OK:
                    log.info("Steam CM: вход через JWT (%s)", saved_username)
                else:
                    log.debug(
                        "Steam CM: JWT не принят (%s), пробую пароль", result
                    )

        if result != EResult.OK and saved:
            saved_username, saved_password = saved
            log.info(
                "Автоматическая авторизация аккаунта Steam под логином %s",
                saved_username,
            )
            # Транзиентные ошибки CM (TryAnotherCM и пр.) — сетевые, не проблема
            # пароля: пара повторов с переподключением к другому CM-серверу.
            for attempt in range(2):
                result = _login_with_timeout(saved_username, saved_password)
                if result is None or _cm_login_outcome(result) != "transient":
                    break
                log.warning(
                    "Steam CM: %s — переподключаюсь к другому CM (%d/2)",
                    result,
                    attempt + 1,
                )
                try:
                    client.disconnect()
                except Exception:
                    pass
                gevent.sleep(2)

            if result is None:
                # Таймаут подключения — сетевое, креды НЕ трогаем, пропускаем CM.
                log.warning(
                    "Steam CM: таймаут подключения (%ds) — пропускаю CM, "
                    "учётные данные сохранены",
                    _CONNECT_TIMEOUT,
                )
                client.disconnect()
                return None

            # Mobile Authenticator: пароль принят, Steam требует 2FA
            if result == EResult.AccountLoginDeniedNeedTwoFactor:
                shared = _load_shared_secret(saved_username)
                auto_code = _compute_steam_totp(shared) if shared else None

                def _do_2fa_login(code: str) -> Any:
                    return _login_with_timeout(
                        saved_username, saved_password, two_factor_code=code
                    )

                def _prompt_2fa() -> str:
                    print()
                    return input(
                        "[Steam Client Master] Введите 2FA код учётной записи "
                        "Steam: "
                    ).strip()

                # Неверный авто-код (перекос часов) → откат на ручной ввод.
                result = _login_saved_with_2fa(
                    _do_2fa_login, auto_code, _prompt_2fa, EResult.OK
                )

                if result is None:
                    log.warning(
                        "Steam CM: таймаут подключения после 2FA (%ds)",
                        _CONNECT_TIMEOUT,
                    )
                    client.disconnect()
                    return None

                # Пароль был верным (иначе 2FA не запросили бы) — не удаляем сессию
                if result != EResult.OK:
                    log.warning("Steam CM: неверный 2FA код (%s)", result)
                    client.disconnect()
                    return None

            elif result != EResult.OK:
                if _password_failure_action(result) == "try_rsa":
                    # InvalidPassword может означать НЕ опечатку, а отказ legacy
                    # ClientLogon для modern-auth аккаунта. Пробуем RSA-путь ДО
                    # удаления валидных кредов.
                    result = _rsa_jwt_login(
                        client, saved_username, saved_password, _CONNECT_TIMEOUT
                    )
                    if result == EResult.OK:
                        log.info(
                            "Steam CM: вход через RSA/JWT (%s)", saved_username
                        )
                    elif _should_clear_session_after_rsa(result):
                        # Достоверно-неверный пароль: современный Begin-путь
                        # (authoritative) отверг RSA-пароль → стираем сессию и
                        # переспрашиваем логин ниже (типично после смены пароля).
                        log.warning("Steam CM: неверный пароль, удаляю сессию")
                        _clear_session()
                        saved = None  # → интерактивный ре-ввод ниже
                    else:
                        # RSA-провал неотличим от сетевого (см.
                        # _should_clear_session_after_rsa): НЕ стираем валидные
                        # креды — пропускаем CM, скан идёт по localconfig + API.
                        log.warning(
                            "Steam CM: RSA-вход не удался (%s) — пропускаю CM, "
                            "учётные данные сохранены",
                            getattr(result, "name", result),
                        )
                        client.disconnect()
                        return None
                else:
                    # Сетевая (transient) или ошибка аккаунта (не пароль): креды
                    # сохраняем, в интерактив НЕ падаем, CM пропускаем — скан идёт
                    # дальше с ID из localconfig + Steam API.
                    log.warning(
                        "Steam CM: вход не удался (%s) — пропускаю CM, "
                        "учётные данные сохранены",
                        getattr(result, "name", result),
                    )
                    client.disconnect()
                    return None

        if not saved and result != EResult.OK:
            if not interactive:
                log.info(
                    "Steam CM: нет сохранённых данных, интерактивный режим отключён"
                )
                # FIX: раньше полагался только на blanket finally (см. разбор
                # рефакторинга в плане) — теперь явно, как и другие пути.
                client.disconnect()
                return None

            first_login = True
            # Спрашиваем ДО логина — чтобы не блокировать event loop после него
            want_to_save = _ask_keep_credentials()
            username = input(
                "[Steam Client Master] Введите логин от учётной записи Steam: "
            ).strip()
            # После неудачного сохранённого входа соединение могло упасть — переподключаемся
            if not client.connected:
                connected = False
                with gevent.Timeout(_CONNECT_TIMEOUT, False):
                    connected = client.connect()
                if not connected:
                    log.warning(
                        "Steam CM: таймаут подключения к CM-серверу (%ds)",
                        _CONNECT_TIMEOUT,
                    )
                    # FIX: та же дыра, что и веткой выше — явный disconnect.
                    client.disconnect()
                    return None

            # _do_interactive_login сам пробует RSA-путь на InvalidPassword
            # (legacy ClientLogon отвергает верный пароль для modern-auth аккаунтов).
            result, username, captured_password = _do_interactive_login(
                client, username
            )

        if result != EResult.OK:
            log.warning(
                "Steam CM: вход не удался: %s", getattr(result, "name", result)
            )
            client.disconnect()
            return None

        # Ждём лицензии
        if not licenses_event.wait(timeout=15):
            log.warning("Steam CM: timeout ожидания списка лицензий")

        print()

        # Даём event loop время обработать ClientUpdateMachineAuth (sentry)
        client.sleep(3)

        if first_login and want_to_save and captured_password:
            _save_session(client.username or username, captured_password)
            log.info(
                "Данные аккаунта Steam сохранены локально в файл: %s",
                _USERNAME_FILE,
            )
            log.info("═" * 80)

        return client
    except BaseException:
        # Любой выход исключением (в т.ч. EOFError из input()/getwch() в cron
        # без stdin) обязан закрыть gevent-соединение — иначе лик клиента.
        # НЕ finally: каждый нормальный (non-exception) путь выше уже
        # отключается сам явно (см. FIX-комментарии) — finally здесь закрывал
        # бы клиента и на успешном `return client`, убивая соединение раньше,
        # чем вызывающий код (cm_session) успеет им воспользоваться.
        try:
            client.disconnect()
        except Exception:
            pass
        raise


@contextlib.contextmanager
def cm_session(
    username: str = "", *, interactive: bool = True
) -> Iterator[Any]:
    """Контекст-менеджер живой сессии Steam CM.

    Логинится через `_cm_login` (JWT → сохранённый пароль → RSA → интерактив)
    и ГАРАНТИРОВАННО отключает клиента на выходе — успех, неуспех логина или
    исключение внутри `with`-блока. Переиспользуемый примитив: раньше вход был
    заперт внутри `read_steam_cm_app_ids`, которая отключалась сразу после
    получения лицензий — новым потребителям (запрос бесплатных лицензий, см.
    app/free_games) нужен ЖИВОЙ клиент для дальнейших вызовов.

    Пример:
        with cm_session() as client:
            if client is None:
                return  # логин не удался — причина уже залогирована
            owned = set(client.licenses.keys())

    Yields:
        SteamClient с заполненным `.licenses` при успехе; None при неуспехе
        логина (все причины уже залогированы `_cm_login` — просто проверь
        `if client is None`).
    """
    client = _cm_login(username, interactive=interactive)
    try:
        yield client
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass


def read_steam_cm_app_ids(
    steam_path: str,
    username: str,
    *,
    interactive: bool = True,
) -> list[int]:
    """Получает App ID всех лицензий аккаунта через Steam CM протокол.

    Args:
        steam_path: путь к папке Steam (нужен для expand_packages_to_apps —
                    чтение локального appcache/packageinfo.vdf)
        username:   логин Steam аккаунта (из конфига или реестра)
        interactive: разрешить интерактивный ввод пароля/2FA.
                     При False возвращает [] если нет сохранённых данных.

    Returns:
        Список всех App ID которые Steam считает принадлежащими аккаунту.
    """
    with cm_session(username, interactive=interactive) as client:
        if client is None:
            return []

        owned_packages = set(client.licenses.keys())
        if not owned_packages:
            log.warning("Steam CM: список лицензий пуст")
            return []

        log.info(
            "Получение ID приложений библиотеки Steam через Steam Client Master"
        )
        return expand_packages_to_apps(steam_path, owned_packages)
```

- [ ] **Step 6: Запустить ВЕСЬ test_steam_cm.py — старые 27 + новые должны быть зелёными**

Run: `pytest tests/unit/test_steam_cm.py -v`
Expected: `33 passed` (27 существующих без изменений + 6 новых из Step 2)

- [ ] **Step 7: Реэкспортировать `cm_session` из `app/steam/__init__.py`**

Файл `app/steam/__init__.py` — заменить целиком:

```python
"""Пакет Steam: Web API, CM протокол, локальные файлы, реестр."""

from .steam_api import fetch_owned_games
from .steam_cm import cm_session, get_web_cookies, read_steam_cm_app_ids
from .steam_id import resolve_steam_id
from .steam_local import find_steam_path, read_library_app_ids

__all__ = [
    "fetch_owned_games",
    "cm_session",
    "get_web_cookies",
    "read_steam_cm_app_ids",
    "resolve_steam_id",
    "find_steam_path",
    "read_library_app_ids",
]
```

- [ ] **Step 8: Полный прогон 4 гейтов + всего юнит-набора**

Run: `ruff check . && ruff format --check . && mypy app && pytest tests/unit -q`
Expected: все 4 команды без ошибок; `pytest tests/unit -q` — все тесты проекта зелёные (не только test_steam_cm.py — рефакторинг мог задеть импорт-граф)

- [ ] **Step 9: Commit**

```bash
git add app/steam/steam_cm.py app/steam/__init__.py tests/unit/test_steam_cm.py
git commit -m "$(cat <<'EOF'
refactor(steam-cm): извлечь cm_session() — переиспользуемый живой CM-клиент

Логин в Steam CM был заперт внутри read_steam_cm_app_ids, которая
отключала клиента сразу после чтения лицензий. Новой фиче
(авто-добавление бесплатных игр) нужен живой клиент для
request_free_license — извлекаю логин в _cm_login()/cm_session()
контекст-менеджер, read_steam_cm_app_ids становится тонким
потребителем поверх него (сигнатура не изменилась).

Попутно закрыты 2 пути (interactive=False без кредов; таймаут
connect() при первом логине), раньше полагавшиеся только на неявный
finally — теперь явный disconnect(), как и остальные пути.

27 существующих тестов CM зелёные без изменений (regression-сеть на
auth-код) + 6 новых на cm_session.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `app/free_games/discovery.py` — обнаружение кандидатов через store search

**Files:**
- Create: `app/free_games/__init__.py`
- Create: `app/free_games/discovery.py`
- Test: `tests/unit/test_free_games_discovery.py`

**Interfaces:**
- Consumes: ничего из проекта (только stdlib `urllib`/`json`/`re`/`time`).
- Produces: `discover_candidates(*, include_demos: bool = True, target_count: int = 3000, page_size: int = 100, max_pages: int = 200) -> list[int]` — используется Task 6 (`orchestrate.py`).

- [ ] **Step 1: Создать пустой пакет**

```python
# app/free_games/__init__.py
"""Пакет авто-добавления бесплатных игр/приложений Steam в библиотеку.

Субмодули:
  discovery    — обнаружение кандидатов через store search (витрина free)
  state        — resume-состояние (candidates/added/refused/error)
  licenses     — батчевый request_free_license + cap-детект + backoff
  report       — честный итоговый отчёт (toast + Telegram)
  orchestrate  — склейка фаз discover/add, точка входа для CLI
"""
```

- [ ] **Step 2: Написать падающий тест `tests/unit/test_free_games_discovery.py`**

```python
"""Тесты обнаружения бесплатных App ID через store search (app/free_games/discovery.py)."""

from __future__ import annotations

import email.message
import json
import urllib.error

from app.free_games import discovery


class _FakeResp:
    """Контекст-менеджер ответа urlopen с валидным JSON-телом."""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _http_error_429() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://store.steampowered.com/x",
        429,
        "Too Many Requests",
        email.message.Message(),
        None,
    )


def _page_payload(appids: list[int], total_count: int) -> dict:
    html = "".join(f'<a data-ds-appid="{a}">x</a>' for a in appids)
    return {
        "success": 1,
        "results_html": html,
        "total_count": total_count,
        "start": 0,
    }


def test_search_page_parses_appids_and_total_count(monkeypatch):
    monkeypatch.setattr(
        discovery.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(_page_payload([730, 570], 19691)),
    )
    appids, total = discovery._search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == [730, 570]
    assert total == 19691


def test_search_page_maxprice_free_only_when_requested(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        return _FakeResp(_page_payload([], 0))

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)

    discovery._search_page(
        category1=10, start=0, count=100, maxprice_free=False
    )
    assert "maxprice=free" not in captured["url"]

    discovery._search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert "maxprice=free" in captured["url"]


def test_collect_category_paginates_until_target_reached(monkeypatch):
    # 2 страницы по 2 id, target_count=3 -> должно остановиться после 2-й
    # страницы (набрали 4 >= 3), не продолжая до конца total_count.
    pages = [_page_payload([1, 2], 100), _page_payload([3, 4], 100)]
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        resp = _FakeResp(pages[calls["n"]])
        calls["n"] += 1
        return resp

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_a: None)

    out = discovery._collect_category(
        category1=998,
        maxprice_free=True,
        target_count=3,
        page_size=2,
        max_pages=50,
    )
    assert out == [1, 2, 3, 4]
    assert calls["n"] == 2


def test_collect_category_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(
        discovery.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(_page_payload([], 0)),
    )
    out = discovery._collect_category(
        category1=998,
        maxprice_free=True,
        target_count=100,
        page_size=50,
        max_pages=50,
    )
    assert out == []


def test_collect_category_dedups_within_category(monkeypatch):
    pages = [_page_payload([1, 2], 100), _page_payload([2, 3], 100)]
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        resp = _FakeResp(pages[calls["n"]])
        calls["n"] += 1
        return resp

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_a: None)

    out = discovery._collect_category(
        category1=998,
        maxprice_free=True,
        target_count=10,
        page_size=2,
        max_pages=2,
    )
    assert out == [1, 2, 3]  # 2 не задублирован


def test_search_page_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error_429()
        return _FakeResp(_page_payload([730], 1))

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_a: None)

    appids, total = discovery._search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == [730]
    assert calls["n"] == 2


def test_search_page_network_error_returns_empty(monkeypatch):
    def fake_urlopen(req, timeout=15):
        raise OSError("connection reset")

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    appids, total = discovery._search_page(
        category1=998, start=0, count=100, maxprice_free=True
    )
    assert appids == []
    assert total == 0


def test_discover_candidates_merges_and_dedups_across_sources(monkeypatch):
    call_order = []

    def fake_collect(*, category1, maxprice_free, **_kw):
        call_order.append(category1)
        return {
            discovery._CATEGORY_GAMES: [1, 2],
            discovery._CATEGORY_SOFTWARE: [2, 3],
            discovery._CATEGORY_DEMOS: [3, 4],
        }[category1]

    monkeypatch.setattr(discovery, "_collect_category", fake_collect)
    out = discovery.discover_candidates(include_demos=True)
    assert out == [1, 2, 3, 4]
    assert call_order == [998, 994, 10]


def test_discover_candidates_skips_demos_when_disabled(monkeypatch):
    def fake_collect(*, category1, **_kw):
        assert category1 != discovery._CATEGORY_DEMOS
        return [1]

    monkeypatch.setattr(discovery, "_collect_category", fake_collect)
    out = discovery.discover_candidates(include_demos=False)
    assert out == [1]
```

- [ ] **Step 3: Запустить тест — убедиться, что падает (модуль не существует)**

Run: `pytest tests/unit/test_free_games_discovery.py -v`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'app.free_games.discovery'`

- [ ] **Step 4: Реализовать `app/free_games/discovery.py`**

```python
"""Обнаружение бесплатных App ID Steam через неофициальный store search API.

Источник — store.steampowered.com/search/results/ (используется самим
сторефронтом для живого поиска; официально Valve его не документирует).
Проверено вживую (2026-07-17): count=100 — макс. размер страницы, пагинация
через start/count работает, total_count в ответе — общее число совпадений.

Три категории (category1):
  998 = Games (дефолт витрины)      + maxprice=free → F2P-игры
  994 = Software                     + maxprice=free → бесплатные не-игровые app
  10  = Demos (демо всегда бесплатны — maxprice=free НЕ нужен и не запрашивается)

Потолок free-лицензий аккаунта ~1000-2000, поэтому набираем кандидатов с
запасом (target_count), а не весь каталог (~20k только по одной категории
Games+maxprice=free — см. total_count в живой проверке).

Ретрай на 429/сеть — свой, не через app.steam.steam_api._api_get: другой
хост (store vs api.steampowered.com) и другая форма ответа (results_html,
не типизированный JSON) — reuse через приватные символы неродственного
модуля добавил бы связность без реальной экономии (~10 строк).
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("sam_automation")

_SEARCH_URL = "https://store.steampowered.com/search/results/"
_USER_AGENT = "Mozilla/5.0 (sam-automation)"

_CATEGORY_GAMES = 998
_CATEGORY_SOFTWARE = 994
_CATEGORY_DEMOS = 10

_APPID_RE = re.compile(r'data-ds-appid="(\d+)"')

# Ограниченный ретрай на 429 — не крутимся вечно на "злом" ответе витрины.
_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0
_PAGE_DELAY = 0.5  # пауза между страницами — не долбить витрину без нужды


def _search_page(
    *, category1: int, start: int, count: int, maxprice_free: bool
) -> tuple[list[int], int]:
    """Одна страница store search. Возвращает (appids, total_count).

    Сетевой/JSON сбой после исчерпания ретраев → ([], 0), не исключение —
    вызывающая пагинация (_collect_category) трактует пустой список как
    конец результатов (частичная выборка допустима, полнота не обещана).
    """
    params = (
        f"query&start={start}&count={count}&category1={category1}"
        f"&supportedlang=english&json=1&infinite=1"
    )
    if maxprice_free:
        params += "&maxprice=free"
    url = f"{_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    for attempt in range(_RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            appids = [
                int(m) for m in _APPID_RE.findall(data.get("results_html", ""))
            ]
            return appids, int(data.get("total_count", 0))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < _RETRY_ATTEMPTS - 1:
                log.warning(
                    "Store search 429 (попытка %d/%d) — жду %.0fс",
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                    _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)
                continue
            log.warning("Store search вернул %s: %s", e.code, e.reason)
            return [], 0
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            log.warning("Store search сетевой сбой: %s", e)
            return [], 0
        except ValueError as e:
            log.warning("Store search вернул не-JSON ответ: %s", e)
            return [], 0
    return [], 0  # недостижимо (цикл всегда return'ит) — для mypy


def _collect_category(
    *,
    category1: int,
    maxprice_free: bool,
    target_count: int,
    page_size: int,
    max_pages: int,
) -> list[int]:
    """Пагинирует одну категорию до target_count кандидатов или конца/max_pages."""
    seen: set[int] = set()
    out: list[int] = []
    start = 0
    for _page in range(max_pages):
        appids, total_count = _search_page(
            category1=category1,
            start=start,
            count=page_size,
            maxprice_free=maxprice_free,
        )
        if not appids:
            break  # пустая страница — конец результатов ИЛИ сбой (уже залогирован)
        for appid in appids:
            if appid not in seen:
                seen.add(appid)
                out.append(appid)
        start += page_size
        if len(out) >= target_count or start >= total_count:
            break
        time.sleep(_PAGE_DELAY)
    return out


def discover_candidates(
    *,
    include_demos: bool = True,
    target_count: int = 3000,
    page_size: int = 100,
    max_pages: int = 200,
) -> list[int]:
    """Собирает кандидатов на бесплатное добавление из витрины Steam.

    Три источника: F2P-игры (category1=998+maxprice=free), бесплатные
    не-игровые app (category1=994+maxprice=free), демо (category1=10,
    include_demos=False пропускает — демо съедают ограниченный потолок
    лицензий и истекают). Дедуп между источниками. Не гарантирует полноту
    каталога — набирает достаточно кандидатов с запасом относительно
    потолка free-лицензий аккаунта (~1000-2000).
    """
    seen: set[int] = set()
    out: list[int] = []

    def _merge(ids: list[int]) -> None:
        for appid in ids:
            if appid not in seen:
                seen.add(appid)
                out.append(appid)

    log.info("Store search: обнаружение F2P-игр (maxprice=free)")
    _merge(
        _collect_category(
            category1=_CATEGORY_GAMES,
            maxprice_free=True,
            target_count=target_count,
            page_size=page_size,
            max_pages=max_pages,
        )
    )
    log.info("Store search: найдено кандидатов (игры): %d", len(out))

    log.info("Store search: обнаружение бесплатных приложений")
    _merge(
        _collect_category(
            category1=_CATEGORY_SOFTWARE,
            maxprice_free=True,
            target_count=target_count,
            page_size=page_size,
            max_pages=max_pages,
        )
    )
    log.info("Store search: найдено кандидатов (игры+app): %d", len(out))

    if include_demos:
        log.info("Store search: обнаружение демо")
        _merge(
            _collect_category(
                category1=_CATEGORY_DEMOS,
                maxprice_free=False,
                target_count=target_count,
                page_size=page_size,
                max_pages=max_pages,
            )
        )
        log.info("Store search: найдено кандидатов (+демо): %d", len(out))

    return out
```

- [ ] **Step 5: Запустить тесты — все зелёные**

Run: `pytest tests/unit/test_free_games_discovery.py -v`
Expected: `10 passed`

- [ ] **Step 6: Гейты + commit**

```bash
ruff check . && ruff format --check . && mypy app && pytest tests/unit -q
git add app/free_games/__init__.py app/free_games/discovery.py tests/unit/test_free_games_discovery.py
git commit -m "$(cat <<'EOF'
feat(free-games): обнаружение бесплатных App ID через store search

Discovery-фаза: неофициальный store.steampowered.com/search/results/
(проверен вживую) — category1=998+maxprice=free для F2P-игр,
994+maxprice=free для бесплатных не-игровых app, 10 для демо (без
maxprice — демо всегда бесплатны). Пагинация до target_count с
запасом относительно потолка free-лицензий аккаунта (~1000-2000),
не весь каталог. Ретрай на 429, дедуп между источниками.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `app/free_games/state.py` — resume-состояние

**Files:**
- Create: `app/free_games/state.py`
- Test: `tests/unit/test_free_games_state.py`

**Interfaces:**
- Consumes: `app.cache.GAMES_DIR`; `app.id_file._append_id`, `_atomic_write_text`, `load_ids_file`, `read_ids_ordered` (те же приватные примитивы, что использует `app/cache.py` — `id_file.py`'s docstring явно называет себя переиспользуемым несколькими доменными модулями).
- Produces: `CANDIDATES_FILE/ADDED_FILE/REFUSED_FILE/ERROR_FILE` (пути), `load_candidates/save_candidates/load_added_ids/load_refused_ids/load_error_ids/mark_added/mark_refused/mark_error/clear_error_ids/clear_state` — используются Task 6.

- [ ] **Step 1: Написать падающий тест `tests/unit/test_free_games_state.py`**

```python
"""Тесты resume-состояния app/free_games/state.py (candidates/added/refused/error)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.free_games.state as state_mod


def _patch_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        state_mod, "CANDIDATES_FILE", tmp_path / "candidates.txt"
    )
    monkeypatch.setattr(state_mod, "ADDED_FILE", tmp_path / "added.txt")
    monkeypatch.setattr(state_mod, "REFUSED_FILE", tmp_path / "refused.txt")
    monkeypatch.setattr(state_mod, "ERROR_FILE", tmp_path / "error.txt")


def test_load_candidates_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    assert state_mod.load_candidates() == []


def test_save_and_load_candidates_sorted_deduped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.save_candidates([730, 10, 730, 440])
    assert state_mod.load_candidates() == [10, 440, 730]


def test_mark_added_and_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_added(730)
    state_mod.mark_added(10)
    assert state_mod.load_added_ids() == {730, 10}


def test_mark_refused_and_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_refused(440)
    assert state_mod.load_refused_ids() == {440}


def test_mark_error_and_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_error(20)
    assert state_mod.load_error_ids() == {20}


def test_clear_error_ids_removes_only_error_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.mark_added(730)
    state_mod.mark_error(20)
    state_mod.clear_error_ids()
    assert state_mod.load_error_ids() == set()
    assert state_mod.load_added_ids() == {730}  # added не тронут


def test_clear_state_removes_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all(monkeypatch, tmp_path)
    state_mod.save_candidates([730])
    state_mod.mark_added(730)
    state_mod.mark_refused(10)
    state_mod.mark_error(20)
    state_mod.clear_state()
    assert state_mod.load_candidates() == []
    assert state_mod.load_added_ids() == set()
    assert state_mod.load_refused_ids() == set()
    assert state_mod.load_error_ids() == set()
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `pytest tests/unit/test_free_games_state.py -v`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'app.free_games.state'`

- [ ] **Step 3: Реализовать `app/free_games/state.py`**

```python
"""Resume-состояние авто-добавления бесплатных игр Steam.

Примитивы id-файлов — из app.id_file (та же атомарная запись/дедуп, что и в
app/cache.py — id_file.py явно спроектирован для переиспользования разными
доменными модулями). Свой каталог data/games/ids/free/, не пересекается с
achievements/cards/playtime.

  candidates.txt — обнаруженные кандидаты (вход фазы add)
  added.txt      — успешно выданные лицензии (granted)
  refused.txt    — CM отказал — ТЕРМИНАЛЬНО, skip-on-resume
  error.txt      — транзиентная ошибка — восстановим --retry-errors
"""

from __future__ import annotations

from app.cache import GAMES_DIR
from app.id_file import (
    _append_id,
    _atomic_write_text,
    load_ids_file,
    read_ids_ordered,
)

_FREE_DIR = GAMES_DIR / "ids" / "free"

CANDIDATES_FILE = _FREE_DIR / "candidates.txt"
ADDED_FILE = _FREE_DIR / "added.txt"
REFUSED_FILE = _FREE_DIR / "refused.txt"
ERROR_FILE = _FREE_DIR / "error.txt"


def load_candidates() -> list[int]:
    """candidates.txt с сохранением порядка обнаружения (дедуп первых вхождений)."""
    return read_ids_ordered(CANDIDATES_FILE)


def save_candidates(appids: list[int]) -> None:
    """Атомарно перезаписывает candidates.txt (числовая сортировка, дедуп)."""
    _atomic_write_text(
        CANDIDATES_FILE, "\n".join(str(i) for i in sorted(set(appids))) + "\n"
    )


def load_added_ids() -> set[int]:
    return load_ids_file(ADDED_FILE)


def load_refused_ids() -> set[int]:
    return load_ids_file(REFUSED_FILE)


def load_error_ids() -> set[int]:
    return load_ids_file(ERROR_FILE)


def mark_added(appid: int) -> None:
    _append_id(ADDED_FILE, appid)


def mark_refused(appid: int) -> None:
    _append_id(REFUSED_FILE, appid)


def mark_error(appid: int) -> None:
    _append_id(ERROR_FILE, appid)


def clear_error_ids() -> None:
    """Удаляет error.txt (для --retry-errors — только транзиент, НЕ refused)."""
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()


def clear_state() -> None:
    """Удаляет ВСЁ resume-состояние (--reset): candidates/added/refused/error."""
    for path in (CANDIDATES_FILE, ADDED_FILE, REFUSED_FILE, ERROR_FILE):
        if path.exists():
            path.unlink()
```

- [ ] **Step 4: Запустить тесты — все зелёные**

Run: `pytest tests/unit/test_free_games_state.py -v`
Expected: `7 passed`

- [ ] **Step 5: Гейты + commit**

```bash
ruff check . && ruff format --check . && mypy app && pytest tests/unit -q
git add app/free_games/state.py tests/unit/test_free_games_state.py
git commit -m "$(cat <<'EOF'
feat(free-games): resume-состояние candidates/added/refused/error

Свой каталог data/games/ids/free/ на примитивах app.id_file (та же
атомарная запись, что и app/cache.py). refused.txt терминален
(skip-on-resume), error.txt — транзиент (восстановим --retry-errors).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `app/free_games/licenses.py` — батчевый `request_free_license`

**Files:**
- Create: `app/free_games/licenses.py`
- Test: `tests/unit/test_free_games_licenses.py`

**Interfaces:**
- Consumes: живой клиент (duck-typed, `client.request_free_license(app_ids) -> (EResult, granted_appids, granted_packageids)` — реальная сигнатура из `steam/client/builtins/apps.py:338` установленной библиотеки, проверена в исходнике).
- Produces: `AddResult` (dataclass: `added: list[int]`, `refused: list[int]`, `error: list[int]`, `hit_cap: bool`), `add_licenses(client, appids, *, batch_size=BATCH_SIZE) -> AddResult` — используется Task 6.

### Cap/rate-limit семантика (проверено в `steam/enums/common.py` установленной библиотеки)

```
LimitExceeded = 25       # "Too much of a good thing" — МОЖЕТ быть перманентным → СТЕНА, стоп
RateLimitExceeded = 84   # "Temporary ... different from k_EResultLimitExceeded which may be permanent" → backoff, продолжаем
```

- [ ] **Step 1: Написать падающий тест `tests/unit/test_free_games_licenses.py`**

```python
"""Тесты батчевого добавления бесплатных лицензий (app/free_games/licenses.py)."""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from steam.enums import EResult  # noqa: E402

from app.free_games import licenses  # noqa: E402


class _FakeClient:
    """Двойник SteamClient.request_free_license — очередь ответов по батчам."""

    def __init__(self, responses: list[tuple]) -> None:
        self._responses = list(responses)
        self.calls: list[list[int]] = []

    def request_free_license(self, app_ids):
        self.calls.append(list(app_ids))
        return self._responses.pop(0)


def test_add_licenses_single_batch_all_granted():
    client = _FakeClient([(EResult.OK, [1, 2, 3], [])])
    result = licenses.add_licenses(client, [1, 2, 3], batch_size=50)
    assert result.added == [1, 2, 3]
    assert result.refused == []
    assert result.error == []
    assert result.hit_cap is False
    assert client.calls == [[1, 2, 3]]


def test_add_licenses_partial_grant_rest_refused():
    client = _FakeClient([(EResult.OK, [1], [])])
    result = licenses.add_licenses(client, [1, 2, 3], batch_size=50)
    assert result.added == [1]
    assert result.refused == [2, 3]


def test_add_licenses_multiple_batches(monkeypatch):
    monkeypatch.setattr(licenses.time, "sleep", lambda *_a: None)
    client = _FakeClient(
        [(EResult.OK, [1, 2], []), (EResult.OK, [3, 4], [])]
    )
    result = licenses.add_licenses(client, [1, 2, 3, 4], batch_size=2)
    assert result.added == [1, 2, 3, 4]
    assert client.calls == [[1, 2], [3, 4]]


def test_add_licenses_limit_exceeded_stops_immediately(monkeypatch):
    monkeypatch.setattr(licenses.time, "sleep", lambda *_a: None)
    client = _FakeClient(
        [
            (EResult.OK, [1, 2], []),
            (EResult.LimitExceeded, None, None),
            (EResult.OK, [5, 6], []),  # НЕ должен быть вызван
        ]
    )
    result = licenses.add_licenses(client, [1, 2, 3, 4, 5, 6], batch_size=2)
    assert result.added == [1, 2]
    assert result.hit_cap is True
    assert client.calls == [[1, 2], [3, 4]]  # третий батч не запрошен


def test_add_licenses_rate_limit_retries_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(licenses.time, "sleep", lambda s: sleeps.append(s))
    client = _FakeClient(
        [(EResult.RateLimitExceeded, None, None), (EResult.OK, [1, 2], [])]
    )
    result = licenses.add_licenses(client, [1, 2], batch_size=50)
    assert result.added == [1, 2]
    assert result.hit_cap is False
    assert sleeps == [licenses._RATE_LIMIT_BASE_DELAY]
    assert len(client.calls) == 2  # ретрай на ТОМ ЖЕ батче


def test_add_licenses_rate_limit_exhausted_goes_to_error(monkeypatch):
    monkeypatch.setattr(licenses.time, "sleep", lambda *_a: None)
    responses = [
        (EResult.RateLimitExceeded, None, None)
    ] * licenses._RATE_LIMIT_ATTEMPTS
    client = _FakeClient(responses)
    result = licenses.add_licenses(client, [1, 2], batch_size=50)
    assert result.error == [1, 2]
    assert result.added == []
    assert result.hit_cap is False


def test_add_licenses_exception_goes_to_error():
    class _BoomClient:
        def request_free_license(self, app_ids):
            raise ConnectionResetError("нет связи")

    result = licenses.add_licenses(_BoomClient(), [1, 2], batch_size=50)
    assert result.error == [1, 2]
    assert result.added == []


def test_add_licenses_empty_input_no_calls():
    client = _FakeClient([])
    result = licenses.add_licenses(client, [], batch_size=50)
    assert result == licenses.AddResult()
    assert client.calls == []
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `pytest tests/unit/test_free_games_licenses.py -v`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'app.free_games.licenses'`

- [ ] **Step 3: Реализовать `app/free_games/licenses.py`**

```python
"""Батчевый запрос бесплатных лицензий через живой Steam CM клиент.

client.request_free_license(app_ids) -> (EResult, granted_appids,
granted_packageids) — реальная сигнатура из steam/client/builtins/apps.py
установленной библиотеки (send_job_and_wait на ClientRequestFreeLicense,
таймаут 10с внутри библиотеки). Вызывается на живом клиенте из
app.steam.steam_cm.cm_session().

Классификация EResult (см. steam/enums/common.py):
  LimitExceeded (25)      — потолок лицензий аккаунта, МОЖЕТ быть
                             перманентным (комментарий в самой библиотеке) —
                             СТЕНА, стоп немедленно.
  RateLimitExceeded (84)  — временный (комментарий: "different from
                             k_EResultLimitExceeded which may be permanent")
                             — экспоненциальный backoff, продолжаем.
  всё остальное           — granted_appids авторитетен независимо от
                             точного eresult (напр. DuplicateRequest на
                             частично уже выданном батче всё равно granted'ит
                             новые): appid из батча, которого нет в granted,
                             считается refused.
  исключение при вызове   — error (appid из батча, транзиент — восстановим
                             --retry-errors).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("sam_automation")

BATCH_SIZE = 50
_RATE_LIMIT_ATTEMPTS = 3
_RATE_LIMIT_BASE_DELAY = 2.0
_RATE_LIMIT_DELAY_CAP = 60.0
_BATCH_PAUSE = 1.0  # пауза между батчами — не долбить CM без нужды


@dataclass
class AddResult:
    """Итог одного прогона добавления лицензий."""

    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False


@dataclass
class _BatchOutcome:
    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_cap: bool = False


def _batches(appids: list[int], size: int) -> list[list[int]]:
    return [appids[i : i + size] for i in range(0, len(appids), size)]


def _request_batch_with_backoff(
    client: Any, batch: list[int], eresult_cls: Any
) -> _BatchOutcome:
    """Один батч с ретраем на RateLimitExceeded (экспоненциальный backoff)."""
    delay = _RATE_LIMIT_BASE_DELAY
    for attempt in range(_RATE_LIMIT_ATTEMPTS):
        try:
            eresult, granted_appids, _granted_packageids = (
                client.request_free_license(batch)
            )
        except Exception as e:
            log.warning("Steam CM: request_free_license упал: %s", e)
            return _BatchOutcome(error=list(batch))

        if eresult == eresult_cls.LimitExceeded:
            return _BatchOutcome(hit_cap=True)

        if eresult == eresult_cls.RateLimitExceeded:
            if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                log.warning("Steam CM: rate limit не отступил — батч в error")
                return _BatchOutcome(error=list(batch))
            log.warning(
                "Steam CM: rate limit (попытка %d/%d) — жду %.0fс",
                attempt + 1,
                _RATE_LIMIT_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, _RATE_LIMIT_DELAY_CAP)
            continue

        granted = {int(a) for a in (granted_appids or [])}
        refused = [a for a in batch if a not in granted]
        if refused:
            log.info(
                "Steam CM: отказано в лицензии (%s): %s",
                getattr(eresult, "name", eresult),
                refused,
            )
        return _BatchOutcome(added=sorted(granted), refused=refused)

    return _BatchOutcome(error=list(batch))  # недостижимо — для mypy


def add_licenses(
    client: Any, appids: list[int], *, batch_size: int = BATCH_SIZE
) -> AddResult:
    """Запрашивает бесплатные лицензии батчами на живом CM-клиенте.

    Останавливается немедленно при EResult.LimitExceeded (потолок аккаунта —
    hit_cap=True, оставшиеся батчи НЕ запрашиваются). RateLimitExceeded —
    backoff, продолжает после восстановления. Прочие неуспехи — refused
    (appid из батча, которого нет в granted_appids). Исключение при вызове —
    error (appid из батча, транзиент — восстановим --retry-errors).
    """
    from steam.enums import EResult

    result = AddResult()
    batches = _batches(appids, batch_size)

    for i, batch in enumerate(batches):
        outcome = _request_batch_with_backoff(client, batch, EResult)
        if outcome.hit_cap:
            result.hit_cap = True
            log.warning(
                "Steam CM: потолок free-лицензий аккаунта (LimitExceeded) — "
                "стоп. Добавлено в этом прогоне: %d",
                len(result.added),
            )
            break
        result.added.extend(outcome.added)
        result.refused.extend(outcome.refused)
        result.error.extend(outcome.error)
        if i < len(batches) - 1:
            time.sleep(_BATCH_PAUSE)

    return result
```

- [ ] **Step 4: Запустить тесты — все зелёные**

Run: `pytest tests/unit/test_free_games_licenses.py -v`
Expected: `8 passed`

- [ ] **Step 5: Гейты + commit**

```bash
ruff check . && ruff format --check . && mypy app && pytest tests/unit -q
git add app/free_games/licenses.py tests/unit/test_free_games_licenses.py
git commit -m "$(cat <<'EOF'
feat(free-games): батчевый request_free_license с cap-детектом

add_licenses() батчами по живому CM-клиенту (client.request_free_
license — сигнатура сверена с исходником steam/client/builtins/
apps.py). EResult.LimitExceeded (потолок, может быть перманентным) —
немедленный стоп; RateLimitExceeded (временный) — экспоненциальный
backoff. granted_appids авторитетен для added/refused-классификации
независимо от точного eresult. Исключение при вызове → error
(восстановим --retry-errors).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `app/free_games/report.py` — честный отчёт

**Files:**
- Create: `app/free_games/report.py`
- Test: `tests/unit/test_free_games_report.py`

**Interfaces:**
- Consumes: `app.logging_setup.SEPARATOR`; `app.notify.toast`, `send_telegram`.
- Produces: `report_result(*, status: str, added: int, refused: int, error: int, hit_cap: bool, cfg: Any) -> None` — используется Task 6. `status` — один из `"ok" | "interrupted" | "error" | "dry_run"`.

- [ ] **Step 1: Написать падающий тест `tests/unit/test_free_games_report.py`**

```python
"""Тесты честного отчёта app/free_games/report.py."""

from __future__ import annotations

from types import SimpleNamespace

import app.free_games.report as report_mod


def _cfg() -> SimpleNamespace:
    return SimpleNamespace()


def _capture(monkeypatch) -> dict:
    calls: dict = {}
    monkeypatch.setattr(
        report_mod, "toast", lambda t, m: calls.setdefault("toast", (t, m))
    )
    monkeypatch.setattr(
        report_mod,
        "send_telegram",
        lambda text, cfg: calls.setdefault("tg", text),
    )
    return calls


def test_report_ok_status_marks_success(monkeypatch):
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=5, refused=0, error=0, hit_cap=False, cfg=_cfg()
    )
    assert "готово" in calls["toast"][1]
    assert "✅" in calls["tg"]


def test_report_hit_cap_never_says_all_added(monkeypatch):
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok",
        added=1200,
        refused=0,
        error=0,
        hit_cap=True,
        cfg=_cfg(),
    )
    assert "стена" in calls["toast"][1]
    assert "⚠️" in calls["tg"]  # НЕ ✅ — упор в лимит не чистый успех


def test_report_interrupted_never_marks_success(monkeypatch):
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="interrupted",
        added=3,
        refused=0,
        error=0,
        hit_cap=False,
        cfg=_cfg(),
    )
    assert "прервано" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_error_status_marks_qualified(monkeypatch):
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="error", added=1, refused=0, error=0, hit_cap=False, cfg=_cfg()
    )
    assert "прервано ошибкой" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_refused_or_error_marks_qualified(monkeypatch):
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=5, refused=2, error=0, hit_cap=False, cfg=_cfg()
    )
    assert "оговорками" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_dry_run_marks_success_without_adding(monkeypatch):
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="dry_run",
        added=0,
        refused=0,
        error=0,
        hit_cap=False,
        cfg=_cfg(),
    )
    assert "dry-run" in calls["toast"][1]
    assert "✅" in calls["tg"]
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `pytest tests/unit/test_free_games_report.py -v`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'app.free_games.report'`

- [ ] **Step 3: Реализовать `app/free_games/report.py`**

```python
"""Честный итоговый отчёт авто-добавления бесплатных игр (toast + Telegram).

status="ok" с hit_cap=True НИКОГДА не даёт ✅ — упор в потолок лицензий не
считается чистым успехом (инвариант честного отчёта проекта, см. другие
скрипты: cookie-ошибка/застревание не пишут success-тост).
"""

from __future__ import annotations

from typing import Any

from app.logging_setup import SEPARATOR
from app.notify import send_telegram, toast

import logging

log = logging.getLogger("sam_automation")


def report_result(
    *,
    status: str,
    added: int,
    refused: int,
    error: int,
    hit_cap: bool,
    cfg: Any,
) -> None:
    """Честный финальный отчёт (лог + toast + Telegram).

    status: "ok" | "interrupted" | "error" | "dry_run".
    """
    if status == "dry_run":
        head, ok = "dry-run (ничего не добавлено)", True
    elif status == "interrupted":
        head, ok = "прервано (Ctrl+C)", False
    elif status == "error":
        head, ok = "прервано ошибкой", False
    elif hit_cap:
        head, ok = "упор в стену (потолок лицензий)", False
    elif refused or error:
        head, ok = "готово с оговорками", False
    else:
        head, ok = "готово", True

    detail = f"добавлено {added}, отказано {refused}, ошибок {error}"
    if hit_cap:
        detail += " — дальше стена"

    log.info(SEPARATOR)
    log.info("Добавление бесплатных игр — %s. %s", head, detail)
    log.info(SEPARATOR)
    toast("SAM Automation — Free Games", f"{head}: {detail}")
    mark = "✅" if ok else "⚠️"
    send_telegram(f"{mark} Free games — {head}: {detail}", cfg)
```

- [ ] **Step 4: Запустить тесты — все зелёные**

Run: `pytest tests/unit/test_free_games_report.py -v`
Expected: `6 passed`

- [ ] **Step 5: Гейты + commit**

```bash
ruff check . && ruff format --check . && mypy app && pytest tests/unit -q
git add app/free_games/report.py tests/unit/test_free_games_report.py
git commit -m "$(cat <<'EOF'
feat(free-games): честный итоговый отчёт (toast + Telegram)

report_result() — hit_cap=True (упор в потолок лицензий) и
interrupted/error НИКОГДА не дают success-маркер, как и остальные
скрипты проекта (cookie-ошибка/застревание не пишут success-тост).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `app/free_games/orchestrate.py` — склейка фаз discover/add

**Files:**
- Modify: `app/free_games/__init__.py` (реэкспорт `run`, `AddResult`)
- Create: `app/free_games/orchestrate.py`
- Test: `tests/unit/test_free_games_orchestrate.py`

**Interfaces:**
- Consumes: `app.free_games.discovery.discover_candidates`, `app.free_games.state.*`, `app.free_games.licenses.add_licenses` + `AddResult`, `app.free_games.report.report_result`, `app.steam.steam_cm.cm_session`, `app.steam.packageinfo.expand_packages_to_apps`, `app.steam.steam_local.find_steam_path`.
- Produces: `discover(*, include_demos: bool = True) -> list[int]`, `add(*, limit: int | None = None) -> licenses.AddResult`, `run(*, do_add: bool, list_only: bool, limit: int | None, include_demos: bool, cfg: Any) -> None` — используется Task 7 (CLI).

- [ ] **Step 1: Написать падающий тест `tests/unit/test_free_games_orchestrate.py`**

```python
"""Тесты оркестрации discover/add (app/free_games/orchestrate.py)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.free_games.orchestrate as orch
import app.free_games.state as state_mod


def _patch_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        state_mod, "CANDIDATES_FILE", tmp_path / "candidates.txt"
    )
    monkeypatch.setattr(state_mod, "ADDED_FILE", tmp_path / "added.txt")
    monkeypatch.setattr(state_mod, "REFUSED_FILE", tmp_path / "refused.txt")
    monkeypatch.setattr(state_mod, "ERROR_FILE", tmp_path / "error.txt")


class _FakeClient:
    def __init__(self, licenses: dict) -> None:
        self.licenses = licenses


def _fake_cm_session(client):
    @contextlib.contextmanager
    def _cm(*_a, **_k):
        yield client

    return _cm


# ── discover(): owned/added/refused вычитание ───────────────────────────────


def test_discover_subtracts_owned_added_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2, 3, 4, 5]
    )
    monkeypatch.setattr(orch, "find_steam_path", lambda: "C:/steam")
    monkeypatch.setattr(
        orch, "cm_session", _fake_cm_session(_FakeClient({999: object()}))
    )
    monkeypatch.setattr(orch, "expand_packages_to_apps", lambda _p, _pk: [2])

    state_mod.mark_added(3)
    state_mod.mark_refused(4)

    result = orch.discover(include_demos=True)

    assert result == [1, 5]  # 2=owned, 3=added, 4=refused исключены
    assert state_mod.load_candidates() == [1, 5]


def test_discover_no_steam_path_skips_owned_subtraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2]
    )
    monkeypatch.setattr(orch, "find_steam_path", lambda: "")

    result = orch.discover(include_demos=True)

    assert result == [1, 2]  # ничего не вычтено — Steam не найден


def test_discover_cm_login_failed_skips_owned_subtraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2]
    )
    monkeypatch.setattr(orch, "find_steam_path", lambda: "C:/steam")
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(None))

    result = orch.discover(include_demos=True)

    assert result == [1, 2]  # логин не удался — owned не вычтен, не падаем


# ── add(): resume-skip + limit + cm_session=None ────────────────────────────


def test_add_skips_already_processed_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3, 4])
    state_mod.mark_added(1)
    state_mod.mark_refused(2)
    state_mod.mark_error(3)

    captured = {}

    def fake_add_licenses(client, appids, **_k):
        captured["appids"] = appids
        return orch.licenses.AddResult(added=appids)

    monkeypatch.setattr(orch.licenses, "add_licenses", fake_add_licenses)
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(_FakeClient({})))

    result = orch.add()

    assert captured["appids"] == [4]  # только 4 не обработан
    assert result.added == [4]
    assert state_mod.load_added_ids() == {1, 4}


def test_add_respects_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3])

    captured = {}

    def fake_add_licenses(client, appids, **_k):
        captured["appids"] = appids
        return orch.licenses.AddResult(added=appids)

    monkeypatch.setattr(orch.licenses, "add_licenses", fake_add_licenses)
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(_FakeClient({})))

    orch.add(limit=2)

    assert captured["appids"] == [1, 2]


def test_add_no_pending_returns_empty_without_cm_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1])
    state_mod.mark_added(1)

    def _boom(*_a, **_k):
        raise AssertionError("cm_session не должен вызываться без кандидатов")

    monkeypatch.setattr(orch, "cm_session", _boom)

    result = orch.add()

    assert result == orch.licenses.AddResult()


def test_add_cm_login_failed_marks_all_pending_as_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(None))

    result = orch.add()

    assert result.error == [1, 2]
    assert state_mod.load_error_ids() == {1, 2}


# ── run(): dry-run / --add / --list ветвление ────────────────────────────────


def test_run_list_only_does_not_call_discover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])

    def _boom(**_k):
        raise AssertionError("discover не должен вызываться при --list")

    monkeypatch.setattr(orch, "discover", _boom)

    orch.run(
        do_add=False,
        list_only=True,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )


def test_run_dry_run_reports_without_adding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2, 3])

    captured = {}
    monkeypatch.setattr(
        orch.report,
        "report_result",
        lambda **kw: captured.update(kw),
    )

    def _boom(**_k):
        raise AssertionError("add не должен вызываться без --add")

    monkeypatch.setattr(orch, "add", _boom)

    orch.run(
        do_add=False,
        list_only=False,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "dry_run"
    assert captured["added"] == 3


def test_run_add_reports_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch,
        "add",
        lambda **_k: orch.licenses.AddResult(added=[1, 2]),
    )

    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "ok"
    assert captured["added"] == 2


def test_run_add_exception_reports_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])

    def _boom(**_k):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(orch, "add", _boom)

    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"


def test_run_add_keyboard_interrupt_reports_interrupted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])

    def _boom(**_k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(orch, "add", _boom)

    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "interrupted"
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `pytest tests/unit/test_free_games_orchestrate.py -v`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'app.free_games.orchestrate'`

- [ ] **Step 3: Реализовать `app/free_games/orchestrate.py`**

```python
"""Оркестрация авто-добавления бесплатных игр Steam: discover + add фазы."""

from __future__ import annotations

import logging
from typing import Any

from app.free_games import discovery, licenses, report, state
from app.logging_setup import SEPARATOR
from app.steam.packageinfo import expand_packages_to_apps
from app.steam.steam_cm import cm_session
from app.steam.steam_local import find_steam_path

log = logging.getLogger("sam_automation")


def discover(*, include_demos: bool = True) -> list[int]:
    """Фаза discover: витрина free → candidates.txt минус owned/added/refused.

    owned вычисляется из client.licenses живой CM-сессии (authoritative для
    аккаунта) через expand_packages_to_apps — тот же путь, что и scan.py.
    Отсутствие Steam или неуспех CM-логина НЕ роняет discover — просто owned
    не вычитается (кандидаты могут включать уже имеющееся, лишнее отсеется
    на фазе add как DuplicateRequest/refused).
    """
    log.info(SEPARATOR)
    discovered = discovery.discover_candidates(include_demos=include_demos)
    log.info("Store search: всего обнаружено кандидатов: %d", len(discovered))

    steam_path = find_steam_path()
    owned: set[int] = set()
    if steam_path:
        with cm_session() as client:
            if client is not None:
                owned_packages = set(client.licenses.keys())
                owned = set(
                    expand_packages_to_apps(steam_path, owned_packages)
                )
                log.info("Steam CM: уже в библиотеке (owned): %d", len(owned))
            else:
                log.warning(
                    "Steam CM: вход не удался — owned не вычтен, кандидаты "
                    "могут включать уже имеющиеся игры"
                )
    else:
        log.warning("Папка Steam не найдена — owned не вычтен")

    already_added = state.load_added_ids()
    already_refused = state.load_refused_ids()
    candidates = [
        a
        for a in discovered
        if a not in owned
        and a not in already_added
        and a not in already_refused
    ]
    state.save_candidates(candidates)
    log.info(
        "Кандидатов к добавлению (минус owned/added/refused): %d",
        len(candidates),
    )
    return candidates


def add(*, limit: int | None = None) -> licenses.AddResult:
    """Фаза add: request_free_license батчами по candidates.txt (resume-aware)."""
    candidates = state.load_candidates()
    already_added = state.load_added_ids()
    already_refused = state.load_refused_ids()
    already_error = state.load_error_ids()
    pending = [
        a
        for a in candidates
        if a not in already_added
        and a not in already_refused
        and a not in already_error
    ]
    if limit is not None:
        pending = pending[:limit]

    if not pending:
        log.info("Нет кандидатов к добавлению")
        return licenses.AddResult()

    log.info(SEPARATOR)
    log.info("Добавление бесплатных лицензий: %d кандидатов", len(pending))

    with cm_session() as client:
        if client is None:
            log.error("Steam CM: вход не удался — добавление невозможно")
            for appid in pending:
                state.mark_error(appid)
            return licenses.AddResult(error=list(pending))
        result = licenses.add_licenses(client, pending)

    for appid in result.added:
        state.mark_added(appid)
    for appid in result.refused:
        state.mark_refused(appid)
    for appid in result.error:
        state.mark_error(appid)

    return result


def run(
    *,
    do_add: bool,
    list_only: bool,
    limit: int | None,
    include_demos: bool,
    cfg: Any,
) -> None:
    """Точка входа: dry-run по умолчанию, реально добавляет только при do_add=True."""
    if list_only:
        candidates = state.load_candidates()
        for appid in candidates:
            print(appid)
        log.info("Кандидатов в candidates.txt: %d", len(candidates))
        return

    candidates = discover(include_demos=include_demos)

    if not do_add:
        report.report_result(
            status="dry_run",
            added=len(candidates),
            refused=0,
            error=0,
            hit_cap=False,
            cfg=cfg,
        )
        return

    status = "ok"
    result = licenses.AddResult()
    try:
        result = add(limit=limit)
    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C) во время добавления.")
    except Exception:
        status = "error"
        log.exception("Добавление лицензий прервано ошибкой.")

    report.report_result(
        status=status,
        added=len(result.added),
        refused=len(result.refused),
        error=len(result.error),
        hit_cap=result.hit_cap,
        cfg=cfg,
    )
```

- [ ] **Step 4: Обновить `app/free_games/__init__.py`**

Заменить целиком:

```python
"""Пакет авто-добавления бесплатных игр/приложений Steam в библиотеку.

Субмодули:
  discovery    — обнаружение кандидатов через store search (витрина free)
  state        — resume-состояние (candidates/added/refused/error)
  licenses     — батчевый request_free_license + cap-детект + backoff
  report       — честный итоговый отчёт (toast + Telegram)
  orchestrate  — склейка фаз discover/add, точка входа для CLI
"""

from .licenses import AddResult
from .orchestrate import run

__all__ = ["AddResult", "run"]
```

- [ ] **Step 5: Запустить тесты — все зелёные**

Run: `pytest tests/unit/test_free_games_orchestrate.py -v`
Expected: `12 passed`

- [ ] **Step 6: Полный прогон + гейты (проверить, что реэкспорт `run`/`AddResult` не сломал остальное)**

Run: `ruff check . && ruff format --check . && mypy app && pytest tests/unit -q`
Expected: все зелёные

- [ ] **Step 7: Commit**

```bash
git add app/free_games/orchestrate.py app/free_games/__init__.py tests/unit/test_free_games_orchestrate.py
git commit -m "$(cat <<'EOF'
feat(free-games): оркестрация discover/add + честное ветвление статусов

discover() вычитает owned (из живой CM-сессии, authoritative) и уже
added/refused из витрины; add() resume-aware (пропускает added/
refused/error), уважает --limit, при неуспехе CM-логина помечает
pending как error (не молчит). run() — dry-run по умолчанию,
Ctrl+C/исключение при --add дают честный status (interrupted/error),
никогда не маскируются под "ok".

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `scripts/library/add_free.py` — тонкий CLI

**Files:**
- Create: `scripts/library/add_free.py`
- Test: не требуется отдельный юнит-тест (скрипт НЕ типизируется mypy, вся логика уже покрыта Task 1-6 — сам скрипт только argparse + вызов `app.free_games.run`, аналогично `scripts/playtime/boost.py`). Ручная smoke-проверка в Step 3.

**Interfaces:**
- Consumes: `app.config.load_config`, `app.free_games.run`, `app.free_games.state`, `app.logging_setup.setup_logging`, `app.steam.resolve_steam_id`, `app.validator.validate`.
- Produces: исполняемый `python scripts/library/add_free.py`.

- [ ] **Step 1: Создать `scripts/library/add_free.py`**

```python
"""Auto-add Free Games — добавляет бесплатные App ID в библиотеку Steam.

Две фазы: discover (витрина free store search → candidates.txt минус owned) и
add (request_free_license батчами, resume-aware). По умолчанию — dry-run
(только discover + отчёт), реальное добавление лицензий — только по --add
(необратимое действие на аккаунте: добавленные бесплатные лицензии нельзя
удалить из библиотеки штатными средствами Steam).

Использование:
    python scripts/library/add_free.py              # dry-run: сколько найдено
    python scripts/library/add_free.py --add         # реально добавить
    python scripts/library/add_free.py --list        # показать candidates.txt
    python scripts/library/add_free.py --add --limit 100
    python scripts/library/add_free.py --add --retry-errors
    python scripts/library/add_free.py --reset
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app.config import load_config
from app.free_games import run
from app.free_games import state as free_games_state
from app.logging_setup import setup_logging
from app.steam import resolve_steam_id
from app.validator import validate

log = logging.getLogger("sam_automation")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Auto-add Free Games — добавляет бесплатные игры/app в "
            "библиотеку Steam"
        )
    )
    parser.add_argument(
        "--add",
        action="store_true",
        help="Реально добавить лицензии (по умолчанию — dry-run, только discover)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать текущих кандидатов из candidates.txt и выйти",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить resume-состояние (candidates/added/refused/error)",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Повторить error.txt (транзиентные неудачи; НЕ refused — тот терминален)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Потолок числа добавлений за прогон",
    )
    parser.add_argument(
        "--no-demos",
        action="store_true",
        help="Пропустить демо-подфазу обнаружения",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    setup_logging(name="add_free", category="library/add_free")
    cfg = load_config()

    # Резолвим Steam ID (vanity-имя/URL → ID64) ДО валидации — как scan.py/
    # boost.py: validate шлёт steam_id в GetPlayerSummaries, которому нужен
    # числовой ID64. Пустой steam_id НЕ резолвим — пусть validate выдаст
    # локальную «missing».
    if cfg.steam_id:
        try:
            cfg.steam_id = resolve_steam_id(cfg.steam_api_key, cfg.steam_id)
        except (RuntimeError, KeyError) as e:
            log.error("Не удалось определить Steam ID: %s", e)
            sys.exit(1)

    validate(cfg)

    if args.list and (args.reset or args.retry_errors):
        log.warning(
            "--list только показывает кандидатов; --reset/--retry-errors "
            "игнорируются"
        )

    if not args.list:
        if args.reset:
            free_games_state.clear_state()
            log.info("Сброшено resume-состояние (--reset)")
        if args.retry_errors:
            free_games_state.clear_error_ids()
            log.info("Очищен error.txt (--retry-errors)")

    run(
        do_add=args.add,
        list_only=args.list,
        limit=args.limit,
        include_demos=not args.no_demos,
        cfg=cfg,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Гейты**

Run: `ruff check . && ruff format --check . && mypy app && pytest tests/unit -q`
Expected: все зелёные (`scripts/` не проверяется mypy — только ruff/format, которые не должны быть нарушены)

- [ ] **Step 3: Smoke-проверка CLI без реального Steam-логина (парсер + --help)**

Run: `python scripts/library/add_free.py --help`
Expected: печатает справку со всеми флагами (`--add --list --reset --retry-errors --limit --no-demos`), код возврата 0 — подтверждает, что импорт-граф (`app.free_games` → `app.steam.steam_cm` → `steam`/`gevent`) грузится без ошибок до первого сетевого вызова.

- [ ] **Step 4: Commit**

```bash
git add scripts/library/add_free.py
git commit -m "$(cat <<'EOF'
feat(free-games): CLI-скрипт scripts/library/add_free.py

Тонкий фасад над app.free_games.run — dry-run по умолчанию (discover
+ отчёт, ничего не добавляет), --add для реального (необратимого)
добавления лицензий. --list/--reset/--retry-errors/--limit/--no-demos
— по образцу boost.py/scan.py. Run-lock не берётся (тот же CM-путь,
что и scan.py — не спавнит SAM.Game.exe, не конфликтует с farm/boost).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Финализация ветки

После Task 7 — работа функционально полна и покрыта тестами (Task 1: 33 CM-теста; Task 2: 10; Task 3: 7; Task 4: 8; Task 5: 6; Task 6: 12 — итого +43 новых теста поверх +6 в Task 1 = ядро фичи под TDD). Дальше — `superpowers:finishing-a-development-branch` для решения о merge в `develop` (PR через `gh`, `--no-ff`, по git-flow из CLAUDE.md).

Не забыть перед PR: обновить `config.example.yaml`, если по факту потребуются новые опциональные поля конфига (v1 плана их не вводит — discovery/лимиты идут через CLI-флаги, не config.yaml); обновить `README`, если он документирует список `scripts/*` (проверить при выполнении Task 7).
