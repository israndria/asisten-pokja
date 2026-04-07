"""
Konfigurasi template Checklist Dokumen Penawaran — Konstruksi Usaha Kecil.

URL target: /dokumen/[ID]/checklist

Kata kunci (keyword) dipakai untuk mencocokkan label checkbox dari HTML
menggunakan substring match, case-insensitive.

Catatan: checklist ini hanya centang saja, tidak ada isian teks.

─────────────────────────────────────────────────────────────────────
LOCKED (sudah dicentang otomatis oleh sistem SPSE, tidak disentuh):
  - Masa Berlaku Penawaran
  - Surat Penawaran

YANG DICENTANG (5 item):
  Teknis:
  1. Daftar isian peralatan utama beserta bukti kepemilikan/sewa (a,b,c)
  2. Daftar isian personel manajerial beserta riwayat pengalaman kerja
  3. Rencana Keselamatan Konstruksi (RKK): Elemen SMKK + Pakta Komitmen
  Harga/Biaya:
  4. Daftar Kuantitas dan Harga / Daftar Keluaran dan Harga
  5. Kewajaran harga <80% HPS (Analisa HSP + Rincian Keluaran dan Harga)

YANG DI-SKIP (4 item, tidak relevan untuk Usaha Kecil biasa):
  1. Metode pelaksanaan pekerjaan untuk kualifikasi usaha besar
  2. Daftar Isian Pekerjaan yang disubkontrakkan
  3. Formulir penyampaian TKDN
  4. Daftar barang yang diimpor
─────────────────────────────────────────────────────────────────────
"""

# ── Item yang HARUS di-check (checkbox saja, tanpa isi teks) ─────────────────
AUTO_CHECK_KEYWORDS = [
    # Teknis
    "peralatan utama",
    "personel manajerial",
    "Rencana Keselamatan Konstruksi",
    # Harga/Biaya
    "Daftar Kuantitas dan Harga",
    "Daftar Keluaran dan Harga",
    "kewajaran harga",
]

# ── Item yang di-SKIP (tidak dicentang, meski tidak locked) ──────────────────
SKIP_KEYWORDS = [
    "Metode pelaksanaan pekerjaan",   # untuk kualifikasi usaha besar
    "disubkontrakkan",
    "TKDN",
    "diimpor",
    "konsorsium",
    "kerja sama operasi",
]
