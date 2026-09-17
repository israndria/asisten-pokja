from undangan_pdf_engine import _build_nomor_surat_pl, _nomor_urut_folder_pl


def test_nomor_surat_pl_memakai_nomor_urut_jika_resolver_fisik_kosong(monkeypatch):
    import parse_kak_pl

    # Unit test tidak boleh bergantung pada folder produksi yang kebetulan ada
    # di laptop dan dapat mengembalikan nomor paket lain.
    monkeypatch.setattr(parse_kak_pl, "_resolve_folder_pl", lambda *args, **kwargs: ("", ""))
    data = {
        "nomor_urut": 35,
        "kode_unik": "KPNGPBng",
        "nama_paket": "Pengaspalan Jalan Lingkungan",
        "jenis_pl": "PK",
    }

    assert _nomor_urut_folder_pl(data) == "35"
    assert _build_nomor_surat_pl("35", "DPUPR", 2026) == (
        "000.3.2/PP-35/DPUPR/Reviu/2026"
    )


def test_nomor_surat_pl_fallback_ke_prefix_folder():
    data = {
        "folder_dibuat": "37. PLPK - Paket Konstruksi",
        "nama_paket": "Paket Konstruksi",
        "jenis_pl": "PK",
    }

    assert _nomor_urut_folder_pl(data) == "37"
