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
from jadwal_config import TAHAPAN, JAM_KERJA_MULAI, JAM_KERJA_SELESAI, LIBUR_API_URLS, LIBUR_HARDCODE

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
    """
    Ambil libur nasional dari 2 sumber:
    1. date.nager.at — 8 hari resmi non-Islam (gratis, reliable)
    2. LIBUR_HARDCODE — hari libur Islam + cuti bersama per tahun
    """
    if tahun in _libur_cache:
        return _libur_cache[tahun]

    libur_list = []

    # Sumber 1: nager.at (format: list of {date: "YYYY-MM-DD", ...})
    try:
        url = f"https://date.nager.at/api/v3/PublicHolidays/{tahun}/ID"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for item in data:
                if isinstance(item, dict) and "date" in item:
                    try:
                        tgl = datetime.strptime(item["date"], "%Y-%m-%d")
                        if tgl not in libur_list:
                            libur_list.append(tgl)
                    except ValueError:
                        pass
    except Exception:
        pass  # fallback ke hardcode saja

    # Sumber 2: hardcode hari libur Islam + cuti bersama
    for tgl_str in LIBUR_HARDCODE.get(tahun, []):
        try:
            tgl = datetime.strptime(tgl_str, "%Y-%m-%d")
            if tgl not in libur_list:
                libur_list.append(tgl)
        except ValueError:
            pass

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
    """Cek jam kerja dengan batas akhir inklusif tepat pada ``17:00``."""
    waktu = (
        dt.hour * 3600
        + dt.minute * 60
        + dt.second
        + dt.microsecond / 1_000_000
    )
    mulai = JAM_KERJA_MULAI * 3600
    selesai = JAM_KERJA_SELESAI * 3600
    return mulai <= waktu <= selesai


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
    if not is_jam_kerja(dt):
        dt = dt.replace(hour=JAM_KERJA_MULAI, minute=0, second=0, microsecond=0)
        return geser_ke_hari_kerja(dt)
    return dt


def geser_hindari_jumat(dt: datetime) -> datetime:
    """Jika Jumat, geser mundur ke Kamis. Jika Kamis libur, geser maju ke Senin (via geser_ke_hari_kerja)."""
    if dt.weekday() == 4:  # Jumat
        kamis = dt - timedelta(days=1)
        if is_hari_kerja(kamis):
            return kamis
        # Kamis libur → maju ke Senin (atau hari kerja berikutnya)
        senin = dt + timedelta(days=3)
        return geser_ke_hari_kerja(senin)
    return dt


def h_min_1_hari_kerja(dt: datetime) -> datetime:
    """Mundur 1 hari kerja (skip weekend/libur)."""
    res = dt - timedelta(days=1)
    attempts = 0
    while (is_weekend(res) or is_libur_nasional(res)) and attempts < 30:
        res = res - timedelta(days=1)
        attempts += 1
    return res


def paskan_t6_selesai(dt: datetime) -> datetime:
    """
    Pastikan T6 selesai BUKAN Jumat, BUKAN Senin.
    Supaya T7 (Mulai H-1) jatuh utuh 2 hari kerja dalam seminggu (misal Senin-Selasa).
    """
    dt = geser_ke_hari_kerja(dt)
    
    if dt.weekday() == 4:  # Jumat mundur ke Kamis
        dt = dt - timedelta(days=1)
        
    attempts = 0
    while attempts < 30:
        if not is_hari_kerja(dt):
            dt = dt + timedelta(days=1)
        elif dt.weekday() == 4:  # Batal Jumat
            dt = dt + timedelta(days=1)
        else:
            h_min = h_min_1_hari_kerja(dt)
            if h_min.weekday() == 4:  # Jika H-1 Jumat (dt berarti Senin)
                dt = dt + timedelta(days=1)
            else:
                return dt
        attempts += 1
    return dt


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Hitung T3 Pemberian Penjelasan
# ─────────────────────────────────────────────────────────────────────────────

