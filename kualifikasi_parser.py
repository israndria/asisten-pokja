"""
Parser data kualifikasi peserta tender.

Sumber data:
1. HTML /kualifikasi/{id}/preview  — requests + BeautifulSoup (data utama)
2. DOM Playwright                  — KSWP status (img logo verified, JS-rendered)
3. PDF via OCR (pytesseract+fitz)  — KSWP validity text + Nilai Kinerja
4. pdfplumber                      — Formulir Isian (SKP double-check)
"""

import os
import re
import io
import glob as _glob

import requests
from bs4 import BeautifulSoup

import spse_browser
from config import SPSE_BASE_URL

# ── Tesseract ──────────────────────────────────────────────────────────────────
_TESSERACT_PATH = r"D:\Tesseract OCR\tesseract.exe"

def _ocr_image(img):
    """OCR PIL Image → string. Lazy import pytesseract."""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_PATH
    return pytesseract.image_to_string(img, lang="ind+eng")


def _pdf_to_text(pdf_path: str) -> str:
    """
    Extract teks dari PDF.
    Kalau halaman berbasis gambar → OCR via pytesseract.
    """
    import fitz
    from PIL import Image, ImageEnhance

    doc = fitz.open(pdf_path)
    parts = []
    for page in doc:
        text = page.get_text().strip()
        if text:
            parts.append(text)
            continue
        # Gambar — render resolusi tinggi lalu OCR
        mat = fitz.Matrix(2.5, 2.5)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        parts.append(_ocr_image(img))
    return "\n".join(parts)


def _pdf_footer_text(pdf_path: str) -> str:
    """
    OCR 25% bawah halaman pertama PDF (area nilai kinerja).
    Dengan enhance kontras agar teks kecil terbaca.
    """
    import fitz
    from PIL import Image, ImageEnhance

    doc = fitz.open(pdf_path)
    page = doc[0]
    imgs = page.get_images(full=True)
    if imgs:
        # Ambil gambar konten terbesar (bukan watermark)
        largest = max(imgs, key=lambda x: doc.extract_image(x[0])["image"].__len__())
        raw = doc.extract_image(largest[0])["image"]
        img = Image.open(io.BytesIO(raw))
    else:
        mat = fitz.Matrix(3, 3)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))

    w, h = img.size
    footer = img.crop((0, int(h * 0.75), w, h))
    footer = ImageEnhance.Contrast(footer).enhance(2.0)
    footer = footer.resize((footer.width * 2, footer.height * 2), Image.LANCZOS)
    return _ocr_image(footer)


# ── Helpers HTTP ──────────────────────────────────────────────────────────────

def _headers():
    cookie = spse_browser.get_spse_cookies()
    return {"Cookie": cookie, "User-Agent": "Mozilla/5.0", "Referer": SPSE_BASE_URL}


# ── Cari file di folder peserta ────────────────────────────────────────────────

def _find_file(folder: str, *patterns: str) -> str | None:
    """Cari file pertama yang cocok salah satu pattern (case-insensitive) di folder."""
    try:
        files = os.listdir(folder)
    except Exception:
        return None
    for pat in patterns:
        pat_lower = pat.lower()
        for f in files:
            if pat_lower in f.lower():
                return os.path.join(folder, f)
    return None


# ── Parse halaman HTML /preview ───────────────────────────────────────────────

