"""
jadwal_engine_pl.py — Jadwal PL non-tender (5 tahap).

Endpoints (production):
- GET  /jadwalnontender/{id}/list
- POST /simpanjadwalnontender?id={id}

5 Tahap PL:
1. Upload Dokumen Penawaran
2. Pembukaan Dokumen Penawaran
3. Evaluasi Penawaran
4. Klarifikasi Teknis dan Negosiasi
5. Penandatanganan Kontrak

Catatan: id endpoint = id_nontender (kolom 0 dt/paketpp), bukan kode_paket.
"""
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

import spse_browser
from config import SPSE_BASE_URL
from jadwal_engine import is_hari_kerja, geser_ke_hari_kerja, geser_ke_jam_kerja, format_spse_datetime

BASE = SPSE_BASE_URL.rstrip("/")
HDRS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": BASE + "/admin/pegawai",
}


# ─────────────────────────────────────────────────────────────────────────────
# Hitung jadwal 5 tahap PL
# ─────────────────────────────────────────────────────────────────────────────

def _tambah_hari_kerja(dt: datetime, n: int) -> datetime:
    """Geser dt maju n hari kerja (skip Sabtu/Minggu + hari libur)."""
    result = dt
    added = 0
    while added < n:
        result += timedelta(days=1)
        if is_hari_kerja(result):
            added += 1
    return result


