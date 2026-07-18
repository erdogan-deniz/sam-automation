# Wishlist Auto-Add Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `app/wishlist/` + `scripts/library/wishlist_add.py` — a resumable
CLI that adds Steam catalog entries (games/DLC/software/videos) to the
account's wishlist via the live-verified `IWishlistService/AddToWishlist`
WebAPI, with an adaptive rate-limit backoff and an honest, resumable report.

**Architecture:** Sibling package to `app/free_games/`, same shape
(state/discovery/report/orchestrate + CLI) but WebAPI-only (no CM, no
run-lock). The new piece is `wishlist_api.py`: a per-appid POST classifier
keyed off the live-verified `x-eresult` HTTP header, feeding an adaptive
backoff-then-stop loop.

**Tech Stack:** Python 3.12, stdlib `urllib`/`json`/`dataclasses` only (no new
dependencies). Reuses `app.id_file`, `app.cache.GAMES_DIR`,
`app.steam.steam_api` (`BASE_URL`, `_api_get`, `fetch_owned_games`),
`app.cookies.get_web_cookies`, `app.notify`, `app.logging_setup`,
`app.validator`, `app.config`.

## Global Constraints

- 4 gates before **every** commit (verbatim from CLAUDE.md, matches CI):
  `ruff check .` / `ruff format --check .` / `mypy app` (scoped to `app/` only
  — `scripts/` is NOT typed) / `pytest tests/unit -q`.
- Branch `feature/add-wishlist` off `develop` (already created), merge
  `--no-ff`. Conventional Commits, Russian body, footer
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` (fixed project
  convention regardless of which model is actually running).
- Dry-run is the default; the account is mutated **only** with explicit
  `--add`.
- `run_lock` is **not** needed — this feature never spawns `SAM.Game.exe`
  (same reasoning as `scan.py`).
- All resume-state writes go through `app.id_file` (`_atomic_write_text` /
  `_append_id`) — atomic, numerically sorted, never hand-rolled.
- Honest-report invariant: rate-limit wall / auth-failure / Ctrl+C must never
  produce a ✅ success toast.
- Line endings LF, UTF-8 everywhere (`.gitattributes`); `from __future__ import
  annotations` at the top of every new module (existing project convention).
- Live-verified facts this plan encodes as fact, not guess (see
  `docs/superpowers/specs/2026-07-18-add-wishlist-design.md`): write endpoint
  is `POST api.steampowered.com/IWishlistService/AddToWishlist/v1/
  ?access_token=<JWT>`; classifier keys off the `x-eresult` response header
  (`1`=added, `2`/`8`=refused-terminal, `429`/`84`=rate-limit, HTTP
  `401`=auth-fail); `GetWishlist/v1` returns the entire list in one call, no
  pagination; real throughput measured at ~2/sec with zero throttling in a
  40-item burst — the adaptive backoff (not a fixed slow interval) is the
  actual governor.

---

### Task 1: Package skeleton + resume-state (`state.py`)

**Files:**
- Create: `app/wishlist/__init__.py`
- Create: `app/wishlist/state.py`
- Test: `tests/unit/test_wishlist_state.py`

**Interfaces:**
- Produces: `CANDIDATES_FILE`, `ADDED_FILE`, `REFUSED_FILE`, `ERROR_FILE`
  (module-level `Path` constants, monkeypatchable by later tests exactly like
  `app/free_games/state.py`); `load_candidates() -> list[int]`,
  `save_candidates(appids: list[int]) -> None`, `load_added_ids() -> set[int]`,
  `load_refused_ids() -> set[int]`, `load_error_ids() -> set[int]`,
  `mark_added(appid: int) -> None`, `mark_refused(appid: int) -> None`,
  `mark_error(appid: int) -> None`, `clear_error_ids() -> None`,
  `clear_state() -> None`.

- [ ] **Step 1: Create the package marker**

`app/wishlist/__init__.py`:

```python
"""Пакет авто-добавления каталога Steam в вишлист аккаунта."""

from __future__ import annotations
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_wishlist_state.py`:

```python
"""Тесты resume-состояния app/wishlist/state.py (candidates/added/refused/error)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.wishlist.state as state_mod


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

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_wishlist_state.py -v`
Expected: FAIL (collection error) — `ModuleNotFoundError: No module named
'app.wishlist.state'`

- [ ] **Step 4: Write the implementation**

`app/wishlist/state.py`:

```python
"""Resume-состояние авто-добавления каталога Steam в вишлист.

Зеркало app/free_games/state.py, свой каталог data/games/ids/wishlist/ (не
пересекается с free/achievements/cards/playtime).

  candidates.txt — universe минус owned/wishlisted/added/refused
  added.txt      — успешно добавлено (x-eresult=1) — skip
  refused.txt    — терминально (owned/уже-в-вишлисте/invalid) — skip
  error.txt      — транзиентная сетевая ошибка — восстановим --retry-errors
"""

from __future__ import annotations

from app.cache import GAMES_DIR
from app.id_file import (
    _append_id,
    _atomic_write_text,
    load_ids_file,
    read_ids_ordered,
)

_WISHLIST_DIR = GAMES_DIR / "ids" / "wishlist"

CANDIDATES_FILE = _WISHLIST_DIR / "candidates.txt"
ADDED_FILE = _WISHLIST_DIR / "added.txt"
REFUSED_FILE = _WISHLIST_DIR / "refused.txt"
ERROR_FILE = _WISHLIST_DIR / "error.txt"


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

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_wishlist_state.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Gate + commit**

```bash
ruff format app/wishlist/ tests/unit/test_wishlist_state.py
ruff check .
mypy app
pytest tests/unit -q
git add app/wishlist/__init__.py app/wishlist/state.py tests/unit/test_wishlist_state.py
git commit -m "$(cat <<'EOF'
feat(wishlist): resume-состояние app/wishlist/state.py

Каркас пакета + candidates/added/refused/error id-файлы, зеркало
app/free_games/state.py. Свой каталог data/games/ids/wishlist/.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `wishlist_api.py` — HTTP call + `x-eresult` classifier

**Files:**
- Create: `app/wishlist/wishlist_api.py`
- Test: `tests/unit/test_wishlist_api.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure stdlib `urllib`).
- Produces: `BASE_URL: str`, `Classification = Literal["added", "refused",
  "rate_limit", "auth_fail"]`, `AddResult` dataclass (`added: list[int]`,
  `refused: list[int]`, `error: list[int]`, `hit_wall: bool`,
  `auth_fail: bool` — all default empty/False), `_classify(http_status: int,
  eresult: str | None) -> Classification`, `_call(action: str, appid: int,
  access_token: str) -> tuple[int, str | None, dict]`,
  `add_to_wishlist(appid: int, access_token: str) -> Classification` (Task 3
  will add `add_pending` on top of these).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_wishlist_api.py`:

```python
"""Тесты app/wishlist/wishlist_api.py: HTTP-вызов + x-eresult классификатор.

