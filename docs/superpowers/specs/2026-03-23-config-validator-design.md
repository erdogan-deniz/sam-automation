# Design: Config Validator

**Date:** 2026-03-23
**Status:** Approved

## Problem

Scripts run for hours overnight. If `config.yaml` has a wrong API key, missing Steam ID, or a
stale `game_ids_file` path, the error surfaces mid-run — after wasting time. The current
`Config.validate()` checks only that `steam_api_key` and `steam_id` are non-empty; it does not
verify that they are actually valid, does not check file paths, and does not confirm Steam is
running.

## Solution

Replace `Config.validate()` with a dedicated `app/validator.py` module that runs a comprehensive
set of local, process, and network checks before any script begins work. All errors are collected
and printed at once (fail-all, not fail-fast), then the process exits with code 1 if any check
failed.

## Scope

- **Trigger:** automatic — called at the start of every script's `main()`
- **Behaviour on failure:** hard stop (`sys.exit(1)`) — no prompts, no "continue anyway"
- **Error reporting:** collect all errors, print them together, then exit
- **Scripts covered:** `unlock.py`, `scan.py`, `farm.py`, `detect_drops.py`, `boost.py`

## Architecture

### `app/validator.py`

One public function:

```python
def validate(cfg: Config) -> None
```

`validate()` calls `sys.exit(1)` directly when errors are found — it does not raise an
exception. This is intentional: the function is a CLI guard, not a library helper. Tests that
need to verify validation behaviour should use `unittest.mock.patch("sys.exit")` or call the
individual private check functions directly.

Internally structured as two phases:

**Phase 1 — Local checks** (filesystem only, no network):
1. `steam_api_key` is non-empty
2. `steam_id` is non-empty
3. `game_ids_file` — if set, the file must exist on disk
4. `steam_path` — if set, the directory must exist on disk
5. `sam_game_exe_path` — if non-empty (the default in `Config` is `""`), the file must exist on
   disk; an empty string means "auto-download on first run" and is not checked here

**Phase 2 — External checks** (process + network, only runs if Phase 1 passes):
6. `steam.exe` process is running — checked via `psutil.process_iter()`
7. Steam API key is valid and Steam ID resolves — single call to
   `ISteamUser/GetPlayerSummaries/v0002/` with both values; a 200 response with a non-empty
   `players` list confirms both

If Phase 1 has any errors, Phase 2 is skipped entirely — no point hitting the network with a
broken config. The summary line always shows the total count of errors collected across whichever
phases ran (e.g. "2 config errors found" when Phase 1 produced 2 errors and Phase 2 was skipped;
"1 config error found" when Phase 1 passed but Phase 2 produced 1 error).

### Error output format

```
[CONFIG ERROR] steam_api_key is missing
[CONFIG ERROR] game_ids_file not found: data/mylist.txt
[CONFIG ERROR] Steam API key is invalid or Steam ID not found (HTTP 200, empty players list)
3 config errors found. Fix config.yaml and try again.
```

Each line is written via `log.error(...)` using the existing `sam_automation` logger (same as
used everywhere else in the project). The final summary line is also `log.error`.

### `Config.validate()` removal

The existing `Config.validate()` method in `app/config.py` is deleted. All call sites are
updated to use `validator.validate(cfg)` instead.

## Integration

Each script calls `validator.validate(cfg)` immediately after `cfg = load_config()`:

```python
from app.validator import validate

cfg = load_config()
validate(cfg)          # exits if any check fails
```

Scripts affected:

| Script | Currently calls |
| --- | --- |
| `scripts/achievements/unlock.py` | `cfg.validate()` → replace |
| `scripts/achievements/scan.py` | nothing → add |
| `scripts/cards/farm.py` | `cfg.validate()` → replace |
| `scripts/cards/detect_drops.py` | `cfg.validate()` → replace |
| `scripts/playtime/boost.py` | `cfg.validate()` → replace |

## Dependencies

`psutil` is already in `requirements.txt` (used by card farming). No new dependencies needed.

The Steam API call uses `urllib.request` (stdlib) — same approach as `app/notify.py`.

## Error Handling within `validator.py`

- Local checks: pure logic, no exceptions expected
- `psutil.process_iter()`: wrapped in `try/except Exception` → treated as "Steam not running"
  if it raises (e.g. permissions error)
- API call HTTP responses (`GetPlayerSummaries` always returns 200 for well-formed requests;
  non-200 responses indicate infrastructure-level failures, not bad credentials):
  - `URLError` / `OSError` (network unreachable) → `[CONFIG ERROR] Could not reach Steam API: <reason>`
  - HTTP 200 with empty `players` list → `[CONFIG ERROR] Steam API key is invalid or Steam ID not found`
  - HTTP 429 → `[CONFIG ERROR] Steam API rate limited (HTTP 429) — try again in a moment`
  - Any other non-200 status → `[CONFIG ERROR] Steam API returned unexpected status: HTTP <code>`

## Files Changed

| File | Change |
| --- | --- |
| `app/validator.py` | New module |
| `app/config.py` | Remove `Config.validate()` method |
| `scripts/achievements/unlock.py` | Replace `cfg.validate()` with `validator.validate(cfg)` |
| `scripts/achievements/scan.py` | Add `validator.validate(cfg)` call |
| `scripts/cards/farm.py` | Replace `cfg.validate()` with `validator.validate(cfg)` |
| `scripts/cards/detect_drops.py` | Replace `cfg.validate()` with `validator.validate(cfg)` |
| `scripts/playtime/boost.py` | Replace `cfg.validate()` with `validator.validate(cfg)` |
| `tests/test_validator.py` | New test file — unit tests for each private check function, `sys.exit` patched via `unittest.mock.patch` |

## Preconditions for Implementation

- `Config.sam_game_exe_path` defaults to `""` in `app/config.py`. Verify this before implementing
  check 5 — if the default changes, the check logic must be updated accordingly.
