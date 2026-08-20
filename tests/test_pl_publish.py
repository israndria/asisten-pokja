import requests

import pl_engine


def test_umumkan_paket_mengikuti_value_tombol_spse(monkeypatch):
    captured = {}

    class Response:
        status_code = 302
        headers = {"Location": "/tapinkab/nontender/11006038000"}
        text = ""

    def fake_get(url, **kwargs):
        assert url.endswith("/nontender/11006038000/edit")
        return type("GetResponse", (), {
            "status_code": 200,
            "text": '<form><input name="authenticityToken" value="token-cdp"></form>',
        })()

    def fake_post(url, data, headers, **kwargs):
        captured.update(url=url, data=data, headers=headers, kwargs=kwargs)
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)

    result = pl_engine.umumkan_paket_pl("11006038000", "sid=session")

    assert result["ok"] is True
    assert captured["data"] == {
        "authenticityToken": "token-cdp",
        "alasan": "",
        "setuju": "true",
    }
    assert captured["headers"]["Referer"].endswith(
        "/nontender/11006038000/edit"
    )

