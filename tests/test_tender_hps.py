import hps_engine
import tender_hps


def test_find_tender_xlsm_prefers_bapk_in_package_root(tmp_path):
    (tmp_path / "Z. cadangan.xlsm").write_bytes(b"z")
    preferred = tmp_path / "0. BAPK - Uji.xlsm"
    preferred.write_bytes(b"bapk")
    nested = tmp_path / "1. Dokumen Kualifikasi"
    nested.mkdir()
    (nested / "nested.xlsm").write_bytes(b"nested")

    assert tender_hps.find_tender_xlsm(str(tmp_path)) == str(preferred)


def test_update_hps_tender_reuses_official_writer(tmp_path, monkeypatch):
    workbook = tmp_path / "0. BAPK - Uji.xlsm"
    workbook.write_bytes(b"macro-workbook")
    calls = {}

    def fake_writer(kode_tender, excel_path, progress_cb=None):
        calls["args"] = (kode_tender, excel_path, progress_cb)
        return {"ok": True, "count": 4, "pesan": "HPS ditulis"}

    monkeypatch.setattr(hps_engine, "scrape_hps_ke_excel", fake_writer)
    progress_cb = lambda _msg: None

    result = tender_hps.update_hps_tender("101", str(tmp_path), progress_cb=progress_cb)

    assert result["ok"] is True
    assert result["count"] == 4
    assert result["excel_path"] == str(workbook)
    assert calls["args"] == ("101", str(workbook), progress_cb)


def test_update_hps_tender_fails_closed_without_workbook(tmp_path):
    result = tender_hps.update_hps_tender("101", str(tmp_path))

    assert result["ok"] is False
    assert result["count"] == 0
    assert result["excel_path"] == ""
