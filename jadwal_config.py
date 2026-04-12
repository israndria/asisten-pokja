"""
Jadwal Config — aturan durasi & pola pembuatan jadwal otomatis.

Semua durasi dan aturan berasal dari penjelasan user.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Jam kerja
# ─────────────────────────────────────────────────────────────────────────────
JAM_KERJA_MULAI = 8   # 08:00
JAM_KERJA_SELESAI = 17  # 17:00

# ─────────────────────────────────────────────────────────────────────────────
# 12 Tahapan Jadwal Tender
# ─────────────────────────────────────────────────────────────────────────────
# Format: (nama_tahap, field_mulai, field_selesai, aturan)

TAHAPAN = [
    {
        "id": 1,
        "nama": "Pengumuman Pascakualifikasi",
        "field_mulai": "jadwalList[0].dtj_tglawal",
        "field_selesai": "jadwalList[0].dtj_tglakhir",
        "input_id_mulai": "mulai0",
        "input_id_selesai": "akhir0",
        "aturan": "5 hari persis dari waktu mulai",
    },
    {
        "id": 2,
        "nama": "Download Dokumen Pemilihan",
        "field_mulai": "jadwalList[1].dtj_tglawal",
        "field_selesai": "jadwalList[1].dtj_tglakhir",
        "input_id_mulai": "mulai1",
        "input_id_selesai": "akhir1",
        "aturan": "6 hari persis dari waktu mulai",
    },
    {
        "id": 3,
        "nama": "Pemberian Penjelasan",
        "field_mulai": "jadwalList[2].dtj_tglawal",
        "field_selesai": "jadwalList[2].dtj_tglakhir",
        "input_id_mulai": "mulai2",
        "input_id_selesai": "akhir2",
        "aturan": "3 hari setelah Tahap 1 dimulai, hari kerja & jam kerja, durasi 2 jam",
    },
    {
        "id": 4,
        "nama": "Upload Dokumen Penawaran",
        "field_mulai": "jadwalList[3].dtj_tglawal",
        "field_selesai": "jadwalList[3].dtj_tglakhir",
        "input_id_mulai": "mulai3",
        "input_id_selesai": "akhir3",
        "aturan": "Mulai 2 jam setelah Tahap 3 selesai, berakhir 3 hari kalender setelahnya (hari kerja)",
    },
    {
        "id": 5,
        "nama": "Pembukaan Dokumen Penawaran",
        "field_mulai": "jadwalList[4].dtj_tglawal",
        "field_selesai": "jadwalList[4].dtj_tglakhir",
        "input_id_mulai": "mulai4",
        "input_id_selesai": "akhir4",
        "aturan": "1 menit setelah Tahap 4 selesai, durasi 24 jam",
    },
    {
        "id": 6,
        "nama": "Evaluasi Administrasi, Kualifikasi, Teknis, dan Harga",
        "field_mulai": "jadwalList[5].dtj_tglawal",
        "field_selesai": "jadwalList[5].dtj_tglakhir",
        "input_id_mulai": "mulai5",
        "input_id_selesai": "akhir5",
        "aturan": "1 menit setelah Tahap 5 dimulai, durasi 4 hari (skip weekend/libur di akhir)",
    },
    {
        "id": 7,
        "nama": "Pembuktian Kualifikasi",
        "field_mulai": "jadwalList[6].dtj_tglawal",
        "field_selesai": "jadwalList[6].dtj_tglakhir",
        "input_id_mulai": "mulai6",
        "input_id_selesai": "akhir6",
        "aturan": "Hari sama dengan akhir Tahap 6, jam 09:00-15:30",
    },
    {
        "id": 8,
        "nama": "Penetapan Pemenang",
        "field_mulai": "jadwalList[7].dtj_tglawal",
        "field_selesai": "jadwalList[7].dtj_tglakhir",
        "input_id_mulai": "mulai7",
        "input_id_selesai": "akhir7",
        "aturan": "Setelah Tahap 7 berakhir, durasi 2 jam",
    },
    {
        "id": 9,
        "nama": "Pengumuman Pemenang",
        "field_mulai": "jadwalList[8].dtj_tglawal",
        "field_selesai": "jadwalList[8].dtj_tglakhir",
        "input_id_mulai": "mulai8",
        "input_id_selesai": "akhir8",
        "aturan": "Setelah Tahap 8 berakhir, durasi 4 jam",
    },
    {
        "id": 10,
        "nama": "Masa Sanggah",
        "field_mulai": "jadwalList[9].dtj_tglawal",
        "field_selesai": "jadwalList[9].dtj_tglakhir",
        "input_id_mulai": "mulai9",
        "input_id_selesai": "akhir9",
        "aturan": "5 hari kalender setelah Tahap 9 berakhir, kelonggaran ke jam kerja",
    },
    {
        "id": 11,
        "nama": "Surat Penunjukan Penyedia Barang/Jasa",
        "field_mulai": "jadwalList[10].dtj_tglawal",
        "field_selesai": "jadwalList[10].dtj_tglakhir",
        "input_id_mulai": "mulai10",
        "input_id_selesai": "akhir10",
        "aturan": "1 jam setelah Tahap 10 berakhir, durasi 5 hari kalender (skip weekend/libur di akhir)",
    },
    {
        "id": 12,
        "nama": "Penandatanganan Kontrak",
        "field_mulai": "jadwalList[11].dtj_tglawal",
        "field_selesai": "jadwalList[11].dtj_tglakhir",
        "input_id_mulai": "mulai11",
        "input_id_selesai": "akhir11",
        "aturan": "1 hari setelah Tahap 11 dimulai, pola sama (skip weekend/libur di akhir)",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# API Libur Nasional
# ─────────────────────────────────────────────────────────────────────────────
# Primer: date.nager.at (gratis, 8 hari resmi non-Islam)
# Fallback: hardcode hari libur Islam + cuti bersama per tahun
LIBUR_API_URLS = [
    "https://date.nager.at/api/v3/PublicHolidays/{year}/ID",  # format berbeda, diparse di engine
]

# Hardcode libur nasional Islam + cuti bersama yang tidak ada di nager.at
# Update setiap tahun (berdasarkan SKB 3 Menteri)
LIBUR_HARDCODE = {
    2025: [
        "2025-01-27",  # Isra Mi'raj
        "2025-01-28",  # Cuti bersama Isra Mi'raj
        "2025-01-29",  # Tahun Baru Imlek
        "2025-03-28",  # Hari Raya Nyepi
        "2025-03-28",  # Cuti bersama Nyepi
        "2025-03-29",  # Cuti bersama Nyepi
        "2025-03-31",  # Idul Fitri 1
        "2025-04-01",  # Idul Fitri 2
        "2025-04-02",  # Cuti bersama Idul Fitri
        "2025-04-03",  # Cuti bersama Idul Fitri
        "2025-04-04",  # Cuti bersama Idul Fitri
        "2025-04-07",  # Cuti bersama Idul Fitri
        "2025-05-12",  # Waisak
        "2025-06-06",  # Idul Adha
        "2025-06-09",  # Cuti bersama Idul Adha
        "2025-06-27",  # Tahun Baru Islam 1447H
        "2025-09-05",  # Maulid Nabi
        "2025-12-26",  # Cuti bersama Natal
    ],
    2026: [
        "2026-01-16",  # Isra Mi'raj (perkiraan)
        "2026-01-17",  # Tahun Baru Imlek
        "2026-02-19",  # Hari Raya Nyepi (perkiraan)
        "2026-03-20",  # Idul Fitri 1 (perkiraan)
        "2026-03-21",  # Idul Fitri 2
        "2026-03-23",  # Cuti bersama Idul Fitri
        "2026-03-24",  # Cuti bersama Idul Fitri
        "2026-03-25",  # Cuti bersama Idul Fitri
        "2026-03-26",  # Cuti bersama Idul Fitri
        "2026-03-27",  # Cuti bersama Idul Fitri
        "2026-05-27",  # Waisak (perkiraan)
        "2026-05-28",  # Idul Adha (perkiraan)
        "2026-05-29",  # Cuti bersama Idul Adha
        "2026-06-17",  # Tahun Baru Islam 1448H (perkiraan)
        "2026-08-25",  # Maulid Nabi (perkiraan)
        "2026-12-26",  # Cuti bersama Natal
    ],
}
