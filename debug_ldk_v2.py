"""Debug: test find_ldk_pages dari module."""
import sys
sys.path.insert(0, "D:/Dokumen/@ POKJA 2026/Asisten_Pokja")

from ldk_pdf_extractor import find_ldk_pages, extract_pages_from_pdf, parse_ldk_content

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"

# Extract pages
pages = extract_pages_from_pdf(PDF_PATH)
print(f"Total pages: {len(pages)}")

# Find LDK
ldk_pages = find_ldk_pages(pages)
print(f"LDK pages: {[p[0] for p in ldk_pages]}")

if ldk_pages:
    # Parse
    result = parse_ldk_content(ldk_pages)
    print(f"\nExtracted: {result.extracted}")
    print(f"Izin Usaha: {[i.jenis_izin for i in result.izin_usaha]}")
    print(f"SBU: {[(s.kode_sbu, s.subklasifikasi) for s in result.sbu]}")
else:
    print("❌ No LDK pages found")
