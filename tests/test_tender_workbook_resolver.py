from kualifikasi_engine import find_xlsm_paket


def test_find_xlsm_paket_handles_square_brackets_in_folder_name(tmp_path):
    folder = tmp_path / "11. [Pokja-057] Lanjutan Pembangunan"
    folder.mkdir()
    expected = folder / "0. BAPK - 057.xlsm"
    expected.write_bytes(b"")
    (folder / "catatan.txt").write_text("x", encoding="utf-8")

    assert find_xlsm_paket(str(folder)) == str(expected)
