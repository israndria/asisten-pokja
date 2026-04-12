"""Compare page 47 vs 68."""
from pypdf import PdfReader

PDF_PATH = r"D:\Dokumen\@ POKJA 2026\Pokja 001\DOKPIL_335.pdf"
reader = PdfReader(PDF_PATH)

for pg in [46, 67]:  # index 46 = page 47, index 67 = page 68
    text = reader.pages[pg].extract_text() or ""
    print(f"\n{'='*60}")
    print(f"PAGE {pg+1} (first 300 chars):")
    print(f"{'='*60}")
    print(repr(text[:300]))
    
    text_lower = text.lower()
    print(f"\n  'bab v.' in [:200]: {'bab v.' in text_lower[:200]}")
    print(f"  'lembar data kualifikasi' in [:300]: {'lembar data kualifikasi' in text_lower[:300]}")
    print(f"  '29.11' in text: {'29.11' in text}")
    print(f"  'subklasifikasi' in text_lower: {'subklasifikasi' in text_lower}")
    print(f"  starts with '- ': {text.strip().startswith('- ')}")

reader.close()
