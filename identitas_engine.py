"""
Scrape identitas peserta dari SPSE /penawaran + /preview → upsert Supabase.

Tabel target:
  - dokumen_penawaran : jumlah dok per kode_tender
  - peserta_identitas : NPWP, alamat, direktur per peserta_id
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from config import sb as _sb, SPSE_BASE_URL, POKJA_ROOT, sanitasi_nama_folder
import spse_browser


def _headers() -> dict:
    return {
        "Cookie": spse_browser.get_spse_cookies(),
        "User-Agent": "Mozilla/5.0",
    }


# ──────────────────────────────────────────────
# 1. Scrape /penawaran → dokumen_penawaran
# ──────────────────────────────────────────────

def scrape_dokumen_penawaran(kode_tender: str) -> dict:
    """
    GET /peserta/{kode_tender}/penawaran → hitung jumlah peserta daftar/kirim.
    Return: {"jml_daftar": int, "jml_kirim": int, "jml_tidak_kirim": int}
    """
    url = f"{SPSE_BASE_URL}peserta/{kode_tender}/penawaran"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    tbl = soup.find("table")
    if not tbl:
        return {"jml_daftar": 0, "jml_kirim": 0, "jml_tidak_kirim": 0}

    rows = tbl.find_all("tr")
    jml_daftar = 0
    jml_kirim = 0

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 10:
            continue
        jml_daftar += 1
        # Kolom "Administrasi dan Teknis" status (index ~9)
        status_adm = cells[9].get_text(strip=True) if len(cells) > 9 else ""
        if "Dikirim" in status_adm:
            jml_kirim += 1

    return {
        "jml_daftar":      jml_daftar,
        "jml_kirim":       jml_kirim,
        "jml_tidak_kirim": jml_daftar - jml_kirim,
    }


def upsert_dokumen_penawaran(kode_tender: str, data: dict) -> None:
    _sb().table("dokumen_penawaran").upsert({
        "kode_tender":     kode_tender,
        "jml_daftar":      data["jml_daftar"],
        "jml_kirim":       data["jml_kirim"],
        "jml_tidak_kirim": data["jml_tidak_kirim"],
    }).execute()


# ──────────────────────────────────────────────
# 2. Scrape /preview → peserta_identitas
# ──────────────────────────────────────────────

def _format_npwp(raw: str) -> str:
    """'0197204597733000' → '19.720.459.7-733.000'"""
    d = re.sub(r"\D", "", raw)
    if len(d) < 15:
        return raw
    # Format NPWP: XX.XXX.XXX.X-XXX.XXX
    return f"{d[1:3]}.{d[3:6]}.{d[6:9]}.{d[9]}-{d[10:13]}.{d[13:16]}"


def scrape_preview(peserta_id: str) -> dict:
    """
    GET /kualifikasi/{peserta_id}/preview → identitas peserta.
    Return: {"nama_perusahaan", "npwp_raw", "alamat", "nama_direktur"}
    """
    url = f"{SPSE_BASE_URL}kualifikasi/{peserta_id}/preview"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    result = {"nama_perusahaan": "", "npwp_raw": "", "alamat": "", "nama_direktur": ""}

    # tbl0 — identitas utama (table tanpa id, pertama)
    tbl0 = soup.find("table")
    if tbl0:
        for row in tbl0.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            key = cells[0].get_text(strip=True).lower()
            val = cells[1].get_text(strip=True)
            if key == "nama":
                result["nama_perusahaan"] = val
            elif key == "npwp":
                result["npwp_raw"] = val
            elif key == "alamat":
                result["alamat"] = val

    # tbl3 — manajerial: filter Status = "Pemilik" untuk direktur
    tbl_manajerial = soup.find("table", id="table-manajerial")
    if tbl_manajerial:
        rows = tbl_manajerial.find_all("tr")
        # Header: Nama | KTP | Alamat | NPWP | Tgl Mulai | Tgl Akhir | Status
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 7:
                nama  = cells[0].get_text(strip=True)
                status = cells[6].get_text(strip=True)
                if "Pemilik" in status or "Direktur" in status:
                    result["nama_direktur"] = nama
                    break
        # Fallback: ambil baris pertama jika tidak ada Pemilik
        if not result["nama_direktur"] and len(rows) > 1:
            cells = rows[1].find_all("td")
            if cells:
                result["nama_direktur"] = cells[0].get_text(strip=True)

    return result


def upsert_peserta_identitas(kode_tender: str, peserta_id: str, data: dict) -> None:
    record = {
        "kode_tender":    kode_tender,
        "peserta_id":     peserta_id,
        "nama_perusahaan": data.get("nama_perusahaan", ""),
        "npwp_raw":       data.get("npwp_raw", ""),
        "alamat":         data.get("alamat", ""),
        "nama_direktur":  data.get("nama_direktur", ""),
        "personel_1":     data.get("personel_1", ""),
        "personel_2":     data.get("personel_2", ""),
        "alat_1":         data.get("alat_1", ""),
        "alat_2":         data.get("alat_2", ""),
        "alat_3":         data.get("alat_3", ""),
        "alat_4":         data.get("alat_4", ""),
        "alat_5":         data.get("alat_5", ""),
        "alat_6":         data.get("alat_6", ""),
    }
    _sb().table("peserta_identitas").upsert(record).execute()


# ──────────────────────────────────────────────
# 3. Gabung PDF + parse Formulir Isian Kualifikasi
# ──────────────────────────────────────────────

def gabung_pdf_peserta(folder_peserta: str, nama_peserta: str, nomor_pokja: str = "", log=None) -> str:
    """
    Gabungkan semua PDF di folder_peserta menjadi satu file.
    Output: DokkualifFull_{nama_peserta}_{nomor_pokja}.pdf di folder yang sama.
    Return: path file output, atau "" jika gagal/tidak ada PDF.
    """
    def _log(m):
        if log: log(m)

    try:
        import fitz  # PyMuPDF
    except ImportError:
        _log("  ⚠️ PyMuPDF tidak tersedia, skip gabung PDF")
        return ""

    pdf_files = sorted([
        os.path.join(folder_peserta, f)
        for f in os.listdir(folder_peserta)
        if f.lower().endswith(".pdf")
    ])
    if not pdf_files:
        _log("  ⚠️ Tidak ada PDF di folder peserta")
        return ""

    nama_safe = sanitasi_nama_folder(nama_peserta)[:80].strip("-")
    suffix    = f"_{nomor_pokja}" if nomor_pokja else ""
    out_path  = os.path.join(folder_peserta, f"1. DokkualifFull_{nama_safe}{suffix}.pdf")

    try:
        merged = fitz.open()
        for fp in pdf_files:
            # Skip file output itu sendiri jika sudah ada
            if os.path.abspath(fp) == os.path.abspath(out_path):
                continue
            try:
                doc = fitz.open(fp)
                merged.insert_pdf(doc)
                doc.close()
            except Exception as e:
                _log(f"  ⚠️ Skip {os.path.basename(fp)}: {e}")
        merged.save(out_path)
        merged.close()
        _log(f"  PDF digabung: {len(pdf_files)} file -> {os.path.basename(out_path)}")
        return out_path
    except Exception as e:
        _log(f"  ⚠️ Gagal gabung PDF: {e}")
        return ""


def parse_formulir_kualifikasi(folder_peserta: str) -> dict:
    """
    Parse personel & peralatan dari FORMULIR ISIAN KUALIFIKASI.pdf
    (format SPSE standar nasional).
    Return: {"personel": [...], "peralatan": [...]}
    """
    # Cari file dengan prioritas: FORMULIR ISIAN KUALIFIKASI → Kualifikasi *.pdf
    kandidat = []
    for f in os.listdir(folder_peserta):
        fl = f.lower()
        if "formulir isian kualifikasi" in fl and fl.endswith(".pdf"):
            kandidat.insert(0, os.path.join(folder_peserta, f))
        elif fl.startswith("kualifikasi") and fl.endswith(".pdf"):
            kandidat.append(os.path.join(folder_peserta, f))

    if not kandidat:
        return {"personel": [], "peralatan": []}

    try:
        import pdfplumber
    except ImportError:
        return {"personel": [], "peralatan": []}

    personel_list = []
    peralatan_list = []

    for pdf_path in kandidat:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    for tbl in (page.extract_tables() or []):
                        if not tbl or len(tbl) < 2:
                            continue
                        header = " ".join(str(c or "") for c in tbl[0]).upper()

                        # Tabel personel: header mengandung "NAMA PERSONIL" atau "TENAGA AHLI"
                        if not personel_list and ("NAMA PERSONIL" in header or "TENAGA AHLI" in header):
                            # Data ada di baris ke-2 (baris 1 = nomor kolom SPSE)
                            data_rows = tbl[2:] if len(tbl) > 2 and re.match(r"^[\d\s]+$", str(tbl[1][0] or "")) else tbl[1:]
                            for row in data_rows:
                                if not row or not row[0]:
                                    continue
                                # Kolom: No | Nama | Tgl Lahir | Pendidikan | Jabatan | ...
                                # Multi-entry dalam satu cell dipisah "\n"
                                nama_col  = str(row[1] or "").strip() if len(row) > 1 else ""
                                jabatan_col = str(row[4] or "").strip() if len(row) > 4 else ""
                                if not nama_col or nama_col.upper() in ("NAMA PERSONIL", "NAMA", "2"):
                                    continue
                                for nama_p, jabatan_p in zip(
                                    nama_col.split("\n"),
                                    jabatan_col.split("\n") if jabatan_col else [""] * len(nama_col.split("\n"))
                                ):
                                    nama_p = nama_p.strip()
                                    jabatan_p = jabatan_p.strip()
                                    if nama_p and nama_p not in ("Nihil", "-"):
                                        personel_list.append(f"{nama_p} ({jabatan_p})" if jabatan_p else nama_p)

                        # Tabel peralatan: header mengandung "JENIS PERALATAN" atau "PERALATAN/PERLENGKAPAN"
                        if not peralatan_list and ("JENIS PERALATAN" in header or "PERALATAN" in header and "PERLENGKAPAN" in header):
                            data_rows = tbl[2:] if len(tbl) > 2 and re.match(r"^[\d\s]+$", str(tbl[1][0] or "")) else tbl[1:]
                            for row in data_rows:
                                if not row or not row[0]:
                                    continue
                                # Kolom: No | Jenis Peralatan | Merk | Tahun | Lokasi | Kapasitas | Jumlah | ...
                                jenis_col  = str(row[1] or "").strip() if len(row) > 1 else ""
                                jumlah_col = str(row[6] or "").strip() if len(row) > 6 else ""
                                if not jenis_col or jenis_col.upper() in ("JENIS PERALATAN/\nPERLENGKAPAN", "JENIS PERALATAN", "2"):
                                    continue
                                for jenis_p, jumlah_p in zip(
                                    jenis_col.split("\n"),
                                    jumlah_col.split("\n") if jumlah_col else [""] * len(jenis_col.split("\n"))
                                ):
                                    jenis_p = jenis_p.strip()
                                    jumlah_p = jumlah_p.strip()
                                    if jenis_p and jenis_p not in ("Nihil", "-"):
                                        peralatan_list.append(f"{jenis_p} ({jumlah_p} unit)" if jumlah_p else jenis_p)

        except Exception:
            continue

        if personel_list and peralatan_list:
            break  # Sudah dapat keduanya, tidak perlu lanjut ke file berikutnya

    return {"personel": personel_list, "peralatan": peralatan_list}


# ──────────────────────────────────────────────
# 4. Entry point: scrape semua sekaligus
# ──────────────────────────────────────────────

def scrape_dan_upsert_semua(kode_tender: str, progress_cb=None,
                            peserta_override: list | None = None) -> dict:
    """
    Entry point utama:
      1. Scrape /penawaran → upsert dokumen_penawaran
      2. Untuk peserta yang sudah kirim → scrape /preview → upsert peserta_identitas

    peserta_override: jika diisi, lewati fetch /penawaran dan langsung pakai list ini.
      Format: [{"peserta_id": str, "nama_peserta": str}, ...]
      (kualifikasi_id dari Tab 6 juga diterima sebagai peserta_id)

    Return: {"peserta": int, "errors": [...]}
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    errors = []

    # Step 1: dokumen penawaran
    try:
        log("Scraping jumlah dokumen penawaran...")
        dok = scrape_dokumen_penawaran(kode_tender)
        upsert_dokumen_penawaran(kode_tender, dok)
        log(f"  Daftar: {dok['jml_daftar']}, Kirim: {dok['jml_kirim']}, Tidak Kirim: {dok['jml_tidak_kirim']}")
    except Exception as e:
        errors.append(f"dokumen_penawaran: {e}")
        log(f"  ERROR dokumen_penawaran: {e}")

    # Step 2: identitas peserta
    peserta_list = []
    if peserta_override is not None:
        # Pakai daftar peserta yang sudah ada dari sesi sebelumnya (Tab 6 langkah 1-2)
        peserta_list = peserta_override
        log(f"Pakai {len(peserta_list)} peserta dari langkah 1-2 (tanpa scrape /penawaran ulang)")
    else:
        try:
            from penawaran_engine import fetch_peserta_ids
            peserta_list = fetch_peserta_ids(kode_tender)
            log(f"Ditemukan {len(peserta_list)} peserta dengan penawaran terkirim")
        except Exception as e:
            errors.append(f"fetch_peserta_ids: {e}")
            log(f"  ERROR fetch peserta: {e}")

    import concurrent.futures as _cf_id
    import threading as _th_id

    _errors_lock = _th_id.Lock()

    # Fetch folder_dibuat sekali (shared, read-only per peserta)
    _folder_dibuat_shared = ""
    try:
        _r_fd = _sb().table("draft_paket").select("folder_dibuat") \
                     .eq("kode_tender", kode_tender).maybe_single().execute()
        _folder_dibuat_shared = _r_fd.data.get("folder_dibuat", "") if _r_fd.data else ""
    except Exception as _e_fd:
        log(f"  ⚠️ lookup folder_dibuat error: {_e_fd}")

    def _scrape_satu_peserta(p_item):
        p, urutan = p_item
        pid  = p.get("peserta_id") or p.get("kualifikasi_id", "")
        nama = p.get("nama_peserta") or p.get("nama", "")
        if not pid:
            return

        def _safe_log(msg):
            try:
                log(msg)
            except Exception:
                pass

        try:
            _safe_log(f"Scraping preview: {nama} ({pid})...")
            data = scrape_preview(pid)

            # Personel & peralatan: coba dari /preview dulu via kualifikasi_parser
            try:
                import kualifikasi_parser
                html_data = kualifikasi_parser.parse_preview_html(pid)
                personel_list  = html_data.get("personel_list", [])
                peralatan_list = html_data.get("peralatan_list", [])
                _safe_log(f"  /preview → {len(personel_list)} personel, {len(peralatan_list)} alat")
            except Exception as ep:
                _safe_log(f"  ⚠️ parse_preview_html error: {ep}")
                personel_list  = []
                peralatan_list = []

            # Fallback: cari folder peserta di disk → gabung PDF + parse Formulir Kualifikasi
            folder_peserta = ""
            folder_dibuat = _folder_dibuat_shared
            if folder_dibuat:
                try:
                    folder_safe = sanitasi_nama_folder(folder_dibuat)
                    slug = sanitasi_nama_folder(nama)[:80].strip("-")
                    fp = os.path.join(POKJA_ROOT, folder_safe, "1. Dokumen Kualifikasi",
                                      f"{urutan}. {slug}")
                    if os.path.isdir(fp):
                        folder_peserta = fp
                except Exception as ef:
                    _safe_log(f"  ⚠️ lookup folder peserta error: {ef}")

            # Gabung semua PDF → DokkualifFull_{nama}_{nomor_pokja}.pdf (selalu dilakukan)
            if folder_peserta:
                import re as _re
                _m = _re.search(r"Pokja\s+(\d+)", folder_dibuat, _re.IGNORECASE) if folder_dibuat else None
                _nomor_pokja = _m.group(1) if _m else ""
                gabung_pdf_peserta(folder_peserta, nama, nomor_pokja=_nomor_pokja, log=_safe_log)

            # Parse personel & alat dari Formulir Isian Kualifikasi jika /preview kosong
            if folder_peserta and (not personel_list or not peralatan_list):
                res_pdf = parse_formulir_kualifikasi(folder_peserta)
                if res_pdf["personel"] or res_pdf["peralatan"]:
                    _safe_log(f"  Formulir PDF → {len(res_pdf['personel'])} personel, {len(res_pdf['peralatan'])} alat")
                    personel_list  = personel_list  or res_pdf["personel"]
                    peralatan_list = peralatan_list or res_pdf["peralatan"]
                else:
                    _safe_log(f"  ⚠️ Personel/alat tidak ditemukan di /preview maupun PDF — isi manual")
            elif not folder_peserta and (not personel_list or not peralatan_list):
                _safe_log(f"  ⚠️ Folder peserta tidak ditemukan di disk — personel/alat kosong")

            data["personel_1"] = personel_list[0] if len(personel_list) > 0 else ""
            data["personel_2"] = personel_list[1] if len(personel_list) > 1 else ""
            data["alat_1"]     = peralatan_list[0] if len(peralatan_list) > 0 else ""
            data["alat_2"]     = peralatan_list[1] if len(peralatan_list) > 1 else ""
            data["alat_3"]     = peralatan_list[2] if len(peralatan_list) > 2 else ""
            data["alat_4"]     = peralatan_list[3] if len(peralatan_list) > 3 else ""
            data["alat_5"]     = peralatan_list[4] if len(peralatan_list) > 4 else ""
            data["alat_6"]     = peralatan_list[5] if len(peralatan_list) > 5 else ""

            upsert_peserta_identitas(kode_tender, pid, data)
            _safe_log(f"  OK: {data['nama_perusahaan']} | direktur: {data['nama_direktur']}")
        except Exception as e:
            with _errors_lock:
                errors.append(f"{nama} ({pid}): {e}")
            _safe_log(f"  ERROR {nama}: {e}")

    # max_workers=3: aman untuk concurrent HTTP ke SPSE (tidak trigger rate limit)
    with _cf_id.ThreadPoolExecutor(max_workers=3) as _pool_id:
        futs_id = [_pool_id.submit(_scrape_satu_peserta, (p, i + 1))
                   for i, p in enumerate(peserta_list)]
        for fut_id in _cf_id.as_completed(futs_id):
            fut_id.result()  # re-raise exceptions (sudah di-catch di dalam)

    return {"peserta": len(peserta_list), "errors": errors}
