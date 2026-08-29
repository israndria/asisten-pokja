"""Regression tests parser KAK/PK yang tidak memerlukan SPSE atau COM."""

import parse_kak_pl
import isi_master_data_pl


def test_pk_kak_extracts_ppk_from_heading_without_label():
    text = """PEJABAT PEMBUAT KOMITMEN
H. M. ZAINNOOR WALADI RAKHMAT, M.Pd
NIP. 19701202 199903 1 003
PROGRAM
"""
    assert parse_kak_pl._extract_nama_ppk(text) == "H. M. ZAINNOOR WALADI RAKHMAT, M.Pd"


def test_pk_kak_extracts_duration_and_technical_role():
    text = """18. Jangka Waktu
Jangka waktu pelaksanaan adalah 90 (Sembilan Puluh) hari kalender.
20. Kebutuhan Personel Minimal
Pelaksana Lapangan (1 Orang) SKK Pelaksana Bangunan Gedung
2 Petugas K3 Konstruksi
21. Persyaratan
"""
    assert parse_kak_pl._extract_jangka_waktu(text) == "90 hari kalender"
    assert parse_kak_pl._extract_jabatan_teknis(text) == "Pelaksana Lapangan"


def test_location_parser_ignores_incidental_word_location():
    text = """Uraian pekerjaan sesuai kondisi lokasi serta dokumen teknis.
4. Lokasi Kegiatan Kecamatan Binuang, Kabupaten Tapin.
5. Sumber Pendanaan APBD.
"""
    assert parse_kak_pl._extract_lokasi(text) == "Kecamatan Binuang, Kabupaten Tapin"


def test_cari_kak_does_not_choose_root_draft_or_hps(tmp_path):
    (tmp_path / "Draft_PL_Paket.pdf").write_bytes(b"not kak")
    (tmp_path / "_HPS_Paket.pdf").write_bytes(b"not kak")
    kak_dir = tmp_path / "1. KAK & Spesifikasi Teknis"
    kak_dir.mkdir()
    expected = kak_dir / "1. KAK.pdf"
    expected.write_bytes(b"kak")

    assert parse_kak_pl.cari_kak_di_folder(str(tmp_path)) == str(expected)


def test_pk_kak_duration_ignores_maintenance_and_shortest_activity():
    text = """KEGIATAN
PENYELENGGARAAN JALAN KABUPATEN/KOTA
SUB KEGIATAN PENYELENGGARAAN JALAN KABUPATEN/KOTA
Pelaksanaan kegiatan dilakukan selama 90 hari kalender.
Masa Pemeliharaan 180 hari kalender.
"""
    assert parse_kak_pl._extract_jangka_waktu(text) == "90 hari kalender"
    assert parse_kak_pl._extract_sub_kegiatan_dari_kak(text) == "PENYELENGGARAAN JALAN KABUPATEN/KOTA"


def test_pk_sbu_fallback_uses_kak_filename_context():
    road = parse_kak_pl._extract_sbu("Jalan dan jembatan sebagai prasarana umum", "KAK Peningkatan Jalan Gang.pdf")
    bridge = parse_kak_pl._extract_sbu("Jalan dan jembatan sebagai prasarana umum", "KAK Pembangunan Jembatan Box.pdf")
    assert "BS001" in road[0]
    assert "BS002" in bridge[0]


def test_draft_contract_parser_prefers_explicit_contract_label(monkeypatch):
    monkeypatch.setattr(
        parse_kak_pl,
        "_text_dari_pdf",
        lambda _path: "JENIS KONTRAK:  Harga Satuan\n1.13 Kontrak Gabungan Lumsum dan Harga",
    )
    assert parse_kak_pl.parse_jenis_kontrak_dari_draft_pl("draft.pdf") == "Harga Satuan"


def test_draft_contract_parser_normalizes_tender_combined_label(monkeypatch):
    monkeypatch.setattr(
        parse_kak_pl,
        "_text_dari_pdf",
        lambda _path: "JENIS KONTRAK: Gabungan Lumsum dan Harga Satuan",
    )
    assert parse_kak_pl.parse_jenis_kontrak_dari_draft_pl("draft.pdf") == "Harga Satuan"


def test_k3_certificate_normalizer_keeps_clear_skk_and_falls_back_otherwise():
    assert isi_master_data_pl._normalize_k3_certificate(
        "SKK Petugas K3 Konstruksi (Jenjang 3)"
    ) == "SKK Petugas K3 Konstruksi (Jenjang 3)"
    assert isi_master_data_pl._normalize_k3_certificate("Sertifikat K3") == (
        "SKK Petugas K3 Konstruksi / Keselamatan Konstruksi"
    )
