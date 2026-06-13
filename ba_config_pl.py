"""Konfigurasi BA Engine PL — 2 jenis BA auto cetak+upload."""

# jenis_key cocok langsung dgn JENIS_BA_PL di ba_engine_pl.py (evaluasi/hasil)
JENIS_BA_PL = {
    "evaluasi": "BA Evaluasi Penawaran",
    "hasil":    "BA Hasil Non Tender (BAHNT)",
}
JENIS_LABEL_PL = {
    "evaluasi": "5. BA Evaluasi Penawaran",
    "hasil":    "7. BA Hasil Non Tender",
}
# Slot nomor urut (dikonfirmasi user): evaluasi=05, hasil=07
NOMOR_URUT_PL = {
    "evaluasi": "05",
    "hasil":    "07",
}
JENIS_KEYS_PL = list(JENIS_BA_PL.keys())
DEFAULT_INFO_PL = {
    "evaluasi": "",
    "hasil":    "",
}
# Label nama file backup PDF
FILE_LABEL_PL = {
    "evaluasi": "5. BA Evaluasi Penawaran PL",
    "hasil":    "7. BA Hasil Non Tender PL",
}
