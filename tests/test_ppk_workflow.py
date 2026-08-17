import os
from types import SimpleNamespace

import ppk_upload_engine as engine
from unittest.mock import MagicMock, patch


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
        verify_fn=lambda *args: {"verified": True, "versi": 8},
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
        verify_fn=lambda *args: {"verified": True, "versi": 7},
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
        verify_fn=lambda *args: {"verified": True, "versi": 3},
    )
    assert deleted == [2]
    assert result["replaced_versions"] == [2]


def test_list_dokumen_uses_cdp_api_fallback_without_browser_tab(monkeypatch):
    monkeypatch.setattr(
        engine,
        "list_dokumen_cdp",
        lambda kode, jenis: {
            "ok": True,
            "documents": [{"nama_file": "1. KAK.pdf", "versi": 0}],
        },
    )

    assert engine.list_dokumen("PK-1", "kak") == [
        {"nama_file": "1. KAK.pdf", "versi": 0}
    ]


def test_replacement_preserves_new_upload_when_delete_fails():
    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "uraian", b"new", "2. Uraian Baru.pdf", "application/pdf",
        existing_docs=[{"nama_file": "2. Uraian Lama.pdf", "versi": 1}],
        upload_fn=lambda **kwargs: {"ok": True, "versi": 9},
        delete_fn=lambda *args, **kwargs: False,
        verify_fn=lambda *args: {"verified": True, "versi": 9},
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
        verify_fn=lambda *args: {"verified": True, "versi": 3},
    )
    assert result["ok"] is True
    assert deleted == []
    assert result["replaced_versions"] == []


def test_submit_false_response_is_not_success():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {
            "ok": False,
            "status": 200,
            "error": "Submit tidak dikonfirmasi SPSE",
        }, ""),
    ):
        result = engine.upload_dokumen(
            "PK-1", "lainnya", b"x", "11. Diskresi PA.pdf", "application/pdf"
        )
    assert result["ok"] is False


def test_submit_invalid_response_is_not_success():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {
            "ok": False,
            "status": 200,
            "error": "Submit response bukan JSON",
        }, ""),
    ):
        result = engine.upload_dokumen(
            "PK-1", "lainnya", b"x", "11. Diskresi PA.pdf", "application/pdf"
        )
    assert result["ok"] is False


def test_download_existing_document_uses_direct_http_and_drops_cookie_on_signed_url():
    spse_response = SimpleNamespace(
        ok=True,
        status_code=302,
        is_redirect=True,
        is_permanent_redirect=False,
        headers={"Location": "https://storage.googleapis.com/signed/token"},
        content=b"",
    )
    signed_response = SimpleNamespace(
        ok=True,
        status_code=200,
        is_redirect=False,
        is_permanent_redirect=False,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-old",
    )

    with patch("spse_browser.get_spse_cookies", return_value="SPSE_SESSION=secret"):
        with patch("requests.get", side_effect=[spse_response, signed_response]) as http_get:
            result = engine.download_existing_document({
                "nama_file": "1. KAK.pdf",
                "url_dl": "https://spse.inaproc.id/tapinkab/dl/token",
            })

    assert result == {
        "ok": True,
        "file_bytes": b"%PDF-old",
        "mime_type": "application/pdf",
        "file_name": "1. KAK.pdf",
    }
    assert http_get.call_args_list[0].kwargs["headers"]["Cookie"] == "SPSE_SESSION=secret"
    assert "Cookie" not in http_get.call_args_list[1].kwargs["headers"]
    assert http_get.call_args_list[0].args == (
        "https://spse.inaproc.id/tapinkab/dl/token",
    )
    assert http_get.call_args_list[1].args == (
        "https://storage.googleapis.com/signed/token",
    )


def test_submit_accepts_single_normalized_file_entry_and_zero_version():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {
            "ok": True,
            "status": 200,
            "fileId": "file-2",
            "path": "/tmp/file-2",
            "files": [{
                "name": "2. U Singkat.pdf",
                "version": "0",
                "file_id": "file-2",
            }],
            "response": {"success": True},
        }, ""),
    ):
        result = engine.upload_dokumen(
            "PK-1", "uraian", b"x", "2. U_Singkat.pdf", "application/pdf"
        )
    assert result["ok"] is True
    assert result["versi"] == "0"


def test_submit_accepts_normalized_name_without_hyphen_and_preserves_version():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {
            "ok": True,
            "status": 200,
            "fileId": "file-5",
            "path": "/tmp/file-5",
            "files": [{
                "name": "5. RSPK.pdf",
                "versi": 13,
                "file_id": "file-5",
            }],
            "response": {"success": True},
        }, ""),
    ):
        result = engine.upload_dokumen(
            "PK-1", "kontrak", b"x", "5. R_SPK.pdf", "application/pdf"
        )
    assert result["ok"] is True
    assert result["versi"] == 13


