import pdfplumber
import os

path = r"D:\Dokumen\@ POKJA 2026\10. Pokja 034 - Normalisasi Dan Penambahan Alur Sei. Bahari Ds. Sawaja Kec. CLU\RK3K Rev.pdf"
if os.path.exists(path):
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            print(f"--- PAGE {i+1} ---")
            print(page.extract_text())
            table = page.extract_table()
            if table:
                print("--- TABLE ---")
                for row in table:
                    print(row)
else:
    print("File not found")
