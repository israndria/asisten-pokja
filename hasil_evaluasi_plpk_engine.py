"""
Engine populate sheet "Hasil Evaluasi" di BAPLPK .xlsm via COM.

ATURAN:
- WAJIB COM (win32com.client) untuk write .xlsm — openpyxl.save() corrupt VBA
- Backup .xlsm sebelum open
- Cek EXCEL.EXE running — skip jika ada
- DispatchEx (instance baru, bukan Dispatch)
- JANGAN sentuh sheet @ Master Data, @ Evaluasi, atau sheet lain
"""

import os
import re
import subprocess

from config import POKJA_ROOT


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slug(nama: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", nama).strip()[:80]


def _normalize_notary(value: str) -> str:
    """Normalisasi typo OCR/HTML pada gelar notaris tanpa mengubah nama."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"M\.K[Nn]{1,2}\b", "M.Kn.", text, flags=re.IGNORECASE)
    return text


def _excel_running() -> bool:
    """Return True jika EXCEL.EXE sedang berjalan (cek via WMIC atau lock file ~$)."""
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", "Name='EXCEL.EXE'", "get", "Name"],
            timeout=5, stderr=subprocess.DEVNULL
        )
        return b"EXCEL" in out
    except Exception:
        pass
    try:
        out = subprocess.check_output("tasklist /FI \"IMAGENAME eq EXCEL.EXE\"", shell=True, timeout=5)
        return b"EXCEL.EXE" in out
    except Exception:
        return False


def _xlsm_locked(xlsm_path: str) -> bool:
    """Cek apakah .xlsm sedang terbuka via lock file ~$ prefix."""
    folder = os.path.dirname(xlsm_path)
    lock_name = "~$" + os.path.basename(xlsm_path)
    return os.path.exists(os.path.join(folder, lock_name))


def _hapus_lock_orphan(xlsm_path: str, log=None) -> bool:
    """
    Cek & hapus lock file orphan (~$<basename>) jika Excel tidak beneran jalan.
    Return True  = aman lanjut (tidak ada lock, atau orphan berhasil dihapus).
    Return False = lock ada DAN Excel sedang jalan (jangan hapus, tolak proses).
    """
    folder    = os.path.dirname(xlsm_path)
    lock_name = "~$" + os.path.basename(xlsm_path)
    lock_path = os.path.join(folder, lock_name)

    if not os.path.exists(lock_path):
        return True  # tidak ada lock, aman

    if _excel_running():
        return False  # Excel jalan + lock ada = beneran terbuka, tolak

    # Lock ada tapi Excel mati → orphan, hapus
    try:
        os.remove(lock_path)
        if log:
            log(f"[INFO] Lock orphan dihapus: {lock_name}")
    except Exception as e:
        if log:
            log(f"[WARN] Gagal hapus lock orphan ({lock_name}): {e}")
        # Tetap lanjut — mungkin sudah hilang sendiri
    return True


def _find_xlsm(kode_paket: str) -> str:
    """Cari workbook PL sesuai keluarga paket: BAPLPK atau BAPLJKK."""
    try:
        from config import sb
        r = sb().table("draft_paket_pl").select(
            "kode_paket,nama_paket,jenis_pl,nomor_urut,is_ulang"
        ).eq("kode_paket", kode_paket).maybe_single().execute()
        if not r.data:
            return ""

        import parse_kak_pl as _pkl
        row = r.data
        folder_paket, _ = _pkl._resolve_folder_pl(
            row.get("nomor_urut", ""), row.get("nama_paket", ""), row.get("jenis_pl", "PK"),
            is_ulang=row.get("is_ulang", False)
        )
        if not folder_paket or not os.path.isdir(folder_paket):
            return ""

        _jenis_pl = str(row.get("jenis_pl") or "PK").upper()
        _workbook_prefix = "0. BAPLJKK" if _jenis_pl == "JKK" else "0. BAPLPK"
        for f in os.listdir(folder_paket):
            if (f.startswith(_workbook_prefix) and f.endswith(".xlsm")
                    and ".backup" not in f and not f.startswith("~$")):
                return os.path.join(folder_paket, f)
        return ""
    except Exception:
        return ""


def _build_rows_peserta(peserta_data: dict, kode_paket: str, no_start: int) -> list:
    """
    Build list of rows untuk sheet Hasil Evaluasi dari data parse_peserta_lengkap_pl.
    Setiap row: [No, Field, Kategori, Sumber, Status, Catatan]
    """
    rows = []
    no = no_start

    def _r(field, kategori, sumber, status="PERIKSA", catatan=""):
        nonlocal no
        rows.append([no, field, kategori, sumber, status, catatan])
        no += 1

    nama = peserta_data.get("nama", "")

    # ── HEADER PESERTA ─────────────────────────────────────────────────────────
    rows.append([no, f"[ {nama} ]", "PESERTA", "", "", ""])
    no += 1

    # ── Administrasi ───────────────────────────────────────────────────────────
    _r("Nama Perusahaan", "Administrasi", "preview t0", "ADA" if nama else "PERIKSA", nama)
    # NPWP: prefix ' agar Excel tidak convert ke scientific notation
    _npwp_raw = str(peserta_data.get("npwp", "") or "")
    _npwp_val = ("'" + _npwp_raw) if _npwp_raw.replace(".", "").replace("-", "").isdigit() else _npwp_raw
    _r("NPWP", "Administrasi", "preview t0", catatan=_npwp_val)
    _r("Alamat", "Administrasi", "preview t0", catatan=peserta_data.get("alamat", ""))
    _r("Email", "Administrasi", "preview t0", catatan=peserta_data.get("email", ""))

    nib_nomor  = peserta_data.get("nib_nomor", "")
    nib_berlaku = peserta_data.get("nib_berlaku", "")
    _r("NIB Nomor + Masa Berlaku", "Administrasi", "preview t1",
       "ADA" if nib_nomor else "PERIKSA", f"{nib_nomor} s/d {nib_berlaku}" if nib_nomor else "")

    ss_nomor = peserta_data.get("ss_nomor", "")
    ss_berlaku = peserta_data.get("ss_berlaku", "")
    ss_kual = peserta_data.get("ss_kualifikasi", "")
    _r("Sertifikat Standar Kualifikasi", "Administrasi", "preview t1",
       peserta_data.get("ss_terverifikasi", "PERIKSA"),
       f"{ss_nomor} s/d {ss_berlaku} ({ss_kual})" if ss_nomor else "")

    sbu_nomor = peserta_data.get("sbu_nomor", "")
    sbu_kual  = peserta_data.get("sbu_kualifikasi", "")
    sbu_label = peserta_data.get("sbu_subklas_label", "")
    sbu_berlaku = peserta_data.get("sbu_berlaku", "")
    _r("SBU Nomor + Subklasifikasi + Kualifikasi", "Administrasi", "preview t1",
       "ADA" if sbu_nomor else "TIDAK ADA",
       f"{sbu_nomor} | {sbu_label} | {sbu_kual} | s/d {sbu_berlaku}" if sbu_nomor else "")

    akta_p = peserta_data.get("akta_pendirian", {})
    _notaris_p = _normalize_notary(akta_p.get("notaris", ""))
    _r("Akta Pendirian", "Administrasi", "preview t2",
       catatan=f"No. {akta_p.get('nomor','')} tgl {akta_p.get('tanggal','')} — {_notaris_p}" if akta_p else "")

    akta_u = peserta_data.get("akta_perubahan", {})
    _notaris_u = _normalize_notary(akta_u.get("notaris", ""))
    _r("Akta Perubahan Terakhir", "Administrasi", "preview t2",
       catatan=f"No. {akta_u.get('nomor','')} tgl {akta_u.get('tanggal','')} — {_notaris_u}" if akta_u else "")

    # Direktur: prioritas dari PDF (direktur_pdf), fallback pemilik[0] (sudah ter-filter nama PT)
    _direktur_pdf = peserta_data.get("direktur_pdf", "")
    pemilik = peserta_data.get("pemilik", [])
    direktur_utama = _direktur_pdf if _direktur_pdf else (pemilik[0] if pemilik else "")
    direktur_utama = re.sub(
        r"^Nama\s+Lengkap\s*[:\-]?\s*|\s+Jabatan\s*$", "",
        str(direktur_utama or ""), flags=re.IGNORECASE
    ).strip()
    # Satu nama saja — TIDAK tampilkan "(+ N lain)" supaya bersih untuk mail-merge
    _r("Direktur Utama/Pimpinan", "Administrasi", "PDF/preview t3",
       "ADA" if direktur_utama else "PERIKSA",
       direktur_utama)

    # ── Teknis JKK ─────────────────────────────────────────────────────────────
    personel = peserta_data.get("personel_list", [])
    if personel:
        _r("Team Leader", "Teknis JKK", "table-tenaga-ahli row 1", catatan=personel[0] if len(personel) > 0 else "")
        _r("Petugas/Ahli K3", "Teknis JKK", "table-tenaga-ahli row 2", catatan=personel[1] if len(personel) > 1 else "-")
        for i, p in enumerate(personel[2:], 3):
            _r(f"Tenaga Ahli {i}", "Teknis JKK", f"table-tenaga-ahli row {i}", catatan=p)
    else:
        _r("Team Leader", "Teknis JKK", "table-tenaga-ahli", catatan="(tidak ada data personel)")
        _r("Petugas/Ahli K3", "Teknis JKK", "table-tenaga-ahli", catatan="(tidak ada data personel)")

    pengalaman = peserta_data.get("pengalaman", [])
    pengalaman_str = ""
    if pengalaman:
        pengalaman_str = "; ".join(
            f"{p.get('nama','')} ({p.get('tgl_mulai','')}-{p.get('tgl_selesai','')})"
            for p in pengalaman[:3]
        )
    _r("Pengalaman Sejenis 3 Tahun", "Teknis JKK", "section PENGALAMAN",
       "ADA" if pengalaman else "TIDAK ADA", pengalaman_str)

    jp_berjalan = peserta_data.get("jp_preview", 0)
    _r("Pekerjaan Sedang Berjalan", "Teknis JKK", "section PEKERJAAN BERJALAN",
       catatan=f"{jp_berjalan} paket berjalan")

    # Cross-check SBU dengan syarat paket
    sbu_match_status = "PERIKSA"
    sbu_match_catatan = ""
    try:
        from config import sb
        r = sb().table("draft_paket_pl").select("sbu_baru").eq("kode_paket", kode_paket).maybe_single().execute()
        if r.data and r.data.get("sbu_baru"):
            sbu_syarat_raw = r.data["sbu_baru"]
            if isinstance(sbu_syarat_raw, list):
                sbu_syarat_items = [str(s) for s in sbu_syarat_raw]
            else:
                sbu_syarat_items = [str(sbu_syarat_raw)]

            # Ekstrak kode SBU dari string panjang: "Subklasifikasi RK003 (KBLI 2020) ..."
            # → kode = token yang cocok pola [A-Z]{1,3}[0-9]{3}
            def _ekstrak_kode_sbu(teks):
                m = re.search(r'\b([A-Z]{1,3}[0-9]{3})\b', teks.upper())
                return m.group(1) if m else teks.upper().strip()

            sbu_syarat_kodes = [_ekstrak_kode_sbu(s) for s in sbu_syarat_items]

            # Kode SBU peserta: dari sbu_label (SPSE) + dari bidang pengalaman di dok PDF
            sbu_peserta_kode_spse = (sbu_label.split(" - ")[0].strip().upper() if sbu_label else "")
            sbu_dari_pdf = peserta_data.get("bidang_pengalaman_pdf", [])  # kode2 dari dok PQ

            # Cocok jika kode SPSE match, ATAU ada kode dari dok PDF yang match syarat
            cocok_spse = sbu_peserta_kode_spse in sbu_syarat_kodes
            cocok_pdf  = any(k in sbu_syarat_kodes for k in sbu_dari_pdf)
            cocok = cocok_spse or cocok_pdf

            sbu_match_status = "MEMENUHI" if cocok else "TIDAK MEMENUHI"
            _pdf_kode_str = ", ".join(sbu_dari_pdf) if sbu_dari_pdf else "-"
            _spse_label = sbu_peserta_kode_spse
            if _spse_label.startswith("M7"):
                _spse_label += " (KBLI/aktivitas)"
            sbu_match_catatan = (
                f"Label/kode SPSE: {_spse_label} | "
                f"Kode bidang dok PQ: {_pdf_kode_str} | "
                f"Syarat: {', '.join(sbu_syarat_kodes)}"
            )
    except Exception:
        pass
    _r("Sub-bidang KAK match SBU", "Teknis JKK", "cross-check draft_paket_pl.sbu_baru",
       sbu_match_status, sbu_match_catatan)

    # ── Kualifikasi ────────────────────────────────────────────────────────────
    kswp = peserta_data.get("kswp_status", "TIDAK DIKETAHUI")
    _r("KSWP", "Kualifikasi", "PDF KSWP / DOM preview",
       "VALID" if kswp == "VALID" else "PERIKSA", kswp)

    kinerja_ada = peserta_data.get("kinerja_ada", False)
    kinerja_nilai = peserta_data.get("kinerja_nilai", "-")
    kinerja_kat = peserta_data.get("kinerja_kategori", "-")
    _r("Kinerja Penyedia", "Kualifikasi", "PDF Penilaian Kinerja",
       "ADA" if kinerja_ada else "PERIKSA",
       f"{kinerja_nilai} ({kinerja_kat})" if kinerja_ada else "-")

    skp = peserta_data.get("skp", 5)
    _r("SKP (Sisa Kemampuan Paket)", "Kualifikasi", "NPWP lookup V20",
       "CUKUP" if skp >= 1 else "HABIS",
       f"SKP = {skp} (JP berjalan: {jp_berjalan})")

    return rows


# ── Entry point ────────────────────────────────────────────────────────────────

def populate_hasil_evaluasi_pl(
    kode_paket: str,
    peserta_list: list,
    progress_cb=None,
) -> dict:
    """
    Parse preview kualifikasi tiap peserta PL + populate sheet "Hasil Evaluasi" di .xlsm.

    Args:
        kode_paket   : kode paket PL (draft_paket_pl.kode_paket)
        peserta_list : [{"nama","kualifikasi_id","kode_paket"}] dari fetch_peserta_pl
        progress_cb  : callback(pesan: str)

    Return: {"ok": bool, "pesan": str, "rows_written": int}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    # 1. Temukan path .xlsm
    xlsm_path = _find_xlsm(kode_paket)
    _workbook_label = "BAPLPK"
    if not xlsm_path:
        return {"ok": False, "pesan": f"File {_workbook_label} .xlsm tidak ditemukan di folder paket.", "rows_written": 0}

    # 2. Cek Excel running / file locked
    # Lock ada DAN Excel jalan = beneran dibuka user → tolak
    if _excel_running() and _xlsm_locked(xlsm_path):
        return {"ok": False, "pesan": f"Excel sedang berjalan + file {_workbook_label} terkunci. Tutup Excel dulu.", "rows_written": 0}
    # Lock orphan (Excel mati tapi lock nyangkut dari crash sebelumnya) → hapus otomatis
    if _xlsm_locked(xlsm_path):
        _hapus_lock_orphan(xlsm_path, _log)

    # 3. Parse tiap peserta
    import kualifikasi_parser_pl as _kpp

    all_rows = []
    peserta_md = []  # kumpul per-penyedia untuk export MD
    for idx, peserta in enumerate(peserta_list, 1):
        nama = peserta.get("nama", "")
        kual_id = peserta.get("kualifikasi_id", "")
        _log(f"[{idx}/{len(peserta_list)}] Parse: {nama}")

        # Resolve folder peserta (untuk cari file PDF KSWP, kinerja, dsb)
        from kualifikasi_engine_plpk import resolve_folder_paket_pl, _slug
        folder_info = resolve_folder_paket_pl(kode_paket)
        folder_kual = folder_info.get("path", "")
        folder_peserta = os.path.join(folder_kual, f"{idx}. {_slug(nama)}") if folder_kual else ""

        peserta_data = _kpp.parse_peserta_lengkap_pl(kual_id, folder_peserta, _log)
        if not peserta_data.get("ok"):
            _log(f"  ⚠️ Gagal parse: {peserta_data.get('pesan','')}")
            peserta_data = {
            "ok": False, "nama": nama,
            "npwp": "", "alamat": "", "email": "",
            "nib_nomor": "", "nib_berlaku": "",
            "ss_nomor": "", "ss_berlaku": "", "ss_kualifikasi": "", "ss_terverifikasi": "PERIKSA",
            "sbu_nomor": "", "sbu_berlaku": "", "sbu_kualifikasi": "", "sbu_subklas_label": "",
            "pengalaman": [], "pemilik": [], "akta_pendirian": {}, "akta_perubahan": {},
            "skp": 5, "skp_jp": 0, "skp_catatan": "", "skp_berbeda": False,
            "kswp_status": "TIDAK DIKETAHUI",
            "kinerja_ada": False, "kinerja_nilai": "-", "kinerja_kategori": "-",
            "personel_list": [], "peralatan_list": [], "jp_preview": 0,
        }

        rows = _build_rows_peserta(peserta_data, kode_paket, no_start=len(all_rows) + 2)
        all_rows.extend(rows)
        all_rows.append(["", "", "", "", "", ""])  # baris kosong antar peserta
        # Kumpul per-penyedia untuk export MD (rows tanpa baris kosong separator)
        peserta_md.append({"nama": nama, "rows": rows})

    if not all_rows:
        return {"ok": False, "pesan": "Tidak ada data untuk ditulis.", "rows_written": 0}

    # 5. COM write ke sheet "Hasil Evaluasi"
    _log(f"Menulis {len(all_rows)} baris ke sheet Hasil Evaluasi...")
    import win32com.client
    import pythoncom

    pythoncom.CoInitialize()
    excel = None
    wb = None
    result = {"ok": False, "pesan": "Tidak dijalankan.", "rows_written": 0}
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        wb = excel.Workbooks.Open(os.path.abspath(xlsm_path))
        ws = wb.Worksheets("Hasil Evaluasi")

        ws.Cells.ClearContents()

        header = [["No", "Field", "Kategori", "Sumber", "Status", "Catatan"]]
        ws.Range(ws.Cells(1, 1), ws.Cells(1, 6)).Value = header

        # Sanitasi: COM hanya terima str/int/float/bool/None→""; list/dict → str repr
        def _san(v):
            if v is None:
                return ""
            if isinstance(v, (list, dict)):
                return str(v)
            if not isinstance(v, (str, int, float, bool)):
                return str(v)
            if isinstance(v, str):
                # bersihkan line break (CR/LF/_x000D_) → spasi, hindari multiline di cell
                v = v.replace("_x000D_", "\n").replace("\r\n", "\n").replace("\r", "\n")
                v = re.sub(r"\s*\n\s*", " ", v).strip()
                if v.startswith(("=", "+", "-", "@")):
                    return "'" + v  # prefix ' → Excel treat as literal text
            return v

        clean_rows = [[_san(v) for v in row] for row in all_rows]
        end_row = 1 + len(clean_rows)
        rng = ws.Range(ws.Cells(2, 1), ws.Cells(end_row, 6))
        rng.Value = clean_rows

        wb.Save()
        wb.Close(False)
        wb = None
        _log(f"✅ Sheet Hasil Evaluasi terisi {len(all_rows)} baris.")
        result = {"ok": True, "pesan": f"✅ {len(all_rows)} baris ditulis ke sheet Hasil Evaluasi.", "rows_written": len(all_rows)}

        # Export MD — additive, jangan gagalkan jika error
        try:
            from hasil_evaluasi_md import export_hasil_md as _export_md
            from config import sb as _sb
            # Ambil nama_paket dari Supabase
            _nama_paket = kode_paket
            try:
                resp = _sb().table("draft_paket_pl").select("nama_paket").eq("kode_paket", kode_paket).single().execute()
                if resp.data:
                    _nama_paket = resp.data.get("nama_paket", kode_paket)
            except Exception:
                pass
            folder_paket = os.path.dirname(os.path.abspath(xlsm_path))
            _export_md(folder_paket, _nama_paket, peserta_md, _log)
        except Exception as _md_err:
            _log(f"[MD Export] Warning: gagal export MD — {_md_err}")

    except Exception as e:
        result = {"ok": False, "pesan": f"COM error: {e}", "rows_written": 0}

    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except Exception:
            pass
        try:
            if excel is not None:
                excel.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()

    return result
