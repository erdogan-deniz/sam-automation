# SAM Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `ensure_sam()` is called and SAM is already installed, compare the installed version against the latest GitHub release and interactively prompt the user to update if a newer version exists.

**Architecture:** A `.sam_version` file next to `SAM.Game.exe` stores the installed `tag_name`. On `ensure_sam()`, a new `check_for_update()` function reads this file, fetches the latest GitHub release tag via the existing API URL, and prompts `[y/n]` if they differ. GitHub API logic is extracted into `_fetch_latest_release()` to avoid double fetching when `check_for_update` passes the already-fetched release to `download_sam`.

**Tech Stack:** Python stdlib only (`urllib.request`, `json`, `pathlib`). Tests use `pytest` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-03-23-sam-auto-update-design.md`

---

## File Map

| File | Action | Responsibility |
| ---- | ------ | -------------- |
| `.gitignore` | Modify | Exclude runtime `.sam_version` files |
| `app/sam/sam_downloader.py` | Modify | All version-check logic lives here |
| `tests/unit/test_sam_downloader.py` | Create | Unit tests for all new/modified functions |

---

## Task 1: Exclude `.sam_version` from git

**Files:**

- Modify: `.gitignore`

- [ ] **Step 1: Add gitignore entry to the Runtime State section**

Open `.gitignore`. Find the `# ── Runtime State ──` section:

```gitignore
# ── Runtime State ─────────────────────────────────────────────────────────────
data/*
!data/.gitkeep
logs/*
!logs/.gitkeep
```

Add one line after `!logs/.gitkeep`:

```gitignore
**/.sam_version
```

`.sam_version` is a runtime artifact (written by the program at runtime), so it belongs
in the Runtime State section, not with SAM binaries.

- [ ] **Step 2: Verify**

```bash
git status
```

Expected: no `.sam_version` files appear as untracked.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore runtime .sam_version files"
```

---

## Task 2: Version file helpers + tests

**Files:**

- Modify: `app/sam/sam_downloader.py`
- Create: `tests/unit/test_sam_downloader.py`

### Step 2a — write failing tests first

- [ ] **Step 1: Create test file**

Create `tests/unit/test_sam_downloader.py` with this full content (consolidated imports
cover all tasks — add to them incrementally as each task adds new imports):

```python
"""Тесты для app/sam/sam_downloader.py."""

from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.sam.sam_downloader import (
    _fetch_latest_release,
    _read_installed_version,
    _save_version,
    check_for_update,
    download_sam,
    ensure_sam,
)


# ── Shared test helpers ───────────────────────────────────────────────────────


def _make_release(tag: str = "r68") -> dict:
    return {
        "tag_name": tag,
        "assets": [{"name": "SAM.zip", "browser_download_url": "http://example.com/SAM.zip"}],
    }


