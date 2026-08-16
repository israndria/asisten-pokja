from datetime import date

import gcal_helper


def test_sppbj_date_matches_package_source_code(monkeypatch):
    monkeypatch.setattr(
        gcal_helper,
        "_list_calendar_events_cached",
        lambda: [{
            "summary": "Surat Penunjukkan Penyedia Barang/Jasa - Paket Contoh",
            "start": {"date": "2026-08-16"},
            "extendedProperties": {"private": {"source_tender": "T-1"}},
        }],
    )

    result = gcal_helper.get_tanggal_ba_dari_gcal("Paket Contoh", kode_paket="T-1")

    assert result["sppbj"] == date(2026, 8, 16)