def test_submit_success_without_version_is_rejected():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {
            "ok": True,
            "status": 200,
            "files": [{"name": "2. U_Singkat.pdf"}],
            "response": {"success": True},
        }, ""),
    ):
        result = engine.upload_dokumen(
            "PK-1", "uraian", b"x", "2. U_Singkat.pdf", "application/pdf"
        )
    assert result["ok"] is False
    assert "versi" in result["error"]


def test_duplicate_name_deletes_old_then_retries_upload():
    events = []

    def fake_upload(**kwargs):
        events.append("upload")
        if len(events) == 1:
            return {
                "ok": False,
                "error": "Submit gagal",
                "response": {
                    "success": False,
                    "message": "File dengan nama yang sama telah ada di server!",
                },
            }
        return {"ok": True, "versi": 14}

    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "kontrak", b"new", "5. R_SPK.pdf", "application/pdf",
        existing_docs=[{"nama_file": "5. RSPK.pdf", "versi": 13, "url_dl": "/old.pdf"}],
        upload_fn=fake_upload,
        delete_fn=lambda kode, jenis, versi, **kwargs: events.append(("delete", versi)) or True,
        verify_fn=lambda *args: {"verified": True, "versi": 14},
        backup_fn=lambda doc: {
            "ok": True,
            "file_name": doc["nama_file"],
            "file_bytes": b"old",
            "mime_type": "application/pdf",
        },
    )
    assert events == ["upload", ("delete", 13), "upload"]
    assert result["ok"] is True
    assert result["versi"] == 14
    assert result["replaced_versions"] == [13]


def test_duplicate_name_aborts_before_delete_when_backup_fails():
    events = []
    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "kontrak", b"new", "5. R_SPK.pdf", "application/pdf",
        existing_docs=[{"nama_file": "5. RSPK.pdf", "versi": 13, "url_dl": "/old.pdf"}],
        upload_fn=lambda **kwargs: {
            "ok": False,
            "error": "File dengan nama yang sama telah ada di server",
            "response": {"message": "nama yang sama telah ada"},
        },
        delete_fn=lambda *args, **kwargs: events.append("delete") or True,
        backup_fn=lambda doc: {"ok": False, "error": "download gagal"},
    )
    assert result["ok"] is False
    assert events == []
    assert "backup" in result["error"] or result["replacement_errors"]


def test_duplicate_name_retry_failure_restores_deleted_document():
    events = []

    def fake_upload(**kwargs):
        events.append(("upload", kwargs["file_name"], kwargs["file_bytes"]))
        if len(events) == 1:
            return {
                "ok": False,
                "response": {"message": "File dengan nama yang sama telah ada"},
            }
        return {"ok": False, "error": "retry server gagal"}

    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "kontrak", b"new", "5. R_SPK.pdf", "application/pdf",
        existing_docs=[{"nama_file": "5. RSPK.pdf", "versi": 13, "url_dl": "/old.pdf"}],
        upload_fn=fake_upload,
        delete_fn=lambda kode, jenis, versi, **kwargs: events.append(("delete", versi)) or True,
        backup_fn=lambda doc: {
            "ok": True,
            "file_name": doc["nama_file"],
            "file_bytes": b"old",
            "mime_type": "application/pdf",
        },
    )
    assert result["ok"] is False
    assert events == [
        ("upload", "5. R_SPK.pdf", b"new"),
        ("delete", 13),
        ("upload", "5. R_SPK.pdf", b"new"),
        ("upload", "5. RSPK.pdf", b"old"),
    ]


def test_verification_failure_never_deletes_old_version():
    deleted = []
    result = engine.upload_dokumen_dengan_replace(
        "PK-1", "lainnya", b"new", "11. Diskresi Baru.pdf", "application/pdf",
        existing_docs=[{"nama_file": "11. Diskresi Lama.pdf", "versi": 2}],
        upload_fn=lambda **kwargs: {"ok": True, "versi": 9},
        delete_fn=lambda *args, **kwargs: deleted.append(args) or True,
        verify_fn=lambda *args: {
            "verified": False,
            "error": "Dokumen belum muncul pada daftar SPSE",
        },
    )
    assert result["ok"] is False
    assert result["verified"] is False
    assert result["versi"] is None
    assert deleted == []


