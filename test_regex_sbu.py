"""Debug: lihat clean_ldk setelah join lines."""
from pypdf import PdfReader
import re

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"
reader = PdfReader(PDF_PATH)

# Ambil halaman 68
text = reader.pages[67].extract_text() or ""

# Clean: join lines
clean = re.sub(r'\n+', ' ', text)
clean = re.sub(r'\s+', ' ', clean)

print("CLEAN LDK (page 68):")
print("=" * 60)
print(clean[:2000])

# Test regex SBU
print("\n" + "=" * 60)
print("TEST REGEX SBU:")
pattern = r'Subklasifikasi\s*([A-Z]{0,2}\d{3})\s*\(\s*KBLI\s*(\d{4})\s*\)\s*([A-Za-z\s\(\),/]+?)(?=\s*Subklasifikasi|\s*atau\s*[;.]|\s*\d\.\s*Memiliki|\s*\.?\s*(?:\d|Memiliki|Peserta|Pokja)|$)'
matches = re.findall(pattern, clean, re.IGNORECASE)
print(f"Matches: {matches}")

# Test simpler pattern
print("\nSIMPLE PATTERN TEST:")
simple = r'Subklasifikasi\s*([A-Z]{0,2}\d{3})\s*\(KBLI\s*(\d{4})\)\s*([A-Za-z\s]+)'
simple_matches = re.findall(simple, clean, re.IGNORECASE)
print(f"Simple matches: {simple_matches}")

reader.close()
