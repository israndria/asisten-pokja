"""
Engine pengisi sheet '3. KK Evaluasi Kualifikasi' di Excel BA PK.

Pakai win32com agar format Excel tidak rusak. Kapasitas arsitektur dibatasi
10 peserta; slot tambahan disisipkan sebelum kolom helper tersembunyi pertama.
"""

import os
import re

# Tiga slot lama: C/D/E. Slot tambahan dibuat dinamis menjadi F/G/...
_BASE_PESERTA_SLOTS = 3
MAX_PARTICIPANTS = 10
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
    "skp_jp":         31,   # jumlah paket berjalan (0 jika tidak ada)
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


def _format_kinerja(nilai, kategori) -> str:
    """Normalisasi tampilan nilai kinerja tanpa tanda kurung kosong/ganda."""
    value = str(nilai or "").strip()
    value = re.sub(r"\s*\(\s*\)\s*$", "", value).strip()
    kat = str(kategori or "").strip()
    if kat and kat not in {"-", "()"} and f"({kat})".lower() not in value.lower():
        value = f"{value} ({kat})" if value else kat
    return value


def _is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


def _find_helper_column(ws, start_col: int = 6, max_col: int = 16384) -> int:
    """Cari kolom helper pertama setelah slot peserta C:E.

    Template aktif memakai F3 sebagai formula helper. Setelah slot tambahan
    disisipkan, formula tersebut bergeser ke kanan. Ini membuat provisioning
    idempotent tanpa marker tambahan di workbook.
    """
    for col in range(start_col, max_col + 1):
        try:
            if _is_formula(ws.Cells(3, col).Formula):
                return col
        except Exception:
            continue
    return start_col


