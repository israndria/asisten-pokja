"""Regression gate folder lokal/workbook untuk daftar operasional PL."""

import parse_kak_pl
import pl_engine
import pl_ui_helpers
from pl_data_ui import filter_local_pl_rows


def test_provider_sync_private_alias_matches_canonical_helper():
    assert (
        pl_ui_helpers._sinkronkan_identitas_penyedia_pl
        is pl_ui_helpers.sinkronkan_identitas_penyedia_pl
    )


def test_row_without_local_folder_is_hidden(monkeypatch, tmp_path):
    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (None, ""),
    )

    rows = [{
        "kode_paket": "PK-NO-FOLDER",
        "nama_paket": "Paket belum dibuat",
        "jenis_pl": "PK",
        "folder_dibuat": None,
    }]

    assert filter_local_pl_rows(rows) == []


def test_physical_folder_and_workbook_are_authoritative(monkeypatch, tmp_path):
    folder = tmp_path / "13. PLPK - Paket Fisik"
    folder.mkdir()
    workbook = folder / "0. BAPLPK - Paket Fisik.xlsm"
    workbook.write_bytes(b"placeholder")

    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(folder), "13"),
    )
    monkeypatch.setattr(
        pl_ui_helpers,
        "_cari_xlsm_pl",
        lambda candidate: str(workbook) if candidate == str(folder) else None,
    )

    row = {
        "kode_paket": "PK-FISIK",
        "nama_paket": "Paket fisik",
        "jenis_pl": "PK",
        # DB status boleh stale/kosong; disk tetap sumber gate.
        "folder_dibuat": None,
    }

    result = filter_local_pl_rows([row])

    assert len(result) == 1
    assert result[0]["_folder_lokal"] == str(folder)
    assert result[0]["_xlsm_lokal"] == str(workbook)


def test_folder_without_workbook_is_hidden(monkeypatch, tmp_path):
    folder = tmp_path / "14. PLPK - Tanpa Workbook"
    folder.mkdir()

    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(folder), "14"),
    )
    monkeypatch.setattr(pl_ui_helpers, "_cari_xlsm_pl", lambda _candidate: None)

    row = {
        "kode_paket": "PK-NO-XLSM",
        "nama_paket": "Paket tanpa workbook",
        "jenis_pl": "PK",
        "folder_dibuat": True,
    }

    assert filter_local_pl_rows([row]) == []


def test_stale_number_cannot_resolve_other_package(monkeypatch, tmp_path):
    other_folder = tmp_path / "15. PLPK - Paket Lain"
    other_folder.mkdir()
    other_workbook = other_folder / "0. BA Paket Lain.xlsm"
    other_workbook.write_bytes(b"placeholder")

    def fake_resolve(_nomor, _nama, _jenis, *, is_ulang=False, strict_name=False):
        assert strict_name is True
        return (None, "")

    monkeypatch.setattr(parse_kak_pl, "_resolve_folder_pl", fake_resolve)
    monkeypatch.setattr(
        pl_ui_helpers,
        "_cari_xlsm_pl",
        lambda _candidate: str(other_workbook),
    )

    row = {
        "kode_paket": "PK-STALE-NUMBER",
        "nama_paket": "Paket yang belum dibuat",
        "jenis_pl": "PK",
        "nomor_urut": "15",
        "folder_dibuat": True,
    }

    assert filter_local_pl_rows([row]) == []


def test_strict_resolver_accepts_officially_truncated_folder(monkeypatch, tmp_path):
    root = tmp_path / "pk"
    root.mkdir()
    package_name = "Belanja Modal Bangunan Gedung Pertokoan Koperasi Pasar Pembangunan Gapura Pintu Gerbang Pasar Binuang Jalan Bay Pass"
    full_name = f"28. PLPK - {package_name}"
    truncated_name = pl_engine.truncate_nama_folder(str(root), full_name)
    folder = root / truncated_name
    folder.mkdir()

    import config

    monkeypatch.setattr(config, "OUTPUT_DIR_PL_PK", str(root))

    resolved, number = parse_kak_pl._resolve_folder_pl(
        28,
        package_name,
        "PK",
        strict_name=True,
    )

    assert resolved == str(folder)
    assert number == "28"
