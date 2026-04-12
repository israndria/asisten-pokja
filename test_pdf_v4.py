"""Test LDK PDF Extractor v4."""
import sys
sys.path.insert(0, "D:/Dokumen/@ POKJA 2026/Asisten_Pokja")

from ldk_pdf_extractor import extract_ldk_from_pdf

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"

print("=" * 70)
print("TEST: LDK PDF Extractor v4")
print("=" * 70)

result = extract_ldk_from_pdf(PDF_PATH)

print(f"\nExtracted: {result.extracted}")
print(f"Errors: {result.errors}")

print(f"\n{'='*60}")
print("IZIN USAHA ROWS:")
print(f"{'='*60}")
for i, row in enumerate(result.izin_usaha_rows):
    print(f"\n  ROW {i+1}:")
    print(f"    Jenis Izin: {row.jenis_izin}")
    print(f"    Klasifikasi: {row.klasifikasi[:200]}...")

print(f"\n{'='*60}")
print("KINERJA PENYEDIA:")
print(f"{'='*60}")
print(f"  Required: {result.kinerja_required}")
print(f"  Text: {result.kinerja_penyedia[:200]}..." if result.kinerja_penyedia else "  NOT FOUND")

print(f"\n{'='*60}")
print("SBU DETAIL:")
print(f"{'='*60}")
print(f"  Kualifikasi: {result.sbu_kualifikasi}")
print(f"  Kode: {result.sbu_kode}")
print(f"  Deskripsi: {result.sbu_deskripsi[:150]}...")

print(f"\n{'='*60}")
print("TEST SELESAI")
print(f"{'='*60}")
