"""Regression tests untuk POST LDK PLPK tanpa SPSE/network nyata."""

from types import SimpleNamespace

import dokpil_engine_plpk as engine
import dokpil_engine_pl as jkk_engine


def test_submit_pk_custom_sbu_keeps_existing_ids_and_updates_sbu_row(monkeypatch):
    context = {
        "csrf": "csrf",
        "cookie": "cookie",
        "hidden_fields": {},
        "admin_list": [{"chk_id": "a1", "ckm_id": "401"}],
        "teknis_list": [{"chk_id": "t1", "ckm_id": "437"}],
        "ijin_chk_ids": ["izin-1", "sbu-1"],
        "ijin_rows": {0: "izin-1", 1: "sbu-1"},
        "url_submit": "https://spse.test/ldksubmitbaru",
        "url_form": "https://spse.test/ldk",
    }
    monkeypatch.setattr(engine, "scrap_ldk_context", lambda _kode: context)

    payload_box = {}

    def fake_post(_url, data, **_kwargs):
        payload_box.update(data)
        return SimpleNamespace(status_code=302, text="", headers={"Location": "/ok"})

    monkeypatch.setattr(engine.requests, "post", fake_post)
    http_box = {}

    def fake_update(_kode, row_index, text, _base, cookie=""):
        http_box.update(row_index=row_index, text=text, cookie=cookie)
        return {"ok": True, "status": 302}

    monkeypatch.setattr(engine, "update_ijin_sbu_via_http", fake_update)

    result = engine.submit_ldk_pl("10975329000", sbu_baru="SBU BG009 KBLI 41019")

    assert result["ok"] is True
    assert payload_box["ijin[0].chk_id"] == "izin-1"
    assert payload_box["ijin[1].chk_id"] == "sbu-1"
    assert "BG009" in payload_box["ijin[1].chk_klasifikasi"]
    assert http_box == {
        "row_index": 1,
        "text": payload_box["ijin[1].chk_klasifikasi"],
        "cookie": "cookie",
    }
    assert result["ijin_update"] == {"ok": True, "status": 302}


def test_update_sbu_http_reposts_native_ldk_form_without_browser(monkeypatch):
    html = """
    <form action="/tapinkab/dokumennontender/PK-1/ldksubmitbaru" method="post">
      <input type="hidden" name="authenticityToken" value="csrf-2">
      <input type="hidden" name="ijin[1].chk_id" value="sbu-1">
      <input name="ijin[1].chk_nama" value="SBU">
      <input name="ijin[1].chk_klasifikasi" value="lama">
      <input type="checkbox" name="syaratAdmin[0].ckm_id" value="401" checked>
      <input type="checkbox" name="syaratAdmin[1].ckm_id" value="402">
      <button type="submit">Simpan</button>
    </form>
    """
    calls = []

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return SimpleNamespace(status_code=200, text=html)

    def fake_post(url, data, **kwargs):
        calls.append(("post", url, data, kwargs))
        return SimpleNamespace(status_code=302, text="", headers={"Location": "/ok"})

    monkeypatch.setattr(engine.requests, "get", fake_get)
    monkeypatch.setattr(engine.requests, "post", fake_post)
    monkeypatch.setattr(
        engine.spse_browser,
        "update_ijin_sbu_via_playwright",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("browser write called")),
        raising=False,
    )

    result = engine.update_ijin_sbu_via_http(
        "PK-1", 1, "SBU baru", "https://spse.test/tapinkab/", cookie="cookie"
    )

    assert result["ok"] is True
    assert calls[0][0] == "get"
    assert calls[1][0] == "post"
    assert calls[1][1] == "https://spse.test/tapinkab/dokumennontender/PK-1/ldksubmitbaru"
    assert calls[1][2]["authenticityToken"] == "csrf-2"
    assert calls[1][2]["ijin[1].chk_id"] == "sbu-1"
    assert calls[1][2]["ijin[1].chk_klasifikasi"] == "SBU baru"
    assert calls[1][2]["syaratAdmin[0].ckm_id"] == "401"
    assert "syaratAdmin[1].ckm_id" not in calls[1][2]


def test_post_login_page_is_not_reported_as_success():
    response = SimpleNamespace(
        status_code=200,
        text='<html><title>Login</title><input name="username"><input name="password"></html>',
        headers={},
    )

    result = engine._http_post_result(response, "Submit masa berlaku")

    assert result["ok"] is False
    assert "login" in result["error"].lower()


def test_scrap_checklist_reads_disabled_and_checked_native_ckm_ids(monkeypatch):
    html = """
    <form action="/tapinkab/dokumennontender/PK-1/checklistsubmit" method="post">
      <input type="hidden" name="authenticityToken" value="csrf-checklist">
      <input type="hidden" name="syaratAdmin[0].chk_id" value="admin-1">
      <input type="hidden" name="syaratAdmin[0].ckm_id" value="336">
      <input type="checkbox" name="syaratAdmin[0].ckm_id" value="336" checked disabled>
      <input type="hidden" name="syarat[0].chk_id" value="teknis-1">
      <input type="checkbox" name="syarat[0].ckm_id" value="341" checked>
    </form>
    """
    monkeypatch.setattr(engine.spse_browser, "get_spse_cookies", lambda: "cookie")
    monkeypatch.setattr(
        engine.requests,
        "get",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200, text=html),
    )

    result = engine.scrap_checklist_context("PK-1")

    assert result["admin_items"] == [{"chk_id": "admin-1", "ckm_id": "336"}]
    assert result["disabled_ckm_ids"] == {"336"}
    assert result["checked_ckm_ids"] == {"336", "341"}


