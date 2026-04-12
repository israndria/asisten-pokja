"""Debug: lihat teks yang di-extract dari PDF."""
from pypdf import PdfReader
import re

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"
reader = PdfReader(PDF_PATH)

# Extract halaman 67-72 (sekitar BAB V LDK)
for i in range(66, 72):
    text = reader.pages[i].extract_text() or ""
    print(f"\n{'='*60}")
    print(f"PAGE {i+1} ({len(text)} chars):")
    print(f"{'='*60}")
    # Show lines that contain relevant keywords
    lines = text.split('\n')
    for line in lines:
        line_clean = line.strip()
        if any(kw in line_clean.lower() for kw in ['izin', 'sbu', 'kbli', 'kualifikasi', 'berusaha', 'konstruksi', 'subklasifikasi']):
            print(f"  → {line_clean[:150]}")

reader.close()
