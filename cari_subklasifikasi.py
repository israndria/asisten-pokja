"""Cari semua halaman yang ada 'Subklasifikasi'."""
from pypdf import PdfReader

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"
reader = PdfReader(PDF_PATH)

for i, page in enumerate(reader.pages):
    text = page.extract_text() or ""
    if 'Subklasifikasi' in text or 'BS001' in text or 'SI003' in text:
        print(f"Page {i+1}: FOUND")
        # Print context around Subklasifikasi
        idx = text.find('Subklasifikasi')
        if idx == -1:
            idx = text.find('BS001')
        if idx == -1:
            idx = text.find('SI003')
        print(f"  Context: ...{text[max(0,idx-50):idx+200]}...")

reader.close()
