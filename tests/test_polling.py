"""poll_until_complete tests."""

import pytest

from app.pixai.errors import PixAITaskFailedError, PixAITimeoutError
from app.pixai.polling import poll_until_complete


class FakeClient:
    def __init__(self, transcript):
        self._transcript = list(transcript)
        self.calls = 0

    def get_task_by_id(self, task_id):
        self.calls += 1
        return self._transcript.pop(0)


def test_polling_returns_completed_task():
    client = FakeClient([
        {"id": "t", "status": "running"},
        {"id": "t", "status": "running"},
        {"id": "t", "status": "completed"},
    ])
    task = poll_until_complete(client, "t", timeout=10, sleep_fn=lambda *_: None)
    assert task["status"] == "completed"
    assert client.calls == 3


def test_polling_raises_on_failed_status():
    client = FakeClient([{"id": "t", "status": "failed"}])
    with pytest.raises(PixAITaskFailedError):
        poll_until_complete(client, "t", timeout=10, sleep_fn=lambda *_: None)


def test_polling_raises_on_timeout():
    client = FakeClient([{"id": "t", "status": "running"}] * 100)
    fake_clock = [0.0]
    def mono():
        fake_clock[0] += 5
        return fake_clock[0]
    with pytest.raises(PixAITimeoutError):
        poll_until_complete(client, "t", timeout=10, sleep_fn=lambda *_: None, monotonic_fn=mono)
