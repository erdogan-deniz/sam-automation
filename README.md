# SAM Automation

Automatically unlock all Steam achievements across your entire game library.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## How it works

SAM Automation drives [Steam Achievement Manager (SAM)](https://github.com/gibbed/SteamAchievementManager) via [pywinauto](https://github.com/pywinauto/pywinauto) UI automation. It iterates through your game library, opens each game in SAM, clicks **Unlock All**, then **Commit Changes**, and moves to the next. Progress is saved after every game — if interrupted, re-running resumes from where it left off.

## Requirements

- Windows 10 / 11
- Python 3.10+
- Steam (must be running)
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
steam_id: "YOUR_STEAM_ID"
```

## Usage

```bash
# 1. Scan your Steam library → writes data/all_ids.txt
python scan.py

# 2. Preview which games will be processed
python main.py --list

# 3. Run (resumes automatically if previously interrupted)
python main.py

# Reset progress and start over
python main.py --reset
```

## Configuration (`config.yaml`)

| Parameter | Default | Description |
|---|---|---|
| `steam_api_key` | *(required)* | Steam Web API key |
| `steam_id` | *(required)* | Steam ID, vanity name, or full profile URL |
| `sam_game_exe_path` | `./SAM/SAM.Game.exe` | Path to SAM.Game.exe; downloaded automatically if missing |
| `exclude_ids` | — | List of App IDs to skip (DLC, tools, demos) |
| `game_ids_file` | — | Path to a text file with App IDs (one per line) |
| `game_ids` | — | Explicit list of App IDs; overrides `scan.py` and `game_ids_file` |
| `launch_delay` | `3` | Seconds to wait after launching SAM.Picker.exe |
| `load_timeout` | `15` | Max seconds to wait for a game to load in SAM |
| `post_commit_delay` | `0.2` | Pause after Commit Changes (seconds) |
| `between_games_delay` | `0.1` | Pause between games (seconds) |
| `max_consecutive_errors` | `3` | Consecutive error threshold before emergency stop |

## Getting a Steam API Key and Steam ID

**Steam API Key**

1. Go to https://steamcommunity.com/dev/apikey
2. Log in and register a key (any domain works, e.g. `localhost`)

**Steam ID**

Your Steam ID is the 17-digit number in your profile URL, a vanity name, or the full URL. All three formats are accepted:

```
76561198000000000
gabelogannewell
https://steamcommunity.com/id/gabelogannewell
```

Find your Steam ID at https://www.steamidfinder.com or in Steam → your username → View Profile.

## State files

Stored in the `data/` folder (gitignored):

| File | Purpose |
|---|---|
| `data/all_ids.txt` | App IDs from your library (written by `scan.py`) |
| `data/done_ids.txt` | Successfully processed games |
| `data/error_ids.txt` | Games that errored out |
| `data/no_achievements_ids.txt` | Games with no achievements |

All state files are plain text — one App ID per line. Delete or edit them manually if needed.

## Limitations

- Windows only (pywinauto requires Win32 API)
- Only processes games that have Steam achievements
- Steam must be running and logged in

## Disclaimer

> **For educational purposes only.** Using this tool may violate [Steam's Terms of Service](https://store.steampowered.com/subscriber_agreement/). Use at your own risk.

## License

MIT
