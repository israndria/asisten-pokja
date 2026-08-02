import ppk_upload_engine as engine


def test_resolve_jkk_from_explicit_metadata_even_if_name_mentions_konstruksi():
    result = engine.resolve_ppk_workflow({
        "nama_paket": "Jasa Pengawasan Konstruksi Jalan",
        "jenis_pengadaan": "Jasa Konsultansi",
    })
    assert result["workflow"] == "JKK"
    assert result["status"] == "resolved"


def test_resolve_pk_from_explicit_metadata():
    result = engine.resolve_ppk_workflow({"jenis_pekerjaan": "Pekerjaan Konstruksi"})
    assert result["workflow"] == "PK"


def test_family_falls_back_to_construction_name_when_metadata_is_missing():
    result = engine.resolve_ppk_workflow({"nama_paket": "Pembangunan Pagar Pasar"})
    assert result == {"status": "resolved", "workflow": "PK", "source": "name_fallback"}


def test_family_falls_back_to_consultancy_name_when_metadata_is_missing():
    result = engine.resolve_ppk_workflow({"nama_paket": "Jasa Konsultansi Pengawasan Jalan"})
    assert result == {"status": "resolved", "workflow": "JKK", "source": "name_fallback"}


def test_goods_name_remains_unresolved_for_ppk_family_modes():
    result = engine.resolve_ppk_workflow({"nama_paket": "Belanja Barang untuk Dijual"})
    assert result == {"status": "ambiguous", "workflow": None, "source": "metadata_missing"}


def test_pk_mapping_does_not_inherit_consultancy_files():
    mapping = engine.ppk_workflow_config("PK")["mapping"]
    assert "3." in mapping
    assert "4." not in mapping
    assert "5." not in mapping
    assert "6." not in mapping


def test_auto_match_folder_accepts_workflow_argument():
    assert engine.auto_match_folder(
        "Pagar Pasar Binuang", ["28. Pagar Pasar Binuang"], workflow="PK"
    ) == "28. Pagar Pasar Binuang"


def test_ppk_modes_are_bound_to_distinct_families():
    assert engine.ppk_mode_config("PPK - Konsultan")["workflow"] == "JKK"
    assert engine.ppk_mode_config("PPK - Pekerjaan Konstruksi")["workflow"] == "PK"


def test_filter_ppk_packages_uses_metadata_then_name_fallback():
    rows = [
        {"kode_paket": "1", "nama_paket": "Pembangunan Pagar"},
        {"kode_paket": "2", "nama_paket": "Jasa Perencanaan"},
        {"kode_paket": "3", "nama_paket": "Nama Tidak Menentukan Family"},
    ]
    details = {
        "1": {"jenis_pengadaan": "Pekerjaan Konstruksi"},
        "2": {"jenis_pengadaan": "Jasa Konsultansi"},
    }
    assert [
        row["kode_paket"]
        for row in engine.filter_paket_ppk_by_workflow(rows, "PK", details)
    ] == ["1"]
    assert [
        row["kode_paket"]
        for row in engine.filter_paket_ppk_by_workflow(rows, "JKK", details)
    ] == ["2"]
    assert [
        row["kode_paket"]
        for row in engine.filter_paket_ppk_by_workflow(rows, "PK", {})
    ] == ["1"]
