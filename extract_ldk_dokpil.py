"""Extract halaman LDK dari DOKPIL_335.pdf"""
from pypdf import PdfReader

pdf = PdfReader(r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf")
print(f"Total halaman: {len(pdf.pages)}")

for i in range(68, 73):
    text = pdf.pages[i].extract_text() or ''
    print(f"\n{'='*60}")
    print(f"=== PAGE {i+1} ({len(text)} chars) ===")
    print(f"{'='*60}")
    print(text[:3000])

pdf.close()
