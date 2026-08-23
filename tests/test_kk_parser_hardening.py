import kk_evaluasi_engine
import kualifikasi_parser


def test_requirement_parser_supports_plain_kbli_and_subclassification():
    tokens = kualifikasi_parser._parse_sbu_requirement_keywords(
        "SBU BG002 Konstruksi Gedung Perkantoran atau "
        "Konstruksi Konvensional Gedung Perkantoran KBLI 41012"
    )

    assert "BG002" in tokens
    assert "41012" in tokens


def test_local_requirement_has_priority_over_stale_database(monkeypatch):
    monkeypatch.setattr(
        kualifikasi_parser,
        "_ambil_requirement_lokal",
        lambda _folder: "SBU BG002 Konstruksi Gedung Perkantoran KBLI 41012",
    )

    tokens = kualifikasi_parser._ambil_syarat_sbu_keywords(
        "10160074000", r"D:\paket\1. Dokumen Kualifikasi\1. Peserta"
    )
    assert "41012" in tokens
    assert "BG002" in tokens


def test_local_license_evidence_corrects_preview_fields(tmp_path, monkeypatch):
    sbu = tmp_path / "SBU BG002.pdf"
    ss = tmp_path / "SS BG002.pdf"
    sbu.write_bytes(b"pdf")
    ss.write_bytes(b"pdf")

    texts = {
        sbu.name: (
            "SERTIFIKAT BADAN USAHA (SBU) KONSTRUKSI "
            "PB-UMKU: 171224002517900010002 "
            "KBLI: 41012 - Konstruksi Gedung Perkantoran "
            "Masa Berlaku s.d. : 2028-01-09 Kecil BG002"
        ),
        ss.name: (
            "SERTIFIKAT STANDAR : 17122400251790015 "
            "Status : Telah terverifikasi"
        ),
    }
    monkeypatch.setattr(
        kualifikasi_parser,
        "_pdf_to_text",
        lambda path: texts[path.split("\\")[-1]],
    )
    data = {
        "sbu_nomor": "stale",
        "ss_nomor": "old",
        "sbu_tidak_sesuai": True,
        "ss_tidak_sesuai": True,
    }

    kualifikasi_parser._merge_local_license_evidence(
        data, str(tmp_path), ["41012", "BG002"]
    )

    assert data["sbu_nomor"] == "171224002517900010002"
    assert data["sbu_subklas_label"] == "BG002 - Konstruksi Gedung Perkantoran"
    assert data["sbu_berlaku"] == "9 Januari 2028"
    assert data["ss_nomor"] == "17122400251790015"
    assert data["ss_status"] == "Terverifikasi"
    assert data["sbu_tidak_sesuai"] is False
    assert data["ss_tidak_sesuai"] is False


def test_ms_tms_requires_verified_ss_and_matching_sbu():
    base = {
        "nib_nomor": "123",
        "ss_nomor": "456",
        "ss_terverifikasi": "Terverifikasi",
        "sbu_nomor": "789",
        "pengalaman": [{"nama": "Pekerjaan"}],
    }
    assert kk_evaluasi_engine._ms_tms(base) == "MS"
    assert kk_evaluasi_engine._ms_tms({**base, "ss_nomor": ""}) == "TMS"
    assert kk_evaluasi_engine._ms_tms({**base, "sbu_tidak_sesuai": True}) == "TMS"
