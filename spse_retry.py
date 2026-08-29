"""Request helper SPSE: retry terbatas untuk gangguan eksternal."""

import time
import requests

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def request_with_retry(request_fn, *, attempts=4, delays=(0.0, 1.5, 4.0, 8.0),
                       log=None, label=""):
    """Retry timeout/koneksi dan HTTP transient; error permanen langsung balik."""
    attempts = max(1, int(attempts))
    for index in range(attempts):
        if index and index < len(delays):
            time.sleep(max(0.0, float(delays[index])))
        try:
            response = request_fn()
            status = getattr(response, "status_code", None)
            if status not in RETRYABLE_STATUS or index + 1 >= attempts:
                return response
            if log:
                log(f"    ↻ retry SPSE {index + 1}/{attempts - 1} {label}: HTTP {status}")
        except RETRYABLE_EXCEPTIONS as exc:
            if index + 1 >= attempts:
                raise
            if log:
                log(f"    ↻ retry SPSE {index + 1}/{attempts - 1} {label}: {exc}")
    raise RuntimeError("request retry berakhir tanpa response")
