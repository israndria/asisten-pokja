"""
Engine pengisi sheet '0. Input BA' di Excel BA PK.

Pakai win32com agar format Excel tidak rusak (openpyxl dilarang untuk .xlsm).
Pola identik dengan kk_evaluasi_engine.fill_kk_evaluasi (gold standard).
"""

import os


# ── Konstanta baris sheet "0. Input BA" ─────────────────────────────────────
ROW_TGL_PEMBUKAAN  = 3
ROW_TGL_PEMBUKTIAN = 4
CELL_TGL_PENETAPAN = "G2"  # helper tanggal khusus BA Penetapan Pemenang

# Layout kanonik peserta berada di matrix C37:L53 (maksimal 10 peserta).
# Baris 7:33 adalah compatibility view untuk BA lama; engine tidak menulis
# langsung ke view tersebut.
MAX_PARTICIPANTS = 10
MATRIX_HEADER_ROW = 37
MATRIX_FIRST_ROW = 38
MATRIX_LAST_ROW = 53
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
ROW_HARGA_PENAWARAN = 11
ROW_HARGA_TERKOREKSI = 12

# JP (Pekerjaan Berjalan) & Hasil Pembuktian (per peserta)
ROW_JP = 32
ROW_HASIL_PEMBUKTIAN = 33
MATRIX_ROW_JP = 52
MATRIX_ROW_HASIL_PEMBUKTIAN = 53

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

# Kolom peserta kanonik: urutan 1..10 → C:L.
_COL_PESERTA = {urutan: urutan + 2 for urutan in range(1, MAX_PARTICIPANTS + 1)}
_LEGACY_VIEW_COLS = {1: 3, 2: 4, 3: 5, 4: 9}  # C/D/E + I
_LEGACY_VIEW_ROWS = {
    ROW_NAMA_PERUSAHAAN: 38,
    ROW_NPWP: 39,
    ROW_ALAMAT: 40,
    ROW_DIREKTUR: 41,
    ROW_HARGA_PENAWARAN: 42,
    ROW_HARGA_TERKOREKSI: 43,
    ROW_PERSONEL_1: 44,
    ROW_PERSONEL_2: 45,
    ROW_ALAT_1: 46,
    ROW_ALAT_2: 47,
    ROW_ALAT_3: 48,
    ROW_ALAT_4: 49,
    ROW_ALAT_5: 50,
    ROW_ALAT_6: 51,
    ROW_JP: 52,
    ROW_HASIL_PEMBUKTIAN: 53,
}
_PESERTA_LAYOUT_ROWS = (
    ROW_NAMA_PERUSAHAAN, ROW_NPWP, ROW_ALAMAT, ROW_DIREKTUR,
    ROW_PERSONEL_1, ROW_PERSONEL_2,
    ROW_ALAT_1, ROW_ALAT_2, ROW_ALAT_3, ROW_ALAT_4, ROW_ALAT_5, ROW_ALAT_6,
    ROW_JP, ROW_HASIL_PEMBUKTIAN,
)

# Baris NPWP harus format teks (cegah notasi ilmiah)
_TEXT_ROWS = {ROW_NPWP, 39}  # view lama + NPWP pada matrix kanonik

_SHEET_INPUT_BA  = "0. Input BA"
_SHEET_SKP_KLARIF = "6. BA KLARIF SKP ALAT"


def _ensure_input_ba_layout(ws, participant_count: int) -> None:
    """Provision matrix 10 peserta + compatibility view secara idempotent."""
    # Header matrix selalu lengkap agar dropdown dan referensi formula stabil,
    # walaupun paket hanya mempunyai 1-3 peserta.
    ws.Cells(36, 2).Value = "DATABASE PESERTA (MAKSIMAL 10)"
    ws.Cells(37, 2).Value = "Data"
    for urutan, col in _COL_PESERTA.items():
        ws.Cells(MATRIX_HEADER_ROW, col).Value = f"Peserta {urutan}"
        ws.Cells(MATRIX_HEADER_ROW, col).Font.Bold = True

    # C5 memilih peserta; F5 menyimpan index 1..10 untuk seluruh formula BA.
    if not ws.Cells(5, 3).Value:
        ws.Cells(5, 3).Value = "Peserta 1"
    ws.Cells(5, 6).Formula = '=IFERROR(MATCH($C$5,$C$37:$L$37,0),1)'
    try:
        ws.Range("C5").Validation.Delete()
        ws.Range("C5").Validation.Add(
            Type=3, AlertStyle=1, Operator=1, Formula1="=$C$37:$L$37"
        )
    except Exception:
        pass

    # G = peserta terpilih; C/D/E/I = view compatibility slot 1..4.
    for view_row, matrix_row in _LEGACY_VIEW_ROWS.items():
        ws.Cells(view_row, 7).Formula = (
            f'=IF(INDEX($C${matrix_row}:$L${matrix_row},1,$F$5)="","",'
            f'INDEX($C${matrix_row}:$L${matrix_row},1,$F$5))'
        )
        for urutan, legacy_col in _LEGACY_VIEW_COLS.items():
            matrix_col = chr(ord("C") + urutan - 1)
            ws.Cells(view_row, legacy_col).Formula = f"={matrix_col}${matrix_row}"


