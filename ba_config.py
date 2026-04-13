"""Konfigurasi BA Engine — jenis BA dan template nomor."""

JENIS_BA = {
    "penjelasan":       "BA Pemberian Penjelasan",
    "evaluasi":         "BA Evaluasi Penawaran",
    "hasil_pemilihan":  "BA Hasil Pemilihan",
    "negosiasi":        "BA Negosiasi",
    "lainnya":          "BA Lainnya",
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
