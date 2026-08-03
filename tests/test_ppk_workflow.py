import os

import ppk_upload_engine as engine
from unittest.mock import patch


def test_fetch_ppk_auth_error_is_not_mistaken_for_empty_data():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {"ok": False, "status": 403, "rows": []}, ""),
    ):
        assert engine.fetch_paket_ppk() == []

    state = engine.get_ppk_fetch_state()
    assert state["reason"] == "auth_error"
    assert state["status"] == 403


def test_fetch_ppk_server_error_is_not_mistaken_for_empty_data():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {"ok": False, "status": 500, "rows": []}, ""),
    ):
        assert engine.fetch_paket_ppk() == []

    state = engine.get_ppk_fetch_state()
    assert state["reason"] == "server_error"
    assert state["status"] == 500


def test_resolve_jkk_from_explicit_metadata_even_if_name_mentions_konstruksi():
    result = engine.resolve_ppk_workflow({
        "nama_paket": "Jasa Pengawasan Konstruksi Jalan",
        "jenis_pengadaan": "Jasa Konsultansi",
    })
    assert result["workflow"] == "JKK"
    assert result["status"] == "resolved"


def test_resolve_pk_from_explicit_metadata():
    result = engine.resolve_ppk_workflow({"jenis_pekerjaan": "Pekerjaan Konstruksi"})
    assert result["workflow"] == "PK"
    assert engine.resolve_ppk_workflow({"jenis_pengadaan": "Konstruksi"})["workflow"] == "PK"


def test_registry_mapping_overrides_package_title():
    assert engine.resolve_ppk_workflow(
        {"kode_paket": "PK-1", "nama_paket": "Jasa Konsultansi Pengawasan"},
        registry={"PK-1": "PK"},
    ) == {"status": "resolved", "workflow": "PK", "source": "registry"}
    assert engine.resolve_ppk_workflow(
        {"kode_paket": "JKK-1", "nama_paket": "Pembangunan Gedung"},
        registry={"JKK-1": "JKK"},
    ) == {"status": "resolved", "workflow": "JKK", "source": "registry"}


def test_title_only_is_ambiguous_including_accounting_nomenclature():
    result = engine.resolve_ppk_workflow({
        "kode_paket": "NO-MAPPING",
        "nama_paket": "Belanja Barang untuk Dijual/Diserahkan kepada Pihak Ketiga/Pihak Lain",
    }, registry={})
    assert result == {"status": "ambiguous", "workflow": None, "source": "metadata_missing"}


def test_save_load_ppk_workflow_registry_round_trip(tmp_path):
    path = tmp_path / ".ppk_workflow_registry.json"
    saved = engine.save_ppk_workflow_registry({
        "11930137000": "pk",
        "11930137001": "JKK",
        "invalid": "BARANG",
    }, path)
    assert saved == {"11930137000": "PK", "11930137001": "JKK"}
    assert engine.load_ppk_workflow_registry(path) == saved


def test_load_ppk_workflow_registry_handles_missing_or_invalid_json(tmp_path):
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    assert engine.load_ppk_workflow_registry(missing) == {}
    assert engine.load_ppk_workflow_registry(invalid) == {}


def test_ppk_workflow_registry_honors_environment_override(monkeypatch, tmp_path):
    path = tmp_path / "shared-registry.json"
    monkeypatch.setenv("POKJA_PPK_WORKFLOW_REGISTRY", str(path))
    assert engine.save_ppk_workflow_registry({"11930137002": "PK"}) == {
        "11930137002": "PK"
    }
    assert engine.load_ppk_workflow_registry() == {"11930137002": "PK"}


def test_empty_registry_environment_override_uses_shared_default(monkeypatch):
    monkeypatch.setenv("POKJA_PPK_WORKFLOW_REGISTRY", "   ")
    assert engine._ppk_workflow_registry_path() == engine.PPK_WORKFLOW_REGISTRY_PATH


def test_pk_mapping_includes_contract_and_kak_documents():
    mapping = engine.ppk_workflow_config("PK")["mapping"]
    assert "3." in mapping
    assert mapping["4."] == "kontrak"
    assert mapping["5."] == "kontrak"
    assert mapping["6."] == "kontrak"
    assert mapping["9."] == "kak"
    assert mapping["12."] == "kak"
    assert mapping["13."] == "kak"
    assert mapping["14."] == "kak"
    assert mapping["15."] == "kak"


