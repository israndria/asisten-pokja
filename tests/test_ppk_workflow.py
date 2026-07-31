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


def test_missing_family_is_ambiguous_not_guessed_from_name():
    result = engine.resolve_ppk_workflow({"nama_paket": "Pembangunan Pagar Pasar"})
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
