# Config Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `app/validator.py` that runs comprehensive pre-flight checks (local, process, network) before any script begins work, replacing the minimal `Config.validate()` method.

**Architecture:** A two-phase validator — Phase 1 checks local filesystem fields, Phase 2 checks that Steam is running and the API key resolves. All errors are collected and printed at once; `sys.exit(1)` fires only after all checks complete. Existing per-script `check_steam_running()` calls are kept (they are operational mid-run guards, not pre-flight).

**Tech Stack:** Python stdlib (`urllib.request`, `json`, `sys`, `logging`), `psutil` (already in requirements), `pytest` + `unittest.mock`

---

## File Map

| File | Action | Responsibility |
| --- | --- | --- |
| `app/validator.py` | Create | All validation logic: private check functions + `validate()` orchestrator |
| `tests/unit/test_validator.py` | Create | Unit tests for every private check function + `validate()` |
| `app/config.py` | Modify | Remove `Config.validate()` method |
| `tests/unit/test_config.py` | Modify | Remove two tests that test `Config.validate()` |
| `scripts/achievements/unlock.py` | Modify | Replace `cfg.validate()` with `validate(cfg)` |
| `scripts/achievements/scan.py` | Modify | Add `validate(cfg)`; remove manual `steam_id` guard (lines 88–90) |
| `scripts/cards/farm.py` | Modify | Replace `cfg.validate()` with `validate(cfg)` |
| `scripts/cards/detect_drops.py` | Modify | Replace `cfg.validate()` with `validate(cfg)` |
| `scripts/playtime/boost.py` | Modify | Replace `cfg.validate()` with `validate(cfg)` |

---

## Task 1: Phase 1 — local checks

**Files:**
- Create: `app/validator.py`
- Create: `tests/unit/test_validator.py`

- [ ] **Step 1: Write failing tests for `_check_required_fields` and `_check_file_paths`**

Create `tests/unit/test_validator.py`:

```python
"""Тесты для app/validator.py."""

from __future__ import annotations

from pathlib import Path

from app.config import Config
from app.validator import _check_file_paths, _check_required_fields


# ── _check_required_fields ────────────────────────────────────────────────


def test_required_fields_both_missing():
    cfg = Config()
    errors = _check_required_fields(cfg)
    assert "steam_api_key is missing" in errors
    assert "steam_id is missing" in errors


def test_required_fields_api_key_missing():
    cfg = Config(steam_id="76561198000000000")
    errors = _check_required_fields(cfg)
    assert "steam_api_key is missing" in errors
    assert len(errors) == 1


def test_required_fields_steam_id_missing():
    cfg = Config(steam_api_key="mykey")
    errors = _check_required_fields(cfg)
    assert "steam_id is missing" in errors
    assert len(errors) == 1


def test_required_fields_both_present():
    cfg = Config(steam_api_key="mykey", steam_id="76561198000000000")
    assert _check_required_fields(cfg) == []


# ── _check_file_paths ─────────────────────────────────────────────────────


def test_file_paths_game_ids_file_missing(tmp_path):
    cfg = Config(game_ids_file=str(tmp_path / "nonexistent.txt"))
    errors = _check_file_paths(cfg)
    assert any("game_ids_file not found" in e for e in errors)


def test_file_paths_game_ids_file_exists(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("440\n", encoding="utf-8")
    cfg = Config(game_ids_file=str(f))
    assert _check_file_paths(cfg) == []


def test_file_paths_steam_path_missing(tmp_path):
    cfg = Config(steam_path=str(tmp_path / "nosteam"))
    errors = _check_file_paths(cfg)
    assert any("steam_path not found" in e for e in errors)


def test_file_paths_steam_path_exists(tmp_path):
    cfg = Config(steam_path=str(tmp_path))
    assert _check_file_paths(cfg) == []


def test_file_paths_sam_exe_missing(tmp_path):
    cfg = Config(sam_game_exe_path=str(tmp_path / "SAM.Game.exe"))
    errors = _check_file_paths(cfg)
    assert any("sam_game_exe_path not found" in e for e in errors)


def test_file_paths_sam_exe_exists(tmp_path):
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"")
    cfg = Config(sam_game_exe_path=str(exe))
    assert _check_file_paths(cfg) == []


def test_file_paths_sam_exe_empty_string_skipped():
    # Empty string = auto-download, must not be checked
    cfg = Config(sam_game_exe_path="")
    assert _check_file_paths(cfg) == []


def test_file_paths_all_unset():
    # Nothing set = nothing to check
    cfg = Config()
    assert _check_file_paths(cfg) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /c/Users/Deniz/Downloads/projects/github/sam-automation
python -m pytest tests/unit/test_validator.py -v
```

