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
    "Persyaratan kepemilikan Sertifikat Badan Usaha",
    "mensyaratkan lebih dari satu SBU",
]

# ── Izin Usaha (WAJIB diisi agar submit berhasil) ────────────────────────────
# Multi-row default values
IJIN_USAHA_DEFAULT = {
    "rows": [
        {
            "jenis_izin": "Izin Usaha di bidang Jasa Konstruksi",
            "klasifikasi": (
                "perizinan berusaha di bidang Jasa Konstruksi. "
                "a) Memiliki Nomor Induk Berusaha (NIB) dan Sertifikat Standar terverifikasi "
                "(untuk Badan Usaha yang memiliki SBU KBLI 2020); "
                "b) Dalam hal Sertifikat Standar sebagaimana dimaksud pada huruf a) belum terverifikasi, "
                "peserta menyampaikan NIB, Sertifikat Standar belum terverifikasi dan tangkapan layar laman OSS "
                "yang mencantumkan bahwa Sertifikat Standar sedang menunggu verifikasi; atau "
                "c) Memiliki Nomor Induk Berusaha (NIB) dan SBU yang masih berlaku "
                "(untuk Badan Usaha yang memiliki SBU KBLI 2015)"
            ),
        },
        {
            "jenis_izin": "Sertifikat Badan Usaha SBU",
            "klasifikasi": (
                "Memiliki Sertifikat Badan Usaha (SBU) dengan Kualifikasi Usaha Kecil, serta disyaratkan: "
                "a) Subklasifikasi BS001 (KBLI 2020) Konstruksi Bangunan Sipil Jalan atau; "
                "b) Subklasifikasi SI003 (KBLI 2015) Jasa Pelaksana Konstruksi Jalan Raya "
                "(Kecuali Jalan Layang), Jalan, Rel Kereta Api, dan Landasan Pacu Bandara."
            ),
        },
    ]
}

# ── Kinerja Penyedia (opsional tapi direkomendasikan) ────────────────────────
KINERJA_PENYEDIA_DEFAULT = (
    "Memiliki kinerja penyedia dengan nilai baik dan/atau sangat baik dalam kurun waktu 4 (empat) tahun terakhir "
    "untuk pekerjaan konstruksi yang penilaian kinerja Penyedia Barang/Jasa telah tercantum dalam Sistem Informasi "
    "Kinerja Penyedia (SIKaP) dan/atau dalam hal penilaian kinerja terhadap Penyedia Barang/Jasa yang bersangkutan "
    "pada SIKaP belum tersedia atau belum dilakukan penilaian kinerja oleh PPK maka penilaian kinerja dapat dilakukan "
    "secara manual sesuai dengan Peraturan LKPP Nomor 4 Tahun 2021 tentang Pembinaan Pelaku Usaha Pengadaan Barang/Jasa Pemerintah"
)