def test_jkk_mapping_includes_personil_and_manual_specification_in_kak():
    mapping = engine.ppk_workflow_config("JKK")["mapping"]
    assert mapping["9."] == "kak"
    assert mapping["12."] == "kak"
    assert mapping["13."] == "kak"
    assert mapping["14."] == "kak"
    assert mapping["15."] == "kak"


def test_scan_folder_pdf_mode_keeps_personil_docx_and_spec_pdf(tmp_path):
    (tmp_path / "9. List_Personil_Alat.docx").write_bytes(b"docx")
    (tmp_path / "12. Spesifikasi Teknis.pdf").write_bytes(b"pdf")
    (tmp_path / "13. Gambar.pdf").write_bytes(b"pdf")
    (tmp_path / "14. RK3.pdf").write_bytes(b"pdf")
    (tmp_path / "15. TKDN.pdf").write_bytes(b"pdf")
    (tmp_path / "10. Survey Pasar.pdf").write_bytes(b"pdf")

    files = engine.scan_folder(str(tmp_path), pdf_only=True, workflow="PK")
    names = {item["nama"] for item in files}
    assert "9. List_Personil_Alat.docx" in names
    assert "12. Spesifikasi Teknis.pdf" in names
    assert "13. Gambar.pdf" in names
    assert "14. RK3.pdf" in names
    assert "15. TKDN.pdf" in names
    assert "10. Survey Pasar.pdf" not in names


def test_windows_long_path_helper_adds_extended_prefix():
    if os.name != "nt":
        return
    path = "C:\\" + ("nested\\" * 40) + "9. List_Personil_Alat.pdf"
    resolved = engine._windows_filesystem_path(path)
    assert resolved.startswith("\\\\?\\")
    assert resolved.endswith("9. List_Personil_Alat.pdf")


def test_bulk_upload_selection_prefers_pdf_but_falls_back_to_personil_docx():
    files = [
        {"nama": "9. List_Personil_Alat.docx", "jenis": "kak", "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        {"nama": "9. List_Personil_Alat.pdf", "jenis": "kak", "mime": "application/pdf"},
        {"nama": "12. Spesifikasi Teknis.pdf", "jenis": "kak", "mime": "application/pdf"},
        {"nama": "13. Gambar.pdf", "jenis": "kak", "mime": "application/pdf"},
        {"nama": "14. RK3.pdf", "jenis": "kak", "mime": "application/pdf"},
        {"nama": "15. TKDN.pdf", "jenis": "kak", "mime": "application/pdf"},
    ]
    selected = engine.select_bulk_upload_files(files)
    assert [item["nama"] for item in selected] == [
        "9. List_Personil_Alat.pdf",
        "12. Spesifikasi Teknis.pdf",
        "13. Gambar.pdf",
        "14. RK3.pdf",
        "15. TKDN.pdf",
    ]

    selected = engine.select_bulk_upload_files(files[:1])
    assert [item["nama"] for item in selected] == ["9. List_Personil_Alat.docx"]


def test_bulk_upload_selection_preserves_legacy_non_pdf_mode():
    files = [
        {"nama": "1. KAK.docx", "jenis": "kak", "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        {"nama": "2. Uraian Singkat.xlsx", "jenis": "uraian", "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ]
    assert [item["nama"] for item in engine.select_bulk_upload_files(files, pdf_only=False)] == [
        "1. KAK.docx",
        "2. Uraian Singkat.xlsx",
    ]


def test_upload_target_labels_are_consistent_for_logs():
    assert engine.upload_target_label("kak") == "KAK / Spesifikasi"
    assert engine.upload_target_label("kontrak") == "Rancangan Kontrak"
    assert engine.upload_target_label("uraian") == "Uraian Singkat"
    assert engine.upload_target_label("lainnya") == "Informasi Lainnya"


def test_replacement_matches_same_numeric_slot_and_deletes_after_upload():
    events = []

    def fake_upload(**kwargs):
        events.append("upload")
        return {"ok": True, "versi": 8}

    def fake_delete(kode, jenis, versi, **kwargs):
        events.append(("delete", versi))
        return True

    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "lainnya", b"new", "11. Diskresi PA.pdf", "application/pdf",
        existing_docs=[
            {"nama_file": "11. Diskresi.pdf", "versi": 0},
            {"nama_file": "10. Survey.pdf", "versi": 4},
        ],
        upload_fn=fake_upload,
        delete_fn=fake_delete,
    )
    assert events == ["upload", ("delete", 0)]
    assert result["replaced_versions"] == [0]
    assert result["replacement_errors"] == []


def test_replacement_uses_exact_normalized_name_without_numeric_prefix():
    deleted = []

    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "kak", b"new", "Lampiran Final.pdf", "application/pdf",
        existing_docs=[
            {"nama_file": "  lampiran   final.PDF ", "versi": 3},
            {"nama_file": "Lampiran Lain.pdf", "versi": 5},
        ],
        upload_fn=lambda **kwargs: {"ok": True, "versi": 7},
        delete_fn=lambda kode, jenis, versi, **kwargs: deleted.append(versi) or True,
    )
    assert deleted == [3]
    assert result["replaced_versions"] == [3]


