"""
parse_kak_pl.py — Ekstrak field dari KAK PDF Pengadaan Langsung Konsultan.

Field yang di-extract:
  nama_ppk       — dari baris "NAMA PPK : ..."
  jangka_waktu   — dari pola "X hari / Y bulan kalender"
  sbu_baru       — kode SBU (RK003, AR001, dll) dari klausul Klasifikasi
  jabatan_teknis — dari baris Ketua Tim di tabel personil
  lokasi         — dari poin "Lokasi Kegiatan"

Dipanggil dari app.py Tab 1 setelah buat folder paket PL.
"""
import re
import os


def _text_dari_pdf(pdf_path: str) -> str:
    """Gabung teks semua halaman PDF."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(pg.extract_text() or "" for pg in pdf.pages)
    except Exception:
        return ""


def _extract_nama_ppk(teks: str) -> str:
    m = re.search(r"NAMA PPK\s*:\s*(.+)", teks)
    if m:
        return m.group(1).strip()
    return ""


def _extract_jangka_waktu(teks: str) -> str:
    """
    Cari pola 'X hari / Y bulan kalender' → kembalikan string "X hari / Y bulan kalender".
    Fallback: cari pola 'X (kata) hari kalender' saja.
    """
    # Pola lengkap: 30 hari / 1 bulan kalender
    m = re.search(
        r"(\d+)\s*\([^)]+\)\s*hari\s*/?\s*\d*\s*\([^)]+\)\s*bulan\s*kalender",
        teks, re.IGNORECASE,
    )
    if m:
        hari = re.search(r"(\d+)\s*\([^)]+\)\s*hari", m.group(0), re.IGNORECASE)
        bulan = re.search(r"(\d+)\s*\([^)]+\)\s*bulan", m.group(0), re.IGNORECASE)
        if hari and bulan:
            return f"{hari.group(1)} hari / {bulan.group(1)} bulan kalender"

    # Fallback: X hari kalender
    m2 = re.search(r"(\d+)\s*\([^)]+\)\s*(?:hari|kalender)", teks, re.IGNORECASE)
    if m2:
        return m2.group(0).strip()

    return ""


def _extract_sbu(teks: str) -> str:
    """Kode SBU dari klausul Klasifikasi (RK003, AR001, BG001, dll)."""
    m = re.search(r"\b(RK\d{3}|AR\d{3}|SI\d{3}|BG\d{3}|SP\d{3}|EL\d{3}|MK\d{3})\b", teks)
    return m.group(1) if m else ""


def _extract_jabatan_teknis(teks: str) -> str:
    """
    Baris pertama tabel personil = Ketua Tim.
    Pola: 'Ketua Tim[/Ahli ...]'
    """
    m = re.search(r"Ketua Tim\s*/?\s*Ahli\s+([\w\s]+?)(?:\s*\(|$)", teks, re.IGNORECASE)
    if m:
        return ("Ahli " + m.group(1).strip()).title()

    m2 = re.search(r"Ketua Tim\s*(.{0,40}?)(?:\n|\(|$)", teks, re.IGNORECASE)
    if m2:
        raw = m2.group(1).strip().rstrip("/")
        return ("Ketua Tim " + raw).strip() if raw else "Ketua Tim"

    return ""


def _extract_lokasi(teks: str) -> str:
    m = re.search(
        r"Lokasi Kegiatan\s*:\s*(.+?)(?=\n\d+\.|$)",
        teks, re.DOTALL | re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip()
        # Bersihkan newline tengah
        raw = re.sub(r"\s+", " ", raw)
        # Potong di kalimat pertama saja (sebelum titik)
        raw = raw.split(".")[0].strip() + "."
        return raw[:200]
    return ""


def parse_kak(pdf_path: str) -> dict:
    """
    Parse KAK PDF, kembalikan dict field.
    Semua field bisa kosong string jika tidak ditemukan.
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return {}

    sbu = _extract_sbu(teks)
    return {
        "nama_ppk":     _extract_nama_ppk(teks),
        "jangka_waktu": _extract_jangka_waktu(teks),
        "sbu_baru":     sbu,
        "lokasi":       _extract_lokasi(teks),
    }


def cari_kak_di_folder(folder: str) -> str | None:
    """
    Cari file KAK PDF di folder.
    Prioritas: nama mengandung 'KAK' (case-insensitive).
    """
    if not os.path.isdir(folder):
        return None
    candidates = []
    for f in os.listdir(folder):
        fl = f.lower()
        if fl.endswith(".pdf") and "kak" in fl:
            candidates.append(os.path.join(folder, f))
    if candidates:
        return sorted(candidates)[0]
    # Fallback: PDF pertama
    for f in os.listdir(folder):
        if f.lower().endswith(".pdf"):
            return os.path.join(folder, f)
    return None


# ── CLI self-test ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python parse_kak_pl.py path/to/KAK.pdf")
        sys.exit(1)
    result = parse_kak(path)
    for k, v in result.items():
        print(f"  {k:20s}: {v}")
