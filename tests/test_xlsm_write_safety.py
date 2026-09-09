"""Guard regresi agar writer .xlsm tidak menyimpan cache UDF saat macro mati."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_xlsm_writers_enable_udf_and_disable_events_before_open():
    for relative in (
        "hasil_evaluasi_pl_engine.py",
        "hasil_evaluasi_plpk_engine.py",
        "hps_engine.py",
        "isi_master_data_pl.py",
        "penawaran_pl_engine.py",
        "pl_ui_helpers.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "AutomationSecurity = 1" in source, relative
        assert "EnableEvents = False" in source, relative


def test_no_production_writer_forces_recalc_with_macro_disabled():
    for relative in (
        "hasil_evaluasi_pl_engine.py",
        "hasil_evaluasi_plpk_engine.py",
        "hps_engine.py",
        "isi_master_data_pl.py",
        "penawaran_pl_engine.py",
        "pl_ui_helpers.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "AutomationSecurity = 3" not in source, relative


def test_penawaran_writer_preserves_rows_and_uses_scoped_recalculation():
    source = (ROOT / "penawaran_pl_engine.py").read_text(encoding="utf-8")

    assert 'ws.Range(f"A2:I{last_row}").ClearContents()' in source
    assert 'ws.Rows(f"2:{last_row}").Delete()' not in source
    assert "wb.Calculate()" not in source
    assert '("7.2 Dengan Nego", "A1:AL42")' in source
