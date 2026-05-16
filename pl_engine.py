"""
Mode Pengadaan Langsung — Tab 0: Draft Paket PL
Input manual paket PL (JKK atau PK), simpan ke Supabase tabel draft_paket_pl.
Juga berisi fungsi scrape otomatis dari SPSE /dt/paketpp.
"""

import os
import re
from datetime import datetime, timezone
from config import sb as _sb

BASE_URL = "https://spse.inaproc.id/tapinkab"

SATKER_LIST = [
    "Dinas Perdagangan",
    "Dinas Pekerjaan Umum Dan Penataan Ruang (Bina Marga)",
    "Dinas Pekerjaan Umum Dan Penataan Ruang (PUPR)",
    "Kecamatan CLU",
    "Dinas Perizinan Terpadu Satu Pintu",
    "Lainnya",
]

STATUS_LIST = ["draft", "undangan", "evaluasi", "negosiasi", "selesai"]


def load_draft_pl() -> list[dict]:
    """Ambil semua baris draft_paket_pl, urut terbaru dulu."""
    try:
        return _sb().table("draft_paket_pl").select("*").order("diambil_pada", desc=True).execute().data or []
    except Exception as e:
        return []


def simpan_paket_pl(data: dict) -> dict:
    """
    Upsert satu paket PL ke draft_paket_pl.
    data harus memiliki key 'kode_paket'.
    Return: {"ok": True} atau {"ok": False, "error": str}
    """
    if not data.get("kode_paket"):
        return {"ok": False, "error": "kode_paket wajib diisi"}
    data.setdefault("diambil_pada", datetime.now(timezone.utc).isoformat())
    try:
        _sb().table("draft_paket_pl").upsert(data).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def hapus_paket_pl(kode_paket: str) -> dict:
    """Hapus satu baris dari draft_paket_pl berdasarkan kode_paket."""
    try:
        _sb().table("draft_paket_pl").delete().eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def update_status(kode_paket: str, status: str) -> dict:
    """Update kolom status paket PL."""
    try:
        _sb().table("draft_paket_pl").update({"status": status}).eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tandai_folder_dibuat(kode_paket: str) -> dict:
    """Set folder_dibuat=True dan folder_dibuat_pada=now."""
    try:
        _sb().table("draft_paket_pl").update({
            "folder_dibuat": True,
            "folder_dibuat_pada": datetime.now(timezone.utc).isoformat(),
        }).eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# Scrape otomatis dari SPSE
# ============================================================

def _parse_hps_dari_edit(html: str) -> str:
    """Ekstrak nilai HPS dari halaman nontender/{kode}/edit."""
    import re
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    teks = soup.get_text(" ", strip=True)
    m = re.search(r"Nilai HPS\s*Rp\.\s*([\d.,]+)", teks)
    return m.group(1) if m else ""


