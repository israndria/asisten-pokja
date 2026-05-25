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
    t3 = _tbl(3)
    pemilik_list = []
    for row in t3[1:]:
        if row and len(row) >= 1 and row[0] and row[0] != "No data available in table":
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

    _log("[Parser PL] Cek KSWP...")
    kswp = get_kswp_status_pl(kualifikasi_id, folder_peserta)

    _log("[Parser PL] Cek Nilai Kinerja...")
    kinerja = get_kinerja(folder_peserta)

    _log("[Parser PL] Hitung SKP...")
    skp_data = get_skp(folder_peserta, html_data.get("jp_preview", 0))

    return {
        "ok": True,
        "nama":    html_data.get("nama", ""),
        "npwp":    html_data.get("npwp", ""),
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
        "pengalaman": html_data.get("pengalaman", []),
        "pemilik":    html_data.get("pemilik", []),
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
