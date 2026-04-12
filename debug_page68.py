"""Debug: lihat teks PAGE 68 secara lengkap."""
from pypdf import PdfReader

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"
reader = PdfReader(PDF_PATH)

text = reader.pages[67].extract_text() or ""  # Page 68 = index 67
print(f"PAGE 68 ({len(text)} chars):")
print("=" * 60)
print(text)
reader.close()