def _hitung_t3(t1_mulai: datetime) -> datetime:
    """
    Hitung tanggal Pemberian Penjelasan (T3) berdasarkan hari tayang (T1).

    Senin  (+3=Kamis): Kamis libur→Rabu; Rabu+Kamis libur→Jumat; semua libur→maju
    Selasa (+3=Jumat): Jumat hari kerja→Kamis (diblok mundur); Jumat libur→Kamis;
                       Kamis+Jumat libur→Senin
    Rabu   (+2=Jumat): Jumat hari kerja→Jumat; Jumat libur→maju (Senin, dst)
    Kamis/Jumat: geser_ke_hari_kerja maju biasa dari +3
    """
    jam = {"hour": JAM_KERJA_MULAI, "minute": 0, "second": 0, "microsecond": 0}
    hari_tayang = t1_mulai.weekday()  # 0=Sen, 1=Sel, 2=Rab, 3=Kam, 4=Jum

    if hari_tayang == 0:  # Senin → target Kamis
        kamis = (t1_mulai + timedelta(days=3)).replace(**jam)
        if is_hari_kerja(kamis):
            return kamis
        rabu = (t1_mulai + timedelta(days=2)).replace(**jam)
        if is_hari_kerja(rabu):
            return rabu
        # Rabu+Kamis libur → Jumat atau maju
        jumat = (t1_mulai + timedelta(days=4)).replace(**jam)
        return geser_ke_hari_kerja(jumat)

    elif hari_tayang == 1:  # Selasa → target Jumat, tapi diblok ke Kamis
        jumat = (t1_mulai + timedelta(days=3)).replace(**jam)
        kamis = (t1_mulai + timedelta(days=2)).replace(**jam)
        if is_hari_kerja(kamis):
            return kamis  # Jumat diblok → Kamis (libur atau tidak)
        # Kamis libur → Senin maju
        senin = (t1_mulai + timedelta(days=6)).replace(**jam)
        return geser_ke_hari_kerja(senin)

    elif hari_tayang == 2:  # Rabu → target Jumat (+2)
        jumat = (t1_mulai + timedelta(days=2)).replace(**jam)
        if is_hari_kerja(jumat):
            return jumat
        # Jumat libur → maju (Senin, dst)
        return geser_ke_hari_kerja((t1_mulai + timedelta(days=3)).replace(**jam))

    else:  # Kamis/Jumat → +3, geser maju biasa
        return geser_ke_hari_kerja((t1_mulai + timedelta(days=3)).replace(**jam))


# ─────────────────────────────────────────────────────────────────────────────
# Hitung 12 Tahapan Jadwal
# ─────────────────────────────────────────────────────────────────────────────

