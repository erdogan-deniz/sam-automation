# Design: SAM Auto-Update

**Date:** 2026-03-23
**Status:** Approved

## Problem

`ensure_sam()` only downloads SAM when the exe is absent. If SAM is already installed,
the version is never checked, and the user may run an outdated binary indefinitely.

## Solution

Store the installed version tag in a `.sam_version` file next to the exe. On each
`ensure_sam()` call, compare it against the latest GitHub release tag. If they differ,
prompt the user interactively (`y/n`) and update if requested.

## Scope

- Single source file change: `app/sam/sam_downloader.py`
- One `.gitignore` entry added: `**/.sam_version`
- No new runtime dependencies (`urllib.request` already imported)
- No new scripts or config fields

## Design

### Version file

Path: `<sam_dir>/.sam_version` — plain text containing the `tag_name` string from the
GitHub release (e.g. `r68`). Written after a successful `download_sam()` call, once
`SAM.Game.exe` has been located in the extracted archive (atomicity: if extraction fails
before locating the exe, the version file is never written).

If the file is absent (pre-existing manual installation), the version is treated as unknown.

### New helper functions

**`_save_version(sam_dir: Path, tag_name: str) -> None`**

Writes `tag_name` to `sam_dir / ".sam_version"`.

**`_read_installed_version(sam_dir: Path) -> str | None`**

Returns the stripped contents of `.sam_version`, or `None` if absent or unreadable.

**`_fetch_latest_release() -> dict`**

Extracted from the existing inline code in `download_sam()`. Makes the GitHub API request
and returns the parsed release dict `{"tag_name": ..., "assets": [...]}`. Raises on
network error.

### Modified `download_sam(target_dir: str, release: dict | None = None) -> str`

A `release` parameter is added so callers that have already fetched the release (i.e.
`check_for_update`) can pass it in, avoiding a second GitHub API request:

```python
def download_sam(target_dir: str, release: dict | None = None) -> str:
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    if release is None:
        release = _fetch_latest_release()
    # ... rest of existing logic unchanged ...
    # after locating SAM.Game.exe:
    _save_version(target, release["tag_name"])
    return exe_path
```

Existing callers that pass only `target_dir` continue to work unchanged — they trigger the
internal `_fetch_latest_release()` call as before.

### `check_for_update(exe_path: str) -> str | None`

Returns the updated exe path if an update was installed, `None` otherwise.

```text
1. exe_dir   = Path(exe_path).parent
2. installed = _read_installed_version(exe_dir)     # str | None
3. release   = _fetch_latest_release()              # may raise
4. latest    = release["tag_name"]
5. if installed == latest:
       log.debug("SAM %s — последняя версия", latest)
       return None
6. if installed is None:
       log.info("Версия SAM неизвестна. Последняя: %s", latest)
   else:
       log.info("Доступна новая версия SAM: %s (текущая: %s)", latest, installed)
7. try:
       answer = input("Обновить SAM? [y/n]: ").strip().lower()
   except EOFError:
       log.info("Не интерактивный режим — пропускаю обновление SAM")
       return None
8. if answer != "y":
       return None
9. return download_sam(str(exe_dir), release=release)   # pass fetched release → no double fetch
```

### Modified `ensure_sam(exe_path: str) -> str`

```python
def ensure_sam(exe_path: str) -> str:
    if not Path(exe_path).exists():
        log.warning("SAM.Game.exe не найден по пути: %s", exe_path)
        sam_dir = Path(exe_path).parent
        return download_sam(str(sam_dir))

    try:
        updated_path = check_for_update(exe_path)
        if updated_path:
            return updated_path          # return new path after update
    except Exception as e:
        log.warning("Не удалось проверить обновления SAM: %s", e)

    return exe_path
```

## Edge Cases

| Situation | Behaviour |
| --------- | --------- |
| `.sam_version` missing (pre-existing install) | Logs "version unknown, latest: X", asks y/n |
| GitHub API unreachable or rate-limited | `log.warning`, script continues with current SAM |
| Non-interactive stdin (`EOFError` on `input()`) | `log.info` "non-interactive mode", treats as "n" |
| User answers anything other than `y` | Current version kept, script continues |
| `download_sam` fails mid-update | Exception propagates; `.sam_version` not written |
| Exe moves inside zip after update | `check_for_update` returns new path; `ensure_sam` returns it |

## Runtime Artifact

`.sam_version` is written at runtime next to the SAM exe. If `sam_game_exe_path` points
inside the project directory, it will appear as an untracked file. Add to `.gitignore`:

```gitignore
**/.sam_version
```

## Files Changed

| File | Change |
| ---- | ------ |
| `app/sam/sam_downloader.py` | Extract `_fetch_latest_release()`; add `_save_version()`, `_read_installed_version()`, `check_for_update()`; modify `download_sam()` (optional `release` param + `_save_version` call) and `ensure_sam()` |
| `.gitignore` | Add `**/.sam_version` |
