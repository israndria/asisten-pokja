"""
Engine pengisi sheet '3. KK Evaluasi Kualifikasi' di Excel BA PK.

Pakai win32com agar Excel tidak perlu ditutup saat diisi.
Kolom peserta: C=1, D=2, E=3 (maks 3 peserta sesuai tender kecil).
"""

import os
import re

# Peta kolom Excel: peserta ke-N → kolom (1=A, 3=C, 4=D, 5=E)
_COL_PESERTA = {1: 3, 2: 4, 3: 5}   # urutan → kolom Excel (C/D/E)
_SHEET_NAME = "3. KK Evaluasi Kualifikasi"

# Peta baris tetap (tidak berubah per paket)
_ROW = {
    "nama_peserta":   3,
    "urutan":         4,
    # Syarat 1: NIB & Perizinan
    "syarat1_hasil":  6,
    "nib_ada":        7,
    "nib_nomor":      8,
    "ss_status":      9,
    "ss_nomor":       10,
    "ss_oss":         11,   # tangkapan layar OSS
    "sbu_ada":        12,
    # Syarat 2: SBU
    "sbu_subklas":    13,
    "sbu_pbumku":     14,
    "sbu_berlaku":    15,
    "sbu_kualifikasi": 16,
    "sbu_subbidang":  17,
    # Syarat 3: Pengalaman (paket 1)
    "pgl_hasil":      19,
    "pgl1_nama":      20,
    "pgl1_pemilik":   21,
    "pgl1_nilai":     22,
    "pgl1_tanggal":   23,
    "pgl1_nomor":     24,
    # Syarat 3: Pengalaman (paket 2, jika ada)
    "pgl2_nama":      25,
    "pgl2_pemilik":   26,
    "pgl2_nilai":     27,
    "pgl2_tanggal":   28,
    "pgl2_nomor":     29,
    # Syarat 4: SKP
    "skp_hasil":      30,
    "skp_nilai":      33,
    # Syarat 5: NPWP & KSWP
    "npwp_nomor":     35,
    "kswp_status":    36,
    # Syarat 6: Akta
    "akta_pendirian_hasil": 38,
    "akta_p_nomor":   39,
    "akta_p_tanggal": 40,
    "akta_p_notaris": 41,
    "akta_k_hasil":   42,
    "akta_k_nomor":   43,
    "akta_k_tanggal": 44,
    "akta_k_notaris": 45,
    "pemilik_label":  46,
    "pemilik_1":      47,
    "pemilik_2":      48,
    "pemilik_3":      49,
    "pemilik_4":      50,
    # Syarat 7: SIKaP/Kinerja
    "sikap_ada":      51,
    "kinerja_nilai":  52,
    # Syarat 8: Daftar Hitam
    "daftar_hitam":   53,
    "hasil_ms":       54,
}


def _cari_excel(folder_paket: str) -> str | None:
    """Cari file .xlsm di folder paket."""
    for f in os.listdir(folder_paket):
        if f.endswith(".xlsm") and "BA PK" in f:
            return os.path.join(folder_paket, f)
    return None


def _ms_tms(data: dict) -> str:
    """Tentukan MS atau TMS dari data peserta."""
    if data.get("kswp_status") == "TIDAK VALID":
        return "TMS"
    if not data.get("nib_nomor"):
        return "TMS"
    if not data.get("sbu_nomor"):
        return "TMS"
    if not data.get("pengalaman"):
        return "TMS"
    return "MS"


