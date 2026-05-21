"""
Setup sheet "6. Penawaran" di template Development dan copy ke Paket 1.

Sheet sudah ada di Paket 1 (dibuat manual user) — perlu:
1. Set header baris 1 (9 kolom)
2. Format kolom angka
3. Copy sheet ke template Development
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win32com.client
import pythoncom
from pathlib import Path

POKJA_ROOT = Path("D:/Dokumen/@ POKJA 2026")

TARGETS = [
    POKJA_ROOT / "@ Pejabat Pengadaan 2026/@ Pengadaan Langsung JKK/1. PLJKK - Konsultan Perencanaan Paket 1/0. BAPLJKK - Konsultan Perencanaan Paket 1.xlsm",
    POKJA_ROOT / "Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi/Development/0. BAPLJKK - Template.xlsm",
]

HEADERS = [
    "No", "Jenis Barang/Jasa", "Satuan", "Volume",
    "Harga/Biaya Satuan (Rp)", "Total sebelum Pajak (Rp)",
    "Pajak (%)", "Total setelah Pajak (Rp)", "Keterangan / Selisih HPS"
]

SHEET_NAME = "6. Penawaran"


def setup_sheet(wb, source_wb=None):
    """Setup sheet '6. Penawaran' di workbook wb. Jika source_wb diberikan, copy dari sana."""
    vb = None

    # Cek apakah sheet sudah ada
    ws = None
    for s in wb.Sheets:
        if s.Name == SHEET_NAME:
            ws = s
            break

    if ws is None:
        # Tambah sheet baru di akhir
        ws = wb.Sheets.Add(After=wb.Sheets(wb.Sheets.Count))
        ws.Name = SHEET_NAME
        print(f"  Sheet '{SHEET_NAME}' dibuat baru")
    else:
        print(f"  Sheet '{SHEET_NAME}' sudah ada")

    # Unprotect
    try:
        ws.Unprotect("pokja2026")
    except Exception:
        pass

    # Baris 1: header
    for col, hdr in enumerate(HEADERS, start=1):
        cell = ws.Cells(1, col)
        cell.Value = hdr
        cell.Font.Bold = True
        cell.Interior.Color = 0x4472C4  # biru
        cell.Font.Color = 0xFFFFFF      # putih
        cell.WrapText = True

    # Set lebar kolom
    COL_WIDTHS = [5, 40, 12, 10, 18, 22, 10, 22, 25]
    for col, w in enumerate(COL_WIDTHS, start=1):
        ws.Columns(col).ColumnWidth = w

    # Row 1 tinggi
    ws.Rows(1).RowHeight = 30

    # Format kolom angka (E,F,H = currency; D = number; G = percent-style)
    CURRENCY_COLS = [5, 6, 8]
    for c in CURRENCY_COLS:
        ws.Columns(c).NumberFormat = '#,##0.00'
    ws.Columns(4).NumberFormat = '#,##0.00'
    ws.Columns(7).NumberFormat = '#,##0.00'

    print(f"  Header & format OK")
    return ws


def main():
    pythoncom.CoInitialize()
    excel = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        for target in TARGETS:
            if not target.exists():
                print(f"SKIP (tidak ada): {target}")
                continue
            print(f"\nProcessing: {target.name}")
            wb = excel.Workbooks.Open(str(target))
            try:
                setup_sheet(wb)
                wb.Save()
                print(f"  SAVED")
            except Exception as e:
                print(f"  ERROR: {e}")
            finally:
                wb.Close(SaveChanges=False)

    finally:
        try:
            if excel:
                excel.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