def _parse_jenis_kontrak_dari_edit(html: str) -> str:
    """Ekstrak Jenis Kontrak dari halaman nontender/{kode}/edit."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    teks = soup.get_text(" ", strip=True)
    m = re.search(r"Jenis Kontrak\s+([\w\s]+?)(?:Dokumen|Jadwal|Survey|\Z)", teks)
    if m:
        return m.group(1).strip()
    return ""


def serap_paket_pl_dari_spse(cookie_str: str, base_url: str, log_fn=None) -> dict:
    """
    Scrape daftar paket non-tender dari SPSE /dt/paketpp,
    fetch detail tiap paket dari /nontender/{kode}/edit,
    upsert ke Supabase draft_paket_pl.

    cookie_str : hasil get_spse_cookies()
    base_url   : SPSE_BASE_URL (diakhiri /)
    log_fn     : callable(str) untuk log progres, opsional
    Returns    : {"ok": True, "scraped": N, "errors": [...]}
    """
    import requests

    def log(msg):
        if log_fn:
            log_fn(msg)

    headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"}

    # 1. Fetch daftar paket
    try:
        resp = requests.get(f"{base_url}dt/paketpp", headers=headers, timeout=15)
        rows = resp.json().get("data", [])
    except Exception as e:
        return {"ok": False, "scraped": 0, "errors": [f"Gagal fetch dt/paketpp: {e}"]}

    log(f"Ditemukan {len(rows)} paket di SPSE")
    errors = []
    scraped = 0

    for row in rows:
        id_nontender = str(row[0])   # ID internal
        nama_paket   = row[1]
        status_spse  = row[2]
        satker       = row[4]
        kode_paket   = str(row[5])   # kode resmi non-tender

        log(f"  Scraping {kode_paket} — {nama_paket[:40]}...")

        # 2. Fetch detail dari halaman edit
        jenis_kontrak = ""
        hps_str = ""
        try:
            r_edit = requests.get(
                f"{base_url}nontender/{kode_paket}/edit",
                headers=headers, timeout=15
            )
            hps_str = _parse_hps_dari_edit(r_edit.text)
            jenis_kontrak = _parse_jenis_kontrak_dari_edit(r_edit.text)
        except Exception as e:
            errors.append(f"{kode_paket}: gagal fetch edit — {e}")

        # 3. Deteksi jenis PL
        nama_lower = nama_paket.lower()
        if any(k in nama_lower for k in ["konsultan", "perencanaan", "pengawasan", "supervisi", "manajemen konstruksi"]):
            jenis_pl = "JKK"
        else:
            jenis_pl = "PK"

        data = {
            "kode_paket":      kode_paket,
            "id_nontender":    id_nontender,
            "nama_paket":      nama_paket,
            "satker":          satker,
            "nilai_hps":       hps_str,
            "jenis_pl":        jenis_pl,
            "jenis_kontrak":   jenis_kontrak,
            "status":          status_spse.lower() if status_spse else "draft",
            "diambil_pada":    datetime.now(timezone.utc).isoformat(),
        }

        try:
            _sb().table("draft_paket_pl").upsert(data, on_conflict="kode_paket").execute()
            scraped += 1
        except Exception as e:
            errors.append(f"{kode_paket}: gagal upsert — {e}")

    log(f"Selesai: {scraped} paket disimpan, {len(errors)} error")
    return {"ok": True, "scraped": scraped, "errors": errors}


# ============================================================
# Download Dokumen Paket PL dari SPSE
# ============================================================

def download_dokumen_paket_pl(
    kode_paket: str,
    folder_tujuan: str,
    progress_cb=None,
) -> dict:
    """
    Download dokumen dari endpoint non-tender PP ke folder_tujuan:
      - /dokumennontender/{kode}/spek  → KAK, Daftar Personil, RAB
      - /dokumennontender/{kode}/docsskk → Rancangan SPK/SPMK/SSUK/SSKK

    Pakai cookie PP via spse_browser.get_spse_cookies().
    Return: {"ok": [...], "error": [...]}
    """
    import requests
    import urllib.parse
    from bs4 import BeautifulSoup
    import spse_browser

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    os.makedirs(folder_tujuan, exist_ok=True)
    hasil = {"ok": [], "error": []}

    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        hasil["error"].append("Cookie SPSE kosong — buka Chrome SPSE dan login ulang.")
        return hasil

    hdrs = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{BASE_URL}/admin/pegawai",
    }

    def _unique_dst(folder, fname):
        dst = os.path.join(folder, fname)
        if not os.path.exists(dst):
            return dst
        base, ext = os.path.splitext(fname)
        n = 2
        while True:
            candidate = os.path.join(folder, f"{base}_{n}{ext}")
            if not os.path.exists(candidate):
                return candidate
            n += 1

    def _download_links_dari_endpoint(endpoint_url, label):
        """Scrape link /dl/ dari endpoint, download semua file."""
        try:
            r = requests.get(endpoint_url, headers=hdrs, timeout=15)
            if r.status_code == 403:
                log(f"  ⏭ {label}: 403 Forbidden")
                return
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/dl/" not in href:
                    continue
                fname_raw = a.get_text(strip=True)
                fname_raw = re.sub(r"\s*-\s*\d+\s*[KkMm][Bb]\s*$", "", fname_raw, re.IGNORECASE).strip()
                fname = re.sub(r'[<>:"/\\|?*]', "_", fname_raw).strip() or "dokumen"
                url_dl = f"https://spse.inaproc.id{href}" if href.startswith("/") else href
                links.append((url_dl, fname))

            log(f"  📂 {label}: {len(links)} file")
            for url_dl, fname in links:
                try:
                    r_dl = requests.get(url_dl, headers=hdrs, timeout=30, stream=True)
                    r_dl.raise_for_status()
                    cd = r_dl.headers.get("Content-Disposition", "")
                    m_cd = re.search(r'filename[^;=\n]*=["\']?([^"\';\n]+)', cd)
                    if m_cd:
                        clean = re.sub(r'[<>:"/\\|?*]', "_", urllib.parse.unquote_plus(m_cd.group(1).strip())).strip()
                        if clean:
                            fname = clean
                    dst = _unique_dst(folder_tujuan, fname)
                    with open(dst, "wb") as f:
                        for chunk in r_dl.iter_content(65536):
                            f.write(chunk)
                    hasil["ok"].append(dst)
                    log(f"    ✅ {os.path.basename(dst)}")
                except Exception as e:
                    hasil["error"].append(f"{fname}: {e}")
                    log(f"    ❌ {fname}: {e}")
        except Exception as e:
            hasil["error"].append(f"{label}: {e}")
            log(f"  ❌ {label}: {e}")

    ENDPOINTS = [
        (f"{BASE_URL}/dokumennontender/{kode_paket}/spek",      "KAK & Personil"),
        (f"{BASE_URL}/dokumennontender/{kode_paket}/docsskk",   "Rancangan Kontrak"),
        (f"{BASE_URL}/dokumennontender/{kode_paket}/docuraian", "Uraian Singkat Pekerjaan"),
        (f"{BASE_URL}/dokumennontender/{kode_paket}/lainnya",   "Informasi Lainnya"),
        (f"{BASE_URL}/nontender/{kode_paket}/edit",             "Nota Dinas PPK"),
    ]

    for url_ep, label_ep in ENDPOINTS:
        _download_links_dari_endpoint(url_ep, label_ep)

    log(f"🏁 Download selesai: {len(hasil['ok'])} file OK, {len(hasil['error'])} error")

    # ── Catat basename PDF uraian singkat ke Supabase
    try:
        for fpath in hasil["ok"]:
            bn = os.path.basename(fpath).lower()
            if "uraian" in bn and bn.endswith(".pdf"):
                _sb().table("draft_paket_pl").update(
                    {"nama_file_uraian": os.path.basename(fpath)}
                ).eq("kode_paket", kode_paket).execute()
                log(f"  📝 nama_file_uraian: {os.path.basename(fpath)}")
                break
    except Exception as e:
        log(f"  ⚠ gagal simpan nama_file_uraian: {e}")

    # ── Gabung semua PDF jadi 1 draft (tiru flow tender)
    try:
        from inbox_engine import _gabung_pdf_draft
        nama_paket_row = _sb().table("draft_paket_pl").select("nama_paket").eq(
            "kode_paket", kode_paket
        ).maybe_single().execute()
        nama_paket = (nama_paket_row.data or {}).get("nama_paket", kode_paket) if nama_paket_row else kode_paket
        nama_clean = re.sub(r'[<>:"/\\|?*]', "_", nama_paket)[:60].strip()
        draft_path = os.path.join(folder_tujuan, f"Draft_PL_{nama_clean}.pdf")
        # urut: KAK + RAB + Personil + Rincian + Rancangan + Uraian + Lainnya + NotaDinas
        ordered = sorted(hasil["ok"], key=lambda p: _pl_pdf_sort_key(os.path.basename(p)))
        merged = _gabung_pdf_draft(draft_path, ordered, progress_cb)
        hasil["draft_pdf"] = merged
        log(f"📎 Draft PDF gabungan: {os.path.basename(merged)}")
    except Exception as e:
        import traceback as _tb
        log(f"❌ Gagal gabung PDF: {e}")
        log(f"   {_tb.format_exc()[-300:]}")
        hasil["error"].append(f"Gabung PDF: {e}")

    return hasil


def _pl_pdf_sort_key(fname: str) -> tuple:
    """Urutan gabung draft PL: KAK → RAB/Personil → Rancangan → Uraian → Lainnya → Nota."""
    f = fname.lower()
    if "kak" in f: return (0, f)
    if "rab" in f: return (1, f)
    if "personil" in f or "personel" in f: return (2, f)
    if "rincian" in f or "prn" in f: return (3, f)
    if "rancangan" in f or "sskk" in f or "ssuk" in f or "spk" in f or "spmk" in f: return (4, f)
    if "uraian" in f: return (5, f)
    if "rekomendasi" in f or "lainnya" in f: return (6, f)
    if "permohonan" in f or "nota" in f: return (7, f)
    return (9, f)