def test_verification_rejects_upload_version_none(monkeypatch):
    monkeypatch.setattr(
        engine,
        "list_dokumen_cdp",
        lambda *args: {"ok": True, "status": 200, "documents": [
            {"nama_file": "11. Diskresi PA.pdf", "versi": 4}
        ]},
    )
    result = engine.verifikasi_dokumen_terunggah(
        "PK-1", "lainnya", "11. Diskresi PA.pdf", None, retries=1
    )
    assert result["verified"] is False


def test_verification_rejects_mismatched_version(monkeypatch):
    monkeypatch.setattr(
        engine,
        "list_dokumen_cdp",
        lambda *args: {"ok": True, "status": 200, "documents": [
            {"nama_file": "11. Diskresi PA.pdf", "versi": 4}
        ]},
    )
    result = engine.verifikasi_dokumen_terunggah(
        "PK-1", "lainnya", "11. Diskresi PA.pdf", 5, retries=1
    )
    assert result["verified"] is False


def test_reconcile_upload_results_rejects_file_missing_from_final_spse_list():
    result = engine.reconcile_upload_results(
        [{
            "jenis": "uraian",
            "nama": "2. U_Singkat.pdf",
            "ok": True,
            "verified": True,
            "versi": 7,
        }],
        {"uraian": {"ok": True, "status": 200, "documents": []}},
    )[0]

    assert result["ok"] is False
    assert result["verified"] is False
    assert result["authoritative"] is False
    assert result["versi"] is None
    assert "tidak ditemukan" in result["error"]


def test_reconcile_upload_results_accepts_only_matching_name_and_version():
    result = engine.reconcile_upload_results(
        [{
            "jenis": "kak",
            "nama": "1. KAK.pdf",
            "ok": True,
            "verified": True,
            "versi": "11",
        }],
        {"kak": {
            "ok": True,
            "status": 200,
            "documents": [{"nama_file": "1. KAK.pdf", "versi": 11}],
        }},
    )[0]

    assert result["ok"] is True
    assert result["verified"] is True
    assert result["authoritative"] is True


def test_list_dokumen_cdp_rejects_http_error():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {
            "ok": False,
            "status": 500,
            "documents": [],
            "error": "List HTTP 500",
        }, ""),
    ):
        result = engine.list_dokumen_cdp("PK-1", "lainnya")
    assert result["ok"] is False
    assert result["status"] == 500


def test_list_dokumen_cdp_rejects_missing_files_table():
    with patch.object(
        engine,
        "_cdp_eval",
        return_value=(True, {
            "ok": False,
            "status": 200,
            "documents": [],
            "error": "Tabel #files tidak ditemukan",
        }, ""),
    ):
        result = engine.list_dokumen_cdp("PK-1", "lainnya")
    assert result["ok"] is False
    assert "#files" in result["error"]


def test_auto_match_folder_accepts_workflow_argument():
    assert engine.auto_match_folder(
        "Pagar Pasar Binuang", ["28. Pagar Pasar Binuang"], workflow="PK"
    ) == "28. Pagar Pasar Binuang"


def test_ppk_modes_are_bound_to_distinct_families():
    assert engine.ppk_mode_config("PPK - Konsultan")["workflow"] == "JKK"
    assert engine.ppk_mode_config("PPK - Pekerjaan Konstruksi")["workflow"] == "PK"


def test_resolve_ppk_upload_folder_prefers_direct_stage_folder(tmp_path):
    package = tmp_path / "13. Paket Contoh"
    direct_stage = package / "01. Upload Awal"
    direct_stage.mkdir(parents=True)

    resolved = engine.resolve_ppk_upload_folder(str(package))

    assert resolved["folder"] == os.path.normpath(str(direct_stage))
    assert resolved["source"] == "stage"


def test_resolve_ppk_upload_folder_accepts_direct_stage_input(tmp_path):
    package = tmp_path / "13. Paket Contoh"
    direct_stage = package / "02. Berkontrak"
    direct_stage.mkdir(parents=True)

    resolved = engine.resolve_ppk_upload_folder(str(direct_stage), "BERKONTRAK")

    assert resolved["package_folder"] == os.path.normpath(str(package))
    assert resolved["folder"] == os.path.normpath(str(direct_stage))


def test_resolve_ppk_upload_folder_keeps_nested_legacy_stage_folder(tmp_path):
    package = tmp_path / "13. Paket Contoh"
    legacy_stage = package / "0. Draft Dokumen PPK" / "01. Upload Awal"
    legacy_stage.mkdir(parents=True)

    resolved = engine.resolve_ppk_upload_folder(str(package))

    assert resolved["folder"] == os.path.normpath(str(legacy_stage))
    assert resolved["source"] == "stage"


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
