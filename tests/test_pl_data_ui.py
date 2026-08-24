"""Regression gate folder lokal/workbook untuk daftar operasional PL."""

from unittest.mock import patch

import parse_kak_pl
import pl_engine
import pl_data_ui
import pl_ui_helpers
import zipfile
from pl_data_ui import _filter_pl_family, _hydrate_provider_from_excel, filter_local_pl_rows
from ui_pl_pk import active_rows, provider_identity_available


def test_pl_setup_draft_filter_excludes_active_or_published_status():
    assert pl_engine.is_paket_draft({"status": "draft"}) is True
    assert pl_engine.is_paket_draft({"status": "paket sedang berjalan"}) is False
    assert pl_engine.is_paket_draft({"status": "draft", "tahap_spse": "Upload Dokumen Penawaran"}) is False
    assert pl_engine.is_paket_draft({"status": "", "tahap_spse": "Upload Dokumen Penawaran"}) is False
    assert pl_engine.is_paket_draft({"status": "", "tahap_spse": ""}) is False


def test_pl_operational_filter_requires_active_status_or_stage():
    assert pl_engine.is_paket_berjalan({"status": "draft"}) is False
    assert pl_engine.is_paket_berjalan({"status": "", "tahap_spse": ""}) is False
    assert pl_engine.is_paket_berjalan({"status": "berjalan"}) is True
    assert pl_engine.is_paket_berjalan({"status": "evaluasi"}) is True
    assert pl_engine.is_paket_berjalan({"status": "draft", "tahap_spse": "Upload Dokumen Penawaran"}) is True
    assert pl_engine.is_paket_berjalan({"status": "selesai"}) is False
    assert pl_engine.is_paket_berjalan({"status": "berjalan", "tahap_spse": "Penandatanganan Kontrak"}) is False


def test_pl_operational_gate_excludes_pre_upload_and_ambiguous_stage():
    assert pl_engine.is_paket_operasional_eligible({
        "status": "paket sedang berjalan",
        "tahap_spse": "Upload Dokumen Penawaran",
    }) is False
    assert pl_engine.is_paket_operasional_eligible({
        "status": "draft",
        "tahap_spse": "",
    }) is False
    assert pl_engine.is_paket_operasional_eligible({
        "status": "paket sedang berjalan",
        "tahap_spse": "Tidak Ada Jadwal",
    }) is True
    assert pl_engine.is_paket_operasional_eligible({
        "status": "paket sedang berjalan",
        "tahap_spse": "Evaluasi Penawaran",
    }) is True
    assert pl_engine.is_paket_operasional_eligible({
        "status": "paket sedang berjalan",
        "tahap_spse": "Penandatanganan Kontrak",
    }) is False


def test_plpk_active_rows_excludes_draft_ambiguous_and_completed():
    rows = [
        {"kode_paket": "D", "status": "draft"},
        {"kode_paket": "A", "status": "berjalan", "tahap_spse": "Evaluasi Penawaran"},
        {"kode_paket": "X", "status": ""},
        {"kode_paket": "S", "status": "selesai"},
    ]

    filtered, duplicate_count = active_rows(lambda _kind: rows, pl_engine)

    assert [row["kode_paket"] for row in filtered] == ["A"]
    assert duplicate_count == 0


def test_provider_identity_allows_name_fallback_without_npwp():
    assert provider_identity_available({"npwp_penyedia": "123"}) is True
    assert provider_identity_available({"nama_penyedia": "CV. Nama Penyedia"}) is True
    assert provider_identity_available({"npwp_penyedia": "", "nama_penyedia": ""}) is False


def test_pl_family_loader_isolated_and_fail_closed():
    rows = [
        {"kode_paket": "PK-1", "jenis_pl": "PK"},
        {"kode_paket": "JKK-1", "jenis_pl": "JKK"},
        {"kode_paket": "UNKNOWN-1", "jenis_pl": ""},
    ]

    assert [row["kode_paket"] for row in _filter_pl_family(rows, "PK")] == ["PK-1"]
    assert [row["kode_paket"] for row in _filter_pl_family(rows, "JKK")] == ["JKK-1"]
    assert _filter_pl_family(rows, "unexpected-family") == []