def hitung_jadwal(tgl_mulai: datetime) -> list[dict]:
    """
    Hitung semua tanggal berdasarkan 1 tanggal mulai.
    Return: list of dict {nama, mulai, selesai}

    Pola diverifikasi dari 8 paket real (Sep–Nov 2025).
    """
    hasil = []

    # ── Tahap 1: Pengumuman Pascakualifikasi ──────────────────────────────────
    # Durasi: min 5 hari kalender. Selesai = mulai + 5 hari (jam sama).
    t1_mulai = tgl_mulai
    t1_selesai = t1_mulai + timedelta(days=5)
    hasil.append({"nama": TAHAPAN[0]["nama"], "mulai": t1_mulai, "selesai": t1_selesai})

    # ── Hitung T3 mulai (dibutuhkan untuk T4) ────────────────────────────────
    # Rule per hari tayang:
    #   Senin  (+3=Kamis): Kamis libur→Rabu, Rabu+Kamis libur→Jumat, semua libur→Senin
    #   Selasa (+3=Jumat): Jumat hari kerja→Kamis (diblok), Jumat libur→Kamis,
    #                      Kamis+Jumat libur→Senin
    #   Rabu   (+2=Jumat): Jumat hari kerja→Jumat, Jumat libur→Senin, dst maju
    #   Kamis/Jumat (+3=Minggu/Senin): geser_ke_hari_kerja maju biasa
    t3_mulai = _hitung_t3(t1_mulai)
    t3_selesai = t3_mulai + timedelta(hours=2)

    # ── T4 mulai = T3 selesai + 1 jam (pola dari data real) ──────────────────
    t4_mulai = geser_ke_jam_kerja(t3_selesai + timedelta(hours=1))

    # ── T4 selesai = T1 mulai + 6 hari kalender → hari kerja ─────────────────
    # Pola dari 8 paket: T4 selesai hampir selalu T1 mulai +6 hari (hari kerja).
    # Jam T4 selesai: ikut jam T3 selesai. Pastikan >= T4 mulai.
    t4_hari = t1_mulai + timedelta(days=6)
    t4_selesai = geser_ke_hari_kerja(t4_hari)
    t4_selesai = t4_selesai.replace(
        hour=t3_selesai.hour, minute=t3_selesai.minute, second=0, microsecond=0
    )
    # Fallback: jika T4 selesai <= T4 mulai (bisa terjadi jika T3 molor karena libur)
    if t4_selesai <= t4_mulai:
        t4_selesai = geser_ke_hari_kerja(t4_mulai + timedelta(days=1))
        t4_selesai = t4_selesai.replace(
            hour=t3_selesai.hour, minute=t3_selesai.minute, second=0, microsecond=0
        )

    # ── Tahap 2: Download Dokumen Pemilihan ───────────────────────────────────
    # Mulai: T1 mulai + 1 menit. Selesai: SAMA dengan T4 selesai (100% konsisten).
    t2_mulai = t1_mulai + timedelta(minutes=1)
    t2_selesai = t4_selesai
    hasil.append({"nama": TAHAPAN[1]["nama"], "mulai": t2_mulai, "selesai": t2_selesai})

    # Simpan T3 dan T4 (urutan array 0-11)
    hasil.append({"nama": TAHAPAN[2]["nama"], "mulai": t3_mulai, "selesai": t3_selesai})
    hasil.append({"nama": TAHAPAN[3]["nama"], "mulai": t4_mulai, "selesai": t4_selesai})

    # ── Tahap 5: Pembukaan Dokumen Penawaran ──────────────────────────────────
    # Mulai: T4 selesai + 1 menit.
    # Selesai: 23:59 hari yang sama (dari 5/8 paket), atau hari berikutnya 09:00.
    # Pakai 23:59 hari yang sama sebagai default (lebih sering).
    t5_mulai = t4_selesai + timedelta(minutes=1)
    t5_selesai = t5_mulai.replace(hour=23, minute=59, second=0, microsecond=0)
    hasil.append({"nama": TAHAPAN[4]["nama"], "mulai": t5_mulai, "selesai": t5_selesai})

    # ── Tahap 6: Evaluasi ─────────────────────────────────────────────────────
    # Mulai: T5 mulai + 1 menit.
    # Selesai: +3 hari kalender, hari kerja jam 16:00.
    # Rule T6: Selesai harus di hari kerja yang H-1 nya bukan Jumat (tidak boleh Senin).
    t6_mulai = t5_mulai + timedelta(minutes=1)
    t6_selesai_kandidat = t6_mulai + timedelta(days=3)
    t6_selesai_hari = paskan_t6_selesai(t6_selesai_kandidat)
    t6_selesai = t6_selesai_hari.replace(hour=16, minute=0, second=0, microsecond=0)
    hasil.append({"nama": TAHAPAN[5]["nama"], "mulai": t6_mulai, "selesai": t6_selesai})

    # ── Tahap 7: Pembuktian Kualifikasi ───────────────────────────────────────
    # Mulai: 1 hari kerja sebelum T6 selesai, jam 09:00.
    # Selesai: hari SAMA dengan T6 selesai, jam 15:30.
    # Total durasi 2 hari kerja berturut-turut.
    t7_mulai_kandidat = h_min_1_hari_kerja(t6_selesai)
    t7_mulai = t7_mulai_kandidat.replace(hour=9, minute=0, second=0, microsecond=0)
    t7_selesai = t6_selesai.replace(hour=15, minute=30, second=0, microsecond=0)
    hasil.append({"nama": TAHAPAN[6]["nama"], "mulai": t7_mulai, "selesai": t7_selesai})

    # ── Tahap 8: Penetapan Pemenang ───────────────────────────────────────────
    # Mulai: T7 selesai + 1 menit. Selesai: +1 jam.
    t8_mulai = t7_selesai + timedelta(minutes=1)
    t8_selesai = t8_mulai + timedelta(hours=1)
    hasil.append({"nama": TAHAPAN[7]["nama"], "mulai": t8_mulai, "selesai": t8_selesai})

    # ── Tahap 9: Pengumuman Pemenang ──────────────────────────────────────────
    # Mulai: T8 selesai + 1 menit. Selesai: +4 jam.
    t9_mulai = t8_selesai + timedelta(minutes=1)
    t9_selesai = t9_mulai + timedelta(hours=4)
    hasil.append({"nama": TAHAPAN[8]["nama"], "mulai": t9_mulai, "selesai": t9_selesai})

    # ── Tahap 10: Masa Sanggah ────────────────────────────────────────────────
    # Mulai: T9 selesai + 1 menit — boleh malam hari, HANYA geser jika weekend/libur.
    # Durasi: 5 hari kalender. Selesai geser ke hari kerja, jam sama dengan T10 mulai.
    t10_mulai = t9_selesai + timedelta(minutes=1)
    if not is_hari_kerja(t10_mulai):
        t10_mulai = geser_ke_hari_kerja(
            t10_mulai.replace(hour=8, minute=0, second=0, microsecond=0),
            jam_mulai=8
        )
    t10_selesai_kandidat = t10_mulai + timedelta(days=5)
    t10_selesai = geser_ke_hari_kerja(t10_selesai_kandidat)
    # Default jam selesai 08:00 mengikuti data real, tetapi tidak boleh
    # memundurkan waktu dari batas minimum 5 x 24 jam.
    t10_selesai_jam_kerja = t10_selesai.replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    t10_selesai = max(t10_selesai_jam_kerja, t10_selesai_kandidat)
    # Jika batas minimum jatuh malam hari, lanjutkan ke pagi hari kerja
    # berikutnya agar tahap berikutnya tidak dimulai larut malam.
    if t10_selesai.hour > 18:
        t10_selesai = geser_ke_hari_kerja(
            (t10_selesai + timedelta(days=1)).replace(
                hour=8, minute=0, second=0, microsecond=0
            ),
            jam_mulai=8,
        )
    hasil.append({"nama": TAHAPAN[9]["nama"], "mulai": t10_mulai, "selesai": t10_selesai})

    # ── Tahap 11: SPPBJ ───────────────────────────────────────────────────────
    # Mulai tepat saat T10 selesai. Jangan gunakan geser_ke_jam_kerja di sini:
    # jika T10 selesai setelah jam kerja, helper itu dapat memundurkan T11 ke
    # pukul 08:00 pada tanggal yang sama.
    # Selesai: fleksibel — set 5 hari kalender, hari kerja jam 16:00.
    t11_mulai = t10_selesai
    t11_selesai_kandidat = t11_mulai + timedelta(days=5)
    t11_selesai = geser_ke_hari_kerja(t11_selesai_kandidat)
    t11_selesai = t11_selesai.replace(hour=16, minute=0, second=0, microsecond=0)
    hasil.append({"nama": TAHAPAN[10]["nama"], "mulai": t11_mulai, "selesai": t11_selesai})

    # ── Tahap 12: Penandatanganan Kontrak ─────────────────────────────────────
    # Mulai: T11 mulai + 1 hari kerja, jam 09:00 (dari data: hampir selalu +1 hari dari T11 mulai).
    t12_kandidat = geser_ke_hari_kerja(t11_mulai + timedelta(days=1), jam_mulai=9)
    t12_mulai = t12_kandidat.replace(hour=9, minute=0, second=0, microsecond=0)
    t12_selesai = t12_mulai + timedelta(days=5)
    t12_selesai = geser_ke_hari_kerja(t12_selesai)
    hasil.append({"nama": TAHAPAN[11]["nama"], "mulai": t12_mulai, "selesai": t12_selesai})

    return hasil


def format_spse_datetime(dt: datetime) -> str:
    """Format datetime sesuai input SPSE: DD-MM-YYYY HH:mm"""
    return dt.strftime("%d-%m-%Y %H:%M")


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
        raise RuntimeError("Cookie SPSE tidak ditemukan. Pastikan Brave sudah login SPSE.")

    url = f"{BASE_URL}/jadwal/{paket_id}/list"
    resp = requests.get(url, headers={**HEADERS_BASE, "Cookie": cookie_str}, timeout=20)

    if resp.status_code == 302 or "login" in resp.url.lower():
        raise RuntimeError("Session SPSE expired. Silakan login ulang di Brave.")
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
        raise RuntimeError("Gagal scrap hidden fields. Pastikan Brave sudah login SPSE.")
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