def _make_zip_bytes() -> bytes:
    """Создаёт in-memory ZIP с SAM.Game.exe внутри."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SAM.Game.exe", b"fake exe")
    return buf.getvalue()


def _make_url_mock(data: bytes) -> MagicMock:
    """Возвращает context-manager mock для urllib.request.urlopen."""
    mock = MagicMock()
    mock.read.return_value = data
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _setup_sam_dir(tmp_path: Path, installed_tag: str | None) -> Path:
    """Создаёт фейковую директорию с exe и опциональным .sam_version."""
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    if installed_tag is not None:
        _save_version(tmp_path, installed_tag)
    return exe


# ── _save_version ─────────────────────────────────────────────────────────────


def test_save_version_writes_tag(tmp_path):
    _save_version(tmp_path, "r68")
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r68"


def test_save_version_overwrites(tmp_path):
    _save_version(tmp_path, "r68")
    _save_version(tmp_path, "r69")
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r69"


# ── _read_installed_version ───────────────────────────────────────────────────


def test_read_installed_version_returns_tag(tmp_path):
    (tmp_path / ".sam_version").write_text("r68\n", encoding="utf-8")
    assert _read_installed_version(tmp_path) == "r68"


def test_read_installed_version_missing_returns_none(tmp_path):
    assert _read_installed_version(tmp_path) is None


def test_read_installed_version_strips_whitespace(tmp_path):
    (tmp_path / ".sam_version").write_text("  r68  \n", encoding="utf-8")
    assert _read_installed_version(tmp_path) == "r68"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/test_sam_downloader.py::test_save_version_writes_tag -v
```

Expected: `ImportError` because `_save_version` does not exist yet.

### Step 2b — implement

- [ ] **Step 3: Add helpers to `sam_downloader.py`**

In `app/sam/sam_downloader.py`, add these two functions after the `SAM_API_URL` constant
and before the existing `download_sam` function:

```python
def _save_version(sam_dir: Path, tag_name: str) -> None:
    """Сохраняет tag_name установленной версии SAM в <sam_dir>/.sam_version."""
    (sam_dir / ".sam_version").write_text(tag_name, encoding="utf-8")


def _read_installed_version(sam_dir: Path) -> str | None:
    """Возвращает tag_name из .sam_version, или None если файл отсутствует."""
    version_file = sam_dir / ".sam_version"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/unit/test_sam_downloader.py -k "_save_version or _read_installed" -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/sam/sam_downloader.py tests/unit/test_sam_downloader.py
git commit -m "feat: add _save_version and _read_installed_version helpers"
```

---

## Task 3: Extract `_fetch_latest_release` + tests

**Files:**

- Modify: `app/sam/sam_downloader.py`
- Modify: `tests/unit/test_sam_downloader.py`

The GitHub API call currently lives inline inside `download_sam()`. Extracting it
prevents a double HTTP round-trip when `check_for_update` passes the release to `download_sam`.

- [ ] **Step 1: Append failing tests to test file**

Add to `tests/unit/test_sam_downloader.py`:

```python
# ── _fetch_latest_release ─────────────────────────────────────────────────────


def test_fetch_latest_release_returns_dict():
    release = _make_release("r68")
    mock_resp = _make_url_mock(json.dumps(release).encode())
    with patch("app.sam.sam_downloader.urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_latest_release()
    assert result["tag_name"] == "r68"
    assert len(result["assets"]) == 1


def test_fetch_latest_release_raises_on_network_error():
    with patch("app.sam.sam_downloader.urllib.request.urlopen",
               side_effect=urllib.error.URLError("timeout")):
        with pytest.raises(urllib.error.URLError):
            _fetch_latest_release()
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/test_sam_downloader.py::test_fetch_latest_release_returns_dict -v
```

Expected: `ImportError` — `_fetch_latest_release` not defined yet.

- [ ] **Step 3: Extract `_fetch_latest_release` in `sam_downloader.py`**

Add after `_read_installed_version`:

```python
def _fetch_latest_release() -> dict:
    """Запрашивает последний релиз SAM с GitHub API и возвращает распарсенный dict."""
    req = urllib.request.Request(SAM_API_URL)
    req.add_header("User-Agent", "SAM-Automation")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

In `download_sam`, **remove** the existing inline block:

```python
# REMOVE:
req = urllib.request.Request(SAM_API_URL)
req.add_header("User-Agent", "SAM-Automation")
with urllib.request.urlopen(req, timeout=30) as resp:
    release = json.loads(resp.read().decode("utf-8"))

# REPLACE WITH:
release = _fetch_latest_release()
```

Keep the `log.info("Скачиваю SAM с GitHub (%s) ...", SAM_REPO)` line in `download_sam`,
immediately before the conditional `_fetch_latest_release()` call. This ensures a log entry
on every download (both fresh installs and updates) and preserves the existing behavior.

- [ ] **Step 4: Run all tests — expect PASS**

```bash
pytest tests/unit/test_sam_downloader.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/sam/sam_downloader.py tests/unit/test_sam_downloader.py
git commit -m "refactor: extract _fetch_latest_release from download_sam"
```

---

## Task 4: Update `download_sam` — add `release` param + save version

**Files:**

- Modify: `app/sam/sam_downloader.py`
- Modify: `tests/unit/test_sam_downloader.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/unit/test_sam_downloader.py`:

```python
# ── download_sam ──────────────────────────────────────────────────────────────


def test_download_sam_saves_version(tmp_path):
    release = _make_release("r68")
    with patch("app.sam.sam_downloader._fetch_latest_release", return_value=release), \
         patch("app.sam.sam_downloader.urllib.request.urlopen",
               return_value=_make_url_mock(_make_zip_bytes())):
        download_sam(str(tmp_path))
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r68"


def test_download_sam_uses_provided_release(tmp_path):
    """Если release передан — _fetch_latest_release не вызывается."""
    release = _make_release("r69")
    with patch("app.sam.sam_downloader._fetch_latest_release") as mock_fetch, \
         patch("app.sam.sam_downloader.urllib.request.urlopen",
               return_value=_make_url_mock(_make_zip_bytes())):
        download_sam(str(tmp_path), release=release)
        mock_fetch.assert_not_called()
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r69"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/unit/test_sam_downloader.py::test_download_sam_saves_version -v
```

Expected: `TypeError` — `download_sam` does not accept `release` param.

- [ ] **Step 3: Update `download_sam` signature**

Change the function signature from:

```python
def download_sam(target_dir: str) -> str:
```

to:

```python
def download_sam(target_dir: str, release: dict | None = None) -> str:
    """Скачивает SAM с GitHub и распаковывает.

    Args:
        target_dir: Директория для распаковки.
        release:    Уже полученный dict релиза (опционально).
                    Если None — запрашивается с GitHub.
    Returns:
        Путь к SAM.Game.exe
    """
```

In the function body, replace the `release = _fetch_latest_release()` line (from Task 3)
with a conditional:

```python
if release is None:
    release = _fetch_latest_release()
```

- [ ] **Step 4: Add `_save_version` call inside the `os.walk` loop**

The current end of `download_sam` looks like this (the exe is found inside a nested loop):

```python
    for root, dirs, files in os.walk(target):
        for f in files:
            if f.lower() == "sam.game.exe":
                exe_path = os.path.join(root, f)
                log.info("SAM скачан: %s", exe_path)
                return exe_path               # ← BEFORE this return
```

Add `_save_version` **inside the inner loop, immediately before the `return`**:

```python
    for root, dirs, files in os.walk(target):
        for f in files:
            if f.lower() == "sam.game.exe":
                exe_path = os.path.join(root, f)
                log.info("SAM скачан: %s", exe_path)
                _save_version(target, release["tag_name"])  # ← добавить
                return exe_path
```

Note: `target` refers to the existing `target = Path(target_dir)` assignment at the top
of `download_sam`'s body — that local variable is already there and is the directory.
Do NOT add `_save_version` after the final `raise RuntimeError` — it is unreachable and
`.sam_version` must only be written after the exe is confirmed present.

- [ ] **Step 5: Run all tests — expect PASS**

```bash
pytest tests/unit/test_sam_downloader.py -v
```

- [ ] **Step 6: Commit**

```bash
git add app/sam/sam_downloader.py tests/unit/test_sam_downloader.py
git commit -m "feat: save .sam_version after download, accept pre-fetched release"
```

---

## Task 5: Implement `check_for_update` + tests

**Files:**

- Modify: `app/sam/sam_downloader.py`
- Modify: `tests/unit/test_sam_downloader.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/unit/test_sam_downloader.py`:

```python
# ── check_for_update ──────────────────────────────────────────────────────────


def test_check_for_update_returns_none_when_up_to_date(tmp_path):
    exe = _setup_sam_dir(tmp_path, "r68")
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r68")):
        assert check_for_update(str(exe)) is None


def test_check_for_update_returns_none_when_user_declines(tmp_path):
    exe = _setup_sam_dir(tmp_path, "r68")
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r69")), \
         patch("builtins.input", return_value="n"):
        assert check_for_update(str(exe)) is None


def test_check_for_update_returns_new_path_when_user_accepts(tmp_path):
    exe = _setup_sam_dir(tmp_path, "r68")
    new_exe = str(exe)
    release = _make_release("r69")
    with patch("app.sam.sam_downloader._fetch_latest_release", return_value=release), \
         patch("builtins.input", return_value="y"), \
         patch("app.sam.sam_downloader.download_sam", return_value=new_exe) as mock_dl:
        result = check_for_update(str(exe))
    assert result == new_exe
    mock_dl.assert_called_once_with(str(tmp_path), release=release)


def test_check_for_update_returns_none_on_eof(tmp_path):
    exe = _setup_sam_dir(tmp_path, "r68")
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r69")), \
         patch("builtins.input", side_effect=EOFError):
        assert check_for_update(str(exe)) is None


def test_check_for_update_prompts_when_version_unknown(tmp_path):
    """Если .sam_version отсутствует — всё равно спрашивает пользователя."""
    exe = _setup_sam_dir(tmp_path, None)
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r69")), \
         patch("builtins.input", return_value="n") as mock_input:
        check_for_update(str(exe))
    mock_input.assert_called_once_with("Обновить SAM? [y/n]: ")


def test_check_for_update_returns_new_path_when_version_unknown_and_accepts(tmp_path):
    """Версия неизвестна + пользователь согласился → возвращает новый путь."""
    exe = _setup_sam_dir(tmp_path, None)
    new_exe = str(exe)
    release = _make_release("r69")
    with patch("app.sam.sam_downloader._fetch_latest_release", return_value=release), \
         patch("builtins.input", return_value="y"), \
         patch("app.sam.sam_downloader.download_sam", return_value=new_exe) as mock_dl:
        result = check_for_update(str(exe))
    assert result == new_exe
    mock_dl.assert_called_once_with(str(tmp_path), release=release)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/test_sam_downloader.py -k "check_for_update" -v
```

Expected: `ImportError` — `check_for_update` not defined.

- [ ] **Step 3: Implement `check_for_update`**

Add after `_fetch_latest_release` in `sam_downloader.py`:

```python
def check_for_update(exe_path: str) -> str | None:
    """Проверяет наличие обновления SAM на GitHub и предлагает обновить.

    Returns:
        Новый путь к SAM.Game.exe если обновление установлено, иначе None.
    """
    exe_dir = Path(exe_path).parent
    installed = _read_installed_version(exe_dir)
    release = _fetch_latest_release()
    latest = release["tag_name"]

    if installed == latest:
        log.debug("SAM %s — последняя версия", latest)
        return None

    if installed is None:
        log.info("Версия SAM неизвестна. Последняя: %s", latest)
    else:
        log.info("Доступна новая версия SAM: %s (текущая: %s)", latest, installed)

    try:
        answer = input("Обновить SAM? [y/n]: ").strip().lower()
    except EOFError:
        log.info("Не интерактивный режим — пропускаю обновление SAM")
        return None

    if answer != "y":
        return None

    return download_sam(str(exe_dir), release=release)
```

- [ ] **Step 4: Run all tests — expect PASS**

```bash
pytest tests/unit/test_sam_downloader.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/sam/sam_downloader.py tests/unit/test_sam_downloader.py
git commit -m "feat: implement check_for_update"
```

---

## Task 6: Update `ensure_sam` + tests

**Files:**

- Modify: `app/sam/sam_downloader.py`
- Modify: `tests/unit/test_sam_downloader.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/unit/test_sam_downloader.py`:

```python
# ── ensure_sam ────────────────────────────────────────────────────────────────


def test_ensure_sam_returns_updated_path_after_update(tmp_path):
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    new_path = str(tmp_path / "sub" / "SAM.Game.exe")
    with patch("app.sam.sam_downloader.check_for_update", return_value=new_path):
        assert ensure_sam(str(exe)) == new_path


def test_ensure_sam_returns_original_path_when_no_update(tmp_path):
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    with patch("app.sam.sam_downloader.check_for_update", return_value=None):
        assert ensure_sam(str(exe)) == str(exe)


def test_ensure_sam_continues_on_network_error(tmp_path):
    """Ошибка сети при проверке обновлений — скрипт продолжает работу."""
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    with patch("app.sam.sam_downloader.check_for_update",
               side_effect=urllib.error.URLError("timeout")):
        assert ensure_sam(str(exe)) == str(exe)


def test_ensure_sam_downloads_when_exe_missing(tmp_path):
    exe_path = str(tmp_path / "SAM.Game.exe")
    expected = str(tmp_path / "SAM.Game.exe")
    with patch("app.sam.sam_downloader.download_sam", return_value=expected) as mock_dl:
        result = ensure_sam(exe_path)
    assert result == expected
    mock_dl.assert_called_once_with(str(tmp_path))
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/unit/test_sam_downloader.py -k "ensure_sam" -v
```

Expected: `test_ensure_sam_returns_updated_path_after_update` FAILS — current `ensure_sam`
returns immediately without calling `check_for_update`.

- [ ] **Step 3: Update `ensure_sam`**

Replace the current `ensure_sam` body with:

```python
def ensure_sam(exe_path: str) -> str:
    """Проверяет наличие SAM.Game.exe. Если нет — скачивает.
    Если есть — проверяет наличие обновлений на GitHub.

    Returns:
        Актуальный путь к SAM.Game.exe
    """
    if not Path(exe_path).exists():
        log.warning("SAM.Game.exe не найден по пути: %s", exe_path)
        sam_dir = Path(exe_path).parent
        return download_sam(str(sam_dir))

    try:
        updated_path = check_for_update(exe_path)
        if updated_path:
            return updated_path
    except Exception as e:  # broad catch: network, API, or unexpected errors are all non-fatal here
        # Trade-off: a programming error in check_for_update (e.g. KeyError on API response)
        # is also caught and logged as a warning instead of crashing. This is acceptable
        # because the update check is a best-effort operation — the script must continue.
        log.warning("Не удалось проверить обновления SAM: %s", e)

    return exe_path
```

- [ ] **Step 4: Run full test suite — expect all PASS**

```bash
pytest tests/ -v
```

Expected: all existing tests + new tests PASS. No regressions.

- [ ] **Step 5: Final commit**

```bash
git add app/sam/sam_downloader.py tests/unit/test_sam_downloader.py
git commit -m "feat: check for SAM updates in ensure_sam"
```

---

## Verification

```bash
pytest tests/ -v
```

Manual smoke test (requires real SAM installed at the path in `config.yaml`):

```bash
# Simulate an older installed version:
python -c "from pathlib import Path; from app.config import load_config; \
  cfg = load_config(); \
  (Path(cfg.sam_game_exe_path).parent / '.sam_version').write_text('r1')"

# Run any script that calls ensure_sam (--list exits early without Steam):
python scripts/cards/farm.py --list

# Expected console output includes:
#   INFO  Доступна новая версия SAM: rXX (текущая: r1)
#   Обновить SAM? [y/n]:
```