def test_provider_sync_private_alias_matches_canonical_helper():
    assert (
        pl_ui_helpers._sinkronkan_identitas_penyedia_pl
        is pl_ui_helpers.sinkronkan_identitas_penyedia_pl
    )


def test_plpk_provider_uses_c77_c78_and_overrides_stale_cache(monkeypatch, tmp_path):
    folder = tmp_path / "30. PLPK - Paket Fisik"
    folder.mkdir()
    workbook = folder / "0. BAPLPK - Paket Fisik.xlsm"
    workbook.write_bytes(b"placeholder")

    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(folder), "30"),
    )
    monkeypatch.setattr(
        pl_ui_helpers,
        "_cari_xlsm_pl",
        lambda candidate: str(workbook) if candidate == str(folder) else None,
    )

    class FakeSheet:
        values = {
            "C51": "1 Unit",
            "C52": "1 Unit",
            "C77": "CV. HARAPAN GROUP",
            "C78": "0503336018733000",
        }

        def __getitem__(self, cell):
            return type("Cell", (), {"value": self.values[cell]})()

    class FakeWorkbook:
        def __getitem__(self, sheet):
            assert sheet == "@ Master Data"
            return FakeSheet()

        def close(self):
            pass

    import openpyxl
    monkeypatch.setattr(openpyxl, "load_workbook", lambda *args, **kwargs: FakeWorkbook())

    row = {
        "kode_paket": "PK-30",
        "nama_paket": "Paket fisik",
        "jenis_pl": "PK",
        "folder_dibuat": True,
        "nama_penyedia": "1 Unit",
        "npwp_penyedia": "1 Unit",
    }

    result = _hydrate_provider_from_excel([row])

    assert result[0]["nama_penyedia"] == "CV. HARAPAN GROUP"
    assert result[0]["npwp_penyedia"] == "0503336018733000"


def test_pljkk_provider_keeps_c51_c52_source(monkeypatch, tmp_path):
    folder = tmp_path / "10. PLJKK - Paket Konsultan"
    folder.mkdir()
    workbook = folder / "0. BAPLJKK - Paket Konsultan.xlsm"
    workbook.write_bytes(b"placeholder")

    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(folder), "10"),
    )
    monkeypatch.setattr(
        pl_ui_helpers,
        "_cari_xlsm_pl",
        lambda candidate: str(workbook) if candidate == str(folder) else None,
    )

    class FakeSheet:
        values = {
            "C51": "CV. RAHMAT BANUA KONSULTAN",
            "C52": "911052223733000",
            "C77": "CV. WRONG",
            "C78": "0000000000000000",
        }

        def __getitem__(self, cell):
            return type("Cell", (), {"value": self.values[cell]})()

    class FakeWorkbook:
        def __getitem__(self, sheet):
            assert sheet == "@ Master Data"
            return FakeSheet()

        def close(self):
            pass

    import openpyxl
    monkeypatch.setattr(openpyxl, "load_workbook", lambda *args, **kwargs: FakeWorkbook())

    row = {
        "kode_paket": "JKK-10",
        "nama_paket": "Paket konsultan",
        "jenis_pl": "JKK",
        "folder_dibuat": True,
    }

    result = _hydrate_provider_from_excel([row])

    assert result[0]["nama_penyedia"] == "CV. RAHMAT BANUA KONSULTAN"
    assert result[0]["npwp_penyedia"] == "911052223733000"


def test_provider_uses_xml_fast_path_without_openpyxl(monkeypatch, tmp_path):
    folder = tmp_path / "10. PLJKK - Paket Konsultan"
    folder.mkdir()
    workbook = folder / "0. BAPLJKK - Paket Konsultan.xlsm"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="@ Master Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>"
            '<row r="51"><c r="C51" t="inlineStr"><is><t>CV. XML CEPAT</t></is></c></row>'
            '<row r="52"><c r="C52" t="inlineStr"><is><t>1234567890123456</t></is></c></row>'
            "</sheetData></worksheet>",
        )

    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(folder), "10"),
    )
    monkeypatch.setattr(
        pl_ui_helpers,
        "_cari_xlsm_pl",
        lambda candidate: str(workbook) if candidate == str(folder) else None,
    )
    import openpyxl
    monkeypatch.setattr(
        openpyxl,
        "load_workbook",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("OpenPyXL tidak boleh dipanggil pada fast path")
        ),
    )
    pl_engine.read_master_cells_cached.cache_clear()

    result = _hydrate_provider_from_excel([{
        "kode_paket": "JKK-XML",
        "nama_paket": "Paket XML",
        "jenis_pl": "JKK",
    }])

    assert result[0]["nama_penyedia"] == "CV. XML CEPAT"
    assert result[0]["npwp_penyedia"] == "1234567890123456"


