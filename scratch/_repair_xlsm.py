"""
Repair xlsm yang corrupt karena openpyxl: buka via COM → SaveAs ke path yang sama → inject ulang.
Excel akan repair struktur VBA saat buka file.
"""
import win32com.client, pythoncom, os, time
from pathlib import Path

POKJA_ROOT = Path("D:/Dokumen/@ POKJA 2026")
PL_ROOT    = POKJA_ROOT / "@ Pejabat Pengadaan 2026/@ Pengadaan Langsung JKK"
DEV        = POKJA_ROOT / "Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi/Development/0. BAPLJKK - Template.xlsm"

TARGETS = [DEV] + sorted(PL_ROOT.glob("*/0. BAPLJKK*.xlsm"))
TARGETS = [t for t in TARGETS if "Paket 1\\" not in str(t)]

def main():
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False

    for target in TARGETS:
        if not target.exists():
            print(f"SKIP: {target.name}")
            continue
        print(f"Repair: {target.name}")
        try:
            wb = xl.Workbooks.Open(str(target.resolve()), CorruptLoad=2)  # xlRepairFile=2
            xl.DisplayAlerts = False
            # SaveAs dengan format xlsm (52)
            xl_format = 52  # xlOpenXMLWorkbookMacroEnabled
            wb.SaveAs(str(target.resolve()), FileFormat=xl_format)
            wb.Close(SaveChanges=False)
            print(f"  OK")
        except Exception as e:
            print(f"  ERROR: {e}")
            try:
                xl.ActiveWorkbook.Close(SaveChanges=False)
            except Exception:
                pass
        time.sleep(0.5)

    xl.Quit()
    pythoncom.CoUninitialize()
    print("Selesai.")

if __name__ == "__main__":
    main()