def test_replacement_loads_existing_docs_when_caller_does_not_supply_them(monkeypatch):
    deleted = []
    monkeypatch.setattr(
        engine,
        "list_dokumen",
        lambda kode, jenis: [{"nama_file": "1. KAK Lama.pdf", "versi": 2}],
    )
    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "kak", b"new", "1. KAK Baru.pdf", "application/pdf",
        upload_fn=lambda **kwargs: {"ok": True, "versi": 3},
        delete_fn=lambda kode, jenis, versi, **kwargs: deleted.append(versi) or True,
    )
    assert deleted == [2]
    assert result["replaced_versions"] == [2]


def test_replacement_preserves_new_upload_when_delete_fails():
    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "uraian", b"new", "2. Uraian Baru.pdf", "application/pdf",
        existing_docs=[{"nama_file": "2. Uraian Lama.pdf", "versi": 1}],
        upload_fn=lambda **kwargs: {"ok": True, "versi": 9},
        delete_fn=lambda *args, **kwargs: False,
    )
    assert result["ok"] is True
    assert result["versi"] == 9
    assert result["replaced_versions"] == []
    assert result["replacement_errors"]


def test_failed_upload_never_deletes_existing_version():
    deleted = []
    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "kontrak", b"bad", "5. R_SPK Baru.pdf", "application/pdf",
        existing_docs=[{"nama_file": "5. R_SPK Lama.pdf", "versi": 2}],
        upload_fn=lambda **kwargs: {"ok": False, "error": "server gagal"},
        delete_fn=lambda *args, **kwargs: deleted.append(args) or True,
    )
    assert result["ok"] is False
    assert deleted == []
    assert result["replaced_versions"] == []


def test_replacement_does_not_delete_nota_dinas():
    deleted = []
    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "nd", b"new", "8. ND Baru.pdf", "application/pdf",
        existing_docs=[{"nama_file": "8. ND Lama.pdf", "versi": 2}],
        upload_fn=lambda **kwargs: {"ok": True, "versi": 3},
        delete_fn=lambda *args, **kwargs: deleted.append(args) or True,
    )
    assert result["ok"] is True
    assert deleted == []
    assert result["replaced_versions"] == []


def test_auto_match_folder_accepts_workflow_argument():
    assert engine.auto_match_folder(
        "Pagar Pasar Binuang", ["28. Pagar Pasar Binuang"], workflow="PK"
    ) == "28. Pagar Pasar Binuang"


def test_ppk_modes_are_bound_to_distinct_families():
    assert engine.ppk_mode_config("PPK - Konsultan")["workflow"] == "JKK"
    assert engine.ppk_mode_config("PPK - Pekerjaan Konstruksi")["workflow"] == "PK"


def test_filter_ppk_packages_uses_registry_then_metadata():
    rows = [
        {"kode_paket": "1", "nama_paket": "Jasa Konsultansi"},
        {"kode_paket": "2", "nama_paket": "Pembangunan Pagar"},
        {"kode_paket": "3", "nama_paket": "Nama Tidak Menentukan Family"},
    ]
    details = {
        "1": {"jenis_pengadaan": "Jasa Konsultansi"},
        "2": {"jenis_pengadaan": "Pekerjaan Konstruksi"},
    }
    assert [
        row["kode_paket"]
        for row in engine.filter_paket_ppk_by_workflow(
            rows, "PK", details, registry={"1": "PK"}
        )
    ] == ["1", "2"]
    assert [
        row["kode_paket"]
        for row in engine.filter_paket_ppk_by_workflow(
            rows, "JKK", {}, registry={"3": "JKK"}
        )
    ] == ["3"]