def test_checklist_pk_posts_only_five_offer_document_rows(monkeypatch):
    context = {
        "csrf": "csrf-checklist",
        "cookie": "cookie",
        "admin_items": [
            {"chk_id": "a1", "ckm_id": "336"},
            {"chk_id": "a2", "ckm_id": "337"},
        ],
        "syarat_items": [
            {"chk_id": "t0", "ckm_id": "340"},
            {"chk_id": "t1", "ckm_id": "341"},
            {"chk_id": "t2", "ckm_id": "342"},
            {"chk_id": "t3", "ckm_id": "343"},
            {"chk_id": "t4", "ckm_id": "344"},
        ],
        "harga_items": [
            {"chk_id": "h0", "ckm_id": "347"},
            {"chk_id": "h1", "ckm_id": "348"},
        ],
        "disabled_ckm_ids": {"336", "337"},
        "checked_ckm_ids": set(),
        "url_submit": "https://spse.test/checklistsubmit",
        "url_form": "https://spse.test/checklist",
    }
    verified_context = {**context, "checked_ckm_ids": {"341", "342", "344", "347", "348"}}
    contexts = iter((context, verified_context))
    monkeypatch.setattr(engine, "scrap_checklist_context", lambda _kode: next(contexts))
    payload_box = {}

    def fake_post(_url, data, **_kwargs):
        payload_box.update(data)
        return SimpleNamespace(status_code=302, text="", headers={"Location": "/ok"})

    monkeypatch.setattr(engine.requests, "post", fake_post)

    result = engine.submit_checklist_pl("PK-1")

    assert result["ok"] is True
    assert payload_box["syarat[1].ckm_id"] == "341"
    assert payload_box["syarat[2].ckm_id"] == "342"
    assert payload_box["syarat[4].ckm_id"] == "344"
    assert payload_box["syaratHarga[0].ckm_id"] == "347"
    assert payload_box["syaratHarga[1].ckm_id"] == "348"
    assert payload_box["syaratAdmin[0].ckm_id"] == "336"
    assert payload_box["syaratAdmin[1].ckm_id"] == "337"
    assert payload_box["simpan"] == "simpan"
    assert "syarat[0].ckm_id" not in payload_box
    assert "syarat[3].ckm_id" not in payload_box


def test_checklist_302_without_checked_rows_is_not_success(monkeypatch):
    context = {
        "csrf": "csrf-checklist",
        "cookie": "cookie",
        "admin_items": [],
        "syarat_items": [{"chk_id": "t1", "ckm_id": "341"}],
        "harga_items": [],
        "disabled_ckm_ids": set(),
        "checked_ckm_ids": set(),
        "url_submit": "https://spse.test/checklistsubmit",
        "url_form": "https://spse.test/checklist",
    }
    contexts = iter((context, context))
    monkeypatch.setattr(engine, "scrap_checklist_context", lambda _kode: next(contexts))
    monkeypatch.setattr(
        engine.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=302, text="", headers={"Location": "/checklist"}
        ),
    )

    result = engine.submit_checklist_pl("PK-1", selected_ckm_ids=("341",))

    assert result["ok"] is False
    assert result["missing_ckm_ids"] == ["341"]
    assert "belum menyimpan" in result["error"].lower()


def test_checklist_verification_error_keeps_original_error(monkeypatch):
    context = {
        "csrf": "csrf-checklist",
        "cookie": "cookie",
        "admin_items": [],
        "syarat_items": [{"chk_id": "t1", "ckm_id": "341"}],
        "harga_items": [],
        "disabled_ckm_ids": set(),
        "checked_ckm_ids": set(),
        "url_submit": "https://spse.test/checklistsubmit",
        "url_form": "https://spse.test/checklist",
    }
    calls = iter((context,))

    def fake_context(_kode):
        try:
            return next(calls)
        except StopIteration as exc:
            raise RuntimeError("SPSE timeout saat verifikasi") from exc

    monkeypatch.setattr(engine, "scrap_checklist_context", fake_context)
    monkeypatch.setattr(
        engine.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=302, text="", headers={"Location": "/checklist"}
        ),
    )

    result = engine.submit_checklist_pl("PK-1", selected_ckm_ids=("341",))

    assert result["ok"] is False
    assert result["missing_ckm_ids"] == ["341"]
    assert "SPSE timeout" in result["error"]
    assert "_sort_ckm" not in result["error"]


def test_jkk_sbu_update_also_uses_direct_http(monkeypatch):
    html = """
    <form action="/tapinkab/dokumennontender/JKK-1/ldksubmitbaru" method="post">
      <input type="hidden" name="authenticityToken" value="csrf-jkk">
      <input type="hidden" name="ijin[1].chk_id" value="sbu-jkk-1">
      <input name="ijin[1].chk_klasifikasi" value="lama">
    </form>
    """
    calls = []

    monkeypatch.setattr(
        jkk_engine.requests,
        "get",
        lambda url, **kwargs: (calls.append(("get", url, kwargs)) or SimpleNamespace(status_code=200, text=html)),
    )
    monkeypatch.setattr(
        jkk_engine.requests,
        "post",
        lambda url, data, **kwargs: (
            calls.append(("post", url, data, kwargs))
            or SimpleNamespace(status_code=302, text="", headers={"Location": "/ok"})
        ),
    )
    monkeypatch.setattr(
        jkk_engine.spse_browser,
        "update_ijin_sbu_via_playwright",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("browser write called")),
        raising=False,
    )

    result = jkk_engine.update_ijin_sbu_via_http(
        "JKK-1", 1, "SBU baru", "https://spse.test/tapinkab/", cookie="cookie"
    )

    assert result["ok"] is True
    assert calls[0][0] == "get"
    assert calls[1][0] == "post"
    assert calls[1][2]["authenticityToken"] == "csrf-jkk"
    assert calls[1][2]["ijin[1].chk_klasifikasi"] == "SBU baru"
