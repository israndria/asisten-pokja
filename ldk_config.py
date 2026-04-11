"""
Konfigurasi template LDK — Persyaratan Kualifikasi Konstruksi Usaha Kecil.

Kata kunci (keyword) dipakai untuk mencocokkan label checkbox dari HTML
menggunakan substring match, case-insensitive.
"""

# ── Item yang HARUS di-check (checkbox saja, tanpa isi teks) ─────────────────
AUTO_CHECK_KEYWORDS = [
    "Memiliki pengalaman paling kurang 1 Pekerjaan Konstruksi",
    "Memperhitungkan Sisa Kemampuan Paket",
    "Untuk kualifikasi Usaha Kecil yang baru berdiri kurang dari 3",
    "pengalaman paling kurang 1 Pekerjaan",      # fallback keyword
    "Sisa Kemampuan Paket",                       # fallback keyword
    "Usaha Kecil yang baru berdiri",              # fallback keyword
]

# ── Item yang HARUS di-check + diisi teks ────────────────────────────────────
# "text" = teks yang diisi di field input terkait checkbox (selalu sama/template)
CHECK_AND_FILL = [
    {
        "keyword": "Memiliki kinerja penyedia",
        "text": (
            "Penilaian kinerja dapat dilakukan secara manual sesuai dengan "
            "Peraturan LKPP Nomor 4 Tahun 2021 tentang Pembinaan Pelaku Usaha "
            "Pengadaan Barang/Jasa Pemerintah"
        ),
    },
]

# ── Item yang di-SKIP (tidak dicentang, meski tidak locked) ──────────────────
# Tidak relevan untuk paket Konstruksi Usaha Kecil biasa
SKIP_KEYWORDS = [
    "konsorsium",
    "kerja sama operasi",
    "Kemampuan Dasar (KD)",
    "Sertifikat Manajemen Mutu",
    "Usaha Menengah atau Usaha Besar",
    "Leadfirm",
]

# ── Izin Usaha (WAJIB diisi agar submit berhasil) ────────────────────────────
# Default values untuk field Izin Usaha — bisa di-override di UI
IJIN_USAHA_DEFAULT = {
    "nama": "Izin Usaha",
    "klasifikasi": "41001 - Konstruksi Umum",
}
