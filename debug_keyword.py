"""Debug keyword matching."""
from ldk_config import AUTO_CHECK_KEYWORDS, CHECK_AND_FILL, SKIP_KEYWORDS

labels_from_html = [
    "Memiliki pengalaman paling kurang 1 Pekerjaan Konstruksi dalam kurun waktu 4 (empat) tahun terakhir,",
    "Memperhitungkan Sisa Kemampuan Paket (SKP).",
    "Untuk kualifikasi Usaha Kecil yang baru berdiri kurang dari 3 (tiga) tahun:",
]

def _matches(label: str, keywords: list[str]) -> bool:
    label_lower = label.lower()
    return any(kw.lower() in label_lower for kw in keywords)

print("Testing AUTO_CHECK_KEYWORDS:")
for kw in AUTO_CHECK_KEYWORDS:
    print(f"  keyword: '{kw}'")
    for label in labels_from_html:
        match = kw.lower() in label.lower()
        print(f"    → '{label[:60]}...' → match: {match}")

print("\nFinal match test:")
for label in labels_from_html:
    matched = _matches(label, AUTO_CHECK_KEYWORDS)
    print(f"  '{label[:60]}...' → matched: {matched}")
