import ai_evaluator


def test_kualifikasi_prompt_requires_decision_and_package_dokpil(tmp_path):
    prompt = ai_evaluator._prompt_evaluasi_kualifikasi(tmp_path, "Paket Uji")

    assert "Dokpil/LDP paket adalah sumber aturan utama" in prompt
    assert "Status Administrasi dan Kualifikasi wajib LULUS atau GUGUR" in prompt
    assert "EVALUATOR_KUALIFIKASI_PL_JKK_LUMSUM.md" in prompt
    assert "flag NONBLOCKING" in prompt


def test_teknis_prompt_is_contract_driven_and_not_verification_driven(tmp_path):
    prompt = ai_evaluator._prompt_evaluasi_teknis(tmp_path, "Paket Uji")

    assert "deteksi jenis kontrak" in prompt
    assert "evaluasi penuh dan tetapkan LULUS/GUGUR" in prompt
    assert "adalah TIDAK MEMENUHI" in prompt
    assert "EVALUATOR_KUALIFIKASI_PL_JKK_ADMIN_TEKNIS.md" in prompt
    assert "setiap Tenaga Ahli pada baris terpisah" in prompt
    assert "Tenaga pendukung/non-ahli" in prompt
    assert "hitung pengalaman Tenaga Ahli dari DRH/referensi" in prompt
    assert "Bedakan dokumen wajib penawaran" in prompt
    assert "Jangan menggugurkan hanya karena RKK/RK3K" in prompt


def test_biaya_prompt_stops_after_technical_failure(tmp_path):
    prompt = ai_evaluator._prompt_evaluasi_biaya(tmp_path, "Paket Uji")

    assert "TIDAK DILANJUTKAN" in prompt
    assert "AGENDA NEGOSIASI" in prompt


def test_teknis_refuses_incomplete_download(tmp_path, monkeypatch):
    marker = (
        tmp_path
        / "9. Dokumen Teknis Biaya"
        / "1. CV UJI"
        / "_DOWNLOAD_TIDAK_LENGKAP.txt"
    )
    marker.parent.mkdir(parents=True)
    marker.write_text("personel.pdf gagal", encoding="utf-8")
    monkeypatch.setattr(
        ai_evaluator,
        "_folder_paket",
        lambda *args, **kwargs: tmp_path,
    )

    result = ai_evaluator.evaluasi_teknis_single(1, "Paket Uji")

    assert result["status"] == "error"
    assert "belum lengkap" in result["error"]
    assert "_DOWNLOAD_TIDAK_LENGKAP.txt" in result["error"]


def test_teknis_handles_missing_package_folder(monkeypatch):
    monkeypatch.setattr(
        ai_evaluator,
        "_folder_paket",
        lambda *args, **kwargs: None,
    )

    result = ai_evaluator.evaluasi_teknis_single(99, "Paket Hilang")

    assert result["status"] == "error"
    assert "Folder paket tidak ditemukan" in result["error"]


def test_reviu_target_must_be_merged_docm(tmp_path):
    source = tmp_path / "2. Isi Reviu PLPK - Paket Uji.docm"
    merged = tmp_path / "2. Isi Reviu PLPK - Paket Uji (Merged).docm"
    source.write_bytes(b"source")
    merged.write_bytes(b"merged")

    assert ai_evaluator._find_reviu_docm(tmp_path, "pl_pk") == merged


def test_reviu_target_missing_merged_does_not_fallback_to_source(tmp_path):
    source = tmp_path / "2. Isi Reviu PLPK - Paket Uji.docm"
    source.write_bytes(b"source")

    assert ai_evaluator._find_reviu_docm(tmp_path, "pl_pk") is None


def test_plpk_prompt_enforces_merged_and_part_one_scope(tmp_path):
    target = tmp_path / "2. Isi Reviu PLPK - Paket Uji (Merged).docm"
    prompt = ai_evaluator._prompt_pra_reviu(tmp_path, "Paket Uji", target, "pl_pk")

    assert "Buka Isi Reviu" in prompt
    assert "(Merged).docm" in prompt
    assert "whitelist 45 CC Bagian I" in prompt
    assert "jangan menyentuh Bagian II" in prompt
    assert "Jangan membuat Content Control baru" in prompt
