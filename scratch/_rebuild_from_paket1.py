"""
Rebuild xlsm Paket 2-15 + Template yang rusak akibat openpyxl.
Strategi:
  - Base = Paket 1 (full structure: drawings, ctrlProps, sharedStrings, dll)
  - Patch sheet2.xml (@ Master Data) dari file rusak masing-masing paket
    (data @ Master Data masih ada di file rusak)
  - Hasilnya: struktur sama dengan Paket 1, data @ Master Data per paket

Paket 1 punya 15 sheet; semua target sebelumnya punya sheet yang sama
(DATABASE SBU 2022, DAFTAR SBU, 0. Data Nama Pokja & PPK ada di semua file).
"""
import zipfile, shutil, io, re
from pathlib import Path

POKJA_ROOT = Path("D:/Dokumen/@ POKJA 2026")
PL_ROOT    = POKJA_ROOT / "@ Pejabat Pengadaan 2026/@ Pengadaan Langsung JKK"
DEV        = POKJA_ROOT / "Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi/Development/0. BAPLJKK - Template.xlsm"
SOURCE     = PL_ROOT / "1. PLJKK - Konsultan Perencanaan Paket 1/0. BAPLJKK - Konsultan Perencanaan Paket 1.xlsm"

# Sheet2 di Paket 1 = @ Master Data (data Paket 1)
# Sheet2 di tiap target = @ Master Data (data paket masing-masing, masih ada di zip rusak)
MASTER_DATA_ENTRY = "xl/worksheets/sheet2.xml"

TARGETS = [DEV] + sorted(PL_ROOT.glob("*/0. BAPLJKK*.xlsm"))
TARGETS = [t for t in TARGETS if "Paket 1\\" not in str(t)]


def rebuild_xlsm(src_path: Path, dst_path: Path):
    """
    Buat file baru:
    - Semua entry dari src_path (Paket 1)
    - KECUALI sheet2.xml → ambil dari dst_path (@ Master Data target)
    """
    # Baca sheet2.xml dari dst (masih ada meski zip rusak)
    try:
        with zipfile.ZipFile(str(dst_path), "r") as zd:
            master_data_xml = zd.read(MASTER_DATA_ENTRY)
    except Exception as e:
        print(f"  WARN: Tidak bisa baca {MASTER_DATA_ENTRY} dari dst: {e}")
        print(f"  Fallback: pakai sheet2.xml dari Paket 1")
        master_data_xml = None

    tmp_path = dst_path.with_suffix(".rebuild_tmp")
    with zipfile.ZipFile(str(src_path), "r") as zs:
        with zipfile.ZipFile(str(tmp_path), "w", compression=zipfile.ZIP_DEFLATED) as zt:
            for item in zs.infolist():
                if item.filename == MASTER_DATA_ENTRY and master_data_xml is not None:
                    # Pakai @ Master Data dari target (data paket masing-masing)
                    zt.writestr(item, master_data_xml)
                else:
                    zt.writestr(item, zs.read(item.filename))

    dst_path.unlink()
    tmp_path.rename(dst_path)


def main():
    print(f"Source (base): {SOURCE.name}")
    if not SOURCE.exists():
        print("ERROR: Source tidak ditemukan!")
        return

    # Verify source valid
    with zipfile.ZipFile(str(SOURCE), "r") as z:
        n_entries = len(z.namelist())
        has_master = MASTER_DATA_ENTRY in z.namelist()
        print(f"  Source: {n_entries} entries, has sheet2: {has_master}")

    for target in TARGETS:
        if not target.exists():
            print(f"SKIP: {target.name} (tidak ada)")
            continue
        print(f"\nRebuild: {target.name}")
        try:
            rebuild_xlsm(SOURCE, target)
            # Verify
            with zipfile.ZipFile(str(target), "r") as zv:
                n = len(zv.namelist())
            print(f"  OK ({n} entries)")
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    print("\nSelesai — jalankan inject_pl.py setelah ini.")


if __name__ == "__main__":
    main()