def fill_kk_evaluasi(
    excel_path: str,
    semua_peserta: list[dict],
    progress_cb=None,
) -> dict:
    """
    Isi sheet '3. KK Evaluasi Kualifikasi' dengan data semua peserta.

    Args:
        excel_path    : path file .xlsm (absolut)
        semua_peserta : list dict dari kualifikasi_parser.parse_peserta_lengkap()
        progress_cb   : callback(pesan: str)

    Return: {"ok": bool, "pesan": str}
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
    except ImportError:
        return {"ok": False, "pesan": "win32com tidak tersedia — pastikan WinPython dipakai"}

    if not os.path.isfile(excel_path):
        return {"ok": False, "pesan": f"File tidak ditemukan: {excel_path}"}

    _log(f"Membuka Excel: {os.path.basename(excel_path)}")
    try:
        xl = win32com.client.Dispatch("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False

        # Buka workbook — cek apakah sudah terbuka
        wb = None
        for w in xl.Workbooks:
            if w.FullName.lower() == excel_path.lower():
                wb = w
                break
        if wb is None:
            wb = xl.Workbooks.Open(excel_path)

        ws = wb.Sheets(_SHEET_NAME)
    except Exception as e:
        return {"ok": False, "pesan": f"Gagal buka Excel: {e}"}

    def _set(row, col, val):
        try:
            ws.Cells(row, col).Value = val
        except Exception:
            pass

    for urutan, data in enumerate(semua_peserta, 1):
        if not data.get("ok"):
            _log(f"  Peserta {urutan}: data tidak lengkap, skip")
            continue

        col = _COL_PESERTA.get(urutan)
        if col is None:
            _log(f"  Peserta {urutan}: melebihi 3 peserta, skip")
            continue

        _log(f"  Mengisi kolom peserta {urutan}: {data.get('nama','')}")

        # Nama & urutan
        _set(_ROW["nama_peserta"], col, data.get("nama", ""))
        _set(_ROW["urutan"], col, urutan)

        # Syarat 1: NIB & Perizinan — tentukan poin a/b/c
        # Poin a: NIB + SS + SBU semua ada
        # Poin b: NIB + SS ada, SBU tidak ada (atau sebaliknya)
        # Poin c: NIB ada saja (SS dan SBU tidak ada)
        # Tidak memenuhi: NIB tidak ada
        nib_ada = "Ada" if data.get("nib_nomor") else "Tidak Ada"
        _has_nib = bool(data.get("nib_nomor"))
        _has_ss  = bool(data.get("ss_nomor"))
        _has_sbu = bool(data.get("sbu_nomor"))
        if _has_nib and _has_ss and _has_sbu:
            _poin1 = "Memenuhi Syarat Kualifikasi pada Poin a)."
        elif _has_nib and (_has_ss or _has_sbu):
            _poin1 = "Memenuhi Syarat Kualifikasi pada Poin b)."
        elif _has_nib:
            _poin1 = "Memenuhi Syarat Kualifikasi pada Poin c)."
        else:
            _poin1 = "Tidak Memenuhi"
        _set(_ROW["syarat1_hasil"], col, _poin1)
        _set(_ROW["nib_ada"],    col, nib_ada)
        _set(_ROW["nib_nomor"],  col, data.get("nib_nomor", ""))
        _set(_ROW["ss_status"],  col, data.get("ss_terverifikasi", ""))
        _set(_ROW["ss_nomor"],   col, data.get("ss_nomor", ""))
        _set(_ROW["ss_oss"],     col, "-")
        _set(_ROW["sbu_ada"],    col, "-")

        # Syarat 2: SBU — pakai sbu_subklas_label dari parser jika ada, fallback _format_sbu_label
        sbu_label = data.get("sbu_subklas_label") or _format_sbu_label(
            data.get("sbu_klasifikasi", ""), data.get("sbu_kualifikasi", ""))
        _set(_ROW["sbu_subklas"],    col, sbu_label)
        _set(_ROW["sbu_pbumku"],     col, data.get("sbu_nomor", ""))
        _set(_ROW["sbu_berlaku"],    col, data.get("sbu_berlaku", ""))
        _set(_ROW["sbu_kualifikasi"], col, data.get("sbu_kualifikasi", ""))
        _set(_ROW["sbu_subbidang"],  col, _klasifikasi_ke_subbidang(data.get("sbu_klasifikasi", "")))

        # Syarat 3: Pengalaman
        pengalaman = data.get("pengalaman", [])
        _set(_ROW["pgl_hasil"], col, "Memenuhi" if pengalaman else "Tidak Memenuhi")
        if pengalaman:
            p1 = pengalaman[0]
            _set(_ROW["pgl1_nama"],    col, p1.get("nama", ""))
            _set(_ROW["pgl1_pemilik"], col, p1.get("instansi", ""))
            _set(_ROW["pgl1_nilai"],   col, p1.get("nilai", ""))
            _set(_ROW["pgl1_tanggal"], col,
                 f"{p1.get('tgl_mulai','')} s/d {p1.get('tgl_selesai','')}" if p1.get("tgl_mulai") else "")
            _set(_ROW["pgl1_nomor"],   col, p1.get("nomor", ""))
        if len(pengalaman) > 1:
            p2 = pengalaman[1]
            _set(_ROW["pgl2_nama"],    col, p2.get("nama", ""))
            _set(_ROW["pgl2_pemilik"], col, p2.get("instansi", ""))
            _set(_ROW["pgl2_nilai"],   col, p2.get("nilai", ""))
            _set(_ROW["pgl2_tanggal"], col,
                 f"{p2.get('tgl_mulai','')} s/d {p2.get('tgl_selesai','')}" if p2.get("tgl_mulai") else "")
            _set(_ROW["pgl2_nomor"],   col, p2.get("nomor", ""))

        # Syarat 4: SKP
        skp = data.get("skp", 5)
        skp_catatan = data.get("skp_catatan", f"{skp} SKP")
        _set(_ROW["skp_hasil"], col, "Memenuhi")
        _set(_ROW["skp_nilai"], col, skp_catatan)

        # Syarat 5: NPWP & KSWP
        _set(_ROW["npwp_nomor"],  col, _format_npwp(data.get("npwp", "")))
        _set(_ROW["kswp_status"], col, data.get("kswp_status", ""))

        # Syarat 6: Akta
        ap = data.get("akta_pendirian", {})
        ak = data.get("akta_perubahan", {})
        _set(_ROW["akta_pendirian_hasil"], col, "Memenuhi" if ap.get("nomor") else "")
        _set(_ROW["akta_p_nomor"],   col, ap.get("nomor", ""))
        _set(_ROW["akta_p_tanggal"], col, ap.get("tanggal", ""))
        _set(_ROW["akta_p_notaris"], col, ap.get("notaris", ""))
        _set(_ROW["akta_k_hasil"],   col, "Memenuhi" if ak.get("nomor") else "")
        _set(_ROW["akta_k_nomor"],   col, ak.get("nomor", ""))
        _set(_ROW["akta_k_tanggal"], col, ak.get("tanggal", ""))
        _set(_ROW["akta_k_notaris"], col, ak.get("notaris", ""))

        pemilik = data.get("pemilik", [])
        _set(_ROW["pemilik_label"], col, "Memenuhi" if pemilik else "")
        for pi, pk_row in enumerate([47, 48, 49, 50]):
            _set(pk_row, col, pemilik[pi] if pi < len(pemilik) else "-")

        # Syarat 7: SIKaP/Kinerja
        kinerja_ada = data.get("kinerja_ada", False)
        _set(_ROW["sikap_ada"],    col, "ADA" if kinerja_ada else "TIDAK MENYAMPAIKAN")
        if kinerja_ada:
            nilai_display = data.get("kinerja_nilai", "-")
            kat = data.get("kinerja_kategori", "")
            _set(_ROW["kinerja_nilai"], col,
                 f"{nilai_display} ({kat})" if kat and kat != "-" else nilai_display)
        else:
            _set(_ROW["kinerja_nilai"], col, "-")

        # Syarat 8: Daftar Hitam
        _set(_ROW["daftar_hitam"], col, "Memenuhi")

        # Hasil akhir MS/TMS
        _set(_ROW["hasil_ms"], col, _ms_tms(data))

    # Simpan
    _log("Menyimpan Excel...")
    try:
        wb.Save()
    except Exception as e:
        return {"ok": False, "pesan": f"Gagal simpan: {e}"}

    _log("✅ KK Evaluasi Kualifikasi berhasil diisi.")
    return {"ok": True, "pesan": f"Berhasil mengisi {len(semua_peserta)} peserta"}


# ── Helpers format ─────────────────────────────────────────────────────────────

def _format_npwp(npwp: str) -> str:
    """
    Format NPWP ke XX.XXX.XXX.X-XXX.XXX dari string digit mentah.
    Menerima 15 atau 16 digit (SPSE kadang kirim dengan leading zero ekstra).
    """
    if not npwp:
        return ""
    digits = re.sub(r"[^0-9]", "", str(npwp))
    # Jika 16 digit, strip leading zero jadi 15
    if len(digits) == 16 and digits[0] == "0":
        digits = digits[1:]
    if len(digits) == 15:
        return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}.{digits[8]}-{digits[9:12]}.{digits[12:15]}"
    return npwp  # panjang tidak standar — kembalikan apa adanya


def _format_sbu_label(klasifikasi: str, kualifikasi: str) -> str:
    """
    Konversi kode klasifikasi SPSE ke label Excel.
    Contoh: "F42101 - KONSTRUKSI BANGUNAN SIPIL JALAN|..." → "Subklasifikasi BS001 ..."
    """
    if not klasifikasi:
        return ""
    # Ambil kode pertama sebelum | atau ,
    kode = klasifikasi.split("|")[0].split(",")[0].strip()
    # Map kode KBLI ke subklasifikasi SBU (umum)
    _MAP = {
        "F42101": "BS001 (KBLI 2020) Konstruksi Bangunan Sipil Jalan",
        "F42201": "BS004 (KBLI 2020) Konstruksi Jaringan Irigasi dan Drainase",
        "F41011": "BG001 (KBLI 2020) Konstruksi Gedung Hunian",
        "F41012": "BG002 (KBLI 2020) Konstruksi Gedung Perkantoran",
    }
    for kbli, label in _MAP.items():
        if kbli in kode:
            return f"Subklasifikasi {label}"
    # Fallback: pakai teks apa adanya
    return kode


def _klasifikasi_ke_subbidang(klasifikasi: str) -> str:
    """Ambil nama subbidang dari string klasifikasi SPSE."""
    if not klasifikasi:
        return ""
    # Format SPSE: "F42101 - KONSTRUKSI BANGUNAN SIPIL JALAN|..."
    first = klasifikasi.split("|")[0]
    if " - " in first:
        return first.split(" - ", 1)[1].strip().title()
    return first.strip()
