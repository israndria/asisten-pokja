import requests

from spse_retry import request_with_retry


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


def test_request_with_retry_retries_transient_http(monkeypatch):
    calls = []
    monkeypatch.setattr("spse_retry.time.sleep", lambda _: None)

    def call():
        calls.append(1)
        return _Response(503 if len(calls) < 3 else 200)

    result = request_with_retry(call, attempts=4)
    assert result.status_code == 200
    assert len(calls) == 3


def test_request_with_retry_retries_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr("spse_retry.time.sleep", lambda _: None)

    def call():
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.ReadTimeout("transient")
        return _Response(200)

    assert request_with_retry(call, attempts=2).status_code == 200
    assert len(calls) == 2


def test_request_with_retry_does_not_retry_permanent_http(monkeypatch):
    calls = []
    monkeypatch.setattr("spse_retry.time.sleep", lambda _: None)

    result = request_with_retry(lambda: (calls.append(1) or _Response(404)), attempts=4)
    assert result.status_code == 404
    assert len(calls) == 1
