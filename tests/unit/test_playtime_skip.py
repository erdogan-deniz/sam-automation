"""Тесты skip-списка playtime — игры, которые не подключаются к Steam."""

from __future__ import annotations

import app.cache as cache


def test_playtime_skip_roundtrip(tmp_path, monkeypatch):
    skip_file = tmp_path / "skip.txt"
    monkeypatch.setattr(cache, "PLAYTIME_SKIP_FILE", skip_file)

    assert cache.load_playtime_skip_ids() == set()
    cache.mark_playtime_skip(111)
    cache.mark_playtime_skip(222)
    assert cache.load_playtime_skip_ids() == {111, 222}


def test_playtime_skip_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PLAYTIME_SKIP_FILE", tmp_path / "nope.txt")
    assert cache.load_playtime_skip_ids() == set()
