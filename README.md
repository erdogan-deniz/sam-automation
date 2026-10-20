# SAM Automation

Automatically unlock all Steam achievements, farm trading card drops, and boost playtime across your entire game library.

![Python](https://img.shields.io/badge/python-3.12-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## How it works

SAM Automation drives [Steam Achievement Manager (SAM)](https://github.com/gibbed/SteamAchievementManager)
via [pywinauto](https://github.com/pywinauto/pywinauto) UI automation.
It iterates through your game library, opens each game in SAM, clicks **Unlock All**,
then **Commit Changes**, and moves to the next.

Progress is saved after every game — if interrupted, re-running resumes from where it left off.

## Requirements

- Windows 10 / 11
- Python 3.12
- Steam (must be running and logged in)
- `SAM.Game.exe` — downloaded automatically from GitHub on first run

## Installation

```bash
git clone https://github.com/erdogan-deniz/sam-automation.git
cd sam-automation
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Edit `config.yaml` and fill in the required fields:

```yaml
steam_api_key: "YOUR_API_KEY"
steam_id:      "YOUR_STEAM_ID"
```

## Usage

Flag names are case-insensitive in every script: `--RESET` is `--reset`.

### Achievements (CLI)

```bash
# 1. Scan your Steam library → writes data/games/ids/all.txt
python scripts/scan_library.py

# 2. Unlock (resumes automatically if previously interrupted)
python scripts/achievements/farm_achievements.py

#    --retry-errors    retry games that errored out (clears error.txt)
#    --reset           wipe all progress and start over
#    --retry-without   re-check ONLY games SAM marked "no achievements" (without.txt)
#    --retry-done      re-run ONLY already-unlocked games (unlocked.txt),
#                      e.g. after new achievements were added to them
```

### Card farming (CLI)

```bash
# Start farming (idles games until all remaining card drops are collected)
python scripts/cards/farm_cards.py
```

### Playtime boosting (CLI)

```bash
# Show the games that would be boosted, then exit
python scripts/playtime/boost_playtime.py --list

# Boost every game in all.txt via short SAM sessions (resumable)
python scripts/playtime/boost_playtime.py

#    --reset         re-boost everything (clears playtime/done.txt)
#    --retry-skips   retry games that previously failed to connect (clears skip.txt)
```

### Growing the library (CLI)

All three scripts are **dry-run by default** — they only report what they
found. The account is modified only when you pass `--add`. All are resumable:
state lives in `data/games/ids/` and a re-run picks up where it stopped.

```bash
# Add every free Steam game/app to your library (CM request_free_license)
python scripts/library/add_free_games.py            # dry-run: how many candidates
python scripts/library/add_free_games.py --add      # actually add

#    --list          show current candidates and exit
#    --reset         wipe resume state
#    --retry-errors  retry transient failures (clears error.txt)
#    --limit N       cap how many are added per run

# Add every demo to your library (same CM mechanism, separate from add_free_games.py)
python scripts/library/add_demos.py           # dry-run: how many candidates
python scripts/library/add_demos.py --add     # actually add

#    --list          show current candidates and exit
#    --reset         wipe resume state
#    --retry-errors  retry transient failures (clears error.txt)
#    --limit N       cap how many are added per run

# Add paid, released Steam content to your wishlist (IWishlistService/AddToWishlist);
# free content is skipped (add_free_games.py puts it in the library), unreleased too
python scripts/library/fill_wishlist.py         # dry-run: how many candidates
python scripts/library/fill_wishlist.py --add   # actually add

#    --games --dlc --software --videos --hardware
#                    only these types, flags combine (default: all);
#                    no demos (demos go to the library via add_demos.py)
#    --list          show current candidates and exit
#    --reset         wipe resume state
#    --retry-errors  retry transient failures (clears error.txt)
#    --limit N       cap how many are added per run
#    --interval SEC  pause between adds (default 1.0; 0 = full speed)

# Remove free and unreleased items from the wishlist (IWishlistService/RemoveFromWishlist)
python scripts/library/clean_wishlist.py           # dry-run: how many to remove
python scripts/library/clean_wishlist.py --remove  # actually remove

#    --free --unreleased  only this reason, flags combine (default: both)
#    --list               show current removal candidates and exit
#    --limit N            cap how many are removed per run
#    --interval SEC       pause between removals (default 1.0)

# Sell the Steam inventory or grind it into gems, whichever pays more (market/sellitem,
# ajaxgrindintogoo). Never touches booster packs or cards of unfinished badges.
python scripts/library/sell_inventory.py          # dry-run: plan and totals
python scripts/library/sell_inventory.py --list   # one line per item
python scripts/library/sell_inventory.py --sell   # list the lots (confirm them in Steam Guard)
python scripts/library/sell_inventory.py --grind  # grind into gems (irreversible)

#    --limit N       cap how many operations run (sells and grinds together)
#    --interval SEC  pause between operations (default 3.0)
#    --reset         forget what was done (e.g. after cancelling lots)
```

All three stop honestly rather than pretending to finish: `add_free_games.py` and
`add_demos.py` stop when the account hits its free-license ceiling, and
`fill_wishlist.py` backs off on Steam's rate limit and stops after five
consecutive throttles. None report success when they stopped early.

### Checking the records against Steam (CLI)

The library scripts record what they added in `added.txt`. `verify_state.py`
checks those records against the account itself: every App ID in the free-games
and demos `added.txt` must be owned, every one in the wishlist `added.txt` must
be on the wishlist. A mismatch usually means a run was killed before Steam's
answer was saved. Read-only: it changes nothing in Steam or in `data/`, and needs
neither SAM nor the run lock.

```bash
python scripts/verify/verify_state.py

# exit 0  everything matches
# exit 1  mismatches found — listed in the log
# exit 2  no mismatches, but some checks could not run (Steam API error) — retry later
```

## Configuration (`config.yaml`)

| Parameter | Default | Description |
| --- | --- | --- |
| `steam_api_key` | *(required)* | Steam Web API key |
| `steam_id` | *(required)* | Steam ID, vanity name, or full profile URL |
| `sam_game_exe_path` | `./external/SAM/SAM.Game.exe` | Path to SAM.Game.exe; downloaded automatically if missing |
| `steam_path` | *(auto)* | Steam installation directory; auto-detected from the registry if omitted |
| `exclude_ids` | — | List of App IDs to skip (DLC, tools, demos) |
| `game_ids_file` | — | Path to a text file with App IDs (one per line); merged (union) on top of `game_ids`, and suppresses the `scan_library.py` list (`all.txt`) |
| `game_ids` | — | Explicit list of App IDs; suppresses the `scan_library.py` list (`all.txt`), but is merged (union, deduped) with `game_ids_file` rather than overriding it |
| `launch_delay` | `3` | Seconds to wait after launching SAM.Picker.exe |
| `load_timeout` | `20` | Max seconds to wait for a game's stats to load in SAM |
| `post_commit_delay` | `0.2` | Pause after Commit Changes (seconds) |
| `between_games_delay` | `0.1` | Pause between games (seconds) |
| `max_consecutive_errors` | `100` | Consecutive error threshold before emergency stop |
| `max_concurrent_games` | `1` | How many games to idle simultaneously (card farming) |
| `card_check_interval` | `10` | Minutes between card drop checks (card farming) |
| `playtime_idle_duration` | `120` | Seconds to idle each game (playtime boost) |
| `playtime_target_minutes` | `3` | Minimum playtime per game; games below this are boosted |
| `playtime_concurrent_games` | `10` | How many games to idle in parallel (playtime boost) |
| `launch_stagger` | `3` | Seconds between staggered game launches within a batch (playtime boost) |
| `telegram_bot_token` | — | Telegram Bot API token; enables remote completion/error notifications (optional) |
| `telegram_chat_id` | — | Telegram chat ID to send notifications to (optional) |

## Getting a Steam API Key and Steam ID

### Steam API Key

1. Go to <https://steamcommunity.com/dev/apikey>
2. Log in and register a key (any domain works, e.g. `localhost`)

### Steam ID

Your Steam ID is the 17-digit number in your profile URL, a vanity name, or the full URL.
All three formats are accepted:

```text
76561198000000000
gabelogannewell
https://steamcommunity.com/id/gabelogannewell
```

Find your Steam ID at <https://www.steamidfinder.com> or in Steam → your username → View Profile.

## Project structure

```text
sam-automation/
├── app/                    # Core library
│   ├── auth/               # Steam authentication (TOTP, JWT, keyring)
│   ├── cards/              # Card drop tracking and farming logic
│   ├── cookies/            # Steam web cookie extraction
│   ├── demos/              # Demo discovery and granting (CM, mirrors free_games/)
│   ├── free_games/         # Free-license discovery and granting (CM)
│   ├── sam/                # SAM process automation (launcher, UI)
│   ├── steam/              # Steam data access (API, CM, local files)
│   ├── wishlist/           # Catalog discovery and wishlist adding (Web API)
│   ├── cache.py            # State file helpers
│   ├── config.py           # config.yaml loader
│   ├── exceptions.py       # Custom exception hierarchy
│   ├── game_list.py        # App ID source merging
│   ├── id_file.py          # Text file ID list helpers
│   ├── logging_setup.py    # File + console logging
│   ├── notify.py           # Local toast + Telegram notifications
│   ├── run_lock.py         # Single-instance run lock (data/.sam_run.lock)
│   ├── safety.py           # Consecutive-error tracker
│   ├── unlock_result.py    # Achievement unlock result type
│   └── validator.py        # Pre-run config/param validation
├── scripts/
│   ├── scan_library.py           # Collect App IDs (VDF + API + CM) → data/games/ids/all.txt
│   ├── achievements/
│   │   └── farm_achievements.py  # Main achievement unlock loop
│   ├── cards/
│   │   └── farm_cards.py         # Idle games to collect card drops
│   ├── library/
│   │   ├── add_free_games.py     # Add every free Steam game/app to the library
│   │   ├── add_demos.py          # Add every demo to the library
│   │   ├── fill_wishlist.py      # Add paid, released Steam content to the wishlist
│   │   ├── clean_wishlist.py     # Remove free and unreleased items from the wishlist
│   │   └── sell_inventory.py     # Sell the inventory on the market or grind it into gems
│   ├── playtime/
│   │   └── boost_playtime.py     # Boost low-playtime games via short SAM sessions
│   └── verify/
│       └── verify_state.py       # Check added.txt records against the Steam account
├── .github/
│   ├── workflows/ci.yml    # CI: version check, pre-commit, tests
│   └── scripts/
│       └── check_version.py  # Release version-invariant gate (run by CI only —
│                              # not a project script, lives outside scripts/)
├── data/                   # Runtime state (gitignored)
│   └── games/
│       ├── names.json      # AppID → game name cache
│       └── ids/
│           ├── all.txt             # Master list of App IDs (from scan_library.py)
│           ├── achievements/       # unlocked, error, without
│           ├── cards/              # done.txt
│           ├── demos/              # candidates, added, refused, error
│           ├── free/               # candidates, added, refused, error
│           ├── playtime/           # done.txt, skip.txt
│           ├── wishlist/           # candidates, added, refused, error
│           ├── wishlist_clean/     # candidates, removed
│           └── inventory_sale/     # listed, pending, ground, refused
├── logs/                   # Session logs (gitignored)
├── external/
│   └── SAM/                # SAM binaries (auto-downloaded on first run)
├── config.example.yaml
└── requirements.txt
```

## State files

All state is stored in `data/games/` (gitignored) as plain-text files — one App ID per line.
Delete or edit them manually if needed.

**Master list** (`data/games/ids/`)

| File | Purpose |
| --- | --- |
| `all.txt` | App IDs collected by `scripts/scan_library.py` (VDF + Steam API + Steam CM) |
| `../names.json` | AppID → game name lookup, populated alongside the scan |

**Achievements** (`data/games/ids/achievements/`)

| File | Purpose |
| --- | --- |
| `unlocked.txt` | Successfully processed games |
| `error.txt` | Games that errored out (retryable) |
| `without.txt` | Games **SAM** confirmed have no achievements (skipped permanently) |

**Cards** (`data/games/ids/cards/`)

| File | Purpose |
| --- | --- |
| `done.txt` | Games with no remaining card drops |

**Free games** (`data/games/ids/free/`), **Demos** (`data/games/ids/demos/`)
and **Wishlist** (`data/games/ids/wishlist/`) share the same four-file layout:

| File | Purpose |
| --- | --- |
| `candidates.txt` | Discovered App IDs still to process (minus owned/already-added) |
| `added.txt` | Successfully added |
| `refused.txt` | Steam refused permanently (delisted, already owned, not free) — never retried |
| `error.txt` | Transient failures; cleared and retried with `--retry-errors` |

The wishlist keeps candidates of each type selection apart, e.g.
`candidates_games.txt` for `--games` or `candidates_games_software.txt`.

**Wishlist cleanup** (`data/games/ids/wishlist_clean/`) keeps `candidates.txt`
(what to remove, rewritten every run) and `removed.txt`. A removed App ID is
also dropped from the wishlist `added.txt`, so an unreleased game comes back as
a candidate once it is out.

**Inventory sale** (`data/games/ids/inventory_sale/`) keys files by asset id:
`listed.txt` (lot placed), `pending.txt` (lot placed, waiting for your
confirmation in Steam Guard — not sold yet), `ground.txt` (turned into gems) and
`refused.txt` (Steam said no, never retried). Errors are not recorded; the item
is tried again on the next run. Each item is listed at the lowest asking
price on the market (at the best buy order if nobody sells it) unless its gems
are worth more; the lot stays up until someone buys it. Steam allows at most 250 lots waiting for
confirmation: the run stops at that ceiling, you confirm the batch in Steam
Guard, then run `--sell` again.

**Playtime boosting** drives off `all.txt` (the whole library). Games the Steam
API reports playtime for are gated on the **actual** `playtime_forever`: those at
or above `playtime_target_minutes` are skipped, and ones still below are re-boosted
each run until they truly reach the target (they are *not* marked done on a single
pass). Games the API has no playtime for (free/demo/license apps) can't be verified,
so they are idled once and recorded in `playtime/done.txt` to resume. **Unknown**
games that fail to connect go to `playtime/skip.txt`; a **known** game that fails
is *not* buried in skip (a one-off connect glitch shouldn't lose it — the Steam
API stays its source of truth and re-checks it next run). A **blind run** (the
Steam API returned no owned games at all) persists neither `done.txt` nor
`skip.txt`: nothing can be verified, so nothing is buried. Use `--reset` to clear
`done.txt`, or `--retry-skips` to clear `skip.txt` and retry skipped games.

Session logs are written to `logs/` with timestamps (`YYYY-MM-DD_HH-MM-SS.log`).
Each script keeps its last 5 log files; older ones are deleted on start. A log
that grows past 20 MB continues in `YYYY-MM-DD_HH-MM-SS_part02.log` and so on,
and those parts count toward the five.

## Password storage

Steam credentials (if used for the CM login path) are stored securely in the
**Windows Credential Manager** via [keyring](https://github.com/jaraco/keyring) —
never in plain text on disk.

## Limitations

- Windows only (pywinauto requires Win32 API)
- Only processes games that have Steam achievements
- Steam must be running and logged in

## Disclaimer

> **For educational purposes only.**
> Using this tool may violate [Steam's Terms of Service](https://store.steampowered.com/subscriber_agreement/).
> Use at your own risk.

## License

MIT