x-eresult и коды сняты вживую на реальном аккаунте 2026-07-18 (см.
docs/superpowers/specs/2026-07-18-add-wishlist-design.md): 1=added,
2/8=refused (owned/уже-в-вишлисте/invalid), 429 или eresult=84=rate_limit,
HTTP 401=auth_fail.
"""

from __future__ import annotations

import email.message
import json
import urllib.error

import app.wishlist.wishlist_api as wishlist_api


class _FakeResp:
    """Контекст-менеджер успешного ответа urlopen (status + headers + JSON body)."""

    def __init__(self, status: int, eresult: str | None, body: dict) -> None:
        self.status = status
        self.headers = {"x-eresult": eresult} if eresult is not None else {}
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _http_error(code: int, eresult: str | None = None) -> urllib.error.HTTPError:
    hdrs = email.message.Message()
    if eresult is not None:
        hdrs["x-eresult"] = eresult
    return urllib.error.HTTPError(
        "https://api.steampowered.com/x", code, "err", hdrs, None
    )


# ── _classify: чистая функция, таблица из живого снятия ─────────────────────


def test_classify_ok_is_added() -> None:
    assert wishlist_api._classify(200, "1") == "added"


def test_classify_fail_is_refused() -> None:
    assert wishlist_api._classify(200, "2") == "refused"


def test_classify_invalid_param_is_refused() -> None:
    assert wishlist_api._classify(200, "8") == "refused"


def test_classify_rate_limit_by_eresult_header() -> None:
    assert wishlist_api._classify(200, "84") == "rate_limit"


def test_classify_rate_limit_by_bare_http_429() -> None:
    assert wishlist_api._classify(429, None) == "rate_limit"


def test_classify_auth_fail_by_http_401() -> None:
    assert wishlist_api._classify(401, None) == "auth_fail"


# ── _call: реальный HTTP-слой (замокан) ──────────────────────────────────────


def test_call_success_returns_status_eresult_and_body(monkeypatch) -> None:
    monkeypatch.setattr(
        wishlist_api.urllib.request,
        "urlopen",
        lambda req, timeout=15: _FakeResp(
            200, "1", {"response": {"wishlist_count": 5}}
        ),
    )
    status, eresult, body = wishlist_api._call("AddToWishlist", 730, "tok")
    assert status == 200
    assert eresult == "1"
    assert body == {"response": {"wishlist_count": 5}}


def test_call_http_error_returns_status_and_eresult(monkeypatch) -> None:
    def fake_urlopen(req, timeout=15):
        raise _http_error(429, "84")

    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    status, eresult, body = wishlist_api._call("AddToWishlist", 730, "tok")
    assert status == 429
    assert eresult == "84"
    assert body == {}


def test_call_http_error_without_eresult_header(monkeypatch) -> None:
    def fake_urlopen(req, timeout=15):
        raise _http_error(401)

    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    status, eresult, body = wishlist_api._call("AddToWishlist", 730, "tok")
    assert status == 401
    assert eresult is None


def test_call_posts_appid_and_access_token_in_url(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return _FakeResp(200, "1", {"response": {}})

    monkeypatch.setattr(wishlist_api.urllib.request, "urlopen", fake_urlopen)
    wishlist_api._call("AddToWishlist", 1600020, "the.jwt.token")
    assert "access_token=the.jwt.token" in captured["url"]
    assert "IWishlistService/AddToWishlist/v1/" in captured["url"]
    assert captured["data"] == b"appid=1600020"


# ── add_to_wishlist: _classify(_call(...)) ───────────────────────────────────


def test_add_to_wishlist_added(monkeypatch) -> None:
    monkeypatch.setattr(
        wishlist_api,
        "_call",
        lambda *_a: (200, "1", {"response": {"wishlist_count": 1}}),
    )
    assert wishlist_api.add_to_wishlist(730, "tok") == "added"


def test_add_to_wishlist_refused(monkeypatch) -> None:
    monkeypatch.setattr(wishlist_api, "_call", lambda *_a: (200, "2", {}))
    assert wishlist_api.add_to_wishlist(730, "tok") == "refused"


def test_add_to_wishlist_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(wishlist_api, "_call", lambda *_a: (429, None, {}))
    assert wishlist_api.add_to_wishlist(730, "tok") == "rate_limit"


def test_add_to_wishlist_auth_fail(monkeypatch) -> None:
    monkeypatch.setattr(wishlist_api, "_call", lambda *_a: (401, None, {}))
    assert wishlist_api.add_to_wishlist(730, "tok") == "auth_fail"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_wishlist_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.wishlist.wishlist_api'`

- [ ] **Step 3: Write the implementation**

`app/wishlist/wishlist_api.py`:

```python
"""Добавление в Wishlist Steam через IWishlistService (модерн WebAPI).

Write-путь снят ЖИВЬЁМ на реальном аккаунте 2026-07-18 (см. дизайн-спеку):
POST api.steampowered.com/IWishlistService/AddToWishlist/v1/?access_token=<JWT>
форма appid=<id>. access_token = community-JWT из app.cookies.get_web_cookies
(aud=["web:community"] — этого достаточно, sessionid/CSRF/store-cookie НЕ
нужны — легаси store-эндпоинт отклонён именно потому, что требует
web:store-aud токен, которого get_web_cookies не даёт).

Классификатор — по HTTP-заголовку x-eresult (authoritative WebAPI-сигнал),
числа совпадают с steam.enums.EResult (OK=1, Fail=2, InvalidParam=8,
RateLimitExceeded=84), но сам enum-класс здесь НЕ импортируется: это другой
транспорт (HTTP-заголовок WebAPI, не CM-протокол), а `steam`-пакет тяжёлый
(gevent/protobuf) — тянуть его в модуль, которому нужны только эти 4 числа,
не оправдано (тот же расчёт, что в app/free_games/discovery.py — не
реюзать через приватные символы неродственного транспорта без реальной
экономии).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger("sam_automation")

BASE_URL = "https://api.steampowered.com"

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded; charset=UTF-8"

_ERESULT_OK = "1"  # steam.enums.EResult.OK
_ERESULT_FAIL = "2"  # steam.enums.EResult.Fail (owned / уже-в-вишлисте)
_ERESULT_INVALID_PARAM = "8"  # EResult.InvalidParam (delisted/несуществующий)
_ERESULT_RATE_LIMIT = "84"  # EResult.RateLimitExceeded

Classification = Literal["added", "refused", "rate_limit", "auth_fail"]


@dataclass
class AddResult:
    """Итог одного прогона добавления в вишлист."""

    added: list[int] = field(default_factory=list)
    refused: list[int] = field(default_factory=list)
    error: list[int] = field(default_factory=list)
    hit_wall: bool = False
    auth_fail: bool = False


def _classify(http_status: int, eresult: str | None) -> Classification:
    """Классифицирует ответ IWishlistService по HTTP-статусу + x-eresult.

    Таблица снята вживую 2026-07-18: 1→added; 2 (Fail, owned/уже-в-вишлисте) и
    8 (InvalidParam, delisted/несуществующий) → refused (терминал); голый HTTP
    429 (заголовок мог не прийти) либо eresult=84 (RateLimitExceeded) →
    rate_limit; HTTP 401 → auth_fail (сессия истекла/невалидна).
    """
    if http_status == 401:
        return "auth_fail"
    if http_status == 429 or eresult == _ERESULT_RATE_LIMIT:
        return "rate_limit"
    if eresult == _ERESULT_OK:
        return "added"
    return "refused"  # включая eresult в (_ERESULT_FAIL, _ERESULT_INVALID_PARAM)


