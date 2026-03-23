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

Internally structured as two phases:

**Phase 1 — Local checks** (filesystem only, no network):
1. `steam_api_key` is non-empty
2. `steam_id` is non-empty
3. `game_ids_file` — if set, the file must exist on disk
4. `steam_path` — if set, the directory must exist on disk
5. `sam_game_exe_path` — if set to a non-default value, the file must exist on disk

**Phase 2 — External checks** (process + network, only runs if Phase 1 passes):
6. `steam.exe` process is running — checked via `psutil.process_iter()`
7. Steam API key is valid and Steam ID resolves — single call to
   `ISteamUser/GetPlayerSummaries/v0002/` with both values; a 200 response with a non-empty
   `players` list confirms both

If Phase 1 has any errors, Phase 2 is skipped entirely — no point hitting the network with a
broken config.

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
- API call: `urllib.error.URLError` / `OSError` caught → treated as a network error, reported
  as `[CONFIG ERROR] Could not reach Steam API: <reason>`

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
