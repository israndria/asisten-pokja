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
                "Memiliki perizinan berusaha di bidang Jasa Konstruksi. "
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

# ── Daftar SBU untuk dropdown (KBLI 2020 dan KBLI 2015) ─────────────────────
# Format: "KODE — Nama Subklasifikasi"
SBU_KBLI_2020 = [
    "BS001 — Konstruksi Bangunan Sipil Jalan",
    "BS002 — Konstruksi Bangunan Sipil Jembatan",
    "BS003 — Konstruksi Bangunan Sipil Jalan Layang, Flyover, dan Underpass",
    "BS004 — Konstruksi Bangunan Sipil Landasan Pacu dan Taxiway Bandara",
    "BS005 — Konstruksi Bangunan Sipil Rel Kereta Api",
    "BS006 — Konstruksi Bangunan Sipil Terowongan",
    "BS007 — Konstruksi Bangunan Sipil Pelabuhan Bukan Perairan Pedalaman",
    "BS008 — Konstruksi Bangunan Sipil Fasilitas Pengolahan",
    "BS009 — Konstruksi Bangunan Sipil Saluran Irigasi, Saluran Air",
    "BS010 — Konstruksi Bangunan Sipil Saluran Drainase dan Jaringan Pipa",
    "BS011 — Konstruksi Bangunan Sipil Minyak dan Gas",
    "BS012 — Konstruksi Bangunan Sipil Kelistrikan",
    "BS013 — Konstruksi Bangunan Sipil Telekomunikasi",
    "BS014 — Konstruksi Bangunan Sipil Pertambangan",
    "BG001 — Konstruksi Gedung Hunian",
    "BG002 — Konstruksi Gedung Perkantoran",
    "BG003 — Konstruksi Gedung Industri",
    "BG004 — Konstruksi Gedung Perbelanjaan",
    "BG005 — Konstruksi Gedung Kesehatan",
    "BG006 — Konstruksi Gedung Pendidikan",
    "BG007 — Konstruksi Gedung Olahraga dan Rekreasi",
    "BG008 — Konstruksi Gedung Lainnya",
    "EL001 — Konstruksi Instalasi Listrik dan Telekomunikasi Gedung",
    "EL002 — Konstruksi Instalasi Pembangkit Tenaga Listrik",
    "EL003 — Konstruksi Jaringan Transmisi Tenaga Listrik",
    "EL004 — Konstruksi Jaringan Distribusi Tenaga Listrik",
    "MK001 — Konstruksi Instalasi Mekanikal Gedung",
    "MK002 — Konstruksi Instalasi Plambing dan Sanitasi",
    "MK003 — Konstruksi Instalasi Tata Udara",
    "PL001 — Konstruksi Pekerjaan Pondasi dan Geoteknik",
    "PL002 — Konstruksi Bangunan Lepas Pantai",
    "PL003 — Konstruksi Bangunan Penahan Tanah",
    "PL004 — Konstruksi Bangunan Pengolahan Limbah",
    "PL005 — Konstruksi Bangunan Pengolahan Air Bersih",
]