def _ensure_participant_columns(ws, participant_count: int, progress_cb=None) -> dict[int, int]:
    """Pastikan sheet KK punya satu kolom aman per peserta.

    Kolom F dan seterusnya pada template lama berisi helper tersembunyi.
    Karena itu kolom baru disisipkan tepat sebelum helper, lalu hanya format
    kolom peserta terakhir (E) yang disalin. Tidak menimpa helper existing.
    """
    wanted = min(MAX_PARTICIPANTS, max(_BASE_PESERTA_SLOTS, int(participant_count or 0)))
    helper_col = _find_helper_column(ws)
    while helper_col <= 2 + wanted:
        source_col = 5  # slot peserta 3, format referensi stabil
        ws.Columns(helper_col).Insert()
        try:
            ws.Columns(source_col).Copy()
            ws.Columns(helper_col).PasteSpecial(Paste=-4122)  # xlPasteFormats
            ws.Application.CutCopyMode = False
        except Exception:
            # Data tetap bisa ditulis bila Excel menolak clipboard format.
            pass
        try:
            ws.Columns(helper_col).ColumnWidth = ws.Columns(source_col).ColumnWidth
        except Exception:
            pass
        helper_col += 1

    return {urutan: 2 + urutan for urutan in range(1, wanted + 1)}


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
    semua_peserta = list(semua_peserta or [])
    peserta_dibatasi = max(0, len(semua_peserta) - MAX_PARTICIPANTS)
    semua_peserta = semua_peserta[:MAX_PARTICIPANTS]

    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass  # callback error (mis. encode emoji ke console) tak boleh abort write

    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
    except ImportError:
        return {"ok": False, "pesan": "win32com tidak tersedia — pastikan WinPython dipakai"}

    # Excel COM butuh path absolut — relatif → "Sorry, we couldn't find ..."
    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        return {"ok": False, "pesan": f"File tidak ditemukan: {excel_path}"}

    _log(f"Membuka Excel: {os.path.basename(excel_path)}")

    xl = None
    wb = None
    try:
        # DispatchEx = instance Excel terisolasi, tidak ganggu file user yang sedang terbuka
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False

        wb = xl.Workbooks.Open(excel_path)
        ws = wb.Sheets(_SHEET_NAME)
    except Exception as e:
        if wb:
            try: wb.Close(SaveChanges=False)
            except Exception: pass
        if xl:
            try: xl.Quit()
            except Exception: pass
        try: pythoncom.CoUninitialize()
        except Exception: pass
        return {"ok": False, "pesan": f"Gagal buka Excel: {e}"}

    # Baris yang harus diformat teks:
    #  - tanggal akta (jangan diinterpretasi Excel sebagai tanggal)
    #  - SEMUA nomor panjang (NIB/SS/PBUMKU/NPWP/akta/kontrak) → cegah notasi
    #    ilmiah (mis. 9120111234567 → 9,12011E+12) dan hilangnya leading zero.
    _TEXT_ROWS = {
        _ROW["akta_p_tanggal"], _ROW["akta_k_tanggal"],
        _ROW["nib_nomor"], _ROW["ss_nomor"], _ROW["sbu_pbumku"],
        _ROW["npwp_nomor"], _ROW["akta_p_nomor"], _ROW["akta_k_nomor"],
        _ROW["pgl1_nomor"], _ROW["pgl2_nomor"],
    }

    def _set(row, col, val):
        try:
            cell = ws.Cells(row, col)
            if row in _TEXT_ROWS:
                cell.NumberFormat = "@"
                # paksa string agar Excel tidak meng-cast ke float (scientific)
                if val is not None:
                    val = str(val)
            cell.Value = val
        except Exception:
            pass

    try:
        try:
            ws.Unprotect()
        except Exception:
            pass
        if peserta_dibatasi:
            _log(
                f"⚠️ {peserta_dibatasi} peserta di luar kapasitas; "
                f"KK Evaluasi dibatasi maksimal {MAX_PARTICIPANTS}."
            )
        col_peserta = _ensure_participant_columns(ws, len(semua_peserta), progress_cb)

        # Jika workbook sebelumnya memuat 10 peserta lalu sekarang hanya 4,
        # slot lama di antara peserta aktif dan helper juga harus dibersihkan.
        # Batas helper aman: tidak menyentuh kolom formula tersembunyi.
        helper_col = _find_helper_column(ws)
        last_provisioned_col = min(2 + MAX_PARTICIPANTS, helper_col - 1)
        ws.Range(
            ws.Cells(3, 3),
            ws.Cells(54, last_provisioned_col),
        ).ClearContents()

        for urutan, data in enumerate(semua_peserta, 1):
            if not data.get("ok"):
                _log(f"  Peserta {urutan}: data tidak lengkap, skip")
                continue

            col = col_peserta[urutan]

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
            jp = data.get("skp_jp", 5 - skp)   # jumlah paket berjalan
            skp_catatan = data.get("skp_catatan")  # int JP dari parser baru
            if skp_catatan is None:
                skp_catatan = jp  # fallback: pakai jp langsung
            _set(_ROW["skp_hasil"], col, "Memenuhi")
            _set(_ROW["skp_jp"],    col, jp if jp > 0 else 0)
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
                # Slot pemilik yang tidak ada harus benar-benar kosong.
                # Placeholder "-"/blank yang ditranspose Excel dapat muncul
                # sebagai 0 di sheet satu_data dan ikut tercetak di Word.
                _set(pk_row, col, pemilik[pi] if pi < len(pemilik) else "")

            # Syarat 7: SIKaP/Kinerja
            kinerja_ada = data.get("kinerja_ada", False)
            _set(_ROW["sikap_ada"],    col, "ADA" if kinerja_ada else "TIDAK MENYAMPAIKAN")
            if kinerja_ada:
                nilai_display = data.get("kinerja_nilai", "-")
                kat = data.get("kinerja_kategori", "")
                _set(_ROW["kinerja_nilai"], col, _format_kinerja(nilai_display, kat))
            else:
                _set(_ROW["kinerja_nilai"], col, "-")

            # Syarat 8: Daftar Hitam
            _set(_ROW["daftar_hitam"], col, "Memenuhi")

            # Hasil akhir MS/TMS
            _set(_ROW["hasil_ms"], col, _ms_tms(data))

        # Simpan
        _log("Menyimpan Excel...")
        wb.Save()
        _log("✅ KK Evaluasi Kualifikasi berhasil diisi.")
        pesan = f"Berhasil mengisi {len(semua_peserta)} peserta"
        if peserta_dibatasi:
            pesan += f"; {peserta_dibatasi} peserta di luar batas maksimal {MAX_PARTICIPANTS}"
        return {"ok": True, "pesan": pesan}

    except Exception as e:
        return {"ok": False, "pesan": f"Error saat menulis: {e}"}

    finally:
        # Anti-zombie: selalu close wb dan quit xl
        if wb:
            try: wb.Close(SaveChanges=False)
            except Exception: pass
        if xl:
            try: xl.Quit()
            except Exception: pass
        try: pythoncom.CoUninitialize()
        except Exception: pass


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
