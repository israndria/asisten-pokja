import pdfplumber
import pandas as pd

pdf_path = r"D:\Download\PermenPUPR 8 2022 SBU.pdf"
output_preview = r"d:\Dokumen\@ POKJA 2026\Asisten_Pokja\scratch\sbu_preview.txt"

with pdfplumber.open(pdf_path) as pdf:
    # Intip 5 halaman pertama yang ada tabelnya
    with open(output_preview, "w", encoding="utf-8") as f:
        for i in range(min(15, len(pdf.pages))):
            page = pdf.pages[i]
            tables = page.extract_tables()
            if tables:
                f.write(f"--- Halaman {i+1} ---\n")
                for table in tables:
                    for row in table:
                        f.write(str(row) + "\n")
                f.write("\n")

print(f"Preview selesai disimpan di {output_preview}")