def fill_input_ba(
    excel_path: str,
    peserta_rows: list,
    dokpen: dict | None,
    tgl_pembukaan,
    tgl_pembuktian,
    tgl_penetapan=None,
    skp_rows: list | None = None,
    progress_cb=None,
) -> dict:
    """
    Isi sheet '0. Input BA' dan (opsional) cell W29 di '6. BA KLARIF SKP ALAT'.

    Args:
        excel_path    : path .xlsm absolut
        peserta_rows  : list dict, urut ranking KK Evaluasi. Maksimal 10
                        peserta ditulis ke matrix kanonik C:L.
                        Key tiap dict: nama_perusahaan, npwp, alamat, nama_direktur,
                        personel_1, personel_2, alat_1..alat_6
        dokpen        : dict atau None. Key: jml_daftar, jml_kirim, jml_tidak_kirim,
                        jml_tidak_lengkap, jml_tidak_dapat_dibuka
        tgl_pembukaan : datetime.date atau None
        tgl_pembuktian: datetime.date atau None
        tgl_penetapan : datetime.date atau None; khusus BA Penetapan Pemenang
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
        peserta_rows = list(peserta_rows or [])
        peserta_dibatasi = max(0, len(peserta_rows) - MAX_PARTICIPANTS)
        if peserta_dibatasi:
            _log(
                f"  ⚠️ {peserta_dibatasi} peserta di luar kapasitas; "
                f"Input BA dibatasi maksimal {MAX_PARTICIPANTS}."
            )
        peserta_rows = peserta_rows[:MAX_PARTICIPANTS]
        _ensure_input_ba_layout(ws, len(peserta_rows))

        # Bersihkan data kanonik lama yang memang dikelola proses ini. Harga
        # (42:43) dipertahankan untuk peserta aktif karena berasal dari Sheet
        # 6/evaluasi harga. Slot di luar peserta aktif wajib ikut dibersihkan
        # agar workbook yang pernah memuat 10 peserta tidak meninggalkan data.
        ws.Range("C38:L41").ClearContents()
        ws.Range("C44:L53").ClearContents()
        harga_clear_start = 3 + len(peserta_rows)
        if harga_clear_start <= 12:
            ws.Range(
                ws.Cells(42, harga_clear_start),
                ws.Cells(43, 12),
            ).ClearContents()

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

        # Penetapan tidak selalu berlangsung pada hari pembuktian. Simpan di
        # helper terpisah agar BA Pembuktian/Klarifikasi tetap memakai C4.
        if tgl_penetapan is not None:
            _log(f"  Mengisi tanggal penetapan: {tgl_penetapan}")
            cell_pen = ws.Cells(2, 7)  # G2
            cell_pen.NumberFormat = "dd mmmm yyyy"
            # Tulis serial Excel, bukan datetime COM, agar timezone WITA tidak
            # menggeser 27 Juli menjadi 26 Juli 16:00.
            _d_pen = tgl_penetapan.date() if isinstance(tgl_penetapan, datetime.datetime) else tgl_penetapan
            cell_pen.Value = (_d_pen - datetime.date(1899, 12, 30)).days

        # ── Identitas peserta (matrix kanonik C:L) ──────────────────────────
        peserta_ditulis = 0
        for urutan, p in enumerate(peserta_rows, 1):
            col = _COL_PESERTA[urutan]
            nama = p.get("nama_perusahaan", "")
            _log(f"  Mengisi peserta {urutan}: {nama}")
            peserta_ditulis += 1

            values = {
                38: nama,
                39: p.get("npwp", ""),
                40: p.get("alamat", ""),
                41: p.get("nama_direktur", ""),
                44: p.get("personel_1", ""),
                45: p.get("personel_2", ""),
                46: p.get("alat_1", ""),
                47: p.get("alat_2", ""),
                48: p.get("alat_3", ""),
                49: p.get("alat_4", ""),
                50: p.get("alat_5", ""),
                51: p.get("alat_6", ""),
            }
            # Harga boleh dibawa caller, tetapi tidak dipaksa kosong bila
            # sumbernya sudah ditulis oleh engine Sheet 6.
            if "harga_penawaran" in p:
                values[42] = p.get("harga_penawaran")
            if "harga_terkoreksi" in p:
                values[43] = p.get("harga_terkoreksi")
            for row, value in values.items():
                _set(ws, row, col, value)

        # ── Dokumen Penawaran (kolom C=3 saja) ───────────────────────────────
        if dokpen:
            _log("  Mengisi dokumen penawaran...")
            _set(ws, ROW_JML_DAFTAR,     3, dokpen.get("jml_daftar"))
            _set(ws, ROW_JML_KIRIM,      3, dokpen.get("jml_kirim"))
            _set(ws, ROW_JML_TDK_KIRIM,  3, dokpen.get("jml_tidak_kirim"))
            _set(ws, ROW_JML_TDK_LENGKAP, 3, dokpen.get("jml_tidak_lengkap"))
            _set(ws, ROW_JML_TDK_BUKA,   3, dokpen.get("jml_tidak_dapat_dibuka"))

        # ── JP (Pekerjaan Berjalan) & Hasil Pembuktian per peserta ───────────
        if skp_rows:
            skp_ditulis = 0
            for urutan, srow in enumerate(list(skp_rows)[:MAX_PARTICIPANTS], 1):
                col = _COL_PESERTA[urutan]
                jp_val = srow.get("skp_catatan")  # sekarang berisi int JP dari parser
                if jp_val is None and srow.get("skp") is not None:
                    jp_val = 5 - int(srow.get("skp"))  # fallback kalkulasi JP dari SKP lama
                if jp_val is not None:
                    _set(ws, MATRIX_ROW_JP, col, jp_val)
                _hasil = srow.get("hasil", "")
                if _hasil:
                    _set(ws, MATRIX_ROW_HASIL_PEMBUKTIAN, col, _hasil)
                skp_ditulis += 1
            _log(f"  JP & Hasil Pembuktian: {skp_ditulis} peserta")

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
        pesan = f"Berhasil mengisi {peserta_ditulis} peserta"
        if peserta_dibatasi:
            pesan += f"; {peserta_dibatasi} peserta di luar batas maksimal {MAX_PARTICIPANTS}"
        return {"ok": True, "pesan": pesan}

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
