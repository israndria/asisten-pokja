from pathlib import Path

import ai_evaluator


def test_prompt_biaya_uses_dokpil_and_handles_hps_conflict(tmp_path):
    prompt = ai_evaluator._prompt_evaluasi_biaya(tmp_path, "Paket Uji")

    assert "klausul 10.4" in prompt
    assert "klausul 7.5" in prompt
    assert "KLARIFIKASI WAJIB" in prompt
    assert "_HASIL_EVALUASI_BIAYA.md" in prompt


def test_evaluasi_biaya_requires_completed_technical_session(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(ai_evaluator, "_folder_paket", lambda *args, **kwargs: tmp_path)

    result = ai_evaluator.evaluasi_biaya_single(1, "Paket Uji")

    assert result["status"] == "error"
    assert "Sesi 2 belum selesai" in result["error"]


def test_evaluasi_biaya_verifies_markdown_output(tmp_path, monkeypatch):
    (tmp_path / "_HASIL_EVALUASI_TEKNIS.md").write_text(
        "Kesimpulan teknis: LULUS", encoding="utf-8"
    )
    (tmp_path / "9. Dokumen Teknis Biaya").mkdir()
    sop = tmp_path / "EVALUATOR_BIAYA_PL_JKK.md"
    sop.write_text("SOP uji", encoding="utf-8")

    monkeypatch.setattr(ai_evaluator, "_folder_paket", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(ai_evaluator, "EVALUASI_BIAYA_PLJKK_SOP", sop)

    def fake_run(prompt, **kwargs):
        assert "klausul 10.4" in prompt
        (tmp_path / "_HASIL_EVALUASI_BIAYA.md").write_text(
            "Kesimpulan: MEMENUHI", encoding="utf-8"
        )
        return "Evaluasi biaya selesai"

    monkeypatch.setattr(ai_evaluator, "_run_evaluator", fake_run)

    result = ai_evaluator.evaluasi_biaya_single(1, "Paket Uji")

    assert result["status"] == "ok"
    assert Path(result["file"]).name == "_HASIL_EVALUASI_BIAYA.md"


def test_evaluasi_biaya_rejects_invalid_technical_output(tmp_path, monkeypatch):
    (tmp_path / "_HASIL_EVALUASI_TEKNIS.md").write_text(
        "ERROR: dokumen teknis tidak ditemukan", encoding="utf-8"
    )
    monkeypatch.setattr(ai_evaluator, "_folder_paket", lambda *args, **kwargs: tmp_path)

    result = ai_evaluator.evaluasi_biaya_single(1, "Paket Uji")

    assert result["status"] == "error"
    assert "Sesi 2 belum valid" in result["error"]