def parse_preview_html(kualifikasi_id: str) -> dict:
    """
    Scrape /kualifikasi/{id}/preview via requests.
    Return dict dengan semua field yang bisa diambil dari HTML.
    """
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/kualifikasi/{kualifikasi_id}/preview"
    try:
        r = requests.get(url, headers=_headers(), timeout=15)
        if r.status_code != 200:
            return {"ok": False, "pesan": f"HTTP {r.status_code}"}
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        return {"ok": False, "pesan": str(e)}

    tables = soup.find_all("table")
    hasil = {"ok": True}

    def _tbl(idx) -> list[list[str]]:
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
    hasil["nama"] = _cell(t0, "Nama")
    hasil["npwp"] = _cell(t0, "NPWP")
    hasil["alamat"] = _cell(t0, "Alamat")
    hasil["email"] = _cell(t0, "Email")

    # Tabel 1: IZIN USAHA (NIB, SS, SBU)
    t1 = _tbl(1)
    nib_row = next((r for r in t1 if r and ("Nomor Induk Berusaha" in r[0] or "NIB" == r[0].strip())), None)
    ss_row  = next((r for r in t1 if r and "Sertifikat Standar" in r[0]), None)
    sbu_row = next((r for r in t1 if r and "Sertifikat Badan Usaha" in r[0]), None)

    if nib_row and len(nib_row) >= 3:
        hasil["nib_nomor"]  = nib_row[1]
        hasil["nib_berlaku"] = nib_row[2]

    if ss_row and len(ss_row) >= 4:
        hasil["ss_nomor"]       = ss_row[1]
        hasil["ss_berlaku"]     = ss_row[2]
        hasil["ss_instansi"]    = ss_row[3] if len(ss_row) > 3 else ""
        hasil["ss_kualifikasi"] = ss_row[4] if len(ss_row) > 4 else ""
        hasil["ss_klasifikasi"] = ss_row[5] if len(ss_row) > 5 else ""

    if sbu_row and len(sbu_row) >= 4:
        hasil["sbu_nomor"]       = sbu_row[1]   # PBUMKU
        hasil["sbu_berlaku"]     = sbu_row[2]
        hasil["sbu_instansi"]    = sbu_row[3] if len(sbu_row) > 3 else ""
        hasil["sbu_kualifikasi"] = sbu_row[4] if len(sbu_row) > 4 else ""
        sbu_klas = sbu_row[5] if len(sbu_row) > 5 else ""
        hasil["sbu_klasifikasi"] = sbu_klas
        # Bentuk label ringkas: "F42911 - KONSTRUKSI BANGUNAN..." → ambil kode + nama pendek
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
            val   = row[1] if len(row) > 1 else ""
            if "nomor" in label:
                data["nomor"] = val
            elif "tanggal" in label:
                data["tanggal"] = val
            elif "notaris" in label:
                data["notaris"] = val
            elif "akta" in label:  # header baru = berhenti
                break
        return data

    hasil["akta_pendirian"] = _akta_block(t2, pendirian_idx)
    hasil["akta_perubahan"] = _akta_block(t2, perubahan_idx)

    # Tabel 3: MANAJERIAL (pemilik/direktur)
    t3 = _tbl(3)
    pemilik_list = []
    for row in t3[1:]:  # skip header
        if row and len(row) >= 1 and row[0] and row[0] != "No data available in table":
            pemilik_list.append(row[0])
    hasil["pemilik"] = pemilik_list

    # Tabel PERSONEL MANAJERIAL — id: "table-tenaga-ahli"
    # Kolom terverifikasi: Nama | Tanggal Lahir | NPWP | Pendidikan | Pengalaman Kerja | Profesi/Keahlian
    # col[0]=Nama, col[5]=Profesi/Keahlian (jabatan)
    _tbl_personel = soup.find("table", id="table-tenaga-ahli")
    if _tbl_personel:
        _rows_per_orang = [
            [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            for tr in _tbl_personel.find_all("tr")
            if tr.find_all(["td", "th"])
        ]
    else:
        _rows_per_orang = []

    personel_list = []
    for row in _rows_per_orang[1:]:
        if not row or row[0] == "No data available in table":
            continue
        nama_p  = row[0].strip()
        jabatan = row[5].strip() if len(row) > 5 else ""
        if not nama_p or nama_p.lower() in ("nama", "no", "no."):
            continue
        entry = f"{nama_p} ({jabatan})" if jabatan else nama_p
        personel_list.append(entry)
    hasil["personel_list"] = personel_list

    # Tabel 5: PENGALAMAN KERJA
    t5 = _tbl(5)
    pengalaman = []
    for row in t5[1:]:
        if not row or row[0] == "No data available in table":
            continue
        pengalaman.append({
            "nama":      row[0] if len(row) > 0 else "",
            "lokasi":    row[1] if len(row) > 1 else "",
            "instansi":  row[2] if len(row) > 2 else "",
            "tgl_mulai": row[4] if len(row) > 4 else "",
            "tgl_selesai": row[5] if len(row) > 5 else "",
            "nilai":     row[6] if len(row) > 6 else "",
            "nomor":     row[7] if len(row) > 7 else "",
        })
    hasil["pengalaman"] = pengalaman

    # Tabel PERALATAN UTAMA — id: "table-peralatan"
    # Kolom terverifikasi: Nama Alat | Jumlah | Kapasitas | Merk/Tipe | Tahun | Kondisi | Lokasi | Status | Bukti
    # col[0]=Nama Alat, col[1]=Jumlah
    _tbl_peralatan = soup.find("table", id="table-peralatan")
    if _tbl_peralatan:
        _rows_alat = [
            [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            for tr in _tbl_peralatan.find_all("tr")
            if tr.find_all(["td", "th"])
        ]
    else:
        _rows_alat = []

    peralatan_list = []
    for row in _rows_alat[1:]:
        if not row or row[0] == "No data available in table":
            continue
        nama_alat = row[0].strip()
        jumlah    = row[1].strip() if len(row) > 1 else ""
        if not nama_alat or nama_alat.lower() in ("nama alat", "peralatan", "no", "no."):
            continue
        entry = f"{nama_alat} ({jumlah})" if jumlah else nama_alat
        peralatan_list.append(entry)
    hasil["peralatan_list"] = peralatan_list

    # Tabel 6: PEKERJAAN SEDANG BERJALAN → hitung JP → SKP
    t6 = _tbl(6)
    jp_berjalan = [
        r for r in t6[1:]
        if r and r[0] and r[0] != "No data available in table"
    ]
    hasil["pekerjaan_berjalan"] = jp_berjalan
    hasil["jp_preview"] = len(jp_berjalan)
    hasil["skp_preview"] = 5 - len(jp_berjalan)

    return hasil


# ── KSWP: DOM Playwright (fallback primer) ─────────────────────────────────────

def get_kswp_from_dom(kualifikasi_id: str) -> str:
    """
    Baca status KSWP dari DOM /preview yang sudah di-render JS.
    Return: 'VALID' | 'TIDAK VALID' | 'TIDAK DIKETAHUI'
    """
    base = SPSE_BASE_URL.rstrip("/")
    url  = f"{base}/kualifikasi/{kualifikasi_id}/preview"

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


# ── KSWP: dari file PDF ────────────────────────────────────────────────────────

def parse_kswp_pdf(pdf_path: str) -> str:
    """
    Baca status KSWP dari file PDF (teks atau scan).
    Return: 'VALID' | 'TIDAK VALID' | 'TIDAK DIKETAHUI'
    """
    try:
        text = _pdf_to_text(pdf_path).lower()
        if "kswp valid" in text or (
            "status kswp" in text and "valid" in text.split("status kswp", 1)[-1][:50]
        ):
            return "VALID"
        if "tidak valid" in text or "not valid" in text:
            return "TIDAK VALID"
        if "valid" in text:
            return "VALID"
        return "TIDAK DIKETAHUI"
    except Exception:
        return "TIDAK DIKETAHUI"


def get_kswp_status(kualifikasi_id: str, folder_peserta: str) -> str:
    """
    Strategi double-check KSWP:
    1. Cari file KSWP*.pdf di folder peserta → parse teks/OCR
    2. Fallback: DOM Playwright logo verified
    """
    pdf = _find_file(folder_peserta, "kswp", "konfirmasi validasi")
    if pdf:
        result = parse_kswp_pdf(pdf)
        if result != "TIDAK DIKETAHUI":
            return result
    # Fallback DOM
    return get_kswp_from_dom(kualifikasi_id)


# ── Nilai Kinerja: dari file PDF ──────────────────────────────────────────────

_KINERJA_KATEGORI = [
    ("SANGAT BAIK", ["sangat baik"]),
    ("BAIK",        ["baik"]),
    ("CUKUP",       ["cukup"]),
    ("BURUK",       ["buruk", "kurang"]),
]

def parse_kinerja_pdf(pdf_path: str) -> dict:
    """
    Baca nilai kinerja dari PDF (teks atau scan).
    Return: {"ada": bool, "nilai": str, "kategori": str}
    """
    try:
        # OCR seluruh dokumen
        full_text = _pdf_to_text(pdf_path).lower()
        # OCR footer (area nilai total)
        footer_text = _pdf_footer_text(pdf_path).lower()
        combined = full_text + "\n" + footer_text

        # Cari angka nilai (pola: "nilai kinerja ... 2.00" atau "2 (baik)" atau "2,00")
        nilai_str = ""
        # Pola 1: "nilai kinerja ... angka"
        m = re.search(r"nilai\s+kinerja\D{0,40}(\d[\d.,]+)", combined)
        if m:
            nilai_str = m.group(1).replace(",", ".")
        # Pola 2: "angka (baik/cukup/...)"
        if not nilai_str:
            m = re.search(r"(\d[\d.,]+)\s*\(\s*(baik|cukup|buruk|sangat)", combined)
            if m:
                nilai_str = m.group(1).replace(",", ".")
        # Pola 3: angka desimal standalone di area footer (misal "2.00" atau "2,00")
        if not nilai_str:
            for m in re.finditer(r"\b([0-3][.,]\d{2})\b", footer_text):
                nilai_str = m.group(1).replace(",", ".")
                break

        # Cari kategori — cek combined lalu footer khusus
        kategori = ""
        for kat, keywords in _KINERJA_KATEGORI:
            if any(kw in combined for kw in keywords):
                kategori = kat
                break

        return {"ada": True, "nilai": nilai_str or "-", "kategori": kategori or "-"}
    except Exception as e:
        return {"ada": False, "nilai": "-", "kategori": "-", "error": str(e)}


def get_kinerja(folder_peserta: str) -> dict:
    """
    Cari file kinerja di folder peserta lalu parse.
    Return: {"ada": bool, "nilai": str, "kategori": str}
    """
    pdf = _find_file(folder_peserta, "kinerja", "penilaian kinerja", "lembar penilaian")
    if not pdf:
        return {"ada": False, "nilai": "-", "kategori": "-"}
    return parse_kinerja_pdf(pdf)


# ── SKP: double-check dari Formulir Isian Kualifikasi PDF ─────────────────────

def parse_skp_formulir(pdf_path: str) -> dict:
    """
    Parse tabel 'PEKERJAAN SEDANG DILAKSANAKAN' dari Formulir Isian.
    Return: {"ok": bool, "jp": int, "skp": int, "baris": list}
    """
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join(
                (p.extract_text() or "") for p in pdf.pages
            )

        # Cari section pekerjaan sedang berjalan
        lower = full_text.lower()
        marker = "pekerjaan yang sedang dilaksanakan"
        if marker not in lower:
            marker = "pekerjaan sedang"
        if marker not in lower:
            return {"ok": False, "jp": 0, "skp": 5, "baris": []}

        section = full_text[lower.index(marker):]
        lines = [l.strip() for l in section.split("\n") if l.strip()]

        # Baris data: skip header, ambil sampai "nihil" atau bagian baru
        baris_data = []
        header_passed = False
        for line in lines[1:]:
            ll = line.lower()
            if not header_passed:
                if any(k in ll for k in ["no.", "nama paket", "bidang"]):
                    header_passed = True
                continue
            if "nihil" in ll:
                break
            if any(k in ll for k in ["modal kerja", "surat keterangan", "demikian"]):
                break
            if line and not line.isdigit():
                baris_data.append(line)

        jp = len(baris_data) if baris_data else 0
        return {"ok": True, "jp": jp, "skp": 5 - jp, "baris": baris_data}
    except Exception as e:
        return {"ok": False, "jp": 0, "skp": 5, "baris": [], "error": str(e)}


def get_skp(folder_peserta: str, jp_preview: int) -> dict:
    """
    Hitung SKP dari jp_preview (tabel pekerjaan berjalan di HTML /preview).
    Formulir Isian PDF tidak dipakai karena sering tidak konsisten.
    Return: {"skp": int, "jp": int, "catatan": str, "berbeda": bool}
    """
    skp = 5 - jp_preview
    return {
        "skp": skp,
        "jp": jp_preview,
        "catatan": f"{skp} SKP",
        "berbeda": False,
    }


# ── Entry point utama: parse semua data 1 peserta ─────────────────────────────

def parse_peserta_lengkap(
    kualifikasi_id: str,
    folder_peserta: str,
    progress_cb=None,
) -> dict:
    """
    Parse semua data kualifikasi 1 peserta dari semua sumber.

    Return dict lengkap siap di-fill ke Excel:
    {
        "ok": bool,
        "nama", "npwp", "alamat",
        "nib_nomor", "nib_berlaku",
        "ss_nomor", "ss_berlaku", "ss_kualifikasi",
        "sbu_nomor", "sbu_berlaku", "sbu_kualifikasi", "sbu_klasifikasi",
        "pengalaman": [...],
        "pemilik": [...],
        "akta_pendirian": {"nomor","tanggal","notaris"},
        "akta_perubahan": {"nomor","tanggal","notaris"},
        "skp": int, "skp_catatan": str, "skp_berbeda": bool,
        "kswp_status": str,
        "kinerja_ada": bool, "kinerja_nilai": str, "kinerja_kategori": str,
    }
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _log(f"[Parser] Fetch HTML preview kualifikasi {kualifikasi_id}...")
    html_data = parse_preview_html(kualifikasi_id)
    if not html_data.get("ok"):
        return {"ok": False, "pesan": html_data.get("pesan", "Gagal fetch preview")}

    _log("[Parser] Cek KSWP...")
    kswp = get_kswp_status(kualifikasi_id, folder_peserta)

    _log("[Parser] Cek Nilai Kinerja...")
    kinerja = get_kinerja(folder_peserta)

    _log("[Parser] Hitung SKP (double-check)...")
    skp_data = get_skp(folder_peserta, html_data.get("jp_preview", 0))

    return {
        "ok": True,
        # Identitas
        "nama":    html_data.get("nama", ""),
        "npwp":    html_data.get("npwp", ""),
        "alamat":  html_data.get("alamat", ""),
        # NIB
        "nib_nomor":   html_data.get("nib_nomor", ""),
        "nib_berlaku": html_data.get("nib_berlaku", ""),
        # Sertifikat Standar
        "ss_nomor":      html_data.get("ss_nomor", ""),
        "ss_berlaku":    html_data.get("ss_berlaku", ""),
        "ss_kualifikasi": html_data.get("ss_kualifikasi", ""),
        # ss_terverifikasi: NIB dari OSS selalu "Terverifikasi" jika ada nomor,
        # "Belum Terverifikasi" hanya jika ada nomor tapi instansi bukan OSS
        "ss_terverifikasi": (
            "Terverifikasi" if html_data.get("ss_nomor") and "OSS" in html_data.get("ss_instansi", "")
            else ("Belum Terverifikasi" if html_data.get("ss_nomor")
            else "Tidak Menyampaikan")
        ),
        # SBU
        "sbu_nomor":      html_data.get("sbu_nomor", ""),
        "sbu_berlaku":    html_data.get("sbu_berlaku", ""),
        "sbu_kualifikasi": html_data.get("sbu_kualifikasi", "Kecil"),
        "sbu_klasifikasi": html_data.get("sbu_klasifikasi", ""),
        "sbu_subklas_label": html_data.get("sbu_subklas_label", ""),
        # Pengalaman
        "pengalaman": html_data.get("pengalaman", []),
        # Pemilik
        "pemilik": html_data.get("pemilik", []),
        # Akta
        "akta_pendirian": html_data.get("akta_pendirian", {}),
        "akta_perubahan": html_data.get("akta_perubahan", {}),
        # SKP
        "skp":          skp_data["skp"],
        "skp_catatan":  skp_data["catatan"],
        "skp_berbeda":  skp_data["berbeda"],
        # KSWP
        "kswp_status": kswp,
        # Kinerja
        "kinerja_ada":       kinerja["ada"],
        "kinerja_nilai":     kinerja["nilai"],
        "kinerja_kategori":  kinerja["kategori"],
        # Personel & Peralatan dari /preview (kosong jika tidak diinput peserta)
        "personel_list":     html_data.get("personel_list", []),
        "peralatan_list":    html_data.get("peralatan_list", []),
    }
