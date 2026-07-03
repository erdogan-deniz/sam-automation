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

### GUI

```bash
python run.py
```

### Achievements (CLI)

```bash
# 1. Scan your Steam library → writes data/games/ids/all.txt
python scripts/scan.py

# 2. Unlock (resumes automatically if previously interrupted)
python scripts/achievements/farm.py

#    --retry-errors  retry games that errored out (clears error.txt)
#    --reset         wipe all progress and start over
#    --no-resume     process every game this run, ignoring saved progress
```

### Library stats (CLI)

```bash
# Summary of the achievements library:
# total / with achievements / without / unlocked / errors / remaining + progress %
python scripts/stats.py
```

### Achievements catalog (advisory, CLI)

```bash
# Classify the library via the Steam Store API into with.txt / store_zero.txt / store_empty.txt.
# Cached and resumable — re-run to continue. Store API is ~1.2s per game.
python scripts/categorize.py

#    --limit N   cap Store requests this run (the full library takes hours)
#    --reset     wipe the catalog and start over
```

> The catalog is **advisory only** — it never causes a game to be skipped.
> Only SAM can terminally mark a game as having no achievements (`without.txt`).
> The Store API is unreliable (demos, region-locked, or delisted apps report an
> empty achievements block even when achievements exist), so its "0 achievements"
> verdict goes to a separate `store_zero.txt` that farming ignores.

### Card farming (CLI)

```bash
# Show games with remaining card drops
python scripts/cards/scan.py

# Start farming (idles games until all drops are collected)
python scripts/cards/farm.py
```

### Playtime boosting (CLI)

```bash
# Show the games that would be boosted, then exit
python scripts/playtime/boost.py --list

# Boost every game in all.txt via short SAM sessions (resumable)
python scripts/playtime/boost.py

#    --reset   re-boost everything (clears playtime/done.txt)
```

## Configuration (`config.yaml`)

| Parameter | Default | Description |
| --- | --- | --- |
| `steam_api_key` | *(required)* | Steam Web API key |
| `steam_id` | *(required)* | Steam ID, vanity name, or full profile URL |
| `sam_game_exe_path` | `./external/SAM/SAM.Game.exe` | Path to SAM.Game.exe; downloaded automatically if missing |
| `steam_path` | *(auto)* | Steam installation directory; auto-detected from the registry if omitted |
| `exclude_ids` | — | List of App IDs to skip (DLC, tools, demos) |
| `game_ids_file` | — | Path to a text file with App IDs (one per line) |
| `game_ids` | — | Explicit list of App IDs; overrides `scan.py` and `game_ids_file` |
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
│   ├── sam/                # SAM process automation (launcher, UI)
│   ├── steam/              # Steam data access (API, CM, local files)
│   ├── cache.py            # State file helpers
│   ├── catalog.py          # Advisory achievements catalog (Store API)
│   ├── config.py           # config.yaml loader
│   ├── exceptions.py       # Custom exception hierarchy
│   ├── game_list.py        # App ID source merging
│   ├── id_file.py          # Text file ID list helpers
│   ├── logging_setup.py    # File + console logging
│   ├── safety.py           # Consecutive-error tracker
│   ├── stats.py            # Library stats summary
│   └── unlock_result.py    # Achievement unlock result type
├── gui/                    # GUI (CustomTkinter)
│   ├── app.py              # Main window
│   ├── runner.py           # Script subprocess runner
│   └── tabs/               # Tab components (achievements, cards, playtime, settings)
├── scripts/
│   ├── scan.py             # Collect App IDs (VDF + API + CM) → data/games/ids/all.txt
│   ├── stats.py            # Library stats summary
│   ├── categorize.py       # Advisory achievements catalog (Store API)
│   ├── achievements/
│   │   └── farm.py         # Main achievement unlock loop
│   ├── cards/
│   │   ├── scan.py         # Detect games with remaining card drops
│   │   └── farm.py         # Idle games to collect card drops
│   └── playtime/
│       └── boost.py        # Boost low-playtime games via short SAM sessions
├── data/                   # Runtime state (gitignored)
│   └── games/
│       ├── names.json      # AppID → game name cache
│       └── ids/
│           ├── all.txt             # Master list of App IDs (from scan.py)
│           ├── achievements/       # unlocked, error, without + catalog (with, store_zero, store_empty)
│           ├── cards/              # done.txt
│           └── playtime/           # done.txt, skip.txt
├── logs/                   # Session logs (gitignored)
├── external/
│   └── SAM/                # SAM binaries (auto-downloaded on first run)
├── config.example.yaml
├── run.py                  # GUI entry point
└── requirements.txt
```

## State files

All state is stored in `data/games/` (gitignored) as plain-text files — one App ID per line.
Delete or edit them manually if needed.

**Master list** (`data/games/ids/`)

| File | Purpose |
| --- | --- |
| `all.txt` | App IDs collected by `scripts/scan.py` (VDF + Steam API + Steam CM) |
| `../names.json` | AppID → game name lookup, populated alongside the scan |

**Achievements** (`data/games/ids/achievements/`)

| File | Purpose |
| --- | --- |
| `unlocked.txt` | Successfully processed games |
| `error.txt` | Games that errored out (retryable) |
| `without.txt` | Games **SAM** confirmed have no achievements (skipped permanently) |
| `with.txt` | Catalog: Store-confirmed to have achievements (advisory priority) |
| `store_zero.txt` | Catalog: Store reported 0 achievements — advisory, farming does **not** skip these |
| `store_empty.txt` | Catalog: Store responded but returned no achievements block — advisory |

**Cards** (`data/games/ids/cards/`)

| File | Purpose |
| --- | --- |
| `done.txt` | Games with no remaining card drops |

**Playtime boosting** drives off `all.txt` (the whole library). Games the Steam
API reports playtime for are gated on the **actual** `playtime_forever`: those at
or above `playtime_target_minutes` are skipped, and ones still below are re-boosted
each run until they truly reach the target (they are *not* marked done on a single
pass). Games the API has no playtime for (free/demo/license apps) can't be verified,
so they are idled once and recorded in `playtime/done.txt` to resume. Games that
fail to connect go to `playtime/skip.txt`. Use `--reset` to clear `done.txt`.

Session logs are written to `logs/` with timestamps (`YYYY-MM-DD_HH-MM-SS.log`).

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
