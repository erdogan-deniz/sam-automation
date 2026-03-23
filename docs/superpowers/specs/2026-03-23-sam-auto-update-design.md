# Design: SAM Auto-Update

**Date:** 2026-03-23
**Status:** Approved

## Problem

`ensure_sam()` only downloads SAM when the exe is absent. If SAM is already installed,
the version is never checked, and the user may run an outdated binary indefinitely without
knowing a newer release is available.

## Solution

Store the installed version tag in a `.sam_version` file next to the exe. On each
`ensure_sam()` call, compare it against the latest GitHub release tag. If they differ,
prompt the user interactively (`y/n`) and update if requested.

## Scope

- Single file change: `app/sam/sam_downloader.py`
- No new dependencies (uses `urllib.request`, already imported)
- No new scripts or config fields

## Design

### Version file

Path: `<sam_dir>/.sam_version` — a plain text file containing the `tag_name` string
from the GitHub release (e.g. `r68`), written immediately after a successful `download_sam()`.

The file lives next to `SAM.Game.exe` so it is automatically co-located with the binary
it describes. If the file is absent (pre-existing installation, manual extraction), the
version is treated as unknown.

### New helper functions

**`_save_version(sam_dir: Path, tag_name: str) -> None`**

Writes `tag_name` to `sam_dir / ".sam_version"`. Called at the end of `download_sam()`
after `SAM.Game.exe` is located.

**`_read_installed_version(sam_dir: Path) -> str | None`**

Reads and returns the stripped contents of `.sam_version`, or `None` if the file does
not exist or cannot be read.

**`_fetch_latest_release() -> dict`**

Extracted from the existing inline code in `download_sam()`. Makes the GitHub API request
and returns the parsed release dict `{"tag_name": ..., "assets": [...]}`. Raises on
network error so callers can catch and handle gracefully.

### `check_for_update(exe_path: str) -> bool`

```
1. installed = _read_installed_version(exe_dir)      # str | None
2. release   = _fetch_latest_release()               # may raise
3. latest    = release["tag_name"]
4. if installed == latest:
       log.debug("SAM %s — последняя версия", latest)
       return False
5. if installed is None:
       log.info("Версия SAM неизвестна. Последняя: %s", latest)
   else:
       log.info("Доступна новая версия SAM: %s (текущая: %s)", latest, installed)
6. answer = input("Обновить SAM? [y/n]: ").strip().lower()
7. if answer == "y":
       download_sam(str(exe_dir))   # _save_version() is called inside
       return True
8. return False
```

Network errors in step 2 are caught by the caller (`ensure_sam`) and logged as `WARNING`.

### Modified `ensure_sam(exe_path: str) -> str`

```python
def ensure_sam(exe_path: str) -> str:
    if not Path(exe_path).exists():
        # existing behaviour: download from scratch
        sam_dir = Path(exe_path).parent
        return download_sam(str(sam_dir))

    # new: check for updates when exe already exists
    try:
        check_for_update(exe_path)
    except Exception as e:
        log.warning("Не удалось проверить обновления SAM: %s", e)

    return exe_path
```

The `try/except` around `check_for_update` ensures that any network failure, GitHub
API error, or unexpected exception is downgraded to a warning and never prevents the
main script from running.

### Modified `download_sam(target_dir: str) -> str`

After locating `SAM.Game.exe` in the extracted archive, add one call before returning:

```python
_save_version(target, release["tag_name"])
```

`release` is already in scope from the GitHub API response parsed at the top of the function.

## Edge Cases

| Situation | Behaviour |
| --------- | --------- |
| `.sam_version` missing (pre-existing install) | Logs "version unknown, latest: X", asks y/n |
| GitHub API unreachable or rate-limited | `log.warning`, script continues unchanged |
| User answers anything other than `y` | Current version kept, script continues |
| `download_sam` fails mid-update | Exception propagates; `.sam_version` is not written (write happens only after successful extraction) |

## Files Changed

| File | Change |
| ---- | ------ |
| `app/sam/sam_downloader.py` | Extract `_fetch_latest_release()`, add `_save_version()`, `_read_installed_version()`, `check_for_update()`; modify `download_sam()` and `ensure_sam()` |
