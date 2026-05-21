"""
Copy sheet dari Paket 1 ke semua target (template + paket 2-15).
Kecuali: @ Master Data, _DraftPaketPLList, _DraftPaketList,
         DATABASE SBU 2022, DAFTAR SBU, 0. Data Nama Pokja & PPK
"""
import sys, io
import win32com.client, pythoncom
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

POKJA_ROOT = Path("D:/Dokumen/@ POKJA 2026")
PL_ROOT    = POKJA_ROOT / "@ Pejabat Pengadaan 2026/@ Pengadaan Langsung JKK"
DEV        = POKJA_ROOT / "Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi/Development/0. BAPLJKK - Template.xlsm"
SOURCE     = PL_ROOT / "1. PLJKK - Konsultan Perencanaan Paket 1/0. BAPLJKK - Konsultan Perencanaan Paket 1.xlsm"

SKIP = {"@ Master Data","_DraftPaketPLList","_DraftPaketList",
        "DATABASE SBU 2022","DAFTAR SBU","0. Data Nama Pokja & PPK"}

SHEETS_TO_COPY = ["@ Evaluasi","satu_data","5. HPS","6. Penawaran",
                  "database_reviu","database_dokpil","7.2 Dengan Nego",
                  "list_reviu","list_dokpil"]

TARGETS = [DEV] + sorted(PL_ROOT.glob("*/0. BAPLJKK*.xlsm"))
TARGETS = [t for t in TARGETS if "Paket 1\\" not in str(t)]

def main():
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False

    print(f"Source: {SOURCE.name}")
    src = xl.Workbooks.Open(str(SOURCE))

    for target in TARGETS:
        if not target.exists():
            print(f"SKIP: {target.name}")
            continue
        print(f"\nProcessing: {target.name}")
        dst = xl.Workbooks.Open(str(target))
        xl.DisplayAlerts = False
        ok = err = 0
        for sh in SHEETS_TO_COPY:
            # Hapus sheet lama di dst
            for s in list(dst.Sheets):
                if s.Name == sh:
                    try:
                        s.Delete()
                    except Exception:
                        pass
                    break
            # Copy dari src setelah sheet terakhir dst
            try:
                after = dst.Sheets(dst.Sheets.Count)
                src.Sheets(sh).Copy(After=after)
                print(f"  OK: {sh}")
                ok += 1
            except Exception as e:
                print(f"  ERR {sh}: {e}")
                err += 1

        dst.Save()
        dst.Close(SaveChanges=False)
        print(f"  => SAVED ({ok} OK, {err} err)")

    src.Close(False)
    xl.Quit()
    pythoncom.CoUninitialize()
    print("\nSelesai.")

if __name__ == "__main__":
    main()
