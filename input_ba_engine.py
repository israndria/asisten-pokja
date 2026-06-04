"""
Engine pengisi sheet '0. Input BA' di Excel BA PK.

Pakai win32com agar format Excel tidak rusak (openpyxl dilarang untuk .xlsm).
Pola identik dengan kk_evaluasi_engine.fill_kk_evaluasi (gold standard).
"""

import os


# ── Konstanta baris sheet "0. Input BA" ─────────────────────────────────────
ROW_TGL_PEMBUKAAN  = 3
ROW_TGL_PEMBUKTIAN = 4

# Per peserta (kolom C=3, D=4, E=5)
ROW_NAMA_PERUSAHAAN = 7
ROW_NPWP            = 8
ROW_ALAMAT          = 9
ROW_DIREKTUR        = 10
ROW_PERSONEL_1      = 13
ROW_PERSONEL_2      = 14
ROW_ALAT_1          = 17
ROW_ALAT_2          = 18
ROW_ALAT_3          = 19
ROW_ALAT_4          = 20
ROW_ALAT_5          = 21
ROW_ALAT_6          = 22

# Dokumen penawaran (kolom C=3 saja)
ROW_JML_DAFTAR     = 25
ROW_JML_KIRIM      = 26
ROW_JML_TDK_KIRIM  = 27
ROW_JML_TDK_LENGKAP = 28
ROW_JML_TDK_BUKA   = 29

# JP (Pekerjaan Berjalan) & Hasil Pembuktian (per peserta, kolom C/D/E)
ROW_JP = 32
ROW_HASIL_PEMBUKTIAN = 33

# Nama bulan English (tanggal ditulis sebagai teks, locale-independent)
_BULAN_EN = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
# Nama hari Indonesia (weekday(): Senin=0 .. Minggu=6)
_HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _tgl_teks(tgl) -> str:
    """date/datetime → '25 May 2026' (teks English, bukan date object)."""
    import datetime as _dt
    if isinstance(tgl, (_dt.date, _dt.datetime)):
        return f"{tgl.day:02d} {_BULAN_EN[tgl.month]} {tgl.year}"
    return str(tgl)

# Kolom peserta: urutan → kolom Excel (C/D/E)
_COL_PESERTA = {1: 3, 2: 4, 3: 5}

# Baris NPWP harus format teks (cegah notasi ilmiah)
_TEXT_ROWS = {ROW_NPWP}

_SHEET_INPUT_BA  = "0. Input BA"
_SHEET_SKP_KLARIF = "6. BA KLARIF SKP ALAT"


