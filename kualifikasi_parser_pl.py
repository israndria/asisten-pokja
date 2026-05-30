"""
Parser data kualifikasi peserta Pengadaan Langsung (Non-Tender).
Clone kualifikasi_parser.py — swap endpoint /kualifikasi/ → /kualifikasinontender/.
Reuse get_kswp_status, get_kinerja, parse_kinerja_pdf dari tender parser (path-based).
"""

import os
import re
import requests
from bs4 import BeautifulSoup

import spse_browser
from config import SPSE_BASE_URL

# Reuse PDF/OCR helpers dari kualifikasi_parser (path-based, endpoint-agnostic)
from kualifikasi_parser import (
    get_kswp_status,
    get_kinerja,
    parse_kinerja_pdf,
    get_skp,
    _find_file,
)


def _headers() -> dict:
    cookie = spse_browser.get_spse_cookies()
    return {"Cookie": cookie, "User-Agent": "Mozilla/5.0", "Referer": SPSE_BASE_URL}


def parse_preview_html_pl(kualifikasi_id: str) -> dict:
    """
    Scrape /kualifikasinontender/{id}/preview via requests.
    Struktur HTML identik dengan /kualifikasi/ — tabel dan id sama.
    Return dict dengan semua field kualifikasi peserta PL.
    """
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/kualifikasinontender/{kualifikasi_id}/preview"
    try:
        r = requests.get(url, headers=_headers(), timeout=15)
        if r.status_code != 200:
            return {"ok": False, "pesan": f"HTTP {r.status_code}"}
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        return {"ok": False, "pesan": str(e)}

    tables = soup.find_all("table")
    hasil = {"ok": True}

    def _tbl(idx) -> list:
        if idx >= len(tables):
            return []
        return [
            [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            for tr in tables[idx].find_all("tr")
            if tr.find_all(["td", "th"])
        ]

    def _cell(rows, label_contains, col=1, default=""):
        for row in rows:
            if row and label_contains.lower() in row[0].lower():
                return row[col] if len(row) > col else default
        return default

    # Tabel 0: IDENTITAS
    t0 = _tbl(0)
    hasil["nama"]   = _cell(t0, "Nama")
    hasil["npwp"]   = _cell(t0, "NPWP")
    hasil["alamat"] = _cell(t0, "Alamat")
    hasil["email"]  = _cell(t0, "Email")

    # Tabel 1: IZIN USAHA (NIB, SS, SBU)
    t1 = _tbl(1)
    nib_row = next((r for r in t1 if r and ("Nomor Induk Berusaha" in r[0] or "NIB" == r[0].strip())), None)
    ss_row  = next((r for r in t1 if r and "Sertifikat Standar" in r[0]), None)
    sbu_row = next((r for r in t1 if r and "Sertifikat Badan Usaha" in r[0]), None)

    if nib_row and len(nib_row) >= 3:
        hasil["nib_nomor"]   = nib_row[1]
        hasil["nib_berlaku"] = nib_row[2]

    if ss_row and len(ss_row) >= 4:
        hasil["ss_nomor"]       = ss_row[1]
        hasil["ss_berlaku"]     = ss_row[2]
        hasil["ss_instansi"]    = ss_row[3] if len(ss_row) > 3 else ""
        hasil["ss_kualifikasi"] = ss_row[4] if len(ss_row) > 4 else ""
        hasil["ss_klasifikasi"] = ss_row[5] if len(ss_row) > 5 else ""

    if sbu_row and len(sbu_row) >= 4:
        hasil["sbu_nomor"]       = sbu_row[1]
        hasil["sbu_berlaku"]     = sbu_row[2]
        hasil["sbu_instansi"]    = sbu_row[3] if len(sbu_row) > 3 else ""
        hasil["sbu_kualifikasi"] = sbu_row[4] if len(sbu_row) > 4 else ""
        sbu_klas = sbu_row[5] if len(sbu_row) > 5 else ""
        hasil["sbu_klasifikasi"] = sbu_klas
        if sbu_klas:
            kode_sbu = sbu_klas.split(" - ")[0].strip() if " - " in sbu_klas else sbu_klas
            nama_sbu = sbu_klas.split(" - ", 1)[1].strip()[:80] if " - " in sbu_klas else ""
            hasil["sbu_subklas_label"] = f"{kode_sbu} - {nama_sbu}" if nama_sbu else kode_sbu
        else:
            hasil["sbu_subklas_label"] = ""

    # Tabel 2: AKTA
    t2 = _tbl(2)
    pendirian_idx = next((i for i, r in enumerate(t2) if r and "Akta Pendirian" in r[0]), None)
    perubahan_idx = next((i for i, r in enumerate(t2) if r and "Akta Perubahan" in r[0]), None)

    def _akta_block(rows, start_idx):
        data = {}
        if start_idx is None:
            return data
        for row in rows[start_idx + 1:]:
            if not row:
                continue
            label = row[0].lower()
            val = row[1] if len(row) > 1 else ""
            if "nomor" in label:
                data["nomor"] = val
            elif "tanggal" in label:
                data["tanggal"] = val
            elif "notaris" in label:
                data["notaris"] = val
            elif "akta" in label:
                break
        return data

    hasil["akta_pendirian"] = _akta_block(t2, pendirian_idx)
    hasil["akta_perubahan"] = _akta_block(t2, perubahan_idx)

    # Tabel 3: MANAJERIAL (pemilik/direktur)
    # Filter baris yang awalan nama perusahaan (CV/PT/UD/dll) — hanya nama orang masuk list
    _re_pt_filter = re.compile(r'^(CV|PT|UD|PD|Koperasi|Firma)\b\.?\s', re.IGNORECASE)
    t3 = _tbl(3)
    pemilik_list = []
    for row in t3[1:]:
        if row and len(row) >= 1 and row[0] and row[0] != "No data available in table":
            if not _re_pt_filter.match(row[0].strip()):
                pemilik_list.append(row[0])
    hasil["pemilik"] = pemilik_list

    # PERSONEL — table#table-tenaga-ahli
    _tbl_personel = soup.find("table", id="table-tenaga-ahli")
    _rows_per_orang = []
    if _tbl_personel:
        _rows_per_orang = [
            [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            for tr in _tbl_personel.find_all("tr")
            if tr.find_all(["td", "th"])
        ]

    personel_list = []
    for row in _rows_per_orang[1:]:
        if not row or row[0] == "No data available in table":
            continue
        nama_p  = row[0].strip()
        jabatan = row[5].strip() if len(row) > 5 else ""
        if not nama_p or nama_p.lower() in ("nama", "no", "no."):
            continue
        personel_list.append(f"{nama_p} ({jabatan})" if jabatan else nama_p)
    hasil["personel_list"] = personel_list

    # Tabel PERALATAN — table#table-peralatan
    _tbl_peralatan = soup.find("table", id="table-peralatan")
    _rows_alat = []
    if _tbl_peralatan:
        _rows_alat = [
            [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            for tr in _tbl_peralatan.find_all("tr")
            if tr.find_all(["td", "th"])
        ]

    peralatan_list = []
    for row in _rows_alat[1:]:
        if not row or row[0] == "No data available in table":
            continue
        nama_alat = row[0].strip()
        jumlah    = row[1].strip() if len(row) > 1 else ""
        if not nama_alat or nama_alat.lower() in ("nama alat", "peralatan", "no", "no."):
            continue
        peralatan_list.append(f"{nama_alat} ({jumlah})" if jumlah else nama_alat)
    hasil["peralatan_list"] = peralatan_list

    # Tabel 5: PENGALAMAN
    t5 = _tbl(5)
    pengalaman = []
    for row in t5[1:]:
        if not row or row[0] == "No data available in table":
            continue
        pengalaman.append({
            "nama":       row[0] if len(row) > 0 else "",
            "lokasi":     row[1] if len(row) > 1 else "",
            "instansi":   row[2] if len(row) > 2 else "",
            "tgl_mulai":  row[4] if len(row) > 4 else "",
            "tgl_selesai":row[5] if len(row) > 5 else "",
            "nilai":      row[6] if len(row) > 6 else "",
            "nomor":      row[7] if len(row) > 7 else "",
        })
    hasil["pengalaman"] = pengalaman

    # Tabel 6: PEKERJAAN SEDANG BERJALAN
    t6 = _tbl(6)
    jp_berjalan = [r for r in t6[1:] if r and r[0] and r[0] != "No data available in table"]
    hasil["pekerjaan_berjalan"] = jp_berjalan
    hasil["jp_preview"] = len(jp_berjalan)
    hasil["skp_preview"] = 5 - len(jp_berjalan)

    # KSWP via DOM (JS-rendered) — ambil langsung dari halaman nontender
    _kswp_section = soup.find(id="kswpS")
    if _kswp_section:
        hasil["kswp_html"] = _kswp_section.get_text(strip=True)

    return hasil


def get_kswp_from_dom_pl(kualifikasi_id: str) -> str:
    """Baca KSWP dari DOM /kualifikasinontender/{id}/preview (JS-rendered)."""
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/kualifikasinontender/{kualifikasi_id}/preview"

    async def _check():
        page = await spse_browser._connect_cdp_async(url, navigate=False)
        return await page.evaluate("""
        () => {
            var span = document.getElementById('kswpS');
            if (!span) return 'TIDAK DIKETAHUI';
            var img = span.querySelector('img[src*="verified"]');
            return img ? 'VALID' : 'TIDAK VALID';
        }
        """)

    try:
        return spse_browser._run(_check())
    except Exception:
        return "TIDAK DIKETAHUI"


def get_kswp_status_pl(kualifikasi_id: str, folder_peserta: str) -> str:
    """Double-check KSWP: PDF file dulu, fallback DOM Playwright."""
    pdf = _find_file(folder_peserta, "kswp", "konfirmasi validasi")
    if pdf:
        from kualifikasi_parser import parse_kswp_pdf
        result = parse_kswp_pdf(pdf)
        if result != "TIDAK DIKETAHUI":
            return result
    return get_kswp_from_dom_pl(kualifikasi_id)


def _parse_pq_pdf(folder_peserta: str) -> dict:
    """
    Parse dokumen PQ (formulir isian kualifikasi) dari folder peserta.
    Cari PDF terbesar di folder (exclude gabungan + checklist).
    Reuse _pdf_to_text dari kualifikasi_parser (fitz + OCR fallback).
    Return: {"direktur": str, "npwp_pdf": str, "bidang_pengalaman": [str]}
    """
    from kualifikasi_parser import _pdf_to_text

    result = {"direktur": "", "npwp_pdf": "", "bidang_pengalaman": []}
    if not folder_peserta or not os.path.isdir(folder_peserta):
        return result

    # Regex filter: nama perusahaan diawali CV/PT/UD/PD/Koperasi/Firma
    _re_pt = re.compile(r'^(CV|PT|UD|PD|Koperasi|Firma)\b\.?\s', re.IGNORECASE)

    # Prioritas: "Kualifikasi *.pdf" (PDF gabungan) → "2. Dokumen Kualifikasi*.pdf" → PDF lain terbesar
    # TIDAK exclude Kualifikasi *.pdf — justru itu sumber terbaik
    pdfs_prioritas = []
    pdfs_lain = []
    for f in os.listdir(folder_peserta):
        if not f.lower().endswith(".pdf"):
            continue
        if f.startswith("checklist_") or f.startswith("~$"):
            continue
        fpath = os.path.join(folder_peserta, f)
        sz = os.path.getsize(fpath)
        # Kualifikasi *.pdf → slot pertama; 2. Dokumen Kualifikasi* → slot kedua
        if f.startswith("Kualifikasi "):
            pdfs_prioritas.insert(0, (0, fpath))     # paling depan
        elif f.lower().startswith("2. dokumen kualifikasi") or f.startswith("2. Dokumen Kualifikasi"):
            pdfs_prioritas.append((1, fpath))        # kedua
        else:
            pdfs_lain.append((sz, fpath))

    pdfs_lain.sort(reverse=True)
    # Urutan final: [Kualifikasi*.pdf, 2.DokumenKualifikasi*.pdf, PDF lain terbesar…]
    ordered_pdfs = [p for _, p in pdfs_prioritas] + [p for _, p in pdfs_lain[:2]]

    if not ordered_pdfs:
        return result

    for pq_path in ordered_pdfs:  # coba berurutan sesuai prioritas
        try:
            # Hanya pakai fitz text layer — TANPA OCR (OCR terlalu lambat untuk batch 15+ paket)
            import fitz as _fitz
            _doc = _fitz.open(pq_path)
            full_text = "\n".join(_doc[i].get_text() for i in range(_doc.page_count))
            _doc.close()
            if len(full_text.strip()) < 50:
                continue  # PDF murni scan, tidak ada text layer — skip
        except Exception:
            continue

        # ── Direktur ──────────────────────────────────────────────────────────
        if not result["direktur"]:
            # Pola 1: tabel Direksi — "1.\nAbdul Malik, ST\n631...\nDirektur"
            m = re.search(
                r'Direksi/Pengurus[^1]*1\.\s*\n?([\w,\s\.]+?)\s*\n\s*\d{16}\s*\n\s*(Direktur)',
                full_text, re.DOTALL | re.IGNORECASE
            )
            if m:
                result["direktur"] = m.group(1).strip()
            else:
                # Pola 2: "Nama : X\nJabatan : Direktur" (form pakta integritas/surat pernyataan)
                m2 = re.search(
                    r'Nama\s*[:\-]\s*(.+?)\s*\nJabatan\s*[:\-]\s*Direktur',
                    full_text, re.IGNORECASE
                )
                if m2:
                    result["direktur"] = m2.group(1).strip()
            # Pola 3: "ABDUL MALIK, ST\nDirektur" (ttd di akhir dokumen)
            if not result["direktur"]:
                m3 = re.search(
                    r'\n([\w,\.\s]{5,40})\s*\nDirektur\s*\n',
                    full_text, re.IGNORECASE
                )
                if m3:
                    cand = m3.group(1).strip()
                    if len(cand.split()) >= 2:  # minimal 2 kata
                        result["direktur"] = cand

            # Pola 4 (PDF gabungan Kualifikasi): multiline — nama diikuti "Direktur" di baris
            # bawahnya, mungkin ada baris kosong di antara. Contoh:
            # "Ir. Muhammad Dhiya Khairi Ananda, M.T. \nDirektur "
            if not result["direktur"]:
                m4 = re.search(
                    r'\n([A-Z][a-zA-Z\s\.,]+(?:M\.T\.|S\.T\.|S\.H\.|M\.M\.|Ir\.|ST|SH)?)\s*\n\s*Direktur\s*\n',
                    full_text, re.IGNORECASE
                )
                if m4:
                    cand4 = m4.group(1).strip()
                    if len(cand4.split()) >= 2 and not _re_pt.match(cand4):
                        result["direktur"] = cand4

            # Pola 5: "Direktur\n\n{NAMA}" (urutan terbalik, form Cover/Cap)
            # Contoh: "Direktur \n \n Ir. Muhammad Dhiya Khairi Ananda, M.T. "
            if not result["direktur"]:
                m5 = re.search(
                    r'\bDirektur\b\s*\n[\s\n]*([A-Z][a-zA-Z\s\.,]+(?:M\.T\.|S\.T\.|Ir\.)?)\s*\n',
                    full_text, re.IGNORECASE
                )
                if m5:
                    cand5 = m5.group(1).strip()
                    if len(cand5.split()) >= 2 and not _re_pt.match(cand5):
                        result["direktur"] = cand5

            # Validasi: jika hasil diawali nama PT/CV → reset ke kosong, lanjut PDF berikutnya
            if result["direktur"] and _re_pt.match(result["direktur"]):
                result["direktur"] = ""

        # ── NPWP ──────────────────────────────────────────────────────────────
        if not result["npwp_pdf"]:
            # Format baku: XX.XXX.XXX.X-XXX.XXX
            m_npwp = re.search(r'(\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3})', full_text)
            if m_npwp:
                result["npwp_pdf"] = m_npwp.group(1)

        # ── Bidang pengalaman (kode SBU di kolom bidang tabel pengalaman) ─────
        # Cari section pengalaman dulu, ekstrak kode SBU dari sana
        lower = full_text.lower()
        sbu_kodes = []
        # Cari di seluruh teks (kode SBU: 1-3 huruf + 3 digit, e.g. RK003, AR001)
        kode_all = re.findall(r'\b([A-Z]{1,3}[0-9]{3})\b', full_text.upper())
        # Filter: exclude kode yang bukan SBU (NIK 16 digit dst sudah dibuang oleh \b)
        # Prioritaskan kode yang muncul di area pengalaman/bidang
        pengalaman_idx = lower.find("pengalaman kerja")
        if pengalaman_idx == -1:
            pengalaman_idx = lower.find("pengalaman")
        if pengalaman_idx != -1:
            section_pengalaman = full_text[pengalaman_idx:pengalaman_idx + 2000]
            sbu_kodes = list(dict.fromkeys(
                re.findall(r'\b([A-Z]{1,3}[0-9]{3})\b', section_pengalaman.upper())
            ))
        if not sbu_kodes:
            sbu_kodes = list(dict.fromkeys(kode_all))
        result["bidang_pengalaman"] = sbu_kodes

        if result["direktur"] or result["npwp_pdf"]:
            break  # cukup dari 1 PDF

    return result


def parse_peserta_lengkap_pl(
    kualifikasi_id: str,
    folder_peserta: str,
    progress_cb=None,
) -> dict:
    """
    Parse semua data kualifikasi 1 peserta PL dari semua sumber.
    Return dict lengkap identik dengan parse_peserta_lengkap (tender).
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    _log(f"[Parser PL] Fetch HTML preview kualifikasi {kualifikasi_id}...")
    html_data = parse_preview_html_pl(kualifikasi_id)
    if not html_data.get("ok"):
        return {"ok": False, "pesan": html_data.get("pesan", "Gagal fetch preview")}

    _log("[Parser PL] Parse PDF kualifikasi (direktur, NPWP, bidang)...")
    pdf_data = _parse_pq_pdf(folder_peserta)

    _log("[Parser PL] Cek KSWP...")
    kswp = get_kswp_status_pl(kualifikasi_id, folder_peserta)

    _log("[Parser PL] Cek Nilai Kinerja...")
    kinerja = get_kinerja(folder_peserta)

    _log("[Parser PL] Hitung SKP...")
    skp_data = get_skp(folder_peserta, html_data.get("jp_preview", 0))

    # Enrichment dari PDF: direktur + NPWP + bidang pengalaman
    # PDF lebih akurat karena dokumen yang diupload peserta (bukan input form SPSE)
    _pemilik_spse = html_data.get("pemilik", [])
    _direktur_pdf = pdf_data.get("direktur", "")
    _npwp_final = pdf_data.get("npwp_pdf", "") or html_data.get("npwp", "")

    # Pemilik: direktur dari PDF jadi baris pertama, sisanya dari SPSE
    if _direktur_pdf:
        # Jika direktur PDF sudah ada di list SPSE, reorder; jika tidak, prepend
        _pemilik_merged = [_direktur_pdf] + [
            p for p in _pemilik_spse
            if _direktur_pdf.upper() not in p.upper()
        ]
    else:
        _pemilik_merged = _pemilik_spse

    return {
        "ok": True,
        "nama":    html_data.get("nama", ""),
        "npwp":    _npwp_final,
        "alamat":  html_data.get("alamat", ""),
        "email":   html_data.get("email", ""),
        "nib_nomor":   html_data.get("nib_nomor", ""),
        "nib_berlaku": html_data.get("nib_berlaku", ""),
        "ss_nomor":      html_data.get("ss_nomor", ""),
        "ss_berlaku":    html_data.get("ss_berlaku", ""),
        "ss_kualifikasi": html_data.get("ss_kualifikasi", ""),
        "ss_terverifikasi": (
            "Terverifikasi" if html_data.get("ss_nomor") and "OSS" in html_data.get("ss_instansi", "")
            else ("Belum Terverifikasi" if html_data.get("ss_nomor") else "Tidak Menyampaikan")
        ),
        "sbu_nomor":       html_data.get("sbu_nomor", ""),
        "sbu_berlaku":     html_data.get("sbu_berlaku", ""),
        "sbu_kualifikasi": html_data.get("sbu_kualifikasi", "Kecil"),
        "sbu_klasifikasi": html_data.get("sbu_klasifikasi", ""),
        "sbu_subklas_label": html_data.get("sbu_subklas_label", ""),
        "bidang_pengalaman_pdf": pdf_data.get("bidang_pengalaman", []),  # kode SBU dari dok PQ
        "direktur_pdf": _direktur_pdf,
        "pengalaman": html_data.get("pengalaman", []),
        "pemilik":    _pemilik_merged,
        "akta_pendirian": html_data.get("akta_pendirian", {}),
        "akta_perubahan": html_data.get("akta_perubahan", {}),
        "skp":          skp_data["skp"],
        "skp_jp":       skp_data["jp"],
        "skp_catatan":  skp_data["catatan"],
        "skp_berbeda":  skp_data["berbeda"],
        "kswp_status":  kswp,
        "kinerja_ada":      kinerja["ada"],
        "kinerja_nilai":    kinerja["nilai"],
        "kinerja_kategori": kinerja["kategori"],
        "personel_list":  html_data.get("personel_list", []),
        "peralatan_list": html_data.get("peralatan_list", []),
        "jp_preview":     html_data.get("jp_preview", 0),
    }