def test_row_without_local_folder_is_hidden(monkeypatch, tmp_path):
    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (None, ""),
    )

    rows = [{
        "kode_paket": "PK-NO-FOLDER",
        "nama_paket": "Paket belum dibuat",
        "jenis_pl": "PK",
        "folder_dibuat": None,
    }]

    assert filter_local_pl_rows(rows) == []


def test_physical_folder_and_workbook_are_authoritative(monkeypatch, tmp_path):
    folder = tmp_path / "13. PLPK - Paket Fisik"
    folder.mkdir()
    workbook = folder / "0. BAPLPK - Paket Fisik.xlsm"
    workbook.write_bytes(b"placeholder")

    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(folder), "13"),
    )
    monkeypatch.setattr(
        pl_ui_helpers,
        "_cari_xlsm_pl",
        lambda candidate: str(workbook) if candidate == str(folder) else None,
    )

    row = {
        "kode_paket": "PK-FISIK",
        "nama_paket": "Paket fisik",
        "jenis_pl": "PK",
        # DB status boleh stale/kosong; disk tetap sumber gate.
        "folder_dibuat": None,
    }

    result = filter_local_pl_rows([row])

    assert len(result) == 1
    assert result[0]["_folder_lokal"] == str(folder)
    assert result[0]["_xlsm_lokal"] == str(workbook)


def test_folder_without_workbook_is_hidden(monkeypatch, tmp_path):
    folder = tmp_path / "14. PLPK - Tanpa Workbook"
    folder.mkdir()

    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(folder), "14"),
    )
    monkeypatch.setattr(pl_ui_helpers, "_cari_xlsm_pl", lambda _candidate: None)

    row = {
        "kode_paket": "PK-NO-XLSM",
        "nama_paket": "Paket tanpa workbook",
        "jenis_pl": "PK",
        "folder_dibuat": True,
    }

    assert filter_local_pl_rows([row]) == []


def test_stale_number_cannot_resolve_other_package(monkeypatch, tmp_path):
    other_folder = tmp_path / "15. PLPK - Paket Lain"
    other_folder.mkdir()
    other_workbook = other_folder / "0. BA Paket Lain.xlsm"
    other_workbook.write_bytes(b"placeholder")

    def fake_resolve(_nomor, _nama, _jenis, *, is_ulang=False, strict_name=False):
        assert strict_name is True
        return (None, "")

    monkeypatch.setattr(parse_kak_pl, "_resolve_folder_pl", fake_resolve)
    monkeypatch.setattr(
        pl_ui_helpers,
        "_cari_xlsm_pl",
        lambda _candidate: str(other_workbook),
    )

    row = {
        "kode_paket": "PK-STALE-NUMBER",
        "nama_paket": "Paket yang belum dibuat",
        "jenis_pl": "PK",
        "nomor_urut": "15",
        "folder_dibuat": True,
    }

    assert filter_local_pl_rows([row]) == []


def test_strict_resolver_accepts_officially_truncated_folder(monkeypatch, tmp_path):
    root = tmp_path / "pk"
    root.mkdir()
    package_name = "Belanja Modal Bangunan Gedung Pertokoan Koperasi Pasar Pembangunan Gapura Pintu Gerbang Pasar Binuang Jalan Bay Pass"
    full_name = f"28. PLPK - {package_name}"
    truncated_name = pl_engine.truncate_nama_folder(str(root), full_name)
    folder = root / truncated_name
    folder.mkdir()

    import config

    monkeypatch.setattr(config, "OUTPUT_DIR_PL_PK", str(root))

    resolved, number = parse_kak_pl._resolve_folder_pl(
        28,
        package_name,
        "PK",
        strict_name=True,
    )

    assert resolved == str(folder)
    assert number == "28"


