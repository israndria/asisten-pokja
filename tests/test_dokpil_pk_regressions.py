"""Regression tests untuk POST LDK PLPK tanpa SPSE/network nyata."""

from types import SimpleNamespace

import dokpil_engine_plpk as engine


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
    cdp_box = {}

    def fake_update(_kode, row_index, text, _base):
        cdp_box.update(row_index=row_index, text=text)
        return "OK"

    monkeypatch.setattr(engine.spse_browser, "update_ijin_sbu_via_playwright", fake_update)

    result = engine.submit_ldk_pl("10975329000", sbu_baru="SBU BG009 KBLI 41019")

    assert result["ok"] is True
    assert payload_box["ijin[0].chk_id"] == "izin-1"
    assert payload_box["ijin[1].chk_id"] == "sbu-1"
    assert "BG009" in payload_box["ijin[1].chk_klasifikasi"]
    assert cdp_box == {"row_index": 1, "text": payload_box["ijin[1].chk_klasifikasi"]}
    assert result["ijin_update"] == "OK"
