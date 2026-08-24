import pindah_penawaran_engine as engine


def test_build_package_status_keeps_packages_without_apendo_source(tmp_path, monkeypatch):
    tender_root = tmp_path / "tender"
    apendo_root = tmp_path / "biddings"
    tender_root.mkdir()
    apendo_root.mkdir()
    monkeypatch.setattr(engine, "TENDER_ROOT", str(tender_root))
    monkeypatch.setattr(engine, "APENDO_ROOT", str(apendo_root))

    (tender_root / "041").mkdir()
    (tender_root / "045").mkdir()
    (tender_root / "046").mkdir()
    output = tender_root / "041" / engine.DEST_SUBFOLDER
    output.mkdir(parents=True)
    (output / "penawaran.pdf").write_bytes(b"pdf")
    output_existing = tender_root / "046" / engine.DEST_SUBFOLDER
    output_existing.mkdir(parents=True)
    (output_existing / "doktek.pdf").write_bytes(b"pdf")

    rows = [
        {"kode_tender": "041", "folder_dibuat": "041", "nama_tender": "Paket 041"},
        {"kode_tender": "045", "folder_dibuat": "045", "nama_tender": "Paket 045"},
        {"kode_tender": "046", "folder_dibuat": "046", "nama_tender": "Paket 046"},
    ]
    scanned = [
        {
            "kode_tender": "041",
            "folder_paket": str(tender_root / "041"),
            "peserta_id": "p1",
        }
    ]

    result = {row["kode_tender"]: row for row in engine.build_package_status(rows, scanned)}

    assert result["041"]["status_key"] == "source_ready"
    assert result["041"]["peserta_count"] == 1
    assert result["041"]["output_file_count"] == 1
    assert result["045"]["status_key"] == "source_missing"
    assert "D:\\data\\biddings" in result["045"]["status_detail"]
    assert result["046"]["status_key"] == "output_present"


def test_build_package_status_distinguishes_incomplete_apendo_folder(tmp_path, monkeypatch):
    tender_root = tmp_path / "tender"
    apendo_root = tmp_path / "biddings"
    (tender_root / "045").mkdir(parents=True)
    (apendo_root / "795177" / "045").mkdir(parents=True)
    monkeypatch.setattr(engine, "TENDER_ROOT", str(tender_root))
    monkeypatch.setattr(engine, "APENDO_ROOT", str(apendo_root))

    result = engine.build_package_status(
        [{"kode_tender": "045", "folder_dibuat": "045"}], []
    )[0]

    assert result["status_key"] == "source_incomplete"
    assert result["apendo_dirs"] == [str(apendo_root / "795177" / "045")]


def test_scan_apendo_returns_only_participants_with_technical_files(tmp_path, monkeypatch):
    apendo_root = tmp_path / "biddings"
    good = apendo_root / "795177" / "041" / "peserta-1" / "unpacked"
    (good / engine.TEKNIS_DIR).mkdir(parents=True)
    (good / engine.HARGA_DIR).mkdir()
    (good / engine.TEKNIS_DIR / "teknis.pdf").write_bytes(b"pdf")
    (good / engine.HARGA_DIR / "harga.pdf").write_bytes(b"pdf")
    bad = apendo_root / "795177" / "041" / "peserta-2" / "unpacked"
    (bad / engine.TEKNIS_DIR).mkdir(parents=True)
    monkeypatch.setattr(engine, "APENDO_ROOT", str(apendo_root))

    result = engine.scan_apendo()

    assert len(result) == 1
    assert result[0]["peserta_id"] == "peserta-1"
    assert result[0]["path_harga"].endswith(engine.HARGA_DIR)
