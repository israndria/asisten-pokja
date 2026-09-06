from decimal import Decimal

import hps_engine


def test_parse_hps_md_validates_code_and_rebuilds_boq(tmp_path):
    path = tmp_path / "_HPS_demo.md"
    path.write_text(
        """# DATA HPS — Demo
Kode Paket: `ABC123`
## RINGKASAN
- **Total Nilai**: Rp 1.234,50
- **Total Nilai Bulat**: Rp 1.235
## TABEL BoQ LENGKAP
No | Jenis B/J | Satuan | Vol | Harga | Pajak% | Total SPSE | Total Hitung | Selisih OK
---|---|---|---|---|---|---|---|---
1 | **DIVISI 1. UMUM** | - | - | - | - | - | - | -
2 | Mobilisasi | LS | 1 | Rp 1.234,50 | 0% | Rp 1.234,50 | Rp 1.234,50 | OK
""",
        encoding="utf-8",
    )
    result = hps_engine.parse_hps_md(str(path), expected_kode="ABC123")
    assert len(result["items"]) == 2
    assert result["items"][0]["is_divisi"] is True
    assert result["items"][1]["harga"] == 1234.5
    assert result["total_nilai_bulat"] == 1235.0
    assert result["nilai_hps_source"] == "local_hps_md_fallback"
    assert hps_engine.parse_hps_md(str(path), expected_kode="WRONG") == {}


def test_parse_amount_decimal_distinguishes_rupiah_thousands_and_cents():
    assert hps_engine._parse_amount_decimal("Rp 1.235") == Decimal("1235")
    assert hps_engine._parse_amount_decimal("Rp 1.234,50") == Decimal("1234.50")
    assert hps_engine._parse_amount_decimal("199984583.13") == Decimal("199984583.13")


def test_build_uraian_singkat_pk_uses_divisi_sentence_format(tmp_path):
    workbook = tmp_path / "91. PLPK - Rekonstruksi Jalan Desa Hiyung.xlsm"
    items = [
        {"jenis_bj": "DIVISI 1. UMUM", "is_divisi": True},
        {"jenis_bj": "DIVISI 3. PEKERJAAN TANAH DAN GEOSINTETIK", "is_divisi": True},
        {"jenis_bj": "DIVISI 7. STRUKTUR", "is_divisi": True},
        {"jenis_bj": "DIVISI 9. PEKERJAAN HARIAN & PEKERJAAN LAIN-LAIN", "is_divisi": True},
        {"jenis_bj": "DIVISI 9. PEKERJAAN HARIAN & PEKERJAAN LAIN-LAIN", "is_divisi": True},
    ]
    assert hps_engine._build_uraian_singkat_pk(items, str(workbook)) == (
        "Mengerjakan paket pekerjaan Rekonstruksi Jalan Desa Hiyung "
        "yaitu : DIVISI 1. UMUM, DIVISI 3. PEKERJAAN TANAH DAN GEOSINTETIK, "
        "DIVISI 7. STRUKTUR DAN DIVISI 9. PEKERJAAN HARIAN & PEKERJAAN LAIN-LAIN"
    )


def test_hps_markdown_preserves_cents(tmp_path):
    path = tmp_path / "0. BAPLPK- Uji.xlsm"
    result = {
        "items": [{
            "urutan": 1,
            "jenis_bj": "Mobilisasi",
            "satuan": "LS",
            "vol": 1.0,
            "harga": 1234.50,
            "pajak_pct": 0.0,
            "total_spse": 1234.50,
            "total_hitung": 1234.50,
            "is_divisi": False,
            "selisih": 0.0,
            "selisih_ok": True,
        }],
        "total_nilai": 1234.50,
        "total_nilai_bulat": 1234.50,
        "nilai_pagu": "Rp. 2.000,00",
    }
    md_path = hps_engine._tulis_hps_ke_md("ABC123", str(path), result)
    content = open(md_path, encoding="utf-8").read()
    assert "Rp 1.234,50" in content
    assert hps_engine.parse_hps_md(md_path, "ABC123")["total_nilai_bulat"] == 1234.5


def test_parse_official_hps_summary_from_edit_page():
    html = """
    <label>Nilai HPS</label><span>Rp. 313.292.000,00</span>
    """
    assert hps_engine._parse_official_hps_summary(html) == Decimal("313292000")


def test_parse_official_hps_summary_from_input_value():
    html = '<input type="text" name="nilai_hps" value="313292000">'
    assert hps_engine._parse_official_hps_summary(html) == Decimal("313292000")


def test_parse_official_hps_summary_preserves_cents():
    html = '<div>Nilai HPS Rp. 199.984.583,13</div>'
    assert hps_engine._parse_official_hps_summary(html) == Decimal("199984583.13")


def test_scrape_hps_pl_prefers_official_summary_and_preserves_raw_sum(monkeypatch):
    monkeypatch.setattr(
        hps_engine,
        "_fetch_hps_page_pl",
        lambda _kode: {
            "items": [
                {"item": "Pekerjaan", "unit": "ls", "vol": 1,
                 "harga": 313292323.48, "pajak": 0,
                 "total_harga": 313292323.48, "kbki": ""},
            ],
            "nilai_pagu": "Rp. 400.000.000,00",
            "nilai_hps_official": Decimal("313292000"),
        },
    )

    result = hps_engine.scrape_hps_pl("10975329000")

    assert result["total_nilai"] == 313292323.48
    assert result["total_nilai_bulat"] == 313292000.0
    assert result["nilai_hps"] == "Rp. 313.292.000,00"
    assert result["nilai_hps_source"] == "official_edit_page"


def test_scrape_hps_pl_fallback_rounding_is_explicit_and_not_ceil(monkeypatch):
    monkeypatch.setattr(
        hps_engine,
        "_fetch_hps_page_pl",
        lambda _kode: {
            "items": [
                {"item": "Pekerjaan", "unit": "ls", "vol": 1,
                 "harga": 10.49, "pajak": 0,
                 "total_harga": 10.49, "kbki": ""},
            ],
            "nilai_pagu": "",
        },
    )

    result = hps_engine.scrape_hps_pl("X")

    assert result["total_nilai"] == 10.49
    assert result["total_nilai_bulat"] == 10.0
    assert result["nilai_hps_source"] == "line_item_sum_rounded_fallback"


def test_scrape_hps_pl_retries_transient_empty_page(monkeypatch):
    responses = [
        {"items": [], "nilai_pagu": ""},
        {"items": [], "nilai_pagu": ""},
        {
            "items": [
                {
                    "item": "Pekerjaan",
                    "unit": "ls",
                    "vol": 1,
                    "harga": 100,
                    "pajak": 0,
                    "total_harga": 100,
                    "kbki": "",
                }
            ],
            "nilai_pagu": "",
        },
    ]
    calls = []

    def fake_fetch(_kode):
        calls.append(True)
        return responses.pop(0)

    monkeypatch.setattr(hps_engine, "_fetch_hps_page_pl", fake_fetch)
    monkeypatch.setattr(hps_engine.time, "sleep", lambda _seconds: None)

    result = hps_engine.scrape_hps_pl("X")

    assert len(calls) == 3
    assert len(result["items"]) == 1
