"""Cari halaman LDK Izin Usaha + SBU di DOKPIL_335.pdf"""
from pypdf import PdfReader

pdf = PdfReader(r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf")

# Cari halaman yang mengandung keyword terkait izin/SBU/KBLI
keywords = ['izin usaha', 'ijin usaha', 'kbli', 'sbu', 'sertifikat badan usaha', 
            'nomor induk berusaha', 'nib', 'sertifikat standar', 'subklasifikasi']

for i in range(len(pdf.pages)):
    text = pdf.pages[i].extract_text() or ''
    text_lower = text.lower()
    
    matches = [kw for kw in keywords if kw.lower() in text_lower]
    if matches:
        print(f"\n{'='*60}")
        print(f"=== PAGE {i+1} — MATCH: {matches}")
        print(f"{'='*60}")
        print(text[:3000])

pdf.close()
