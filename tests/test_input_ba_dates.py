from datetime import date, datetime

import pytest

import input_ba_engine


@pytest.mark.parametrize(
    "value, expected",
    [
        (date(2026, 8, 26), date(2026, 8, 26)),
        (datetime(2026, 8, 26, 21, 45), date(2026, 8, 26)),
        ("2026-08-26", date(2026, 8, 26)),
        ("2026-08-26T21:45:00+08:00", date(2026, 8, 26)),
        ("26 Agustus 2026", date(2026, 8, 26)),
        ("26 August 2026", date(2026, 8, 26)),
        (46260, date(2026, 8, 26)),
    ],
)
def test_coerce_tanggal_accepts_parser_date_boundaries(value, expected):
    assert input_ba_engine._coerce_tanggal(value) == expected


def test_excel_serial_tanggal_is_numeric_and_stable():
    assert input_ba_engine._excel_serial_tanggal(date(2026, 8, 26)) == 46260
    assert isinstance(input_ba_engine._excel_serial_tanggal("26/08/2026"), int)


def test_invalid_date_is_rejected_before_writing_text_to_excel():
    with pytest.raises(ValueError, match="Tanggal tidak valid"):
        input_ba_engine._excel_serial_tanggal("tanggal tidak dikenal")