Expected: `ERROR` — `app/validator.py` does not exist yet.

- [ ] **Step 3: Implement `_check_required_fields` and `_check_file_paths`**

Create `app/validator.py`:

```python
"""Pre-flight validation for config.yaml.

Usage in scripts:
    from app.validator import validate
    cfg = load_config()
    validate(cfg)   # sys.exit(1) if any check fails
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from app.config import Config

log = logging.getLogger("sam_automation")


# ── Phase 1: local checks ─────────────────────────────────────────────────


def _check_required_fields(cfg: Config) -> list[str]:
    errors: list[str] = []
    if not cfg.steam_api_key:
        errors.append("steam_api_key is missing")
    if not cfg.steam_id:
        errors.append("steam_id is missing")
    return errors


def _check_file_paths(cfg: Config) -> list[str]:
    errors: list[str] = []
    if cfg.game_ids_file and not Path(cfg.game_ids_file).exists():
        errors.append(f"game_ids_file not found: {cfg.game_ids_file}")
    if cfg.steam_path and not Path(cfg.steam_path).exists():
        errors.append(f"steam_path not found: {cfg.steam_path}")
    if cfg.sam_game_exe_path and not Path(cfg.sam_game_exe_path).exists():
        errors.append(f"sam_game_exe_path not found: {cfg.sam_game_exe_path}")
    return errors


# ── Phase 2: external checks ──────────────────────────────────────────────


def _check_steam_process() -> list[str]:
    try:
        names = {p.name().lower() for p in psutil.process_iter(["name"])}
        if "steam.exe" not in names:
            return ["Steam is not running — start Steam and try again"]
        return []
    except Exception as exc:
        return [f"Could not check Steam process: {exc}"]


def _check_steam_api(cfg: Config) -> list[str]:
    url = (
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
        f"?key={cfg.steam_api_key}&steamids={cfg.steam_id}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            # urlopen only returns here on HTTP 200; non-2xx raises HTTPError
            data = json.loads(resp.read())
            players = data.get("response", {}).get("players", [])
            if not players:
                return ["Steam API key is invalid or Steam ID not found"]
            return []
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return ["Steam API rate limited (HTTP 429) — try again in a moment"]
        return [f"Steam API returned unexpected status: HTTP {exc.code}"]
    except urllib.error.URLError as exc:
        return [f"Could not reach Steam API: {exc.reason}"]
    except OSError as exc:
        return [f"Could not reach Steam API: {exc}"]


# ── Orchestrator ──────────────────────────────────────────────────────────


def _report_and_exit(errors: list[str]) -> None:
    for err in errors:
        log.error("[CONFIG ERROR] %s", err)
    count = len(errors)
    noun = "error" if count == 1 else "errors"
    log.error("%d config %s found. Fix config.yaml and try again.", count, noun)
    sys.exit(1)


def validate(cfg: Config) -> None:
    """Run all pre-flight checks. Calls sys.exit(1) if any check fails."""
    # Phase 1 — local (fast, no network)
    errors: list[str] = []
    errors.extend(_check_required_fields(cfg))
    errors.extend(_check_file_paths(cfg))
    if errors:
        _report_and_exit(errors)

    # Phase 2 — external (process + network)
    errors.extend(_check_steam_process())
    errors.extend(_check_steam_api(cfg))
    if errors:
        _report_and_exit(errors)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_validator.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/validator.py tests/unit/test_validator.py
git commit -m "feat: add validator.py with Phase 1 local checks"
```

---

## Task 2: Phase 2 — external checks

**Files:**
- Modify: `tests/unit/test_validator.py` (add Phase 2 tests)

- [ ] **Step 1: Add failing tests for `_check_steam_process` and `_check_steam_api`**

Append to `tests/unit/test_validator.py`:

```python
from unittest.mock import MagicMock, patch

from app.validator import _check_steam_api, _check_steam_process


# ── _check_steam_process ──────────────────────────────────────────────────


def test_steam_process_running():
    proc = MagicMock()
    proc.name.return_value = "steam.exe"
    with patch("psutil.process_iter", return_value=[proc]):
        assert _check_steam_process() == []


def test_steam_process_not_running():
    proc = MagicMock()
    proc.name.return_value = "chrome.exe"
    with patch("psutil.process_iter", return_value=[proc]):
        errors = _check_steam_process()
        assert any("Steam is not running" in e for e in errors)


def test_steam_process_psutil_raises():
    with patch("psutil.process_iter", side_effect=RuntimeError("access denied")):
        errors = _check_steam_process()
        assert any("Could not check Steam process" in e for e in errors)


# ── _check_steam_api ──────────────────────────────────────────────────────


def _make_response(status: int, body: bytes):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_steam_api_valid():
    body = b'{"response":{"players":[{"steamid":"76561198000000000"}]}}'
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch("urllib.request.urlopen", return_value=_make_response(200, body)):
        assert _check_steam_api(cfg) == []


def test_steam_api_empty_players():
    body = b'{"response":{"players":[]}}'
    cfg = Config(steam_api_key="badkey", steam_id="76561198000000000")
    with patch("urllib.request.urlopen", return_value=_make_response(200, body)):
        errors = _check_steam_api(cfg)
        assert any("invalid or Steam ID not found" in e for e in errors)


def test_steam_api_rate_limited():
    import urllib.error
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None),
    ):
        errors = _check_steam_api(cfg)
        assert any("rate limited" in e for e in errors)


def test_steam_api_unexpected_status():
    import urllib.error
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 500, "Internal Server Error", {}, None),
    ):
        errors = _check_steam_api(cfg)
        assert any("HTTP 500" in e for e in errors)


def test_steam_api_network_error():
    import urllib.error
    cfg = Config(steam_api_key="key", steam_id="76561198000000000")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        errors = _check_steam_api(cfg)
        assert any("Could not reach Steam API" in e for e in errors)
```

- [ ] **Step 2: Run new tests to verify they pass**

```bash
python -m pytest tests/unit/test_validator.py -v
```

Expected: all tests PASS (Phase 2 functions are already in `app/validator.py`).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_validator.py
git commit -m "test: add Phase 2 tests for validator (steam process + API)"
```

---

## Task 3: `validate()` orchestrator tests

**Files:**
- Modify: `tests/unit/test_validator.py` (add orchestrator tests)

- [ ] **Step 1: Add failing tests for `validate()`**

Append to `tests/unit/test_validator.py`:

```python
import pytest
from app.validator import validate


# ── validate() orchestrator ───────────────────────────────────────────────


def _valid_cfg():
    return Config(steam_api_key="key", steam_id="76561198000000000")


def _steam_running():
    proc = MagicMock()
    proc.name.return_value = "steam.exe"
    return patch("psutil.process_iter", return_value=[proc])


def _api_ok():
    body = b'{"response":{"players":[{"steamid":"76561198000000000"}]}}'
    return patch("urllib.request.urlopen", return_value=_make_response(200, body))


def test_validate_passes_with_valid_config():
    cfg = _valid_cfg()
    with _steam_running(), _api_ok():
        validate(cfg)  # must not raise or exit


def test_validate_exits_on_missing_api_key():
    cfg = Config(steam_id="76561198000000000")
    with pytest.raises(SystemExit):
        validate(cfg)


def test_validate_exits_on_missing_steam_id():
    cfg = Config(steam_api_key="key")
    with pytest.raises(SystemExit):
        validate(cfg)


def test_validate_phase2_skipped_when_phase1_fails():
    # Phase 2 (psutil, urlopen) must never be called when Phase 1 fails
    cfg = Config()
    with (
        patch("psutil.process_iter") as mock_psutil,
        patch("urllib.request.urlopen") as mock_urlopen,
        pytest.raises(SystemExit),
    ):
        validate(cfg)
    mock_psutil.assert_not_called()
    mock_urlopen.assert_not_called()


def test_validate_exits_when_steam_not_running(tmp_path):
    cfg = _valid_cfg()
    proc = MagicMock()
    proc.name.return_value = "explorer.exe"
    with (
        patch("psutil.process_iter", return_value=[proc]),
        pytest.raises(SystemExit),
    ):
        validate(cfg)


