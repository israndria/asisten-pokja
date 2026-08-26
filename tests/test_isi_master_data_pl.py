"""Regression gate resolver snapshot V2 untuk workflow PL."""

import isi_master_data_pl


def test_master_data_v2_resolver_uses_sibling_procurement_core(monkeypatch, tmp_path):
    code_base = tmp_path / "code"
    asisten_root = code_base / "Asisten_Pokja"
    core_root = code_base / "procurement_core"
    core_root.mkdir(parents=True)
    (core_root / "master_data_v2.py").write_text("# test module\n", encoding="utf-8")

    monkeypatch.setattr(
        isi_master_data_pl,
        "__file__",
        str(asisten_root / "isi_master_data_pl.py"),
    )
    monkeypatch.setenv("POKJA_CODE_ROOT", str(asisten_root))
    monkeypatch.delenv("POKJA_V19_ROOT", raising=False)

    assert isi_master_data_pl._find_master_data_v2_root() == str(core_root.resolve())


def test_master_data_v2_resolver_prefers_configured_v19_root(monkeypatch, tmp_path):
    configured_root = tmp_path / "procurement_core"
    configured_root.mkdir()
    (configured_root / "master_data_v2.py").write_text("# test module\n", encoding="utf-8")

    monkeypatch.setenv("POKJA_CODE_ROOT", str(tmp_path / "wrong"))
    monkeypatch.setenv("POKJA_V19_ROOT", str(configured_root))

    assert isi_master_data_pl._find_master_data_v2_root() == str(configured_root.resolve())
