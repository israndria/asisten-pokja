"""
Restore vbaProject.bin dari Paket 1 ke semua file xlsm yang corrupt karena openpyxl.
xlsm = zip. Ganti xl/vbaProject.bin dari source yang valid.
Setelah restore → inject_pl.py bisa jalan lagi.
"""
import zipfile, shutil, os
from pathlib import Path
import io

POKJA_ROOT = Path("D:/Dokumen/@ POKJA 2026")
PL_ROOT    = POKJA_ROOT / "@ Pejabat Pengadaan 2026/@ Pengadaan Langsung JKK"
DEV        = POKJA_ROOT / "Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi/Development/0. BAPLJKK - Template.xlsm"
SOURCE     = PL_ROOT / "1. PLJKK - Konsultan Perencanaan Paket 1/0. BAPLJKK - Konsultan Perencanaan Paket 1.xlsm"

TARGETS = [DEV] + sorted(PL_ROOT.glob("*/0. BAPLJKK*.xlsm"))
TARGETS = [t for t in TARGETS if "Paket 1\\" not in str(t)]

VBA_ENTRY = "xl/vbaProject.bin"


def patch_xlsm(src_path: Path, dst_path: Path):
    """Copy vbaProject.bin dari src ke dst (in-place via temp)."""
    # Baca vbaProject.bin dari source
    with zipfile.ZipFile(str(src_path), "r") as zs:
        vba_bin = zs.read(VBA_ENTRY)

    # Patch dst: ganti entry VBA_ENTRY
    tmp_path = dst_path.with_suffix(".tmp_xlsm")
    with zipfile.ZipFile(str(dst_path), "r") as zd:
        with zipfile.ZipFile(str(tmp_path), "w", compression=zipfile.ZIP_DEFLATED) as zt:
            for item in zd.infolist():
                if item.filename == VBA_ENTRY:
                    zt.writestr(item, vba_bin)
                else:
                    zt.writestr(item, zd.read(item.filename))

    # Replace
    dst_path.unlink()
    tmp_path.rename(dst_path)


def main():
    print(f"Source VBA: {SOURCE.name}")
    # Verify source valid
    try:
        with zipfile.ZipFile(str(SOURCE), "r") as z:
            names = z.namelist()
            if VBA_ENTRY not in names:
                print(f"ERROR: {VBA_ENTRY} tidak ada di source")
                return
            print(f"  vbaProject.bin = {len(z.read(VBA_ENTRY))} bytes")
    except Exception as e:
        print(f"ERROR membuka source: {e}")
        return

    for target in TARGETS:
        if not target.exists():
            print(f"SKIP: {target.name}")
            continue
        print(f"Patch: {target.name}")
        try:
            patch_xlsm(SOURCE, target)
            print(f"  OK")
        except Exception as e:
            print(f"  ERROR: {e}")

    print("Selesai — jalankan inject_pl.py setelah ini.")


if __name__ == "__main__":
    main()
