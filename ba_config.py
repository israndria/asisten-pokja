"""Konfigurasi BA Engine — jenis BA dan template nomor."""

JENIS_BA = {
    "penjelasan":       "BA Pemberian Penjelasan",
    "evaluasi":         "BA Evaluasi Penawaran",
    "hasil_pemilihan":  "BA Hasil Pemilihan",
    "negosiasi":        "BA Negosiasi",
    "lainnya":          "BA Lainnya",
}

# Label tampilan dengan nomor urut (untuk UI Tab 5)
JENIS_LABEL = {
    "penjelasan":       "2. BA Pemberian Penjelasan",
    "evaluasi":         "4. BA Evaluasi Penawaran",
    "hasil_pemilihan":  "10. BA Hasil Pemilihan",
    "negosiasi":        "8. BA Negosiasi",
    "lainnya":          "BA Lainnya",
}

# Nomor urut dalam format /XX/ untuk auto-generate nomor BA dari nomor dokpil
# Contoh dokpil: 000.3.3/01/T/PJ.D_... → ubah /01/ jadi /02/ untuk Penjelasan
NOMOR_URUT = {
    "penjelasan":       "02",
    "evaluasi":         "04",
    "hasil_pemilihan":  "10",
    "negosiasi":        "08",
    "lainnya":          "99",
}

JENIS_KEYS = list(JENIS_BA.keys())

# Template keterangan tambahan per jenis
DEFAULT_INFO = {
    "penjelasan": "Dengan berakhirnya pemberian penjelasan ini, maka seluruh peserta dianggap sudah membaca, memahami, dan menerima seluruh ketentuan yang tertuang pada dokumen pemilihan paket pengadaan ini.\nBerita acara ini akan kami gunakan untuk dokumen bukti terhadap segala bentuk sanggahan yang terkait dengan ketentuan dokumen pemilihan.",
    "evaluasi": "",
    "hasil_pemilihan": "",
    "negosiasi": "",
    "lainnya": "",
}
