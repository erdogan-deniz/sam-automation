"""Тесты для app/sam/sam_downloader.py."""

from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.sam.sam_downloader import (
    _fetch_latest_release,
    _read_installed_version,
    _save_version,
    check_for_update,
    download_sam,
    ensure_sam,
)


# ── Shared test helpers ───────────────────────────────────────────────────────


def _make_release(tag: str = "r68") -> dict:
    """Строит минимальный словарь релиза GitHub API с одним ZIP-ассетом."""
    return {
        "tag_name": tag,
        "assets": [{"name": "SAM.zip", "browser_download_url": "http://example.com/SAM.zip"}],
    }


def _make_zip_bytes() -> bytes:
    """Создаёт in-memory ZIP с SAM.Game.exe внутри."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SAM.Game.exe", b"fake exe")
    return buf.getvalue()


def _make_url_mock(data: bytes) -> MagicMock:
    """Возвращает context-manager mock для urllib.request.urlopen."""
    mock = MagicMock()
    mock.read.return_value = data
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _setup_sam_dir(tmp_path: Path, installed_tag: str | None) -> Path:
    """Создаёт фейковую директорию с exe и опциональным .sam_version."""
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    if installed_tag is not None:
        _save_version(tmp_path, installed_tag)
    return exe


# ── _save_version ─────────────────────────────────────────────────────────────


def test_save_version_writes_tag(tmp_path: Path) -> None:
    _save_version(tmp_path, "r68")
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r68"


def test_save_version_overwrites(tmp_path: Path) -> None:
    _save_version(tmp_path, "r68")
    _save_version(tmp_path, "r69")
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r69"


# ── _read_installed_version ───────────────────────────────────────────────────


def test_read_installed_version_returns_tag(tmp_path: Path) -> None:
    (tmp_path / ".sam_version").write_text("r68\n", encoding="utf-8")
    assert _read_installed_version(tmp_path) == "r68"


def test_read_installed_version_missing_returns_none(tmp_path: Path) -> None:
    assert _read_installed_version(tmp_path) is None


def test_read_installed_version_strips_whitespace(tmp_path: Path) -> None:
    (tmp_path / ".sam_version").write_text("  r68  \n", encoding="utf-8")
    assert _read_installed_version(tmp_path) == "r68"


# ── _fetch_latest_release ─────────────────────────────────────────────────────


def test_fetch_latest_release_returns_dict() -> None:
    release = _make_release("r68")
    mock_resp = _make_url_mock(json.dumps(release).encode())
    with patch("app.sam.sam_downloader.urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_latest_release()
    assert result["tag_name"] == "r68"
    assert len(result["assets"]) == 1


def test_fetch_latest_release_raises_on_network_error() -> None:
    with patch("app.sam.sam_downloader.urllib.request.urlopen",
               side_effect=urllib.error.URLError("timeout")):
        with pytest.raises(urllib.error.URLError):
            _fetch_latest_release()


# ── download_sam ──────────────────────────────────────────────────────────────


def test_download_sam_saves_version(tmp_path: Path) -> None:
    release = _make_release("r68")
    with patch("app.sam.sam_downloader._fetch_latest_release", return_value=release), \
         patch("app.sam.sam_downloader.urllib.request.urlopen",
               return_value=_make_url_mock(_make_zip_bytes())):
        download_sam(str(tmp_path))
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r68"


def test_download_sam_uses_provided_release(tmp_path: Path) -> None:
    """Если release передан — _fetch_latest_release не вызывается."""
    release = _make_release("r69")
    with patch("app.sam.sam_downloader._fetch_latest_release") as mock_fetch, \
         patch("app.sam.sam_downloader.urllib.request.urlopen",
               return_value=_make_url_mock(_make_zip_bytes())):
        download_sam(str(tmp_path), release=release)
        mock_fetch.assert_not_called()
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r69"


# ── check_for_update ──────────────────────────────────────────────────────────


def test_check_for_update_returns_none_when_up_to_date(tmp_path: Path) -> None:
    exe = _setup_sam_dir(tmp_path, "r68")
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r68")):
        assert check_for_update(str(exe)) is None


def test_check_for_update_returns_none_when_user_declines(tmp_path: Path) -> None:
    exe = _setup_sam_dir(tmp_path, "r68")
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r69")), \
         patch("builtins.input", return_value="n"):
        assert check_for_update(str(exe)) is None


def test_check_for_update_returns_new_path_when_user_accepts(tmp_path: Path) -> None:
    exe = _setup_sam_dir(tmp_path, "r68")
    new_exe = str(exe)
    release = _make_release("r69")
    with patch("app.sam.sam_downloader._fetch_latest_release", return_value=release), \
         patch("builtins.input", return_value="y"), \
         patch("app.sam.sam_downloader.download_sam", return_value=new_exe) as mock_dl:
        result = check_for_update(str(exe))
    assert result == new_exe
    mock_dl.assert_called_once_with(str(tmp_path), release=release)


def test_check_for_update_returns_none_on_eof(tmp_path: Path) -> None:
    exe = _setup_sam_dir(tmp_path, "r68")
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r69")), \
         patch("builtins.input", side_effect=EOFError):
        assert check_for_update(str(exe)) is None


def test_check_for_update_prompts_when_version_unknown(tmp_path: Path) -> None:
    """Если .sam_version отсутствует — всё равно спрашивает пользователя."""
    exe = _setup_sam_dir(tmp_path, None)
    with patch("app.sam.sam_downloader._fetch_latest_release",
               return_value=_make_release("r69")), \
         patch("builtins.input", return_value="n") as mock_input:
        check_for_update(str(exe))
    mock_input.assert_called_once_with("Обновить SAM? [y/n]: ")


def test_check_for_update_returns_new_path_when_version_unknown_and_accepts(tmp_path: Path) -> None:
    """Версия неизвестна + пользователь согласился → возвращает новый путь."""
    exe = _setup_sam_dir(tmp_path, None)
    new_exe = str(exe)
    release = _make_release("r69")
    with patch("app.sam.sam_downloader._fetch_latest_release", return_value=release), \
         patch("builtins.input", return_value="y"), \
         patch("app.sam.sam_downloader.download_sam", return_value=new_exe) as mock_dl:
        result = check_for_update(str(exe))
    assert result == new_exe
    mock_dl.assert_called_once_with(str(tmp_path), release=release)


# ── ensure_sam ────────────────────────────────────────────────────────────────


def test_ensure_sam_returns_updated_path_after_update(tmp_path: Path) -> None:
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    new_path = str(tmp_path / "sub" / "SAM.Game.exe")
    with patch("app.sam.sam_downloader.check_for_update", return_value=new_path):
        assert ensure_sam(str(exe)) == new_path


def test_ensure_sam_returns_original_path_when_no_update(tmp_path: Path) -> None:
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    with patch("app.sam.sam_downloader.check_for_update", return_value=None):
        assert ensure_sam(str(exe)) == str(exe)


def test_ensure_sam_continues_on_network_error(tmp_path: Path) -> None:
    """Ошибка сети при проверке обновлений — скрипт продолжает работу."""
    exe = tmp_path / "SAM.Game.exe"
    exe.write_bytes(b"fake")
    with patch("app.sam.sam_downloader.check_for_update",
               side_effect=urllib.error.URLError("timeout")):
        assert ensure_sam(str(exe)) == str(exe)


def test_ensure_sam_downloads_when_exe_missing(tmp_path: Path) -> None:
    exe_path = str(tmp_path / "SAM.Game.exe")
    expected = str(tmp_path / "SAM.Game.exe")
    with patch("app.sam.sam_downloader.download_sam", return_value=expected) as mock_dl:
        result = ensure_sam(exe_path)
    assert result == expected
    mock_dl.assert_called_once_with(str(tmp_path))
