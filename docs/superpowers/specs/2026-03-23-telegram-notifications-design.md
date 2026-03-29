# Design: Telegram Notifications

**Date:** 2026-03-23
**Status:** Approved

## Problem

Scripts like `cards/farm.py`, `playtime/boost.py`, and `achievements/farm.py` run for hours in the background. The user has no way to know when they finish or crash without keeping a terminal window open.

## Solution

Add an optional `app/notify.py` module that sends Telegram messages at key events. Notifications are opt-in: if `telegram_bot_token` / `telegram_chat_id` are empty in `config.yaml`, the module silently does nothing.

## Scope

- **Platform:** Telegram only (Bot API)
- **Events:** script completion + unhandled errors / emergency stop
- **Scripts:** `scripts/cards/farm.py`, `scripts/playtime/boost.py`, `scripts/achievements/farm.py`

## Architecture

### `app/notify.py`

Single public function:

```python
def send_telegram(text: str, cfg: Config) -> None
```

- Uses `urllib.request` (stdlib) — no new dependencies
- POST to `https://api.telegram.org/bot{token}/sendMessage` with `chat_id` and `text`
- If `telegram_bot_token` or `telegram_chat_id` is falsy → return immediately (silent no-op)
- Network/HTTP errors → `log.warning(...)` only, never `raise` — the calling script must not crash due to a notification failure

### Config additions (`app/config.py`)

Two new string fields with empty-string defaults — follow the existing `raw.get()` pattern used
for `steam_api_key`, `steam_id`, and `steam_path`:

```python
telegram_bot_token: str = ""
telegram_chat_id: str = ""
```

In `load_config()`, loaded as:

```python
cfg.telegram_bot_token = raw.get("telegram_bot_token", "")
cfg.telegram_chat_id = str(raw.get("telegram_chat_id", ""))
```

(`str()` cast handles the case where `chat_id` is written as a bare integer in YAML.)

### `config.example.yaml` addition

```yaml
# ── Telegram уведомления (опционально) ───────────────────────────────────────
# Токен бота от @BotFather, chat_id от @userinfobot
# telegram_bot_token: ""
# telegram_chat_id: ""
```

## Notification Points

### `scripts/cards/farm.py`

`main()` currently calls `_farm_loop(...)` with no surrounding `try/except`. A new wrapper is
added around that call:

```python
try:
    _farm_loop(games_with_drops, cfg, cookies, steam_id)
    notify.send_telegram(
        f"✅ Card farming завершён: {len(games_with_drops)} игр в очереди",
        cfg,
    )
except Exception as e:
    notify.send_telegram(f"❌ Card farming упал: {type(e).__name__}: {e}", cfg)
    raise
```

`KeyboardInterrupt` is caught **inside** `_farm_loop` and does not propagate to `main()`, so it
is handled silently (no notification on Ctrl+C — this is intentional).

### `scripts/playtime/boost.py`

Same pattern — `_boost_loop(games, cfg)` in `main()` has no surrounding `try/except`:

```python
try:
    _boost_loop(games, cfg)
    notify.send_telegram(
        f"✅ Playtime boost завершён: {len(games)} игр в очереди",
        cfg,
    )
except Exception as e:
    notify.send_telegram(f"❌ Playtime boost упал: {type(e).__name__}: {e}", cfg)
    raise
```

`KeyboardInterrupt` is caught inside `_boost_loop`; same reasoning applies.

### `scripts/achievements/farm.py`

`main()` already has a `try/except SAMTooManyErrors / except KeyboardInterrupt / finally` block
(lines 207–222). A `completed_cleanly` flag gates the completion notification so it fires only
on a clean run — not after `SAMTooManyErrors` or `KeyboardInterrupt`:

```python
completed_cleanly = False
try:
    for i, game_id in enumerate(game_ids, 1):
        ...
    completed_cleanly = True   # reached only if no exception was raised
except SAMTooManyErrors:
    log.error("Прервано. Перезапусти скрипт — продолжит с места остановки.")
    notify.send_telegram(
        f"❌ Achievements unlock: слишком много ошибок подряд, остановлено ({errors} ошибок)",
        cfg,
    )
except KeyboardInterrupt:
    log.info("Прервано (Ctrl+C). Перезапусти — продолжит с места остановки.")
finally:
    kill_process(proc)

_log_summary(results, errors)
if completed_cleanly:
    ok_count = len([r for r in results if not r.skipped])
    notify.send_telegram(
        f"✅ Achievements unlock завершён: {ok_count} unlocked, {errors} errors"
        f" ({len(results)} of {total} processed)",
        cfg,
    )
```

Two notification points total:

1. **Error** — inside `except SAMTooManyErrors:` (fires only on emergency stop).
2. **Completion** — after `_log_summary`, gated by `completed_cleanly` (fires only on clean finish).

`Ctrl+C` produces no notification — consistent with the behavior of `farm.py` and `boost.py`.

## Error Handling

- `send_telegram` catches all exceptions internally (`urllib.error.URLError`, `OSError`, etc.)
- Logs a `WARNING` with the reason — the main script is unaffected
- No retry logic (notifications are best-effort)

## Setup (user-facing)

1. Create a bot via [@BotFather](https://t.me/BotFather) → get token
2. Get your chat ID via [@userinfobot](https://t.me/userinfobot)
3. Add both to `config.yaml`

## Files Changed

| File | Change |
| ---- | ------ |
| `app/notify.py` | New module |
| `app/config.py` | 2 new fields + loading via `raw.get()` |
| `config.example.yaml` | New commented section |
| `scripts/cards/farm.py` | `try/except` wrapper around `_farm_loop(...)` call in `main()` |
| `scripts/playtime/boost.py` | `try/except` wrapper around `_boost_loop(...)` call in `main()` |
| `scripts/achievements/farm.py` | 1 call in `except SAMTooManyErrors`, 1 call after `_log_summary` |