def _call(
    action: str, appid: int, access_token: str
) -> tuple[int, str | None, dict[str, Any]]:
    """POST IWishlistService/<action>/v1/. Возвращает (http_status, x-eresult, body).

    Сетевые исключения (URLError/OSError/HTTPException — НЕ HTTPError, тот уже
    несёт валидный http_status) пробрасываются наверх — вызывающий
    add_pending() ловит их как error-исход для конкретного appid.
    """
    url = f"{BASE_URL}/IWishlistService/{action}/v1/?access_token={access_token}"
    data = urllib.parse.urlencode({"appid": appid}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": _FORM_CONTENT_TYPE}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            eresult = resp.headers.get("x-eresult")
            try:
                body: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = {}
            return resp.status, eresult, body
    except urllib.error.HTTPError as e:
        eresult = e.headers.get("x-eresult") if e.headers else None
        return e.code, eresult, {}


def add_to_wishlist(appid: int, access_token: str) -> Classification:
    """Один appid → добавление в вишлист; логирует wishlist_count при успехе."""
    status, eresult, body = _call("AddToWishlist", appid, access_token)
    classification = _classify(status, eresult)
    if classification == "added":
        log.info(
            "Wishlist: добавлено appid=%d (wishlist_count=%s)",
            appid,
            body.get("response", {}).get("wishlist_count"),
        )
    return classification
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_wishlist_api.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Gate + commit**

```bash
ruff format app/wishlist/wishlist_api.py tests/unit/test_wishlist_api.py
ruff check .
mypy app
pytest tests/unit -q
git add app/wishlist/wishlist_api.py tests/unit/test_wishlist_api.py
git commit -m "$(cat <<'EOF'
feat(wishlist): классификатор x-eresult + POST AddToWishlist

Write-путь и классификатор сняты вживую 2026-07-18 на реальном аккаунте:
модерн IWishlistService/AddToWishlist (не legacy store), сигнал — HTTP-
заголовок x-eresult (1=added, 2/8=refused-терминал, 429/84=rate_limit,
401=auth_fail). Числа совпадают с EResult, но enum не импортируется —
другой транспорт, steam-пакет тяжёлый и не нужен здесь.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `wishlist_api.py` — `add_pending` loop (adaptive backoff + wall)

**Files:**
- Modify: `app/wishlist/wishlist_api.py` (append after `add_to_wishlist`)
- Modify: `tests/unit/test_wishlist_api.py` (append)

**Interfaces:**
- Consumes: `add_to_wishlist(appid, access_token) -> Classification`,
  `AddResult` (Task 2).
- Produces: `add_pending(access_token: str, appids: list[int], *, interval:
  float = 1.0, sleep: Callable[[float], None] = time.sleep) -> AddResult`
  (Task 7's `orchestrate.add()` calls this directly).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_wishlist_api.py` (add these imports at the top,
next to the existing ones — insert after the `import urllib.error` line):

```python
from collections.abc import Callable
```

Append these tests at the end of the file:

```python
# ── add_pending: адаптивный backoff + стена (K=5 подряд rate_limit) ─────────


def _sequence(outcomes: list[str]) -> Callable[[int, str], str]:
    """Возвращает фейковый add_to_wishlist, отдающий outcomes по порядку."""
    it = iter(outcomes)

    def _fake(appid: int, access_token: str) -> str:
        return next(it)

    return _fake


def test_add_pending_added_then_refused(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["added", "refused"])
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2], interval=0.5, sleep=sleeps.append
    )
    assert result.added == [1]
    assert result.refused == [2]
    assert sleeps == [0.5, 0.5]


def test_add_pending_rate_limit_then_success_retries_same_appid(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["rate_limit", "added"])
    )
    result = wishlist_api.add_pending(
        "tok", [1], interval=1.0, sleep=sleeps.append
    )
    assert result.added == [1]
    # backoff(streak=1)=60, затем вежливая пауза 1.0 после успеха
    assert sleeps == [60.0, 1.0]


def test_add_pending_hits_wall_after_five_consecutive_rate_limits(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["rate_limit"] * 5)
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2, 3], interval=1.0, sleep=sleeps.append
    )
    assert result.hit_wall is True
    assert result.added == []
    # 4 backoff-ожидания (streak 1..4), на 5-м — стена без ожидания
    assert sleeps == [60.0, 120.0, 240.0, 300.0]


def test_add_pending_streak_resets_after_success_between_appids(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        wishlist_api,
        "add_to_wishlist",
        _sequence(
            ["rate_limit", "rate_limit", "added"]
            + ["rate_limit"] * 5  # appid=2 не наследует streak от appid=1
        ),
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2], interval=1.0, sleep=lambda *_a: None
    )
    assert result.added == [1]
    assert result.hit_wall is True


def test_add_pending_auth_fail_stops_immediately(monkeypatch) -> None:
    monkeypatch.setattr(
        wishlist_api, "add_to_wishlist", _sequence(["auth_fail"])
    )
    result = wishlist_api.add_pending(
        "tok", [1, 2, 3], interval=1.0, sleep=lambda *_a: None
    )
    assert result.auth_fail is True
    assert result.added == []
    assert result.refused == []


def test_add_pending_network_exception_marks_error_and_continues(
    monkeypatch,
) -> None:
    def _fake(appid: int, access_token: str) -> str:
        if appid == 1:
            raise ConnectionResetError("нет связи")
        return "added"

    monkeypatch.setattr(wishlist_api, "add_to_wishlist", _fake)
    result = wishlist_api.add_pending(
        "tok", [1, 2], interval=0, sleep=lambda *_a: None
    )
    assert result.error == [1]
    assert result.added == [2]


def test_add_pending_empty_input_no_calls(monkeypatch) -> None:
    def _boom(appid: int, access_token: str) -> str:
        raise AssertionError("add_to_wishlist не должен вызываться")

    monkeypatch.setattr(wishlist_api, "add_to_wishlist", _boom)
    result = wishlist_api.add_pending("tok", [], interval=1.0)
    assert result == wishlist_api.AddResult()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_wishlist_api.py -v`
Expected: FAIL — `AttributeError: module 'app.wishlist.wishlist_api' has no
attribute 'add_pending'`

- [ ] **Step 3: Write the implementation**

In `app/wishlist/wishlist_api.py`, change the imports at the top: add `import
time` after `import logging`, and `from collections.abc import Callable`
after `import urllib.request`. The full updated import block:

```python
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
```

Append this to the end of `app/wishlist/wishlist_api.py` (after
`add_to_wishlist`):

```python
# Экспоненциальный backoff на rate-limit. Индекс = streak-1, капается на
# последнем элементе. Живая мера 2026-07-18: 40 добавлений подряд без пауз —
# ноль троттла (~2/сек) — устойчивый предел за тысячи adds НЕ измерен (не
# долбили ради IP soft-ban). Поэтому governor адаптивный, не хардкод: идём
# быстро, отступаем ТОЛЬКО когда Steam реально сигналит rate_limit.
_BACKOFF_SCHEDULE: tuple[float, ...] = (60.0, 120.0, 240.0, 300.0)
# 5-й подряд rate_limit — стена; долбить дальше опасно (soft-ban ~6ч,
# продлевается при долбёжке) — отличие от app/free_games/licenses.py, которая
# ретраит RateLimitExceeded бесконечно (там единственная стена — license-cap).
_WALL_STREAK = 5


def add_pending(
    access_token: str,
    appids: list[int],
    *,
    interval: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> AddResult:
    """Добавляет appids по одному (batch-эндпоинта нет).

    Rate-limit (429/eresult=84) ретраит ТОТ ЖЕ appid с растущим backoff;
    streak подряд идущих rate-limit сбрасывается любым иным исходом. 5 подряд
    → hit_wall=True, стоп, оставшийся pending не трогаем. auth_fail (401) —
    немедленный стоп (caller решает, обновлять ли токен). Сетевое исключение
    на appid → error, переходим к следующему (не ретраим бесконечно).
    """
    result = AddResult()
    streak = 0
    i = 0
    while i < len(appids):
        appid = appids[i]
        try:
            classification = add_to_wishlist(appid, access_token)
        except Exception as e:  # noqa: BLE001 — любой сетевой сбой → error appid
            log.warning("Wishlist: сетевой сбой на appid=%d: %s", appid, e)
            result.error.append(appid)
            i += 1
            continue

        if classification == "added":
            result.added.append(appid)
            streak = 0
            i += 1
            sleep(interval)
        elif classification == "refused":
            result.refused.append(appid)
            streak = 0
            i += 1
            sleep(interval)
        elif classification == "auth_fail":
            result.auth_fail = True
            break
        else:  # "rate_limit"
            streak += 1
            if streak >= _WALL_STREAK:
                result.hit_wall = True
                log.warning(
                    "Wishlist: %d подряд rate-limit — стена. Добавлено: %d",
                    streak,
                    len(result.added),
                )
                break
            delay = _BACKOFF_SCHEDULE[
                min(streak - 1, len(_BACKOFF_SCHEDULE) - 1)
            ]
            log.warning(
                "Wishlist: rate-limit (streak %d/%d) — жду %.0fс",
                streak,
                _WALL_STREAK,
                delay,
            )
            sleep(delay)
            # retry ТОТ ЖЕ appid — i не увеличиваем
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_wishlist_api.py -v`
Expected: PASS (21 tests)

- [ ] **Step 5: Gate + commit**

```bash
ruff format app/wishlist/wishlist_api.py tests/unit/test_wishlist_api.py
ruff check .
mypy app
pytest tests/unit -q
git add app/wishlist/wishlist_api.py tests/unit/test_wishlist_api.py
git commit -m "$(cat <<'EOF'
feat(wishlist): адаптивный backoff-then-stop в add_pending

Идём быстро (замер: ~2/сек без троттла), отступаем ТОЛЬКО по реальному
сигналу Steam. Rate-limit ретраит тот же appid с растущим backoff
(60→120→240→300с), 5 подряд — честная стена (hit_wall), не бесконечный
ретрай (в отличие от free_games — там долбить безопасно, license-cap это
единственная стена; здесь долбёжка 429 продлевает IP soft-ban).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `discovery.py` — `GetAppList` universe pagination

**Files:**
- Create: `app/wishlist/discovery.py`
- Test: `tests/unit/test_wishlist_discovery.py`

**Interfaces:**
- Consumes: `app.steam.steam_api.BASE_URL`, `app.steam.steam_api._api_get`
  (same host + JSON shape as `GetAppList`/`GetWishlist` — direct reuse is
  justified, unlike `free_games/discovery.py`'s store-search which is a
  different host/response shape).
- Produces: `_fetch_universe_page(api_key: str, *, last_appid: int,
  max_results: int = 50000) -> tuple[list[int], bool, int]`,
  `discover_universe(api_key: str, *, max_pages: int = 200) -> list[int]`
  (Task 5 builds `discover_candidates` on top of this).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_wishlist_discovery.py`:

```python
"""Тесты app/wishlist/discovery.py: вселенная (GetAppList) + дедуп owned/wishlisted."""

from __future__ import annotations

from app.wishlist import discovery


def _apps_page(appids: list[int]) -> list[dict]:
    return [{"appid": a, "name": f"app{a}"} for a in appids]


# ── _fetch_universe_page ─────────────────────────────────────────────────────


def test_fetch_universe_page_parses_appids_have_more_and_cursor(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {
                "apps": _apps_page([10, 20, 30]),
                "have_more_results": True,
                "last_appid": 30,
            }
        },
    )
    appids, have_more, last_appid = discovery._fetch_universe_page(
        "key", last_appid=0
    )
    assert appids == [10, 20, 30]
    assert have_more is True
    assert last_appid == 30


def test_fetch_universe_page_requests_all_content_types(monkeypatch) -> None:
    captured = {}

    def fake_api_get(url: str) -> dict:
        captured["url"] = url
        return {"response": {"apps": [], "have_more_results": False, "last_appid": 0}}

    monkeypatch.setattr(discovery, "_api_get", fake_api_get)
    discovery._fetch_universe_page("mykey", last_appid=5)
    for flag in (
        "key=mykey",
        "include_games=1",
        "include_dlc=1",
        "include_software=1",
        "include_videos=1",
        "include_hardware=1",
        "last_appid=5",
    ):
        assert flag in captured["url"]


def test_fetch_universe_page_missing_response_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "_api_get", lambda url: {})
    appids, have_more, last_appid = discovery._fetch_universe_page(
        "key", last_appid=0
    )
    assert appids == []
    assert have_more is False
    assert last_appid == 0


# ── discover_universe: пагинация до конца или max_pages ─────────────────────


def test_discover_universe_paginates_until_have_more_false(monkeypatch) -> None:
    pages = [
        {
            "response": {
                "apps": _apps_page([1, 2]),
                "have_more_results": True,
                "last_appid": 2,
            }
        },
        {
            "response": {
                "apps": _apps_page([3]),
                "have_more_results": False,
                "last_appid": 3,
            }
        },
    ]
    calls = {"n": 0}

    def fake_api_get(url: str) -> dict:
        page = pages[calls["n"]]
        calls["n"] += 1
        return page

    monkeypatch.setattr(discovery, "_api_get", fake_api_get)
    out = discovery.discover_universe("key")
    assert out == [1, 2, 3]
    assert calls["n"] == 2


def test_discover_universe_stops_on_empty_page(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {"apps": [], "have_more_results": True, "last_appid": 0}
        },
    )
    out = discovery.discover_universe("key")
    assert out == []


def test_discover_universe_respects_max_pages_on_stuck_cursor(
    monkeypatch,
) -> None:
    # have_more всегда True, cursor не двигается (защита от зависания).
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {
                "apps": _apps_page([1]),
                "have_more_results": True,
                "last_appid": 0,
            }
        },
    )
    out = discovery.discover_universe("key", max_pages=3)
    assert out == [1, 1, 1]  # 3 страницы, затем max_pages останавливает
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_wishlist_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.wishlist.discovery'`

- [ ] **Step 3: Write the implementation**

`app/wishlist/discovery.py`:

```python
"""Обнаружение вселенной кандидатов Steam для вишлиста (GetAppList).

GetAppList и GetWishlist (Task 5) — оба на api.steampowered.com с типизированным
JSON-ответом: тот же хост и форма, что уже обрабатывает
app/steam/steam_api.py::_api_get (429-ретрай с Retry-After). В отличие от
app/free_games/discovery.py (store.steampowered.com, HTML results_html) здесь
реюз ЧЕРЕЗ приватный _api_get оправдан — не дублируем retry-логику ради ~10
одинаковых строк.
"""

from __future__ import annotations

import logging

from app.steam.steam_api import BASE_URL, _api_get

log = logging.getLogger("sam_automation")

_MAX_RESULTS = 50000  # максимум GetAppList/v1 на страницу


def _fetch_universe_page(
    api_key: str, *, last_appid: int, max_results: int = _MAX_RESULTS
) -> tuple[list[int], bool, int]:
    """Одна страница GetAppList/v1 (все типы контента).

    Возвращает (appids, have_more_results, следующий last_appid).
    """
    url = (
        f"{BASE_URL}/IStoreService/GetAppList/v1/?key={api_key}"
        f"&include_games=1&include_dlc=1&include_software=1"
        f"&include_videos=1&include_hardware=1"
        f"&max_results={max_results}&last_appid={last_appid}"
    )
    data = _api_get(url)
    resp = data.get("response", {})
    apps = resp.get("apps", [])
    appids = [int(a["appid"]) for a in apps if a.get("appid") is not None]
    have_more = bool(resp.get("have_more_results", False))
    next_last_appid = int(resp.get("last_appid", last_appid))
    return appids, have_more, next_last_appid


def discover_universe(api_key: str, *, max_pages: int = 200) -> list[int]:
    """Пагинирует GetAppList/v1 до конца каталога (games+dlc+software+videos+hardware).

    max_pages — защита от зависания, если Steam когда-либо вернёт
    have_more_results=True с незменяющимся курсором.
    """
    out: list[int] = []
    last_appid = 0
    for _page in range(max_pages):
        appids, have_more, last_appid = _fetch_universe_page(
            api_key, last_appid=last_appid
        )
        if not appids:
            break
        out.extend(appids)
        if not have_more:
            break
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_wishlist_discovery.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Gate + commit**

```bash
ruff format app/wishlist/discovery.py tests/unit/test_wishlist_discovery.py
ruff check .
mypy app
pytest tests/unit -q
git add app/wishlist/discovery.py tests/unit/test_wishlist_discovery.py
git commit -m "$(cat <<'EOF'
feat(wishlist): пагинация вселенной кандидатов через GetAppList

IStoreService/GetAppList/v1 (все типы: games/dlc/software/videos/hardware),
курсор last_appid + have_more_results, снято вживую. Реюзает
app.steam.steam_api._api_get (тот же хост+JSON-форма, оправданно в отличие
от free_games/discovery.py).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `discovery.py` — owned/wishlisted dedup (`discover_candidates`)

**Files:**
- Modify: `app/wishlist/discovery.py` (append)
- Modify: `tests/unit/test_wishlist_discovery.py` (append)

**Interfaces:**
- Consumes: `discover_universe(api_key) -> list[int]` (Task 4),
  `app.steam.steam_api.fetch_owned_games(api_key, steam_id) -> list[dict]`
  (existing).
- Produces: `fetch_wishlist_ids(steam_id: str) -> set[int]`,
  `discover_candidates(*, api_key: str, steam_id: str) -> list[int]`
  (Task 7's `orchestrate.discover()` calls this).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_wishlist_discovery.py`:

```python
# ── fetch_wishlist_ids: keyless GetWishlist, весь список одним ответом ──────


def test_fetch_wishlist_ids_parses_items(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery,
        "_api_get",
        lambda url: {
            "response": {
                "items": [
                    {"appid": 1200, "priority": 0, "date_added": 111},
                    {"appid": 730, "priority": 1, "date_added": 222},
                ]
            }
        },
    )
    assert discovery.fetch_wishlist_ids("76561198190468628") == {1200, 730}


def test_fetch_wishlist_ids_empty_response(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "_api_get", lambda url: {"response": {}})
    assert discovery.fetch_wishlist_ids("76561198190468628") == set()


# ── discover_candidates: universe − owned − wishlisted, устойчиво к сбоям ──


def test_discover_candidates_subtracts_owned_and_wishlisted(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery, "discover_universe", lambda _key, **_kw: [1, 2, 3, 4, 5]
    )
    monkeypatch.setattr(
        discovery,
        "fetch_owned_games",
        lambda _key, _sid: [{"appid": 2, "name": "owned"}],
    )
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: {3})

    out = discovery.discover_candidates(api_key="key", steam_id="76561198190468628")
    assert out == [1, 4, 5]


def test_discover_candidates_universe_failure_returns_empty(monkeypatch) -> None:
    def _boom(_key, **_kw):
        raise RuntimeError("Steam API вернул 500")

    monkeypatch.setattr(discovery, "discover_universe", _boom)
    out = discovery.discover_candidates(api_key="key", steam_id="76561198190468628")
    assert out == []


def test_discover_candidates_owned_failure_still_returns_candidates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(discovery, "discover_universe", lambda _key, **_kw: [1, 2])

    def _boom(_key, _sid):
        raise RuntimeError("GetOwnedGames упал")

    monkeypatch.setattr(discovery, "fetch_owned_games", _boom)
    monkeypatch.setattr(discovery, "fetch_wishlist_ids", lambda _sid: set())

    out = discovery.discover_candidates(api_key="key", steam_id="76561198190468628")
    assert out == [1, 2]  # owned не вычтен, но прогон не падает


def test_discover_candidates_wishlist_failure_still_returns_candidates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(discovery, "discover_universe", lambda _key, **_kw: [1, 2])
    monkeypatch.setattr(discovery, "fetch_owned_games", lambda _key, _sid: [])

    def _boom(_sid):
        raise RuntimeError("GetWishlist упал")

    monkeypatch.setattr(discovery, "fetch_wishlist_ids", _boom)

    out = discovery.discover_candidates(api_key="key", steam_id="76561198190468628")
    assert out == [1, 2]  # wishlisted не вычтен, но прогон не падает
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_wishlist_discovery.py -v`
Expected: FAIL — `AttributeError: module 'app.wishlist.discovery' has no
attribute 'fetch_wishlist_ids'`

- [ ] **Step 3: Write the implementation**

In `app/wishlist/discovery.py`, change the import line `from
app.steam.steam_api import BASE_URL, _api_get` to:

```python
from app.steam.steam_api import BASE_URL, _api_get, fetch_owned_games
```

Append this to the end of `app/wishlist/discovery.py`:

```python
def fetch_wishlist_ids(steam_id: str) -> set[int]:
    """GetWishlist/v1 (keyless) → set appid. Весь список одним ответом —
    снято вживую на 24 253 позициях, пагинация читателю не требуется."""
    url = f"{BASE_URL}/IWishlistService/GetWishlist/v1/?steamid={steam_id}"
    data = _api_get(url)
    items = data.get("response", {}).get("items", [])
    return {int(it["appid"]) for it in items if it.get("appid") is not None}


def discover_candidates(*, api_key: str, steam_id: str) -> list[int]:
    """Вселенная минус owned минус wishlisted.

    Устойчив к сбою отдельного источника: owned/wishlisted недоступны →
    просто не вычитаются (WARNING в лог, лишнее появление появится как
    refused при add — самозалечивание); universe недоступна → 0 кандидатов
    честно (без неё строить список нечего).
    """
    try:
        universe = discover_universe(api_key)
    except Exception as e:
        log.warning("Wishlist: GetAppList не удался — 0 кандидатов: %s", e)
        return []
    log.info(
        "Wishlist: вселенная кандидатов (GetAppList, все типы): %d",
        len(universe),
    )

    try:
        owned = {g["appid"] for g in fetch_owned_games(api_key, steam_id)}
    except Exception as e:
        log.warning(
            "Wishlist: GetOwnedGames не удался — owned не вычтен: %s", e
        )
        owned = set()

    try:
        wishlisted = fetch_wishlist_ids(steam_id)
    except Exception as e:
        log.warning(
            "Wishlist: GetWishlist не удался — wishlisted не вычтен: %s", e
        )
        wishlisted = set()

    candidates = [a for a in universe if a not in owned and a not in wishlisted]
    log.info(
        "Wishlist: кандидатов (минус owned=%d, wishlisted=%d): %d",
        len(owned),
        len(wishlisted),
        len(candidates),
    )
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_wishlist_discovery.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Gate + commit**

```bash
ruff format app/wishlist/discovery.py tests/unit/test_wishlist_discovery.py
ruff check .
mypy app
pytest tests/unit -q
git add app/wishlist/discovery.py tests/unit/test_wishlist_discovery.py
git commit -m "$(cat <<'EOF'
feat(wishlist): дедуп owned/wishlisted в discover_candidates

GetWishlist (keyless, весь список одним ответом — снято вживую на 24k
позициях) + fetch_owned_games (owned-DLC слепая зона задокументирована,
CM-вычитание — будущий шаг). Устойчиво к сбою любого отдельного источника.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `report.py` — honest report

**Files:**
- Create: `app/wishlist/report.py`
- Test: `tests/unit/test_wishlist_report.py`

**Interfaces:**
- Consumes: `app.notify.toast`, `app.notify.send_telegram` (existing).
- Produces: `report_result(*, status: Literal["ok", "interrupted", "error",
  "dry_run"], added: int, refused: int, error: int, hit_wall: bool, cfg: Any)
  -> None` (Task 7's `orchestrate.run()` calls this).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_wishlist_report.py`:

```python
"""Тесты честного отчёта app/wishlist/report.py."""

from __future__ import annotations

from types import SimpleNamespace

import app.wishlist.report as report_mod


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


def test_report_ok_status_marks_success(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=5, refused=0, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "готово" in calls["toast"][1]
    assert "✅" in calls["tg"]


def test_report_hit_wall_never_says_all_added(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=40, refused=0, error=0, hit_wall=True, cfg=_cfg()
    )
    assert "стена" in calls["toast"][1]
    assert "⚠️" in calls["tg"]  # НЕ ✅ — упор в rate-limit не чистый успех


def test_report_interrupted_never_marks_success(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="interrupted", added=3, refused=0, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "прервано" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_error_status_marks_qualified(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="error", added=1, refused=0, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "прервано ошибкой" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_refused_or_error_marks_qualified(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="ok", added=5, refused=2, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "оговорками" in calls["toast"][1]
    assert "⚠️" in calls["tg"]


def test_report_dry_run_marks_success_without_adding(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    report_mod.report_result(
        status="dry_run", added=0, refused=0, error=0, hit_wall=False, cfg=_cfg()
    )
    assert "dry-run" in calls["toast"][1]
    assert "✅" in calls["tg"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_wishlist_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.wishlist.report'`

- [ ] **Step 3: Write the implementation**

`app/wishlist/report.py`:

```python
"""Честный итоговый отчёт авто-добавления в Wishlist Steam (toast + Telegram).

status="ok" с hit_wall=True НИКОГДА не даёт ✅ — упор в rate-limit-стену не
считается чистым успехом (инвариант честного отчёта проекта).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.logging_setup import SEPARATOR
from app.notify import send_telegram, toast

log = logging.getLogger("sam_automation")


def report_result(
    *,
    status: Literal["ok", "interrupted", "error", "dry_run"],
    added: int,
    refused: int,
    error: int,
    hit_wall: bool,
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
    elif hit_wall:
        head, ok = "упор в стену (rate-limit)", False
    elif refused or error:
        head, ok = "готово с оговорками", False
    else:
        head, ok = "готово", True

    detail = f"добавлено {added}, отказано {refused}, ошибок {error}"
    if hit_wall:
        detail += " — дальше стена"

    log.info(SEPARATOR)
    log.info("Добавление в Wishlist — %s. %s", head, detail)
    log.info(SEPARATOR)
    toast("SAM Automation — Wishlist", f"{head}: {detail}")
    mark = "✅" if ok else "⚠️"
    send_telegram(f"{mark} Wishlist — {head}: {detail}", cfg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_wishlist_report.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Gate + commit**

```bash
ruff format app/wishlist/report.py tests/unit/test_wishlist_report.py
ruff check .
mypy app
pytest tests/unit -q
git add app/wishlist/report.py tests/unit/test_wishlist_report.py
git commit -m "$(cat <<'EOF'
feat(wishlist): честный отчёт (toast + Telegram)

Зеркало app/free_games/report.py: hit_wall=True (упор в rate-limit-стену)
НИКОГДА не даёт success-тост, как и interrupted/error/refused>0.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `orchestrate.py` — discover/add/run + package exports

**Files:**
- Create: `app/wishlist/orchestrate.py`
- Modify: `app/wishlist/__init__.py` (replace docstring-only content)
- Test: `tests/unit/test_wishlist_orchestrate.py`

**Interfaces:**
- Consumes: `state.*` (Task 1), `wishlist_api.AddResult`,
  `wishlist_api.add_pending` (Tasks 2-3), `discovery.discover_candidates`
  (Tasks 4-5), `report.report_result` (Task 6), `app.cookies.get_web_cookies`
  (existing).
- Produces: `discover(*, api_key: str, steam_id: str) -> list[int]`,
  `add(*, limit: int | None = None, interval: float = 1.0) ->
  wishlist_api.AddResult`, `run(*, do_add: bool, list_only: bool, limit: int |
  None, interval: float, api_key: str, steam_id: str, cfg: Any) -> None`
  (Task 8's CLI calls `run`). Package re-exports `run`, `AddResult`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_wishlist_orchestrate.py`:

```python
"""Тесты оркестрации discover/add/run (app/wishlist/orchestrate.py)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.wishlist.orchestrate as orch
import app.wishlist.state as state_mod


def _patch_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_mod, "CANDIDATES_FILE", tmp_path / "candidates.txt")
    monkeypatch.setattr(state_mod, "ADDED_FILE", tmp_path / "added.txt")
    monkeypatch.setattr(state_mod, "REFUSED_FILE", tmp_path / "refused.txt")
    monkeypatch.setattr(state_mod, "ERROR_FILE", tmp_path / "error.txt")


# ── discover() ────────────────────────────────────────────────────────────


def test_discover_subtracts_added_and_refused(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2, 3, 4, 5]
    )
    state_mod.mark_added(3)
    state_mod.mark_refused(4)

    result = orch.discover(api_key="key", steam_id="76561198190468628")

    assert result == [1, 2, 5]
    assert state_mod.load_candidates() == [1, 2, 5]


def test_discover_passes_api_key_and_steam_id_through(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    captured = {}

    def fake_discover_candidates(*, api_key, steam_id):
        captured["api_key"] = api_key
        captured["steam_id"] = steam_id
        return []

    monkeypatch.setattr(orch.discovery, "discover_candidates", fake_discover_candidates)
    orch.discover(api_key="mykey", steam_id="76561198190468628")
    assert captured == {"api_key": "mykey", "steam_id": "76561198190468628"}


# ── add() ─────────────────────────────────────────────────────────────────


def test_add_skips_already_processed_ids(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3, 4])
    state_mod.mark_added(1)
    state_mod.mark_refused(2)
    state_mod.mark_error(3)

    captured = {}

    def fake_add_pending(access_token, appids, **_k):
        captured["appids"] = appids
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)
    monkeypatch.setattr(
        orch,
        "get_web_cookies",
        lambda *_a, **_k: {"steamLoginSecure": "76561198190468628||jwt.tok"},
    )

    result = orch.add()

    assert captured["appids"] == [4]
    assert result.added == [4]
    assert state_mod.load_added_ids() == {1, 4}


def test_add_respects_limit(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3])
    captured = {}

    def fake_add_pending(access_token, appids, **_k):
        captured["appids"] = appids
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)
    monkeypatch.setattr(
        orch, "get_web_cookies", lambda *_a, **_k: {"steamLoginSecure": "id||jwt"}
    )

    orch.add(limit=2)

    assert captured["appids"] == [1, 2]


def test_add_no_pending_returns_empty_without_cookie_fetch(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1])
    state_mod.mark_added(1)

    def _boom(*_a, **_k):
        raise AssertionError("get_web_cookies не должен вызываться без кандидатов")

    monkeypatch.setattr(orch, "get_web_cookies", _boom)

    result = orch.add()

    assert result == orch.wishlist_api.AddResult()


def test_add_no_session_returns_auth_fail_without_marking_error(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    monkeypatch.setattr(orch, "get_web_cookies", lambda *_a, **_k: None)

    result = orch.add()

    assert result.auth_fail is True
    assert state_mod.load_error_ids() == set()  # НЕ error.txt — resume подхватит


def test_add_passes_access_token_extracted_from_cookie(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1])
    captured = {}

    def fake_add_pending(access_token, appids, **_k):
        captured["access_token"] = access_token
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)
    monkeypatch.setattr(
        orch,
        "get_web_cookies",
        lambda *_a, **_k: {"steamLoginSecure": "76561198190468628||the.jwt.token"},
    )

    orch.add()

    assert captured["access_token"] == "the.jwt.token"


def test_add_auth_fail_retries_once_with_fresh_cookie(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    cookies_calls = {"n": 0}

    def fake_get_web_cookies(*_a, **_k):
        cookies_calls["n"] += 1
        return {"steamLoginSecure": f"id||tok{cookies_calls['n']}"}

    monkeypatch.setattr(orch, "get_web_cookies", fake_get_web_cookies)

    add_calls = {"n": 0}

    def fake_add_pending(access_token, appids, **_k):
        add_calls["n"] += 1
        if add_calls["n"] == 1:
            return orch.wishlist_api.AddResult(auth_fail=True)
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)

    result = orch.add()

    assert cookies_calls["n"] == 2  # первичный + одна попытка обновления
    assert result.added == [1, 2]
    assert result.auth_fail is False


def test_add_auth_fail_retry_also_fails_leaves_pending_unmarked(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    cookies_calls = {"n": 0}

    def fake_get_web_cookies(*_a, **_k):
        cookies_calls["n"] += 1
        if cookies_calls["n"] == 1:
            return {"steamLoginSecure": "id||tok1"}
        return None  # обновление тоже не удалось

    monkeypatch.setattr(orch, "get_web_cookies", fake_get_web_cookies)
    monkeypatch.setattr(
        orch.wishlist_api,
        "add_pending",
        lambda *_a, **_k: orch.wishlist_api.AddResult(auth_fail=True),
    )

    result = orch.add()

    assert result.auth_fail is True
    assert state_mod.load_added_ids() == set()
    assert state_mod.load_error_ids() == set()


# ── run() ─────────────────────────────────────────────────────────────────


def test_run_list_only_does_not_call_discover(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])

    def _boom(**_k):
        raise AssertionError("discover не должен вызываться при --list")

    monkeypatch.setattr(orch, "discover", _boom)

    orch.run(
        do_add=False,
        list_only=True,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )


def test_run_dry_run_reports_without_adding(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2, 3])
    captured = {}
    monkeypatch.setattr(orch.report, "report_result", lambda **kw: captured.update(kw))

    def _boom(**_k):
        raise AssertionError("add не должен вызываться без --add")

    monkeypatch.setattr(orch, "add", _boom)

    orch.run(
        do_add=False,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "dry_run"
    assert captured["added"] == 3


def test_run_add_reports_ok(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch, "add", lambda **_k: orch.wishlist_api.AddResult(added=[1, 2])
    )
    captured = {}
    monkeypatch.setattr(orch.report, "report_result", lambda **kw: captured.update(kw))

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "ok"
    assert captured["added"] == 2
    assert captured["hit_wall"] is False


def test_run_add_hit_wall_reports_not_ok(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch,
        "add",
        lambda **_k: orch.wishlist_api.AddResult(added=[1], hit_wall=True),
    )
    captured = {}
    monkeypatch.setattr(orch.report, "report_result", lambda **kw: captured.update(kw))

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "ok"
    assert captured["hit_wall"] is True  # report_result сам решает ✅/⚠️


def test_run_add_auth_fail_reports_error(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch, "add", lambda **_k: orch.wishlist_api.AddResult(auth_fail=True)
    )
    captured = {}
    monkeypatch.setattr(orch.report, "report_result", lambda **kw: captured.update(kw))

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"


def test_run_add_exception_reports_error(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])

    def _boom(**_k):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(orch, "add", _boom)
    captured = {}
    monkeypatch.setattr(orch.report, "report_result", lambda **kw: captured.update(kw))

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"


def test_run_add_keyboard_interrupt_reports_interrupted(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])

    def _boom(**_k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(orch, "add", _boom)
    captured = {}
    monkeypatch.setattr(orch.report, "report_result", lambda **kw: captured.update(kw))

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "interrupted"


def test_run_dry_run_discover_exception_reports_error(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)

    def _boom(**_k):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(orch, "discover", _boom)
    captured = {}
    monkeypatch.setattr(orch.report, "report_result", lambda **kw: captured.update(kw))

    orch.run(
        do_add=False,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_wishlist_orchestrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.wishlist.orchestrate'`

- [ ] **Step 3: Write the implementation**

`app/wishlist/orchestrate.py`:

```python
"""Оркестрация авто-добавления каталога Steam в вишлист: discover + add фазы."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.cookies import get_web_cookies
from app.logging_setup import SEPARATOR
from app.wishlist import discovery, report, state, wishlist_api

log = logging.getLogger("sam_automation")


def discover(*, api_key: str, steam_id: str) -> list[int]:
    """Фаза discover: universe (GetAppList) минус owned/wishlisted (Web API)
    минус added/refused (state) → candidates.txt."""
    log.info(SEPARATOR)
    discovered = discovery.discover_candidates(api_key=api_key, steam_id=steam_id)
    log.info(
        "Wishlist: обнаружено кандидатов (минус owned/wishlisted): %d",
        len(discovered),
    )

    already_added = state.load_added_ids()
    already_refused = state.load_refused_ids()
    candidates = [
        a for a in discovered if a not in already_added and a not in already_refused
    ]
    state.save_candidates(candidates)
    log.info("Кандидатов к добавлению (минус added/refused): %d", len(candidates))
    return candidates


def add(*, limit: int | None = None, interval: float = 1.0) -> wishlist_api.AddResult:
    """Фаза add: добавляет pending appid по одному (resume-aware).

    Сбой веб-сессии (нет cookie вовсе, или add_pending вернул auth_fail) НЕ
    помечает appid в error.txt — это сбой сессии, не транзиент конкретного
    appid; пользователь просто перезапустит --add после восстановления
    сессии, без --retry-errors (отличие от free_games, где CM-login-failure
    метит ВСЕ pending как error — там сессия внутри cm_session() ближе к
    per-run ресурсу, не хранится между запусками).
    """
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
        return wishlist_api.AddResult()

    log.info(SEPARATOR)
    log.info("Добавление в вишлист: %d кандидатов", len(pending))

    cookies = get_web_cookies("", interactive=False)
    if cookies is None:
        log.error("Steam: нет действующей веб-сессии — добавление невозможно")
        return wishlist_api.AddResult(auth_fail=True)

    access_token = cookies["steamLoginSecure"].split("||", 1)[1]
    result = wishlist_api.add_pending(access_token, pending, interval=interval)

    if result.auth_fail:
        remaining = [
            a for a in pending if a not in result.added and a not in result.refused
        ]
        log.warning("Wishlist: сессия истекла (401) — одна попытка обновить токен")
        cookies = get_web_cookies("", interactive=False)
        if cookies is not None:
            access_token = cookies["steamLoginSecure"].split("||", 1)[1]
            retry = wishlist_api.add_pending(access_token, remaining, interval=interval)
            result.added.extend(retry.added)
            result.refused.extend(retry.refused)
            result.error.extend(retry.error)
            result.hit_wall = result.hit_wall or retry.hit_wall
            result.auth_fail = retry.auth_fail
        # else: остаётся auth_fail=True, remaining НЕ помечен error — resume подхватит

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
    interval: float,
    api_key: str,
    steam_id: str,
    cfg: Any,
) -> None:
    """Точка входа: dry-run по умолчанию, реально добавляет только при do_add=True."""
    if list_only:
        listed_candidates = state.load_candidates()
        for appid in listed_candidates:
            print(appid)
        log.info("Кандидатов в candidates.txt: %d", len(listed_candidates))
        return

    status: Literal["ok", "interrupted", "error", "dry_run"] = "ok"
    candidates: list[int] = []
    result = wishlist_api.AddResult()
    try:
        candidates = discover(api_key=api_key, steam_id=steam_id)
        if do_add:
            result = add(limit=limit, interval=interval)
    except KeyboardInterrupt:
        status = "interrupted"
        log.info("Прервано (Ctrl+C).")
    except Exception:
        status = "error"
        log.exception("Прервано ошибкой.")

    if result.auth_fail and status == "ok":
        status = "error"

    if not do_add and status == "ok":
        report.report_result(
            status="dry_run",
            added=len(candidates),
            refused=0,
            error=0,
            hit_wall=False,
            cfg=cfg,
        )
        return

    report.report_result(
        status=status,
        added=len(result.added),
        refused=len(result.refused),
        error=len(result.error),
        hit_wall=result.hit_wall,
        cfg=cfg,
    )
```

Replace the full content of `app/wishlist/__init__.py`:

```python
"""Пакет авто-добавления каталога Steam в вишлист аккаунта.

Субмодули:
  discovery    — вселенная (GetAppList) минус owned/wishlisted (Web API дедуп)
  state        — resume-состояние (candidates/added/refused/error)
  wishlist_api — POST IWishlistService/AddToWishlist, x-eresult классификатор,
                 адаптивный backoff/wall
  report       — честный итоговый отчёт (toast + Telegram)
  orchestrate  — склейка фаз discover/add, точка входа для CLI
"""

from .orchestrate import run
from .wishlist_api import AddResult

__all__ = ["AddResult", "run"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_wishlist_orchestrate.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Gate + commit**

```bash
ruff format app/wishlist/ tests/unit/test_wishlist_orchestrate.py
ruff check .
mypy app
pytest tests/unit -q
git add app/wishlist/orchestrate.py app/wishlist/__init__.py tests/unit/test_wishlist_orchestrate.py
git commit -m "$(cat <<'EOF'
feat(wishlist): оркестрация discover/add/run + экспорт пакета

Склеивает state/wishlist_api/discovery/report. Сбой веб-сессии (нет cookie
или add_pending вернул auth_fail) НЕ метит pending в error.txt — это сбой
сессии, не транзиент конкретного appid; одна попытка обновить токен перед
честной остановкой.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: CLI `scripts/library/wishlist_add.py` + full-suite verification

**Files:**
- Create: `scripts/library/wishlist_add.py`

**Interfaces:**
- Consumes: `app.wishlist.run` (Task 7), `app.wishlist.state.clear_state`,
  `app.wishlist.state.clear_error_ids` (Task 1), `app.config.load_config`,
  `app.logging_setup.setup_logging`, `app.steam.resolve_steam_id`,
  `app.validator.validate` (all existing, unchanged).
- Produces: CLI entry point (no importable interface — this is the terminal
  task; `scripts/` is not mypy-typed and has no dedicated unit test file,
  matching the existing `scripts/library/add_free.py` precedent).

- [ ] **Step 1: Write the CLI script**

`scripts/library/wishlist_add.py`:

```python
"""Auto-add Wishlist — добавляет позиции каталога Steam в вишлист аккаунта.

Две фазы: discover (GetAppList минус owned/wishlisted → candidates.txt) и add
(добавление по одному через IWishlistService, resume-aware, адаптивный
backoff на rate-limit). По умолчанию — dry-run (только discover + отчёт),
реальное добавление — только по --add.

Использование:
    python scripts/library/wishlist_add.py              # dry-run: сколько найдено
    python scripts/library/wishlist_add.py --add         # реально добавить
    python scripts/library/wishlist_add.py --list        # показать candidates.txt
    python scripts/library/wishlist_add.py --add --limit 100
    python scripts/library/wishlist_add.py --add --retry-errors
    python scripts/library/wishlist_add.py --add --interval 0.2
    python scripts/library/wishlist_add.py --reset
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
from app.logging_setup import setup_logging
from app.steam import resolve_steam_id
from app.validator import validate
from app.wishlist import run
from app.wishlist import state as wishlist_state

log = logging.getLogger("sam_automation")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auto-add Wishlist — добавляет позиции каталога Steam в вишлист"
    )
    parser.add_argument(
        "--add",
        action="store_true",
        help="Реально добавить в вишлист (по умолчанию — dry-run, только discover)",
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
        "--interval",
        type=float,
        default=1.0,
        help="Пауза между добавлениями в секундах (0 = максимальная скорость)",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    setup_logging(name="wishlist_add", category="library/wishlist_add")
    cfg = load_config()

    # Резолвим Steam ID ДО валидации — как add_free.py/scan.py/boost.py:
    # validate шлёт steam_id в GetPlayerSummaries, которому нужен числовой ID64.
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
            wishlist_state.clear_state()
            log.info("Сброшено resume-состояние (--reset)")
        if args.retry_errors:
            wishlist_state.clear_error_ids()
            log.info("Очищен error.txt (--retry-errors)")

    run(
        do_add=args.add,
        list_only=args.list,
        limit=args.limit,
        interval=args.interval,
        api_key=cfg.steam_api_key,
        steam_id=cfg.steam_id,
        cfg=cfg,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the CLI (import + `--help`, no network/mutation)**

Run: `python scripts/library/wishlist_add.py --help`
Expected: argparse help text listing `--add`, `--list`, `--reset`,
`--retry-errors`, `--limit`, `--interval`, no traceback.

Run: `python -c "import ast; ast.parse(open('scripts/library/wishlist_add.py', encoding='utf-8').read())"`
Expected: no output (valid syntax) — cheap sanity check since this file is
not covered by `mypy` (scripts/ is out of scope) or a unit test.

- [ ] **Step 3: Full gate + final commit**

```bash
ruff format scripts/library/wishlist_add.py
ruff check .
ruff format --check .
mypy app
pytest tests/unit -q
```

Expected: all four green; `pytest tests/unit -q` shows the full project
suite passing including all `test_wishlist_*.py` files added in Tasks 1-7.

```bash
git add scripts/library/wishlist_add.py
git commit -m "$(cat <<'EOF'
feat(wishlist): CLI scripts/library/wishlist_add.py

Копия структуры add_free.py: --add/--list/--reset/--retry-errors/--limit +
новый --interval (пауза между add, дефолт 1с — вежливый, не троттлящий;
реальный ограничитель — адаптивный backoff в wishlist_api.add_pending).
Dry-run по умолчанию, мутация аккаунта только по явному --add.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Manual live smoke test (owner-run, NOT part of CI)**

This step is NOT automated — the owner runs it manually against the real
account when ready, per the design doc's "интеграция вне CI" note:

```bash
python scripts/library/wishlist_add.py            # dry-run: candidate count
python scripts/library/wishlist_add.py --add --limit 5   # small real --add
```

Confirms end-to-end: cookie session pickup, `candidates.txt` populated,
`added.txt` grows by ≤5, honest toast fires. Report back any deviation from
the live-verified facts in the design doc (e.g. if Steam's throttle behavior
has changed) before scaling up `--limit`.

---

## Definition of Done

- All 8 tasks committed on `feature/add-wishlist`, each passing the 4 gates.
- `pytest tests/unit -q` green with all new `test_wishlist_*.py` files
  included (state: 7, wishlist_api: 21, discovery: 12, report: 6,
  orchestrate: 17 — 63 new tests).
- No changes to `app/free_games/*`, `app/steam/*`, or any other existing
  module (pure addition, per Approach A / sibling package).
- Manual live smoke test (Task 8 Step 4) run by the owner before considering
  the feature "proven" end-to-end — this plan's automated tests all use
  mocked HTTP/cookies per the design doc's constraint (`tests/unit` only, no
  live network in CI).
