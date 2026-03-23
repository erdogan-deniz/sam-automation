# Design: Telegram Notifications

**Date:** 2026-03-23
**Status:** Approved

## Problem

Scripts like `cards/farm.py`, `playtime/boost.py`, and `achievements/unlock.py` run for hours in the background. The user has no way to know when they finish or crash without keeping a terminal window open.

## Solution

Add an optional `app/notify.py` module that sends Telegram messages at key events. Notifications are opt-in: if `telegram_bot_token` / `telegram_chat_id` are empty in `config.yaml`, the module silently does nothing.

## Scope

- **Platform:** Telegram only (Bot API)
- **Events:** script completion + unhandled errors / emergency stop
- **Scripts:** `scripts/cards/farm.py`, `scripts/playtime/boost.py`, `scripts/achievements/unlock.py`

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

```python
telegram_bot_token: str = ""
telegram_chat_id: str = ""
```

Loaded in `load_config()` via `raw.get(...)`.

### `config.example.yaml` addition

```yaml
# ── Telegram уведомления (опционально) ───────────────────────────────────────
# Токен бота от @BotFather, chat_id от @userinfobot
# telegram_bot_token: ""
# telegram_chat_id: ""
```

## Notification Points

Each script gets exactly 2 additions — both in already-existing `try/finally` or `except` blocks:

| Script | Event | Message |
|--------|-------|---------|
| `cards/farm.py` | Completion (after `_farm_loop`) | `✅ Card farming завершён: N игр` |
| `cards/farm.py` | Unhandled exception in `main()` | `❌ Card farming упал: {type}: {msg}` |
| `playtime/boost.py` | Completion (after `_boost_loop`) | `✅ Playtime boost завершён: N / M игр` |
| `playtime/boost.py` | Unhandled exception in `main()` | `❌ Playtime boost упал: {type}: {msg}` |
| `achievements/unlock.py` | Completion | `✅ Achievements unlock завершён: N игр` |
| `achievements/unlock.py` | Unhandled exception in `main()` | `❌ Achievements unlock упал: {type}: {msg}` |

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
|------|--------|
| `app/notify.py` | New module |
| `app/config.py` | 2 new fields + loading |
| `config.example.yaml` | New commented section |
| `scripts/cards/farm.py` | 2 `send_telegram` calls |
| `scripts/playtime/boost.py` | 2 `send_telegram` calls |
| `scripts/achievements/unlock.py` | 2 `send_telegram` calls |
