import pdfplumber
import os

folder = r"d:\Dokumen\@ POKJA 2026\9. Pokja 030 - Normalisasi Sungai Lingkar Periuk Desa Masta Kec. Bakarangan"
files = [
    "Uraian Singkat Pekerjaan.pdf",
    "Daftar Peralatan Rev.pdf",
    "Daftar Personil Inti Rev.pdf",
    "RK3K Rev.pdf",
    "Daftar Kuantitas Rev.pdf"
]

for f in files:
    path = os.path.join(folder, f)
    if os.path.exists(path):
        print(f"\n--- FILE: {f} ---")
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                print(f"--- Page {i+1} ---")
                print(page.extract_text())
                table = page.extract_table()
                if table:
                    print("--- TABLE ---")
                    for row in table[:5]: # Show first 5 rows
                        print(row)
    else:
        print(f"\n--- FILE NOT FOUND: {f} ---")
