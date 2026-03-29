# SAM Automation

Automatically unlock all Steam achievements and farm trading card drops across your entire game library.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
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
- Python 3.10+
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
# 1. Scan your Steam library → writes data/achievements/ids.txt
python scripts/achievements/scan.py

# 2. Run (resumes automatically if previously interrupted)
python scripts/achievements/farm.py
```

### Card farming (CLI)

```bash
# Show games with remaining card drops
python scripts/cards/scan.py

# Start farming (idles games until all drops are collected)
python scripts/cards/farm.py
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
| `load_timeout` | `10` | Max seconds to wait for a game to load in SAM |
| `post_commit_delay` | `0.2` | Pause after Commit Changes (seconds) |
| `between_games_delay` | `0.1` | Pause between games (seconds) |
| `max_consecutive_errors` | `100` | Consecutive error threshold before emergency stop |
| `max_concurrent_games` | `1` | How many games to idle simultaneously (card farming) |
| `card_check_interval` | `10` | Minutes between card drop checks (card farming) |

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
│   ├── config.py           # config.yaml loader
│   ├── exceptions.py       # Custom exception hierarchy
│   ├── game_list.py        # App ID source merging
│   ├── id_file.py          # Text file ID list helpers
│   ├── logging_setup.py    # File + console logging
│   ├── safety.py           # Consecutive-error tracker
│   └── unlock_result.py    # Achievement unlock result type
├── gui/                    # GUI (CustomTkinter)
│   ├── app.py              # Main window
│   ├── runner.py           # Script subprocess runner
│   └── tabs/               # Tab components (achievements, cards, settings)
├── scripts/
│   ├── achievements/
│   │   ├── scan.py         # Collect App IDs → data/achievements/ids.txt
│   │   └── farm.py         # Main achievement unlock loop
│   └── cards/
│       ├── scan.py         # Detect games with remaining card drops
│       └── farm.py         # Idle games to collect card drops
├── data/                   # Runtime state (gitignored)
│   ├── achievements/       # ids.txt, done_ids.txt, error_ids.txt, no_achievements_ids.txt
│   └── cards/              # has_cards_ids.txt, no_cards_ids.txt, card_done_ids.txt
├── logs/                   # Session logs (gitignored)
├── external/
│   └── SAM/                # SAM binaries (auto-downloaded on first run)
├── config.example.yaml
├── run.py                  # GUI entry point
└── requirements.txt
```

## State files

All state is stored in `data/` (gitignored) as plain-text files — one App ID per line.
Delete or edit them manually if needed.

**Achievements** (`data/achievements/`)

| File | Purpose |
| --- | --- |
| `ids.txt` | App IDs collected by `scripts/achievements/scan.py` |
| `done_ids.txt` | Successfully processed games |
| `error_ids.txt` | Games that errored out (retryable) |
| `no_achievements_ids.txt` | Games with no achievements (skipped permanently) |

**Cards** (`data/cards/`)

| File | Purpose |
| --- | --- |
| `has_cards_ids.txt` | Games confirmed to have trading cards |
| `no_cards_ids.txt` | Games confirmed to have no trading cards |
| `card_done_ids.txt` | Games with no remaining card drops |

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