def test_strict_resolver_accepts_unique_short_physical_name(monkeypatch, tmp_path):
    import config

    root = tmp_path / "plpk"
    folder = root / "28. PLPK - Belanja Modal Bangunan Gedung Pertokoan-Koperasi-Pasar Pembangunan"
    folder.mkdir(parents=True)
    monkeypatch.setattr(config, "OUTPUT_DIR_PL_PK", str(root))

    resolved, nomor = parse_kak_pl._resolve_folder_pl(
        28,
        "Belanja Modal Bangunan Gedung Pertokoan/Koperasi/Pasar Pembangunan Gapura Pintu Gerbang",
        "PK",
        strict_name=True,
    )

    assert resolved == str(folder)
    assert nomor == "28"


def test_strict_resolver_rejects_ambiguous_short_physical_name(monkeypatch, tmp_path):
    import config

    root = tmp_path / "plpk"
    (root / "28. PLPK - Belanja Modal Pembangunan A").mkdir(parents=True)
    (root / "28. PLPK - Belanja Modal Pembangunan B").mkdir(parents=True)
    monkeypatch.setattr(config, "OUTPUT_DIR_PL_PK", str(root))

    resolved, nomor = parse_kak_pl._resolve_folder_pl(
        28,
        "Belanja Modal Pembangunan",
        "PK",
        strict_name=True,
    )

    assert resolved is None
    assert nomor == ""

def test_status_peserta_tab1_lazy_loads_only_when_requested():
    state = {}
    kode = ("1001", "1002")
    status = {"1001": {"jumlah": 1}, "1002": {"jumlah": 0}}

    with patch.object(pl_data_ui.st, "session_state", state), patch.object(
        pl_data_ui.st, "button", side_effect=[False, True]
    ), patch.object(
        pl_data_ui, "fetch_status_semua_paket_cached", return_value=status
    ) as fetch:
        awal = pl_data_ui.load_status_peserta_on_demand(
            kode, "test_status", "test_status_button"
        )
        assert awal == {}
        fetch.assert_not_called()

        setelah_muat = pl_data_ui.load_status_peserta_on_demand(
            kode, "test_status", "test_status_button"
        )

    assert setelah_muat == status
    assert state["test_status"] == status
    fetch.assert_called_once_with(kode)


def test_paket_umumkan_status_uses_session_then_spse_fields():
    assert pl_data_ui.is_paket_sudah_diumumkan(
        {"kode_paket": "34", "status": "draft"},
        {"34": {"status": "sudah diumumkan"}},
    ) is True
    assert pl_data_ui.is_paket_sudah_diumumkan(
        {"kode_paket": "35", "status": "berjalan"},
        {},
    ) is True
    assert pl_data_ui.is_paket_sudah_diumumkan(
        {"kode_paket": "36", "status": "draft", "tahap_spse": "Pengumuman"},
        {},
    ) is True
    assert pl_data_ui.is_paket_sudah_diumumkan(
        {"kode_paket": "36b", "status": "draft", "tahap_spse": "Upload Dokumen Penawaran"},
        {},
    ) is True
    assert pl_data_ui.is_paket_sudah_diumumkan(
        {"kode_paket": "37", "status": "draft", "tahap_spse": ""},
        {},
    ) is False
    assert pl_data_ui.is_paket_sudah_diumumkan(
        {
            "kode_paket": "34",
            "status": "draft",
            "tahap_spse": "Paket Belum Dilaksanakan",
        },
        {},
    ) is True


def test_mark_paket_sudah_diumumkan_ke_session_state():
    state = {}
    with patch.object(pl_data_ui.st, "session_state", state):
        pl_data_ui.mark_paket_sudah_diumumkan(
            "34", {"status_code": 302, "location": "/nontender/34"}
        )

    assert state["pl_umumkan_status"]["34"] == {
        "status": "sudah diumumkan",
        "status_code": 302,
        "location": "/nontender/34",
    }


