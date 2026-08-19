from pl_ui_helpers import plan_nomor_folder_pl


def test_backup_number_wins_over_stale_database_number(tmp_path):
    root = tmp_path / "pk"
    backup = root / "backup"
    (backup / "35. PLPK - Pengaspalan Jalan Lingkungan Rt. 01 Desa Lumbu").mkdir(parents=True)

    result = plan_nomor_folder_pl(
        [{
            "kode_paket": "paket-35",
            "nama_paket": "Pengaspalan Jalan Lingkungan Rt. 01 Desa Lumbu Raya",
            "jenis_pl": "PK",
            "nomor_urut": "72",
        }],
        (str(root),),
    )

    planned = result["assignments"]["paket-35"]
    assert planned["nomor_urut"] == 35
    assert planned["source"] == "backup"
    assert result["conflicts"] == []


def test_new_number_skips_active_backup_and_quarantine_numbers(tmp_path):
    root = tmp_path / "pk"
    (root / "59. PLPK - Paket Aktif").mkdir(parents=True)
    (root / "backup" / "35. PLPK - Paket Arsip").mkdir(parents=True)
    (root / "backup" / "_duplikat_72_77" / "72. PLPK - Duplikat").mkdir(parents=True)

    result = plan_nomor_folder_pl(
        [{
            "kode_paket": "paket-baru",
            "nama_paket": "Paket Baru",
            "jenis_pl": "PK",
        }],
        (str(root),),
    )

    planned = result["assignments"]["paket-baru"]
    assert planned["nomor_urut"] == 60
    assert planned["source"] == "baru"


def test_clean_pk_reset_ignores_backup_and_stale_database_numbers(tmp_path):
    root = tmp_path / "pk"
    jkk_root = tmp_path / "jkk"
    for number in (28, 29, 30):
        (root / f"{number}. PLPK - Paket Aktif {number}").mkdir(parents=True)
    (jkk_root / "71. PLJKK - Paket Aktif").mkdir(parents=True)
    (root / "backup" / "35. PLPK - Paket Lama 1").mkdir(parents=True)
    (root / "backup" / "36. PLPK - Paket Lama 2").mkdir(parents=True)

    rows = [
        {"kode_paket": f"paket-{i}", "nama_paket": f"Paket Baru {i}", "jenis_pl": "PK", "nomor_urut": str(72 + i)}
        for i in range(3)
    ]
    result = plan_nomor_folder_pl(
        rows,
        (str(jkk_root), str(root)),
        use_backup=False,
        use_database=False,
        start_number=35,
        allocation_base=str(root),
    )

    planned = [result["assignments"][row["kode_paket"]] for row in rows]
    assert [item["nomor_urut"] for item in planned] == [35, 36, 37]
    assert all(item["source"] == "baru" for item in planned)


def test_reset_request_falls_back_after_new_pk_folder_exists(tmp_path):
    root = tmp_path / "pk"
    for number in (28, 29, 30, 35):
        (root / f"{number}. PLPK - Paket Aktif {number}").mkdir(parents=True)
    (root / "backup" / "36. PLPK - Paket Lama").mkdir(parents=True)

    result = plan_nomor_folder_pl(
        [{"kode_paket": "paket-baru", "nama_paket": "Paket Baru", "jenis_pl": "PK", "nomor_urut": "72"}],
        (str(root),),
        use_backup=False,
        use_database=False,
        start_number=35,
        allocation_base=str(root),
    )

    planned = result["assignments"]["paket-baru"]
    assert planned["nomor_urut"] == 72
    assert planned["source"] == "database"
