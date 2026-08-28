import upload_ba_reviu_pl as mod
import requests


def test_scrap_upload_form_collects_versions_descending(monkeypatch):
    html = '''<form><input name="authenticityToken" value="tok"></form>
      <a id="hapusDokBa" href="/nontender/1/bataluploadbareviu?versi=0">Batalkan</a>
      <a id="hapusDokBa" href="/nontender/1/bataluploadbareviu?versi=2">Batalkan</a>
      <a id="hapusDokBa" href="/nontender/1/bataluploadbareviu?versi=1">Batalkan</a>'''

    class Response:
        status_code = 200
        text = html

    def fake_get(url, **kwargs):
        if url.endswith("/uploadbareviu"):
            return Response()
        return type("EditResponse", (), {"status_code": 200, "text": html})()

    monkeypatch.setattr(mod.requests, "get", fake_get)
    ctx = mod._scrap_upload_form("1", "cookie")
    assert ctx["csrf"] == "tok"
    assert ctx["existing_versions"] == [2, 1, 0]


def test_delete_existing_ba_reviu_deletes_highest_version_first(monkeypatch):
    seen = []

    class Response:
        def __init__(self, status):
            self.status_code = status

    def fake_get(url, **kwargs):
        seen.append(kwargs["params"]["versi"])
        return Response(302)

    monkeypatch.setattr(mod.requests, "get", fake_get)
    result = mod._delete_existing_ba_reviu("1", [0, 2, 1, 2], "cookie")
    assert result["ok"] is True
    assert seen == ["2", "1", "0"]


def test_delete_existing_ba_reviu_converts_timeout_to_failed_result(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.ReadTimeout("slow SPSE")

    monkeypatch.setattr(mod.requests, "get", timeout)
    result = mod._delete_existing_ba_reviu("1", [0], "cookie")
    assert result["ok"] is False
    assert result["results"][0]["status"] == 0


def test_submit_timeout_is_returned_without_traceback(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.ReadTimeout("slow submit")

    monkeypatch.setattr(mod.requests, "post", timeout)
    result = mod._submit_bareviu_form(
        {"csrf": "tok", "url_submit": "https://example/submit", "url_form": "https://example/form"},
        "28-08-2026", "/path", "file-id", "cookie",
    )
    assert result["ok"] is False
    assert result["timeout"] is True


def test_submit_http_failure_always_has_actionable_error(monkeypatch):
    class Response:
        status_code = 403
        headers = {"Location": "/login"}
        text = "csrf tidak valid"

    monkeypatch.setattr(mod.requests, "post", lambda *args, **kwargs: Response())
    result = mod._submit_bareviu_form(
        {"csrf": "tok", "url_submit": "https://example/submit", "url_form": "https://example/form"},
        "28-08-2026", "/path", "file-id", "cookie",
    )
    assert result["ok"] is False
    assert "HTTP 403" in result["error"]
    assert "csrf tidak valid" in result["error"]


def test_public_upload_normalizes_put_exception(monkeypatch):
    monkeypatch.setattr(mod.spse_browser, "get_spse_cookies", lambda: "cookie")
    monkeypatch.setattr(
        mod,
        "_scrap_upload_form",
        lambda *args, **kwargs: {
            "csrf": "tok",
            "url_submit": "https://example/submit",
            "url_form": "https://example/form",
            "existing_versions": [],
        },
    )
    monkeypatch.setattr(
        mod,
        "_get_signed_url",
        lambda *args, **kwargs: {"signedUrl": "https://example/upload", "fileId": "id", "path": "/path"},
    )

    def put_timeout(*args, **kwargs):
        raise requests.ReadTimeout("GCS lambat")

    monkeypatch.setattr(mod, "_put_to_gcs", put_timeout)
    result = mod.upload_ba_reviu_pl("1", b"%PDF", "ba.pdf", "28-08-2026")
    assert result["ok"] is False
    assert result["stage"] == "PUT GCS"
    assert "GCS lambat" in result["error"]


def test_with_retry_restarts_whole_cycle_only_for_transient_error(monkeypatch):
    calls = []
    results = iter([
        {"ok": False, "status": 503, "stage": "getSignedUrl", "error": "HTTP 503"},
        {"ok": True, "status": 302},
    ])

    def fake_upload(**kwargs):
        calls.append(kwargs["kode_paket"])
        return next(results)

    monkeypatch.setattr(mod, "upload_ba_reviu_pl", fake_upload)
    result = mod.upload_ba_reviu_pl_with_retry(
        kode_paket="1", file_bytes=b"%PDF", file_name="ba.pdf", retry_delay=0,
    )
    assert result["ok"] is True
    assert result["attempts"] == 2
    assert calls == ["1", "1"]


def test_with_retry_does_not_repeat_non_transient_http_error(monkeypatch):
    calls = []

    def fake_upload(**kwargs):
        calls.append(kwargs["kode_paket"])
        return {"ok": False, "status": 403, "stage": "submitbareviu", "error": "forbidden"}

    monkeypatch.setattr(mod, "upload_ba_reviu_pl", fake_upload)
    result = mod.upload_ba_reviu_pl_with_retry(
        kode_paket="1", file_bytes=b"%PDF", file_name="ba.pdf", retry_delay=0,
    )
    assert result["ok"] is False
    assert result["attempts"] == 1
    assert calls == ["1"]