def fill_input_ba(
    excel_path: str,
    peserta_rows: list,
    dokpen: dict | None,
    tgl_pembukaan,
    tgl_pembuktian,
    skp_rows: list | None = None,
    progress_cb=None,
) -> dict:
    """
    Isi sheet '0. Input BA' dan (opsional) cell W29 di '6. BA KLARIF SKP ALAT'.

    Args:
        excel_path    : path .xlsm absolut
        peserta_rows  : list dict maks 3, urut ranking KK Evaluasi.
                        Key tiap dict: nama_perusahaan, npwp, alamat, nama_direktur,
                        personel_1, personel_2, alat_1..alat_6
        dokpen        : dict atau None. Key: jml_daftar, jml_kirim, jml_tidak_kirim,
                        jml_tidak_lengkap, jml_tidak_dapat_dibuka
        tgl_pembukaan : datetime.date atau None
        tgl_pembuktian: datetime.date atau None
        skp_rows      : list dict per peserta (urut sama dgn peserta_rows) atau None.
                        Key: skp_catatan (int JP — jumlah pekerjaan berjalan), skp (int), hasil (str "Memenuhi"/"Tidak Memenuhi")
        progress_cb   : callback(msg: str) — opsional

    Return: {"ok": bool, "pesan": str}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass  # encode emoji ke console cp1252 bisa gagal, jangan abort

    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
    except ImportError:
        return {"ok": False, "pesan": "win32com tidak tersedia — pastikan WinPython dipakai"}

    # COM Excel butuh path absolut — relatif → "Sorry, we couldn't find ..."
    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        return {"ok": False, "pesan": f"File tidak ditemukan: {excel_path}"}

    _log(f"Membuka Excel: {os.path.basename(excel_path)}")

    xl = None
    wb = None
    try:
        # DispatchEx = instance Excel terisolasi, tidak ganggu file yang sedang dibuka user
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False

        wb = xl.Workbooks.Open(excel_path)
        ws = wb.Sheets(_SHEET_INPUT_BA)
    except Exception as e:
        if wb:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if xl:
            try:
                xl.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
        return {"ok": False, "pesan": f"Gagal buka Excel: {e}"}

    def _set(ws_obj, row, col, val):
        """Tulis nilai ke cell, format teks untuk baris NPWP."""
        try:
            cell = ws_obj.Cells(row, col)
            if row in _TEXT_ROWS:
                cell.NumberFormat = "@"
                if val is not None:
                    val = str(val)
            cell.Value = val
        except Exception:
            pass

    try:
        # Unprotect sheet utama (beberapa sheet BA protected)
        try:
            ws.Unprotect()
        except Exception:
            pass

        # ── Tanggal Pembukaan & Pembuktian (kolom C=3) ───────────────────────
        # Ditulis sebagai TEKS Indonesia ('25 Mei 2026'), bukan date object,
        # agar tidak bergantung locale Excel (menghindari 'May'/'June').
        import datetime
        if tgl_pembukaan is not None:
            _log(f"  Mengisi tanggal pembukaan: {tgl_pembukaan}")
            cell_buka = ws.Cells(ROW_TGL_PEMBUKAAN, 3)
            cell_buka.NumberFormat = "@"  # teks
            cell_buka.Value = _tgl_teks(tgl_pembukaan)
            # Kolom D = nama hari Indonesia
            if isinstance(tgl_pembukaan, (datetime.date, datetime.datetime)):
                cell_hari = ws.Cells(ROW_TGL_PEMBUKAAN, 4)
                cell_hari.NumberFormat = "@"
                cell_hari.Value = _HARI_ID[tgl_pembukaan.weekday()]

        if tgl_pembuktian is not None:
            _log(f"  Mengisi tanggal pembuktian: {tgl_pembuktian}")
            cell_bkt = ws.Cells(ROW_TGL_PEMBUKTIAN, 3)
            cell_bkt.NumberFormat = "@"
            cell_bkt.Value = _tgl_teks(tgl_pembuktian)
            if isinstance(tgl_pembuktian, (datetime.date, datetime.datetime)):
                cell_hari2 = ws.Cells(ROW_TGL_PEMBUKTIAN, 4)
                cell_hari2.NumberFormat = "@"
                cell_hari2.Value = _HARI_ID[tgl_pembuktian.weekday()]

        # ── Identitas peserta (kolom C/D/E per urutan) ───────────────────────
        for urutan, p in enumerate(peserta_rows[:3], 1):
            col = _COL_PESERTA[urutan]
            nama = p.get("nama_perusahaan", "")
            _log(f"  Mengisi peserta {urutan}: {nama}")

            _set(ws, ROW_NAMA_PERUSAHAAN, col, nama)
            _set(ws, ROW_NPWP,            col, p.get("npwp", ""))
            _set(ws, ROW_ALAMAT,          col, p.get("alamat", ""))
            _set(ws, ROW_DIREKTUR,        col, p.get("nama_direktur", ""))
            _set(ws, ROW_PERSONEL_1,      col, p.get("personel_1", ""))
            _set(ws, ROW_PERSONEL_2,      col, p.get("personel_2", ""))
            _set(ws, ROW_ALAT_1,          col, p.get("alat_1", ""))
            _set(ws, ROW_ALAT_2,          col, p.get("alat_2", ""))
            _set(ws, ROW_ALAT_3,          col, p.get("alat_3", ""))
            _set(ws, ROW_ALAT_4,          col, p.get("alat_4", ""))
            _set(ws, ROW_ALAT_5,          col, p.get("alat_5", ""))
            _set(ws, ROW_ALAT_6,          col, p.get("alat_6", ""))

        # ── Dokumen Penawaran (kolom C=3 saja) ───────────────────────────────
        if dokpen:
            _log("  Mengisi dokumen penawaran...")
            _set(ws, ROW_JML_DAFTAR,     3, dokpen.get("jml_daftar"))
            _set(ws, ROW_JML_KIRIM,      3, dokpen.get("jml_kirim"))
            _set(ws, ROW_JML_TDK_KIRIM,  3, dokpen.get("jml_tidak_kirim"))
            _set(ws, ROW_JML_TDK_LENGKAP, 3, dokpen.get("jml_tidak_lengkap"))
            _set(ws, ROW_JML_TDK_BUKA,   3, dokpen.get("jml_tidak_dapat_dibuka"))

        # ── JP (Pekerjaan Berjalan) & Hasil Pembuktian per peserta (kolom C/D/E) ──
        if skp_rows:
            for urutan, srow in enumerate(skp_rows[:3], 1):
                col = _COL_PESERTA[urutan]
                jp_val = srow.get("skp_catatan")  # sekarang berisi int JP dari parser
                if jp_val is None and srow.get("skp") is not None:
                    jp_val = 5 - int(srow.get("skp"))  # fallback kalkulasi JP dari SKP lama
                if jp_val is not None:
                    _set(ws, ROW_JP, col, jp_val)
                _hasil = srow.get("hasil", "")
                if _hasil:
                    _set(ws, ROW_HASIL_PEMBUKTIAN, col, _hasil)
            _log(f"  JP & Hasil Pembuktian: {len(skp_rows[:3])} peserta")

            # Port dari VBA: sheet 6 W29 = jp (jumlah pekerjaan berjalan, peserta 1).
            # Jangan pakai formula referensi → circular reference.
            _skp1 = skp_rows[0].get("skp")
            if _skp1 is not None:
                try:
                    ws6 = wb.Sheets(_SHEET_SKP_KLARIF)
                    try:
                        ws6.Unprotect()
                    except Exception:
                        pass
                    jp1 = 5 - int(_skp1)  # jp = 5 - skp
                    ws6.Range("W29").Value = jp1
                    _log(f"  Sheet 6 W29 = {jp1} (pekerjaan berjalan)")
                except Exception as e_ws6:
                    _log(f"  ⚠️ Sheet '{_SHEET_SKP_KLARIF}' tidak ditemukan/W29 gagal: {e_ws6}")

        # ── Simpan ────────────────────────────────────────────────────────────
        _log("Menyimpan Excel...")
        wb.Save()
        _log("Input BA berhasil diisi.")
        return {"ok": True, "pesan": f"Berhasil mengisi {len(peserta_rows[:3])} peserta"}

    except Exception as e:
        return {"ok": False, "pesan": f"Error saat menulis: {e}"}

    finally:
        # Anti-zombie: selalu close wb dan quit xl tanpa SaveChanges (sudah Save() di atas)
        if wb:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if xl:
            try:
                xl.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
