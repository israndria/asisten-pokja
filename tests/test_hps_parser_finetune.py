from decimal import Decimal

import hps_engine


def test_parse_official_hps_summary_from_edit_page():
    html = """
    <label>Nilai HPS</label><span>Rp. 313.292.000,00</span>
    """
    assert hps_engine._parse_official_hps_summary(html) == Decimal("313292000")


def test_parse_official_hps_summary_from_input_value():
    html = '<input type="text" name="nilai_hps" value="313292000">'
    assert hps_engine._parse_official_hps_summary(html) == Decimal("313292000")


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
