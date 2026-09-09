import evaluasi_admin_kualifikasi_pl as evaluasi


def test_evaluasi_batch_reuses_supplied_participants(monkeypatch):
    peserta = [{"nama": "CV UJI", "id_nontender": "123"}]
    calls = []

    def fail_scrape(_kode):
        raise AssertionError("scrape daftar peserta tidak boleh diulang")

    def fake_submit(id_nontender, **kwargs):
        calls.append((id_nontender, kwargs))
        return {
            "admin_ok": True,
            "kualifikasi_ok": True,
            "teknis_ok": True,
            "harga_ok": True,
            "pesan": "Lulus",
            "token": "",
        }

    monkeypatch.setattr(evaluasi, "scrape_peserta_evaluasi", fail_scrape)
    monkeypatch.setattr(evaluasi, "submit_evaluasi_lulus_peserta", fake_submit)

    result = evaluasi.evaluasi_batch_lulus(
        "PK-1",
        admin=False,
        kualifikasi=False,
        peserta_list=peserta,
    )

    assert result["ok"] is True
    assert result["ringkasan"] == "1/1 peserta lulus "
    assert calls == [("123", {"admin": False, "kualifikasi": False, "teknis": False, "harga": False, "progress_cb": None})]