SBU_KBLI_2015 = [
    # ── Sipil (SI) ────────────────────────────────────────────────────────────
    "SI001 — Jasa Pelaksana Konstruksi Saluran Air, Pelabuhan, Dam, dan Prasarana Sumber Daya Air Lainnya",
    "SI002 — Jasa Pelaksana Konstruksi Instalasi Pengolahan Air Minum dan Air Limbah",
    "SI003 — Jasa Pelaksana Konstruksi Jalan Raya (Kecuali Jalan Layang), Jalan, Rel Kereta Api, dan Landasan Pacu Bandara",
    "SI004 — Jasa Pelaksana Konstruksi Jembatan, Jalan Layang, Terowongan, dan Subways",
    "SI005 — Jasa Pelaksana Konstruksi Perpipaan Air Minum Jarak Jauh",
    "SI006 — Jasa Pelaksana Konstruksi Perpipaan Air Limbah Jarak Jauh",
    "SI007 — Jasa Pelaksana Konstruksi Perpipaan Minyak dan Gas Jarak Jauh",
    "SI008 — Jasa Pelaksana Konstruksi Perpipaan Air Minum Lokal",
    "SI009 — Jasa Pelaksana Konstruksi Perpipaan Air Limbah Lokal",
    "SI010 — Jasa Pelaksana Konstruksi Perpipaan Minyak dan Gas Lokal",
    "SI011 — Jasa Pelaksana Konstruksi Bangunan Stadion untuk Olahraga Outdoor",
    "SI012 — Jasa Pelaksana Konstruksi Bangunan Fasilitas Olahraga Indoor dan Fasilitas Rekreasi",
    # ── Gedung (BG) ───────────────────────────────────────────────────────────
    "BG001 — Jasa Pelaksana Konstruksi Bangunan Gedung Hunian",
    "BG002 — Jasa Pelaksana Konstruksi Bangunan Gedung Industri",
    "BG003 — Jasa Pelaksana Konstruksi Bangunan Gedung Komersial",
    "BG004 — Jasa Pelaksana Konstruksi Bangunan Gedung Hiburan dan Kebudayaan",
    "BG005 — Jasa Pelaksana Konstruksi Bangunan Gedung Hotel",
    "BG006 — Jasa Pelaksana Konstruksi Bangunan Gedung Pendidikan",
    "BG007 — Jasa Pelaksana Konstruksi Bangunan Gedung Kesehatan",
    "BG008 — Jasa Pelaksana Konstruksi Bangunan Gedung Lainnya",
    "BG009 — Jasa Pelaksana Konstruksi Bangunan Gedung Peribadatan",
    # ── Mekanikal (MK) ────────────────────────────────────────────────────────
    "MK001 — Jasa Pelaksana Konstruksi Pemasangan Pendingin Udara (AC), Pemanas, dan Ventilasi",
    "MK002 — Jasa Pelaksana Konstruksi Pemasangan Pipa Air (Plumbing) dalam Bangunan",
    "MK003 — Jasa Pelaksana Konstruksi Pemasangan Pipa Gas dalam Bangunan",
    "MK004 — Jasa Pelaksana Konstruksi Insulasi dalam Bangunan",
    # ── Elektrikal (EL) ───────────────────────────────────────────────────────
    "EL001 — Jasa Pelaksana Konstruksi Instalasi Pembangkit Tenaga Listrik Semua Daya",
    "EL002 — Jasa Pelaksana Konstruksi Instalasi Pembangkit Tenaga Listrik Daya Maksimum 10 MW",
    "EL003 — Jasa Pelaksana Konstruksi Instalasi Pembangkit Tenaga Listrik Energi Baru dan Terbarukan",
    "EL004 — Jasa Pelaksana Konstruksi Instalasi Jaringan Transmisi Tenaga Listrik Tegangan Tinggi/Ekstra Tinggi",
    "EL005 — Jasa Pelaksana Konstruksi Jaringan Transmisi Telekomunikasi dan/atau Telepon",
    "EL006 — Jasa Pelaksana Konstruksi Jaringan Distribusi Tenaga Listrik Tegangan Menengah",
    "EL007 — Jasa Pelaksana Konstruksi Instalasi Jaringan Distribusi Tenaga Listrik Tegangan Rendah",
    "EL008 — Jasa Pelaksana Konstruksi Instalasi Jaringan Distribusi Telekomunikasi dan/atau Telepon",
    "EL009 — Jasa Pelaksana Konstruksi Instalasi Sistem Kontrol dan Instrumentasi",
    "EL010 — Jasa Pelaksana Konstruksi Instalasi Tenaga Listrik Gedung dan Pabrik",
    "EL011 — Jasa Pelaksana Konstruksi Instalasi Elektrikal dan Sinyal Jalan, Rel, Bandara, dan Pelabuhan",
    # ── Pelaksanaan Lainnya / Spesialis (SP/PL) ───────────────────────────────
    "PL001 — Jasa Penyewaan Alat Konstruksi dengan Operator",
    "PL002 — Jasa Perakitan dan Pemasangan Konstruksi Prafabrikasi Bangunan Gedung",
    "PL003 — Jasa Perakitan dan Pemasangan Konstruksi Prafabrikasi Jalan, Jembatan, dan Rel Kereta Api",
    "PL004 — Jasa Perakitan dan Pemasangan Konstruksi Prafabrikasi Prasarana Sumber Daya Air dan Pelabuhan",
    "SP001 — Pekerjaan Penyelidikan Lapangan",
    "SP002 — Pekerjaan Pembongkaran Bangunan",
    "SP003 — Pekerjaan Penyiapan dan Pematangan Tanah/Lokasi",
    "SP004 — Pekerjaan Tanah, Galian, dan Timbunan",
    "SP005 — Pekerjaan Persiapan Lapangan untuk Pertambangan",
    "SP006 — Pekerjaan Perancah",
    "SP007 — Pekerjaan Pondasi, Termasuk Pemancangan",
    "SP008 — Pekerjaan Pengeboran Sumur Air Tanah Dalam",
    "SP009 — Pekerjaan Atap dan Kedap Air (Waterproofing)",
    "SP010 — Pekerjaan Beton",
    "SP011 — Pekerjaan Baja dan Pemasangannya, Termasuk Pengelasan",
    "SP013 — Pekerjaan Konstruksi Khusus Lainnya",
    "SP014 — Pekerjaan Pengaspalan dengan Rangkaian Peralatan Khusus",
    "SP015 — Pekerjaan Lansekap/Pertamanan",
    "SP016 — Pekerjaan Perawatan Bangunan Gedung",
]


