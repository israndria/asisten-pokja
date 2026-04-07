"""
Template teks pemberian penjelasan per jenis paket.
Dipilih user saat mendaftarkan jadwal.
"""

JENIS_PAKET = {
    "tender":              "Tender (1x penjelasan)",
    "seleksi_kualifikasi": "Seleksi — Penjelasan Kualifikasi",
    "seleksi_seleksi":     "Seleksi — Penjelasan Seleksi",
}

TEMPLATE = {
    "tender": """\
Selamat pagi, mohon untuk memperhatikan bagian penting dari dokumen pemilihan yang anda download, yaitu:
1.Instruksi Kepada Peserta, yang berisi segala aturan yang digunakan untuk tender ini.
2.Lembar Data Kualifikasi berisi persyaratan kualifikasi peserta, antara lain:
2.1 Peserta yang berbadan usaha harus memiliki perizinan berusaha di bidang Jasa Konstruksi:
a)Memiliki Nomor lnduk Berusaha (NlB) dan Sertifikat Standar terverifikasi (untuk Badan Usaha yang memiliki SBU KBLI 2020);
b)Dalam hal Sertifikat Standar sebagaimana dimaksud pada huruf a) belum terverifikasi, peserta menyampaikan NlB, Sertifikat Standar belum terverifikasi dan tangkapan layar laman OSS yang mencantumkan bahwa Sertifikat Standar sedang menunggu verifikasi; atau
c)Memiliki Nomor lnduk Berusaha (NlB) dan SBU yang masih berlaku (untuk Badan Usaha yang memiliki SBU KBLI 2015);
2.2Memiliki kinerja penyedia dengan nilai baik dan/atau sangat baik dalam kurun waktu 4 (empat) tahun terakhir untuk pekerjaan kontruksi yang penilaian kinerja Penyedia Barang/Jasa telah tercantum dalam Sistem Informasi Kinerja Penyedia (SIKaP) dan/atau dalam hal penilaian kinerja terhadap Penyedia Barang/Jasa yang bersangkutan pada SIKaP belum tersedia atau belum dilakukan penilaian kinerja oleh PPK maka penilaian kinerja dapat dilakukan secara manual sesuai dengan Peraturan LKPP Nomor 4 Tahun 2021 tentang Pembinaan Pelaku Usaha Pengadaan Barang/Jasa Pemerintah;
3.Lembar Data Pemilihan berisi persyaratan teknis penawaran.
4.Untuk tender paket pekerjaan ini tidak diberlakukan preferensi harga
5.Rancangan kontrak, SSUK dan SSKK sebagaimana diupload PPK pada SPSE.
Demikian informasi kami sampaikan, diharapkan peserta dapat memanfaatkan jadwal penjelasan ini, untuk menanyakan atau menyampaikan hal-hal yang dirasa kurang jelas, terimakasih.""",

    "seleksi_kualifikasi": """\
Selamat pagi, mohon untuk memperhatikan bagian penting dari dokumen kualifikasi yang anda download, yaitu:
1.Instruksi Kepada Peserta, yang berisi segala aturan yang digunakan untuk seleksi ini.
2.Lembar Data Kualifikasi berisi persyaratan kualifikasi peserta, antara lain:
2.1 Peserta yang berbadan usaha harus memiliki perizinan berusaha di bidang Jasa Konsultansi Konstruksi/Non Konstruksi;
2.2 Memiliki kinerja penyedia dengan nilai baik dan/atau sangat baik dalam kurun waktu 4 (empat) tahun terakhir;
3.Rancangan kontrak, SSUK dan SSKK sebagaimana diupload PPK pada SPSE.
Demikian informasi kami sampaikan, diharapkan peserta dapat memanfaatkan jadwal penjelasan dokumen kualifikasi ini, untuk menanyakan atau menyampaikan hal-hal yang dirasa kurang jelas, terimakasih.""",

    "seleksi_seleksi": """\
Selamat pagi, mohon untuk memperhatikan bagian penting dari dokumen pemilihan yang anda download, yaitu:
1.Instruksi Kepada Peserta, yang berisi segala aturan yang digunakan untuk seleksi ini.
2.Lembar Data Pemilihan berisi persyaratan teknis penawaran.
3.Untuk seleksi paket pekerjaan ini tidak diberlakukan preferensi harga.
4.Rancangan kontrak, SSUK dan SSKK sebagaimana diupload PPK pada SPSE.
Demikian informasi kami sampaikan, diharapkan peserta dapat memanfaatkan jadwal penjelasan ini, untuk menanyakan atau menyampaikan hal-hal yang dirasa kurang jelas, terimakasih.""",
}
