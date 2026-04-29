"""
Scrape identitas peserta dari SPSE /penawaran + /preview → upsert Supabase.

Tabel target:
  - dokumen_penawaran : jumlah dok per kode_tender
  - peserta_identitas : NPWP, alamat, direktur per peserta_id
"""

import re
import requests
from bs4 import BeautifulSoup
from config import sb as _sb, SPSE_BASE_URL
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
    }
    _sb().table("peserta_identitas").upsert(record).execute()


# ──────────────────────────────────────────────
# 3. Entry point: scrape semua sekaligus
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

    for p in peserta_list:
        pid  = p.get("peserta_id") or p.get("kualifikasi_id", "")
        nama = p.get("nama_peserta") or p.get("nama", "")
        if not pid:
            continue
        try:
            log(f"Scraping preview: {nama} ({pid})...")
            data = scrape_preview(pid)
            upsert_peserta_identitas(kode_tender, pid, data)
            log(f"  OK: {data['nama_perusahaan']} | direktur: {data['nama_direktur']}")
        except Exception as e:
            errors.append(f"{nama} ({pid}): {e}")
            log(f"  ERROR {nama}: {e}")

    return {"peserta": len(peserta_list), "errors": errors}
