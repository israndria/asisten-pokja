"""
kode_unik_engine.py — Generate kode unik dari nama tender.

Strategi:
1. Gemini Vision (gemini-2.5-flash-lite) — semantic compression, PascalCase 8-18 char
2. Fallback: akronim huruf kapital tiap kata, potong 8 char
"""

from pathlib import Path
import re


# ── Config ────────────────────────────────────────────────────
_MAX_LEN = 18
_MIN_LEN = 4
_FALLBACK_LEN = 8

_STOPWORDS = {
    "dan", "atau", "dengan", "untuk", "dari", "ke", "di", "yang",
    "pada", "dalam", "oleh", "adalah", "atas", "bagi",
}

_GEMINI_PROMPT = """Buat kode unik dari nama paket pengadaan berikut.
Aturan ketat:
- PascalCase (huruf besar di awal tiap segmen), TANPA spasi/simbol/tanda baca
- Panjang 8-18 karakter
- Prioritaskan kata dalam kurung (paling distinctive/spesifik)
- Singkat kata generik: Belanja→B, Bangunan→Bng, Gedung→Gd, Pemeliharaan→Plhr, Pengadaan→Pgd, Modal→Md, Jasa→Js, Barang→Brg
- Pertahankan kata teknis/domain: singkat 3-5 huruf pertama (Cytotoxic→Cyto, Kesehatan→Kes, Rehabilitasi→Rehab)
- Buang angka di awal, tanda hubung, garis miring

Contoh:
Input: Belanja Modal Bangunan Kesehatan (Pembangunan Cytotoxic)
Output: BMBngKesCyto

Input: Belanja Pemeliharaan Bangunan Gedung-Bangunan Gedung Tempat Kerja-Bangunan Kesehatan (Rehab Plafon)
Output: BPlhrBGKesRhbPlfn

Input: Pengadaan Alat Kesehatan ICU RSUD
Output: PgdAlatKesICU

Input: {nama}
Output:"""


def _load_gemini_key() -> str:
    from config import find_secret
    env_path = find_secret("secret_spse.env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    import os
    return os.environ.get("GEMINI_API_KEY", "")


def _fallback_akronim(nama: str) -> str:
    """Ambil huruf pertama tiap kata bermakna, PascalCase, max 8 char."""
    # Bersihkan nama
    clean = re.sub(r"^\d+[\.\s]+", "", nama)          # buang angka awal
    clean = re.sub(r"[()\/\-]", " ", clean)            # kurung/slash/dash → spasi
    words = clean.split()

    result = ""
    for w in words:
        if not w:
            continue
        if w.lower() in _STOPWORDS:
            continue
        result += w[0].upper()
        if len(result) >= _FALLBACK_LEN:
            break

    return result[:_FALLBACK_LEN] if result else "PAKET"


def generate_kode_unik(nama_tender: str) -> str:
    """
    Generate kode unik dari nama tender.
    Return: string PascalCase 8-18 char.
    """
    if not nama_tender or not nama_tender.strip():
        return "PAKET"

    # Coba Gemini dulu
    api_key = _load_gemini_key()
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            prompt = _GEMINI_PROMPT.format(nama=nama_tender.strip())
            resp = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
            )
            raw = resp.text.strip()
            # Ambil baris pertama saja, bersihkan non-alnum
            raw = raw.splitlines()[0].strip()
            result = re.sub(r"[^a-zA-Z0-9]", "", raw)
            if _MIN_LEN <= len(result) <= _MAX_LEN:
                return result
        except Exception:
            pass  # Fallback ke akronim

    # Fallback: akronim 8 char
    return _fallback_akronim(nama_tender)


if __name__ == "__main__":
    # Quick test
    samples = [
        "1. Belanja Modal Bangunan Kesehatan (Pembangunan Cytotoxic)",
        "2. Belanja Pemeliharaan Bangunan Gedung-Bangunan Gedung Tempat Kerja-Bangunan Kesehatan (Rehab Plafon/Pasad)",
        "Pengadaan Alat Kesehatan ICU RSUD",
        "Jasa Konsultansi Perencanaan Pembangunan Gedung Kantor",
    ]
    for s in samples:
        print(f"Input : {s[:70]}")
        print(f"Output: {generate_kode_unik(s)}")
        print()
