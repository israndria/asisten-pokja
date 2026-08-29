from unittest.mock import patch

import peserta_monitor_pl


def test_fetch_jumlah_peserta_retries_transient_404():
    class _Response:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    responses = iter([
        _Response(404),
        _Response(200, "<html><body><table><tbody></tbody></table></body></html>"),
    ])
    with patch.object(
        peserta_monitor_pl.requests,
        "get",
        side_effect=lambda *args, **kwargs: next(responses),
    ) as request, patch.object(peserta_monitor_pl.time, "sleep"):
        result = peserta_monitor_pl.fetch_jumlah_peserta_pl("P-1")

    assert result == {"jumlah": 0, "error": None}
    assert request.call_count == 2