def test_validate_exits_on_invalid_api_key():
    cfg = _valid_cfg()
    body = b'{"response":{"players":[]}}'
    with (
        _steam_running(),
        patch("urllib.request.urlopen", return_value=_make_response(200, body)),
        pytest.raises(SystemExit),
    ):
        validate(cfg)
```

- [ ] **Step 2: Run new tests to verify they pass**

```bash
python -m pytest tests/unit/test_validator.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_validator.py
git commit -m "test: add orchestrator tests for validate()"
```

---

## Task 4: Remove `Config.validate()`

**Files:**
- Modify: `app/config.py` (remove `validate()` method)
- Modify: `tests/unit/test_config.py` (remove two tests that test `Config.validate()`)

- [ ] **Step 1: Delete `Config.validate()` from `app/config.py`**

Remove lines 43–52 from `app/config.py`:

```python
    def validate(self) -> None:
        """Проверяет обязательные поля конфига. Завершает процесс при ошибке."""
        import logging
        import sys

        if not self.steam_api_key or not self.steam_id:
            log = logging.getLogger("sam_automation")
            log.error("Заполни steam_api_key и steam_id в config.yaml")
            log.error("API ключ: https://steamcommunity.com/dev/apikey")
            sys.exit(1)
```

- [ ] **Step 2: Remove `Config.validate()` tests from `tests/unit/test_config.py`**

Remove the two tests under `# ── Config.validate ───` (lines 86–100):

```python
# ── Config.validate ───────────────────────────────────────────────────────


def test_validate_exits_when_missing_credentials():
    ...


def test_validate_passes_with_credentials():
    ...
```

- [ ] **Step 3: Run full test suite to verify nothing is broken**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS. (The two removed tests are gone; all others pass.)

- [ ] **Step 4: Commit**

```bash
git add app/config.py tests/unit/test_config.py
git commit -m "refactor: remove Config.validate() — superseded by app/validator.py"
```

---

## Task 5: Wire `validate()` into all scripts

**Files:**
- Modify: `scripts/achievements/unlock.py`
- Modify: `scripts/achievements/scan.py`
- Modify: `scripts/cards/farm.py`
- Modify: `scripts/cards/detect_drops.py`
- Modify: `scripts/playtime/boost.py`

- [ ] **Step 1: Update `scripts/achievements/unlock.py`**

Find the import block and `cfg.validate()` call. Replace:

```python
cfg = load_config()
cfg.validate()
```

With:

```python
from app.validator import validate

cfg = load_config()
validate(cfg)
```

Move the `from app.validator import validate` import to the top-level import block (alongside other `from app.*` imports), not inline.

- [ ] **Step 2: Update `scripts/achievements/scan.py`**

Add import at top of import block:

```python
from app.validator import validate
```

After `cfg = load_config()` (line 86), replace the manual guard:

```python
if not cfg.steam_id:
    log.error("Заполни steam_id в config.yaml")
    sys.exit(1)
```

With:

```python
validate(cfg)
```

Remove the `log.info("Ваш Steam ID: %s", cfg.steam_id)` line that immediately followed the removed guard (line 92) — it is now redundant since the validator already confirmed the value.

Actually, keep the log.info line — it provides useful context for the user. Only remove the manual guard (lines 88–90).

- [ ] **Step 3: Update `scripts/cards/farm.py`**

Same pattern as `unlock.py`:

```python
from app.validator import validate

cfg = load_config()
validate(cfg)
```

Replace `cfg.validate()`.

- [ ] **Step 4: Update `scripts/cards/detect_drops.py`**

Same pattern:

```python
from app.validator import validate

cfg = load_config()
validate(cfg)
```

Replace `cfg.validate()`.

- [ ] **Step 5: Update `scripts/playtime/boost.py`**

Same pattern:

```python
from app.validator import validate

cfg = load_config()
validate(cfg)
```

Replace `cfg.validate()`.

- [ ] **Step 6: Verify no remaining `cfg.validate()` calls**

```bash
grep -rn "cfg\.validate()" scripts/
```

Expected: no output.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/achievements/unlock.py scripts/achievements/scan.py \
        scripts/cards/farm.py scripts/cards/detect_drops.py \
        scripts/playtime/boost.py
git commit -m "feat: wire validator.validate(cfg) into all scripts"
```
