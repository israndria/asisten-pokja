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
