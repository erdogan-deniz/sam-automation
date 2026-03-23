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


def test_save_version_writes_tag(tmp_path):
    _save_version(tmp_path, "r68")
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r68"


def test_save_version_overwrites(tmp_path):
    _save_version(tmp_path, "r68")
    _save_version(tmp_path, "r69")
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r69"


# ── _read_installed_version ───────────────────────────────────────────────────


def test_read_installed_version_returns_tag(tmp_path):
    (tmp_path / ".sam_version").write_text("r68\n", encoding="utf-8")
    assert _read_installed_version(tmp_path) == "r68"


def test_read_installed_version_missing_returns_none(tmp_path):
    assert _read_installed_version(tmp_path) is None


def test_read_installed_version_strips_whitespace(tmp_path):
    (tmp_path / ".sam_version").write_text("  r68  \n", encoding="utf-8")
    assert _read_installed_version(tmp_path) == "r68"


# ── _fetch_latest_release ─────────────────────────────────────────────────────


def test_fetch_latest_release_returns_dict():
    release = _make_release("r68")
    mock_resp = _make_url_mock(json.dumps(release).encode())
    with patch("app.sam.sam_downloader.urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_latest_release()
    assert result["tag_name"] == "r68"
    assert len(result["assets"]) == 1


def test_fetch_latest_release_raises_on_network_error():
    with patch("app.sam.sam_downloader.urllib.request.urlopen",
               side_effect=urllib.error.URLError("timeout")):
        with pytest.raises(urllib.error.URLError):
            _fetch_latest_release()


# ── download_sam ──────────────────────────────────────────────────────────────


def test_download_sam_saves_version(tmp_path):
    release = _make_release("r68")
    with patch("app.sam.sam_downloader._fetch_latest_release", return_value=release), \
         patch("app.sam.sam_downloader.urllib.request.urlopen",
               return_value=_make_url_mock(_make_zip_bytes())):
        download_sam(str(tmp_path))
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r68"


def test_download_sam_uses_provided_release(tmp_path):
    """Если release передан — _fetch_latest_release не вызывается."""
    release = _make_release("r69")
    with patch("app.sam.sam_downloader._fetch_latest_release") as mock_fetch, \
         patch("app.sam.sam_downloader.urllib.request.urlopen",
               return_value=_make_url_mock(_make_zip_bytes())):
        download_sam(str(tmp_path), release=release)
        mock_fetch.assert_not_called()
    assert (tmp_path / ".sam_version").read_text(encoding="utf-8") == "r69"
