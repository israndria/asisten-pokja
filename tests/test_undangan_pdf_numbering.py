from undangan_pdf_engine import _build_nomor_surat_pl, _nomor_urut_folder_pl


def test_nomor_surat_pl_memakai_nomor_urut_bukan_kode_unik():
    data = {
        "nomor_urut": 35,
        "kode_unik": "KPNGPBng",
        "nama_paket": "Pengaspalan Jalan Lingkungan",
        "jenis_pl": "PK",
    }

    assert _nomor_urut_folder_pl(data) == "35"
    assert _build_nomor_surat_pl("35", "DPUPR", 2026) == (
        "000.3.3/PP-35/DPUPR/Reviu/2026"
    )


def test_nomor_surat_pl_fallback_ke_prefix_folder():
    data = {
        "folder_dibuat": "37. PLPK - Paket Konstruksi",
        "nama_paket": "Paket Konstruksi",
        "jenis_pl": "PK",
    }

    assert _nomor_urut_folder_pl(data) == "37"
