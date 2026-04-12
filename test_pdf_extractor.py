"""Test LDK PDF Extractor."""
import sys
sys.path.insert(0, "D:/Dokumen/@ POKJA 2026/Asisten_Pokja")

from ldk_pdf_extractor import extract_ldk_from_pdf, generate_ijin_config

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"

print("=" * 70)
print("TEST: LDK PDF Extractor")
print("=" * 70)

# Extract
print(f"\nExtracting dari: {PDF_PATH}")
result = extract_ldk_from_pdf(PDF_PATH)

print(f"\nExtracted: {result.extracted}")
print(f"Errors: {result.errors}")

# Izin Usaha
print(f"\n{'='*60}")
print("IZIN USAHA:")
print(f"{'='*60}")
for izin in result.izin_usaha:
    print(f"  Jenis: {izin.jenis_izin}")
    print(f"  KBLI: {izin.kbli_codes}")
    print(f"  Tahun KBLI: {izin.tahun_kbli}")
    print(f"  Deskripsi: {izin.deskripsi[:200]}...")

# SBU
print(f"\n{'='*60}")
print("SBU:")
print(f"{'='*60}")
for sbu in result.sbu:
    print(f"  Kualifikasi: {sbu.kualifikasi}")
    print(f"  Kode SBU: {sbu.kode_sbu}")
    print(f"  Subklasifikasi: {sbu.subklasifikasi}")
    print(f"  Max SBU: {sbu.max_sbu}")
    print(f"  Deskripsi: {sbu.deskripsi[:200]}...")

# Generate config
print(f"\n{'='*60}")
print("GENERATED IJIN CONFIG:")
print(f"{'='*60}")
config = generate_ijin_config(result)
print(f"  nama: {config['nama']}")
print(f"  klasifikasi: {config['klasifikasi']}")

print(f"\n{'='*60}")
print("TEST SELESAI")
print(f"{'='*60}")
