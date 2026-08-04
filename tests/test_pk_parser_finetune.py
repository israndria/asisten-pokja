"""Regression tests parser KAK/PK yang tidak memerlukan SPSE atau COM."""

import parse_kak_pl


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
