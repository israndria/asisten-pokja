"""Fix formula Tahun + BA Hasil di sheet @ Evaluasi semua BAPLJKK."""
import win32com.client, pythoncom
from pathlib import Path

POKJA_ROOT = Path("D:/Dokumen/@ POKJA 2026")
PL_ROOT = POKJA_ROOT / "@ Pejabat Pengadaan 2026/@ Pengadaan Langsung JKK"
DEV_TEMPLATE = POKJA_ROOT / "Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi/Development/0. BAPLJKK - Template.xlsm"

TARGETS = [DEV_TEMPLATE] + sorted(PL_ROOT.glob("*/0. BAPLJKK*.xlsm"))

FORMULAS = [
    (8,  3, '=RIGHT(C4,4)'),
    (14, 3, '=RIGHT(C10,4)'),
    (20, 3, '=RIGHT(C16,4)'),
    (30, 3, '=LEFT(C29,2)'),
    (31, 3, '=terbilang(C30)'),
    (32, 3, '=TRIM(MID(C29,4,FIND(" ",C29,4)-4))'),
]

def process_one(xl, target):
    wb = xl.Workbooks.Open(str(target))
    xl.DisplayAlerts = False
    try:
        ws = None
        for s in wb.Sheets:
            if s.Name == "@ Evaluasi":
                ws = s
                break
        if ws is None:
            print(f"  SKIP (tidak ada sheet @ Evaluasi)")
            return

        try:
            ws.Unprotect("pokja2026")
        except Exception:
            pass

        for row, col, formula in FORMULAS:
            ws.Cells(row, col).Formula = formula

        wb.Save()
        print(f"  SAVED")
    finally:
        try:
            wb.Close(SaveChanges=False)
        except Exception:
            pass

def main():
    pythoncom.CoInitialize()
    xl = None
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False

        for target in TARGETS:
            if not target.exists():
                print(f"SKIP: {target.name}")
                continue
            print(f"Processing: {target.name}")
            try:
                process_one(xl, target)
            except Exception as e:
                print(f"  ERROR: {e}")
    finally:
        try:
            if xl: xl.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    main()
