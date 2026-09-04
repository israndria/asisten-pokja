"""Regression tests for source-faithful NPWP handling in PL parsers."""

from kualifikasi_parser import _normalize_npwp_source
from kualifikasi_parser_pl import parse_peserta_lengkap_pl


def test_normalize_npwp_preserves_source_format_and_leading_zero():
    assert _normalize_npwp_source(" 39.162.267.7-733.000\n") == "39.162.267.7-733.000"
    assert _normalize_npwp_source("0018756072733000") == "0018756072733000"


def test_normalize_npwp_rejects_missing_or_malformed_identity():
    assert _normalize_npwp_source("") == ""
    assert _normalize_npwp_source("-") == ""
    assert _normalize_npwp_source("39.162.267") == ""
    assert _normalize_npwp_source("NPWP 39.162.267.7-733.000") == ""


def test_pl_parser_prefers_preview_npwp_over_pdf_ocr(monkeypatch):
    monkeypatch.setattr(
        "kualifikasi_parser_pl.parse_preview_html_pl",
        lambda _id: {"ok": True, "nama": "CV. Contoh", "npwp": "0018756072733000"},
    )
    monkeypatch.setattr(
        "kualifikasi_parser_pl._parse_pq_pdf",
        lambda _folder: {"direktur": "", "npwp_pdf": "01.875.607.2-733.000", "bidang_pengalaman": []},
    )
    monkeypatch.setattr("kualifikasi_parser_pl.get_kswp_status_pl", lambda *_args: "VALID")
    monkeypatch.setattr(
        "kualifikasi_parser_pl.get_kinerja",
        lambda _folder: {"ada": False, "nilai": "-", "kategori": "-"},
    )
    monkeypatch.setattr(
        "kualifikasi_parser_pl.get_skp",
        lambda _folder, _jp: {"skp": 5, "jp": 0, "catatan": "", "berbeda": False},
    )

    result = parse_peserta_lengkap_pl("peserta-1", "")

    assert result["npwp"] == "0018756072733000"
