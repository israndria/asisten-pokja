"""
Jadwal Engine v2 — hitung tanggal + POST langsung ke SPSE (tanpa navigasi manual).

Flow:
1. User input paket_id + tanggal mulai di Streamlit
2. Engine auto-navigate ke /jadwal/[ID]/list via CDP
3. Scrap hidden fields (akt_id, dtj_id, thp_id, CSRF)
4. Hitung 12 tahapan
5. POST langsung ke /jadwal/[ID]/simpan
"""

import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import spse_browser
from jadwal_config import TAHAPAN, JAM_KERJA_MULAI, JAM_KERJA_SELESAI, LIBUR_API_URLS

BASE_URL = "https://spse.inaproc.id/tapinkab"
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "Referer": BASE_URL + "/",
}

# ─────────────────────────────────────────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────────────────────────────────────────
TZ_WITA = ZoneInfo("Asia/Makassar")
TZ_WIB = ZoneInfo("Asia/Jakarta")

# Cache libur nasional per tahun
_libur_cache: dict[int, list[datetime]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Libur Nasional
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_libur_nasional(tahun: int) -> list[datetime]:
    """Fetch libur nasional dari API."""
    if tahun in _libur_cache:
        return _libur_cache[tahun]

    libur_list = []
    for bulan in range(1, 13):
        for url_template in LIBUR_API_URLS:
            url = url_template.format(month=bulan, year=tahun)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "tanggal" in item:
                                try:
                                    tgl = datetime.strptime(item["tanggal"], "%Y-%m-%d")
                                    if tgl not in libur_list:
                                        libur_list.append(tgl)
                                except ValueError:
                                    pass
                    break
            except Exception:
                continue

    _libur_cache[tahun] = libur_list
    return libur_list


def is_libur_nasional(dt: datetime) -> bool:
    """Cek apakah tanggal adalah libur nasional."""
    liburs = _fetch_libur_nasional(dt.year)
    for l in liburs:
        if l.year == dt.year and l.month == dt.month and l.day == dt.day:
            return True
    return False


def is_weekend(dt: datetime) -> bool:
    return dt.weekday() >= 5


def is_hari_kerja(dt: datetime) -> bool:
    return not is_weekend(dt) and not is_libur_nasional(dt)


def is_jam_kerja(dt: datetime) -> bool:
    return JAM_KERJA_MULAI <= dt.hour < JAM_KERJA_SELESAI


def geser_ke_hari_kerja(dt: datetime, jam_mulai: int = None) -> datetime:
    """Geser ke hari kerja terdekat (skip weekend/libur)."""
    if jam_mulai is None:
        jam_mulai = JAM_KERJA_MULAI

    attempts = 0
    while (is_weekend(dt) or is_libur_nasional(dt)) and attempts < 30:
        dt = dt + timedelta(days=1)
        attempts += 1

    if not is_jam_kerja(dt):
        dt = dt.replace(hour=jam_mulai, minute=0, second=0, microsecond=0)

    return dt


def geser_ke_jam_kerja(dt: datetime) -> datetime:
    """Jika di luar jam kerja, geser ke jam kerja berikutnya."""
    if dt.hour < JAM_KERJA_MULAI or dt.hour >= JAM_KERJA_SELESAI:
        dt = dt.replace(hour=JAM_KERJA_MULAI, minute=0, second=0, microsecond=0)
        return geser_ke_hari_kerja(dt)
    return dt


# ─────────────────────────────────────────────────────────────────────────────
# Hitung 12 Tahapan Jadwal
# ─────────────────────────────────────────────────────────────────────────────

def hitung_jadwal(tgl_mulai: datetime) -> list[dict]:
    """
    Hitung semua tanggal berdasarkan 1 tanggal mulai.
    Return: list of dict {nama, mulai, selesai, aturan}
    """
    hasil = []

    # Tahap 1: Pengumuman Pascakualifikasi (5 hari persis)
    t1_mulai = tgl_mulai
    t1_selesai = t1_mulai + timedelta(days=5)
    hasil.append({"nama": TAHAPAN[0]["nama"], "mulai": t1_mulai, "selesai": t1_selesai})

    # Tahap 2: Download Dokumen Pemilihan (6 hari persis)
    t2_mulai = tgl_mulai
    t2_selesai = t2_mulai + timedelta(days=6)
    hasil.append({"nama": TAHAPAN[1]["nama"], "mulai": t2_mulai, "selesai": t2_selesai})

    # Tahap 3: Pemberian Penjelasan (3 hari setelah Tahap 1, hari kerja, 2 jam)
    t3_kandidat = t1_mulai + timedelta(days=3)
    t3_mulai = geser_ke_hari_kerja(t3_kandidat)
    t3_selesai = t3_mulai + timedelta(hours=2)
    hasil.append({"nama": TAHAPAN[2]["nama"], "mulai": t3_mulai, "selesai": t3_selesai})

    # Tahap 4: Upload Dokumen Penawaran (2 jam setelah Tahap 3 selesai, 3 hari kalender)
    t4_mulai = t3_selesai + timedelta(hours=2)
    t4_mulai = geser_ke_hari_kerja(t4_mulai)
    t4_selesai_kandidat = t4_mulai + timedelta(days=3)
    t4_selesai = geser_ke_hari_kerja(t4_selesai_kandidat)
    hasil.append({"nama": TAHAPAN[3]["nama"], "mulai": t4_mulai, "selesai": t4_selesai})

    # Tahap 5: Pembukaan Dokumen (1 menit setelah Tahap 4 selesai, 24 jam)
    t5_mulai = t4_selesai + timedelta(minutes=1)
    t5_selesai = t5_mulai + timedelta(hours=24)
    hasil.append({"nama": TAHAPAN[4]["nama"], "mulai": t5_mulai, "selesai": t5_selesai})

    # Tahap 6: Evaluasi (1 menit setelah Tahap 5 dimulai, 4 hari, skip weekend/libur di akhir)
    t6_mulai = t5_mulai + timedelta(minutes=1)
    t6_selesai_kandidat = t6_mulai + timedelta(days=4)
    t6_selesai = geser_ke_hari_kerja(t6_selesai_kandidat)
    hasil.append({"nama": TAHAPAN[5]["nama"], "mulai": t6_mulai, "selesai": t6_selesai})

    # Tahap 7: Pembuktian Kualifikasi (hari sama akhir Tahap 6, 09:00-15:30)
    t7_mulai = t6_selesai.replace(hour=9, minute=0, second=0, microsecond=0)
    t7_selesai = t6_selesai.replace(hour=15, minute=30, second=0, microsecond=0)
    if t7_mulai.hour >= 15 or (t7_mulai.hour == 15 and t7_mulai.minute >= 30):
        t7_mulai = geser_ke_hari_kerja(t6_selesai + timedelta(days=1), jam_mulai=9)
        t7_selesai = t7_mulai.replace(hour=15, minute=30)
    hasil.append({"nama": TAHAPAN[6]["nama"], "mulai": t7_mulai, "selesai": t7_selesai})

    # Tahap 8: Penetapan Pemenang (setelah Tahap 7, durasi 2 jam)
    t8_mulai = t7_selesai
    t8_selesai = t8_mulai + timedelta(hours=2)
    hasil.append({"nama": TAHAPAN[7]["nama"], "mulai": t8_mulai, "selesai": t8_selesai})

    # Tahap 9: Pengumuman Pemenang (setelah Tahap 8, durasi 4 jam)
    t9_mulai = t8_selesai
    t9_selesai = t9_mulai + timedelta(hours=4)
    hasil.append({"nama": TAHAPAN[8]["nama"], "mulai": t9_mulai, "selesai": t9_selesai})

    # Tahap 10: Masa Sanggah (5 hari kalender setelah Tahap 9, kelonggaran jam kerja)
    t10_kandidat = t9_selesai + timedelta(days=5)
    t10_mulai = geser_ke_jam_kerja(t10_kandidat)
    t10_selesai = t10_mulai + timedelta(days=5)
    t10_selesai = geser_ke_hari_kerja(t10_selesai)
    hasil.append({"nama": TAHAPAN[9]["nama"], "mulai": t10_mulai, "selesai": t10_selesai})

    # Tahap 11: SPPBJ (1 jam setelah Tahap 10, durasi 5 hari, skip weekend/libur)
    t11_kandidat = t10_selesai + timedelta(hours=1)
    t11_mulai = geser_ke_hari_kerja(t11_kandidat)
    t11_selesai = t11_mulai + timedelta(days=5)
    t11_selesai = geser_ke_hari_kerja(t11_selesai)
    hasil.append({"nama": TAHAPAN[10]["nama"], "mulai": t11_mulai, "selesai": t11_selesai})

    # Tahap 12: Kontrak (1 hari setelah Tahap 11 dimulai, pola sama)
    t12_kandidat = t11_mulai + timedelta(days=1)
    t12_mulai = geser_ke_hari_kerja(t12_kandidat)
    t12_selesai = t12_mulai + timedelta(days=5)
    t12_selesai = geser_ke_hari_kerja(t12_selesai)
    hasil.append({"nama": TAHAPAN[11]["nama"], "mulai": t12_mulai, "selesai": t12_selesai})

    return hasil


def format_spse_datetime(dt: datetime) -> str:
    """Format datetime sesuai input SPSE: DD/MM/YYYY HH:mm"""
    return dt.strftime("%d/%m/%Y %H:%M")


# ─────────────────────────────────────────────────────────────────────────────
# Scrap Hidden Fields (auto-navigate, user tidak perlu lakukan apa pun)
# ─────────────────────────────────────────────────────────────────────────────

def scrap_hidden_fields(paket_id: str) -> dict | None:
    """
    Scrap hidden fields via pure HTTP GET (tanpa navigasi browser).
    Ambil cookie dari CDP, GET /jadwal/[ID]/list, parse HTML.
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        raise RuntimeError("Cookie SPSE tidak ditemukan. Pastikan Chrome sudah login SPSE.")

    url = f"{BASE_URL}/jadwal/{paket_id}/list"
    resp = requests.get(url, headers={**HEADERS_BASE, "Cookie": cookie_str}, timeout=20)

    if resp.status_code == 302 or "login" in resp.url.lower():
        raise RuntimeError("Session SPSE expired. Silakan login ulang di Chrome.")
    if resp.status_code != 200:
        raise RuntimeError(f"Gagal akses halaman jadwal: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form", {"id": "jadwalEdit"})
    if not form:
        raise RuntimeError("Form jadwalEdit tidak ditemukan. Pastikan kode paket benar dan sudah login.")

    # CSRF token
    csrf_input = form.find("input", {"name": "authenticityToken"})
    csrf = csrf_input["value"] if csrf_input else None

    # id paket (hidden)
    id_input = form.find("input", {"name": "id"})
    paket_id_val = id_input["value"] if id_input else paket_id

    # jamAwal / jamAkhir (id-based, bukan name)
    jam_awal_input = soup.find(id="jamAwal")
    jam_akhir_input = soup.find(id="jamAkhir")
    jam_awal = jam_awal_input["value"] if jam_awal_input else "00:00"
    jam_akhir = jam_akhir_input["value"] if jam_akhir_input else "23:59"

    # Rows: tiap baris jadwal
    rows = []
    tbl = form.find("tbody")
    if tbl:
        for idx, tr in enumerate(tbl.find_all("tr")):
            hidden = {}
            for h in tr.find_all("input", type="hidden"):
                if h.get("name"):
                    hidden[h["name"]] = h.get("value", "")

            mulai_input = tr.find("input", {"name": lambda n: n and n.endswith("dtj_tglawal")})
            selesai_input = tr.find("input", {"name": lambda n: n and n.endswith("dtj_tglakhir")})

            # Nama tahap: ambil dari teks td ke-2, potong di newline/spasi berlebih
            nama = f"Tahap {idx + 1}"
            tds = tr.find_all("td")
            if len(tds) >= 2:
                nama_raw = tds[1].get_text(separator="\n").strip()
                nama = nama_raw.split("\n")[0].strip()

            rows.append({
                "index": idx,
                "nama": nama,
                "hidden": hidden,
                "name_mulai": mulai_input["name"] if mulai_input else f"jadwalList[{idx}].dtj_tglawal",
                "name_selesai": selesai_input["name"] if selesai_input else f"jadwalList[{idx}].dtj_tglakhir",
            })

    return {
        "csrf": csrf,
        "id": paket_id_val,
        "jamAwal": jam_awal,
        "jamAkhir": jam_akhir,
        "rows": rows,
        "cookie": cookie_str,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Build Payload + Submit
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(scraped: dict, jadwal_list: list[dict]) -> dict:
    """Build payload POST dari hidden fields + jadwal yang sudah dihitung."""
    payload = {}

    # Hidden fields umum
    payload["id"] = scraped.get("id", "")
    payload["jamAwal"] = scraped.get("jamAwal", "00:00")
    payload["jamAkhir"] = scraped.get("jamAkhir", "23:59")
    if scraped.get("csrf"):
        payload["authenticityToken"] = scraped["csrf"]

    # Isi setiap baris
    for i, jadwal in enumerate(jadwal_list):
        if i < len(scraped.get("rows", [])):
            row = scraped["rows"][i]
            # Hidden fields per row
            for hname, hval in row.get("hidden", {}).items():
                payload[hname] = hval
            # Tanggal
            if row.get("name_mulai"):
                payload[row["name_mulai"]] = format_spse_datetime(jadwal["mulai"])
            if row.get("name_selesai"):
                payload[row["name_selesai"]] = format_spse_datetime(jadwal["selesai"])

    # Tombol simpan
    payload["simpan"] = "simpan"

    return payload


def submit_jadwal(paket_id: str, payload: dict, cookie_str: str = None) -> dict:
    """POST langsung ke /jadwal/[ID]/simpan via pure HTTP requests."""
    if not cookie_str:
        cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        raise RuntimeError("Cookie SPSE tidak ditemukan.")

    url = f"{BASE_URL}/jadwal/{paket_id}/simpan"
    headers = {
        **HEADERS_BASE,
        "Cookie": cookie_str,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://spse.inaproc.id",
        "Referer": f"{BASE_URL}/jadwal/{paket_id}/list",
    }

    resp = requests.post(url, data=payload, headers=headers, allow_redirects=False, timeout=30)
    body = ""
    try:
        body = resp.text[:2000]
    except Exception:
        pass

    return {
        "ok": resp.status_code in (200, 302),
        "status": resp.status_code,
        "body": body,
        "redirect": resp.headers.get("Location", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main Flow: scrap → hitung → build → submit (semua otomatis)
# ─────────────────────────────────────────────────────────────────────────────

def auto_fill_jadwal(paket_id: str, tgl_mulai: datetime) -> dict:
    """
    Full flow: scrap hidden fields → hitung jadwal → build payload.
    Return: {scraped, jadwal_list, payload}
    """
    scraped = scrap_hidden_fields(paket_id)
    if not scraped:
        raise RuntimeError("Gagal scrap hidden fields. Pastikan Chrome sudah login SPSE.")
    if not scraped.get("csrf"):
        raise RuntimeError("CSRF token tidak ditemukan. Pastikan sudah login di SPSE.")

    jadwal_list = hitung_jadwal(tgl_mulai)
    payload = build_payload(scraped, jadwal_list)

    return {
        "scraped": scraped,
        "jadwal_list": jadwal_list,
        "payload": payload,
    }


def submit_full(paket_id: str, tgl_mulai: datetime) -> dict:
    """
    Full flow: scrap → hitung → build → submit.
    Return: {scraped, jadwal_list, payload, submit_result}
    """
    result = auto_fill_jadwal(paket_id, tgl_mulai)
    # Gunakan cookie yang sudah disimpan saat scrap (biar konsisten)
    cookie_str = result["scraped"].get("cookie")
    submit_result = submit_jadwal(paket_id, result["payload"], cookie_str=cookie_str)
    result["submit_result"] = submit_result
    return result
