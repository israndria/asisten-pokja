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


def test_biaya_prompt_stops_after_technical_failure(tmp_path):
    prompt = ai_evaluator._prompt_evaluasi_biaya(tmp_path, "Paket Uji")

    assert "TIDAK DILANJUTKAN" in prompt
    assert "AGENDA NEGOSIASI" in prompt
