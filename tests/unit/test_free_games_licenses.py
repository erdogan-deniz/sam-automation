"""Тесты батчевого добавления бесплатных лицензий (app/free_games/licenses.py)."""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from steam.enums import EResult  # noqa: E402

from app.free_games import licenses  # noqa: E402


class _FakeClient:
    """Двойник SteamClient.request_free_license — очередь ответов по батчам."""

    def __init__(self, responses: list[tuple]) -> None:
        self._responses = list(responses)
        self.calls: list[list[int]] = []

    def request_free_license(self, app_ids):
        self.calls.append(list(app_ids))
        return self._responses.pop(0)


def test_add_licenses_single_batch_all_granted():
    client = _FakeClient([(EResult.OK, [1, 2, 3], [])])
    result = licenses.add_licenses(client, [1, 2, 3], batch_size=50)
    assert result.added == [1, 2, 3]
    assert result.refused == []
    assert result.error == []
    assert result.hit_cap is False
    assert client.calls == [[1, 2, 3]]


def test_add_licenses_partial_grant_rest_refused():
    client = _FakeClient([(EResult.OK, [1], [])])
    result = licenses.add_licenses(client, [1, 2, 3], batch_size=50)
    assert result.added == [1]
    assert result.refused == [2, 3]


def test_add_licenses_multiple_batches(monkeypatch):
    monkeypatch.setattr(licenses.time, "sleep", lambda *_a: None)
    client = _FakeClient([(EResult.OK, [1, 2], []), (EResult.OK, [3, 4], [])])
    result = licenses.add_licenses(client, [1, 2, 3, 4], batch_size=2)
    assert result.added == [1, 2, 3, 4]
    assert client.calls == [[1, 2], [3, 4]]


def test_add_licenses_limit_exceeded_stops_immediately(monkeypatch):
    monkeypatch.setattr(licenses.time, "sleep", lambda *_a: None)
    client = _FakeClient(
        [
            (EResult.OK, [1, 2], []),
            (EResult.LimitExceeded, None, None),
            (EResult.OK, [5, 6], []),  # НЕ должен быть вызван
        ]
    )
    result = licenses.add_licenses(client, [1, 2, 3, 4, 5, 6], batch_size=2)
    assert result.added == [1, 2]
    assert result.hit_cap is True
    assert client.calls == [[1, 2], [3, 4]]  # третий батч не запрошен


def test_add_licenses_rate_limit_retries_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(licenses.time, "sleep", lambda s: sleeps.append(s))
    client = _FakeClient(
        [(EResult.RateLimitExceeded, None, None), (EResult.OK, [1, 2], [])]
    )
    result = licenses.add_licenses(client, [1, 2], batch_size=50)
    assert result.added == [1, 2]
    assert result.hit_cap is False
    assert sleeps == [licenses._RATE_LIMIT_BASE_DELAY]
    assert len(client.calls) == 2  # ретрай на ТОМ ЖЕ батче


def test_add_licenses_rate_limit_exhausted_goes_to_error(monkeypatch):
    monkeypatch.setattr(licenses.time, "sleep", lambda *_a: None)
    responses = [
        (EResult.RateLimitExceeded, None, None)
    ] * licenses._RATE_LIMIT_ATTEMPTS
    client = _FakeClient(responses)
    result = licenses.add_licenses(client, [1, 2], batch_size=50)
    assert result.error == [1, 2]
    assert result.added == []
    assert result.hit_cap is False


def test_add_licenses_exception_goes_to_error():
    class _BoomClient:
        def request_free_license(self, app_ids):
            raise ConnectionResetError("нет связи")

    result = licenses.add_licenses(_BoomClient(), [1, 2], batch_size=50)
    assert result.error == [1, 2]
    assert result.added == []


def test_add_licenses_empty_input_no_calls():
    client = _FakeClient([])
    result = licenses.add_licenses(client, [], batch_size=50)
    assert result == licenses.AddResult()
    assert client.calls == []
