"""Debug: find_ldk_pages."""
from pypdf import PdfReader

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"
reader = PdfReader(PDF_PATH)

pages = []
for i, page in enumerate(reader.pages):
    text = page.extract_text() or ""
    pages.append((i + 1, text))

# Cari LDK
ldk_pages = []
in_ldk = False
for page_num, text in pages:
    text_lower = text.lower()
    if 'bab v' in text_lower or 'lembar data kualifikasi' in text_lower:
        print(f"  → Page {page_num}: MULAI LDK")
        in_ldk = True
    if in_ldk:
        ldk_pages.append((page_num, text))
    if in_ldk and ('bab vi' in text_lower or 'bentuk dokumen penawaran' in text_lower):
        print(f"  → Page {page_num}: SELESAI LDK")
        break

print(f"\nLDK pages found: {[p[0] for p in ldk_pages]}")

# Gabungkan & clean
full = "\n".join(t for _, t in ldk_pages)
import re
clean = re.sub(r'\n+', ' ', full)
clean = re.sub(r'\s+', ' ', clean)

# Test Izin Usaha
izin = re.search(r'perizinan\s*berusaha\s*di\s*bidang\s*Jasa\s*Konstruksi', clean, re.IGNORECASE)
print(f"\nIzin Usaha match: {izin.group(0) if izin else 'NO MATCH'}")

# Test SBU
pattern = r'Subklasifikasi\s*([A-Z]{0,2}\d{3})\s*\(\s*KBLI\s*(\d{4})\s*\)\s*([A-Za-z\s\(\),/]+?)(?=\s*Subklasifikasi|\s*atau\s*[;.]|\s*\d\.\s*Memiliki|\s*\.?\s*(?:\d|Memiliki|Peserta|Pokja)|$)'
sbu = re.findall(pattern, clean, re.IGNORECASE)
print(f"SBU matches: {sbu}")

reader.close()