def build_sbu_klasifikasi(sbu_2020: str, sbu_2015: str) -> str:
    """
    Bangun teks klasifikasi SBU dari pilihan dropdown.
    - Hanya 2020 terisi   → "...serta disyaratkan: a) Subklasifikasi XXX..."
    - Hanya 2015 terisi   → "...serta disyaratkan: a) Subklasifikasi XXX..."
    - Keduanya terisi     → "...serta disyaratkan: a) 2020 atau; b) 2015."
    """
    kode_2020 = sbu_2020.split(" — ")[0].strip() if sbu_2020 else ""
    nama_2020 = sbu_2020.split(" — ")[1].strip() if sbu_2020 and " — " in sbu_2020 else ""
    kode_2015 = sbu_2015.split(" — ")[0].strip() if sbu_2015 else ""
    nama_2015 = sbu_2015.split(" — ")[1].strip() if sbu_2015 and " — " in sbu_2015 else ""

    prefix = "Memiliki Sertifikat Badan Usaha (SBU) dengan Kualifikasi Usaha Kecil, serta disyaratkan: "

    if kode_2020 and kode_2015:
        return (
            f"{prefix}"
            f"a) Subklasifikasi {kode_2020} (KBLI 2020) {nama_2020} atau; "
            f"b) Subklasifikasi {kode_2015} (KBLI 2015) {nama_2015}."
        )
    elif kode_2020:
        return (
            f"{prefix}"
            f"Subklasifikasi {kode_2020} (KBLI 2020) {nama_2020}."
        )
    elif kode_2015:
        return (
            f"{prefix}"
            f"Subklasifikasi {kode_2015} (KBLI 2015) {nama_2015}."
        )
    return ""


# ── Kinerja Penyedia (opsional tapi direkomendasikan) ────────────────────────
KINERJA_PENYEDIA_DEFAULT = (
    "Memiliki kinerja penyedia dengan nilai baik dan/atau sangat baik dalam kurun waktu 4 (empat) tahun terakhir "
    "untuk pekerjaan konstruksi yang penilaian kinerja Penyedia Barang/Jasa telah tercantum dalam Sistem Informasi "
    "Kinerja Penyedia (SIKaP) dan/atau dalam hal penilaian kinerja terhadap Penyedia Barang/Jasa yang bersangkutan "
    "pada SIKaP belum tersedia atau belum dilakukan penilaian kinerja oleh PPK maka penilaian kinerja dapat dilakukan "
    "secara manual sesuai dengan Peraturan LKPP Nomor 4 Tahun 2021 tentang Pembinaan Pelaku Usaha Pengadaan Barang/Jasa Pemerintah"
)