def test_mark_tahap_spse_sudah_diumumkan_menyimpan_status_batch():
    state = {}
    with patch.object(pl_data_ui.st, "session_state", state):
        jumlah = pl_data_ui.mark_tahap_spse_sudah_diumumkan({
            "34": "Paket Belum Dilaksanakan",
            "35": "Upload Dokumen Penawaran",
            "36": "",
        })

    assert jumlah == 2
    assert state["pl_umumkan_status"]["34"]["tahap_spse"] == "Paket Belum Dilaksanakan"
    assert state["pl_umumkan_status"]["35"]["status"] == "sudah diumumkan"


def test_update_hps_paket_pl_backs_up_workbook_before_official_writer(tmp_path, monkeypatch):
    workbook = tmp_path / "0. BAPLPK - Uji.xlsm"
    workbook.write_bytes(b"macro-workbook")
    calls = {}

    class Engine:
        @staticmethod
        def _find_xlsm(kode_paket):
            calls["kode"] = kode_paket
            return str(workbook)

    def fake_writer(kode_paket, excel_path, progress_cb=None):
        calls["writer"] = (kode_paket, excel_path, progress_cb)
        return {"ok": True, "pesan": "HPS ditulis", "count": 3}

    import hps_engine
    monkeypatch.setattr(hps_engine, "scrape_hps_pl_ke_excel", fake_writer)

    logs = []
    result = pl_ui_helpers.update_hps_paket_pl("PK-1", Engine, logs.append)

    assert result["ok"] is True
    assert result["count"] == 3
    assert calls["kode"] == "PK-1"
    assert calls["writer"] == ("PK-1", str(workbook), logs.append)
    backup = tmp_path / result["backup_path"].split("\\")[-1]
    assert backup.is_file()
    assert backup.read_bytes() == workbook.read_bytes()
    assert any(line.startswith("Backup HPS:") for line in logs)


def test_dokpil_resolver_uses_only_package_root(tmp_path):
    folder = tmp_path / "41. PLPK - Paket Fisik"
    folder.mkdir()
    root_pdf = folder / "dokpil_Paket Fisik.pdf"
    root_pdf.write_bytes(b"root")
    nested = folder / "2. Rancangan Kontrak"
    nested.mkdir()
    (nested / "dokpil_Paket Fisik - subfolder.pdf").write_bytes(b"nested")

    result = pl_ui_helpers._find_dokpil_pdf_root(str(folder))

    assert result["status"] == "found"
    assert result["path"] == str(root_pdf)


def test_dokpil_resolver_does_not_guess_ambiguous_root_files(tmp_path):
    folder = tmp_path / "61. PLJKK - Paket Konsultan"
    folder.mkdir()
    (folder / "dokpil_Paket Konsultan.pdf").write_bytes(b"one")
    (folder / "dokpil_Paket Konsultan v2.pdf").write_bytes(b"two")
    (folder / "_backup_dokpil_lama.pdf").write_bytes(b"backup")

    result = pl_ui_helpers._find_dokpil_pdf_root(str(folder))

    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2
    assert all("backup" not in path.casefold() for path in result["candidates"])


def test_sync_live_paket_umumkan_status_marks_and_throttles(monkeypatch):
    state = {}
    calls = []

    monkeypatch.setattr(pl_data_ui.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(pl_data_ui.st, "session_state", state)

    import pl_engine
    import spse_browser

    monkeypatch.setattr(spse_browser, "get_spse_cookies", lambda: "cookie")
    monkeypatch.setattr(
        pl_engine,
        "_fetch_tahap_spse",
        lambda *_args, **_kwargs: (calls.append(True) or {"74": "Upload Dokumen Penawaran"}),
    )

    first = pl_data_ui.sync_live_paket_umumkan_status("test_tayang")
    second = pl_data_ui.sync_live_paket_umumkan_status("test_tayang")

    assert first == {"ok": True, "cached": False, "count": 1}
    assert second == {"ok": True, "cached": True, "count": 0}
    assert len(calls) == 1
    assert pl_data_ui.is_paket_sudah_diumumkan({"kode_paket": "74", "status": "draft"}) is True