def hitung_jadwal_pl(tgl_mulai: datetime) -> list[dict]:
    """
    Hitung 5 tahap PL dari tanggal mulai (T1).

    Pola yang dikonfirmasi user (2026-05-17):
    - T1: mulai D jam X → selesai D+2 hari kerja jam X (jam sama)
    - T2: T1.selesai → T1.selesai + 65 menit (hari sama, no geser)
    - T3: T2.selesai + 1 menit → mulai; selesai = T3.mulai + 2 hari kerja replace(hour=16)
    - T4: hari sama T3.selesai, replace(hour=9) → replace(hour=15,minute=45)
    - T5: geser_ke_hari_kerja(T4.selesai + 1 day) replace(hour=8) → +7 hari kerja replace(hour=16)
    """
    # T1 Upload Penawaran
    t1_mulai = geser_ke_jam_kerja(tgl_mulai)
    t1_selesai = _tambah_hari_kerja(t1_mulai, 2).replace(
        hour=t1_mulai.hour, minute=t1_mulai.minute, second=0, microsecond=0
    )

    # T2 Pembukaan Penawaran (hari sama T1.selesai, +65 menit)
    t2_mulai = t1_selesai + timedelta(minutes=1)
    t2_selesai = t1_selesai + timedelta(minutes=65)

    # T3 Evaluasi Penawaran
    t3_mulai = t2_selesai + timedelta(minutes=1)
    t3_selesai = _tambah_hari_kerja(t3_mulai, 2).replace(hour=16, minute=0, second=0, microsecond=0)

    # T4 Klarifikasi + Negosiasi (hari sama T3.selesai)
    t4_mulai = t3_selesai.replace(hour=9, minute=0, second=0, microsecond=0)
    t4_selesai = t3_selesai.replace(hour=15, minute=45, second=0, microsecond=0)

    # T5 Penandatanganan Kontrak
    t5_mulai_kand = t4_selesai + timedelta(days=1)
    t5_mulai = geser_ke_hari_kerja(t5_mulai_kand).replace(hour=8, minute=0, second=0, microsecond=0)
    t5_selesai = _tambah_hari_kerja(t5_mulai, 7).replace(hour=16, minute=0, second=0, microsecond=0)

    return [
        {"nama": "Upload Dokumen Penawaran",         "mulai": t1_mulai, "selesai": t1_selesai},
        {"nama": "Pembukaan Dokumen Penawaran",      "mulai": t2_mulai, "selesai": t2_selesai},
        {"nama": "Evaluasi Penawaran",               "mulai": t3_mulai, "selesai": t3_selesai},
        {"nama": "Klarifikasi Teknis dan Negosiasi", "mulai": t4_mulai, "selesai": t4_selesai},
        {"nama": "Penandatanganan Kontrak",          "mulai": t5_mulai, "selesai": t5_selesai},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Scrape form fields PL
# ─────────────────────────────────────────────────────────────────────────────

def scrap_hidden_fields_pl(id_nontender: str) -> dict:
    """GET /jadwalnontender/{id}/list — scrap hidden fields + CSRF."""
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        raise RuntimeError("Cookie SPSE kosong — login PP di Chrome dulu.")

    url = f"{BASE}/jadwalnontender/{id_nontender}/list"
    r = requests.get(url, headers={**HDRS, "Cookie": cookie_str}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"GET jadwalnontender gagal: HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Form jadwal (action mengandung 'simpanjadwalnontender')
    form_jadwal = None
    for f in soup.find_all("form"):
        if "simpanjadwalnontender" in (f.get("action") or ""):
            form_jadwal = f
            break
    if not form_jadwal:
        raise RuntimeError("Form simpanjadwalnontender tidak ditemukan.")

    # CSRF
    csrf_inp = form_jadwal.find("input", {"name": "authenticityToken"})
    csrf = csrf_inp["value"] if csrf_inp else None

    # Field id (paket_id)
    id_inp = form_jadwal.find("input", {"name": "id"})
    paket_id_val = id_inp["value"] if id_inp else id_nontender

    # Rows (hidden: akt_id, dtj_id, thp_id + text: tglawal, tglakhir)
    rows = []
    # Cari semua tr yang ada dtj_id-nya
    seen_idx = set()
    for inp in form_jadwal.find_all("input", {"name": lambda n: n and "dtj_id" in n}):
        name = inp["name"]
        # jadwalList[N].dtj_id → idx = N
        import re
        m = re.search(r"jadwalList\[(\d+)\]\.dtj_id", name)
        if not m:
            continue
        idx = int(m.group(1))
        if idx in seen_idx:
            continue
        seen_idx.add(idx)

        # Cari semua hidden untuk row ini
        prefix = f"jadwalList[{idx}]."
        hidden = {}
        for h in form_jadwal.find_all("input", type="hidden"):
            n = h.get("name", "")
            if n.startswith(prefix):
                hidden[n] = h.get("value", "")

        rows.append({
            "index":        idx,
            "hidden":       hidden,
            "name_mulai":   f"{prefix}dtj_tglawal",
            "name_selesai": f"{prefix}dtj_tglakhir",
        })

    rows.sort(key=lambda r: r["index"])

    return {
        "csrf":     csrf,
        "id":       paket_id_val,
        "rows":     rows,
        "cookie":   cookie_str,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Build payload + submit
# ─────────────────────────────────────────────────────────────────────────────

def build_payload_pl(scraped: dict, jadwal_list: list[dict]) -> dict:
    payload = {}
    if scraped.get("csrf"):
        payload["authenticityToken"] = scraped["csrf"]
    if scraped.get("id"):
        payload["id"] = scraped["id"]

    for i, jadwal in enumerate(jadwal_list):
        if i >= len(scraped.get("rows", [])):
            break
        row = scraped["rows"][i]
        for hn, hv in row.get("hidden", {}).items():
            payload[hn] = hv
        payload[row["name_mulai"]]   = format_spse_datetime(jadwal["mulai"])
        payload[row["name_selesai"]] = format_spse_datetime(jadwal["selesai"])

    return payload


def submit_jadwal_pl(id_nontender: str, payload: dict, cookie_str: str = None) -> dict:
    if not cookie_str:
        cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        raise RuntimeError("Cookie SPSE kosong.")

    url = f"{BASE}/simpanjadwalnontender?id={id_nontender}"
    headers = {
        **HDRS,
        "Cookie": cookie_str,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE.split("/tapinkab")[0] if "/tapinkab" in BASE else "https://spse.inaproc.id",
        "Referer": f"{BASE}/jadwalnontender/{id_nontender}/list",
    }

    r = requests.post(url, data=payload, headers=headers, allow_redirects=False, timeout=30)
    return {
        "ok":       r.status_code in (200, 302),
        "status":   r.status_code,
        "body":     (r.text or "")[:2000],
        "redirect": r.headers.get("Location", ""),
    }


def auto_fill_jadwal_pl(id_nontender: str, tgl_mulai: datetime) -> dict:
    """Full flow: scrap → hitung → build payload."""
    scraped = scrap_hidden_fields_pl(id_nontender)
    jadwal_list = hitung_jadwal_pl(tgl_mulai)
    payload = build_payload_pl(scraped, jadwal_list)
    return {"scraped": scraped, "jadwal_list": jadwal_list, "payload": payload}


def submit_full_pl(id_nontender: str, tgl_mulai: datetime) -> dict:
    result = auto_fill_jadwal_pl(id_nontender, tgl_mulai)
    cookie = result["scraped"].get("cookie")
    sub = submit_jadwal_pl(id_nontender, result["payload"], cookie_str=cookie)
    result["submit_result"] = sub
    return result
