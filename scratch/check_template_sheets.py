import openpyxl
import os

tpl_path = r"d:\Dokumen\@ POKJA 2026\Paket Experiment\0. BAPK - Template.xlsm"
if os.path.exists(tpl_path):
    wb = openpyxl.load_workbook(tpl_path, read_only=True, keep_vba=True)
    print("Daftar Sheet di Template:")
    for name in wb.sheetnames:
        print(f"  - {name}")
    wb.close()
else:
    print("File template tidak ditemukan.")
