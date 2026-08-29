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

Catatan: id endpoint = kode_paket (kolom 5 dt/paketpp), BUKAN id_nontender (kolom 0).
Verified: /jadwalnontender/{kode_paket}/list → 200, /jadwalnontender/{id_nontender}/list → 500.
"""
import requests
import time
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
_RETRYABLE_STATUS = {404, 408, 425, 429, 500, 502, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.75

NAMA_TAHAP_PL = [
    "1. Upload Dokumen Penawaran",
    "2. Pembukaan Dokumen Penawaran",
    "3. Evaluasi Penawaran",
    "4. Klarifikasi Teknis dan Negosiasi",
    "5. Penandatanganan Kontrak",
]


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


def _mulai_setelah_selesai(selesai: datetime) -> datetime:
    """Mulai tahap berikutnya satu menit setelah tahap sebelumnya selesai."""
    return selesai + timedelta(minutes=1)


def hitung_jadwal_pl(tgl_mulai: datetime) -> list[dict]:
    """
    Hitung 5 tahap PL dari tanggal mulai (T1).

    Pola yang dikonfirmasi user (2026-06-10):
    - T1: mulai D jam X → selesai D+5 hari KALENDER jam X (bukan hari kerja)
    - T2: T1.selesai → T1.selesai + 65 menit (hari sama, no geser)
    - T3: T2.selesai + 1 menit → mulai; selesai = T3.mulai + 1 hari kerja replace(hour=16)
    - T4: hari sama T3.selesai, replace(hour=9) → replace(hour=15,minute=45)
    - T5: mulai satu menit setelah T4.selesai → selesai +10 hari jam 16:00
    """
    # T1 Upload Penawaran — 5 hari KALENDER, geser ke hari kerja jika jatuh di weekend/libur
    t1_mulai = geser_ke_jam_kerja(tgl_mulai)
    t1_selesai_kand = (t1_mulai + timedelta(days=5)).replace(
        hour=t1_mulai.hour, minute=t1_mulai.minute, second=0, microsecond=0
    )
    t1_selesai = geser_ke_hari_kerja(t1_selesai_kand).replace(
        hour=t1_mulai.hour, minute=t1_mulai.minute, second=0, microsecond=0
    )

    # T2 Pembukaan Penawaran (hari sama T1.selesai, +65 menit)
    t2_mulai = t1_selesai + timedelta(minutes=1)
    t2_selesai = t1_selesai + timedelta(minutes=65)

    # T3 Evaluasi Penawaran
    t3_mulai = t2_selesai + timedelta(minutes=1)
    t3_selesai = _tambah_hari_kerja(t3_mulai, 1).replace(hour=16, minute=0, second=0, microsecond=0)

    # T4 Klarifikasi + Negosiasi (hari sama T3.selesai)
    t4_mulai = t3_selesai.replace(hour=9, minute=0, second=0, microsecond=0)
    t4_selesai = t3_selesai.replace(hour=15, minute=45, second=0, microsecond=0)

    # T5 Penandatanganan Kontrak
    t5_mulai = _mulai_setelah_selesai(t4_selesai)
    t5_selesai_kand = (t5_mulai + timedelta(days=7)).replace(hour=16, minute=0, second=0, microsecond=0)
    t5_selesai = geser_ke_hari_kerja(t5_selesai_kand).replace(hour=16, minute=0, second=0, microsecond=0)

    return [
        {"nama": "1. Upload Dokumen Penawaran",         "mulai": t1_mulai, "selesai": t1_selesai},
        {"nama": "2. Pembukaan Dokumen Penawaran",      "mulai": t2_mulai, "selesai": t2_selesai},
        {"nama": "3. Evaluasi Penawaran",               "mulai": t3_mulai, "selesai": t3_selesai},
        {"nama": "4. Klarifikasi Teknis dan Negosiasi", "mulai": t4_mulai, "selesai": t4_selesai},
        {"nama": "5. Penandatanganan Kontrak",          "mulai": t5_mulai, "selesai": t5_selesai},
    ]


def hitung_jadwal_pl_santai(tgl_mulai: datetime) -> list[dict]:
    """Mode Santai: pola Normal dengan evaluasi penawaran 2 hari kerja.

    T1 mempertahankan jam input (termasuk sore/malam), sedangkan checkpoint
    berikutnya mengikuti pola Normal. T3 diperpanjang dari satu menjadi dua
    hari kerja; T4 berlangsung dari satu hari kerja sebelum hari selesai T3
    sampai hari selesai T3, lalu T5 menyambung satu menit setelah T4.
    """
    # Mode Santai memang menerima jam mulai custom. Jangan memakai
    # hitung_jadwal_pl() sebagai basis karena fungsi Normal menggeser jam
    # selain jam kerja ke 08:00 (contoh input 19:00).
    t1_mulai = tgl_mulai.replace(second=0, microsecond=0)
    t1_selesai_kand = (t1_mulai + timedelta(days=5)).replace(
        hour=t1_mulai.hour, minute=t1_mulai.minute, second=0, microsecond=0
    )
    t1_selesai = geser_ke_hari_kerja(t1_selesai_kand).replace(
        hour=t1_mulai.hour, minute=t1_mulai.minute, second=0, microsecond=0
    )
    t2_mulai = t1_selesai + timedelta(minutes=1)
    t2_selesai = t1_selesai + timedelta(minutes=65)
    t3_mulai = t2_selesai + timedelta(minutes=1)
    t3_selesai = _tambah_hari_kerja(t3_mulai, 2).replace(
        hour=16, minute=0, second=0, microsecond=0
    )

    t4_mulai = _tambah_hari_kerja(t3_mulai, 1).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    t4_selesai = t3_selesai.replace(hour=15, minute=45, second=0, microsecond=0)

    t5_mulai = _mulai_setelah_selesai(t4_selesai)
    t5_selesai_kand = (t5_mulai + timedelta(days=7)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    t5_selesai = geser_ke_hari_kerja(t5_selesai_kand).replace(
        hour=16, minute=0, second=0, microsecond=0
    )

    return [
        {"nama": "1. Upload Dokumen Penawaran",         "mulai": t1_mulai, "selesai": t1_selesai},
        {"nama": "2. Pembukaan Dokumen Penawaran",      "mulai": t2_mulai, "selesai": t2_selesai},
        {"nama": "3. Evaluasi Penawaran",               "mulai": t3_mulai, "selesai": t3_selesai},
        {"nama": "4. Klarifikasi Teknis dan Negosiasi", "mulai": t4_mulai, "selesai": t4_selesai},
        {"nama": "5. Penandatanganan Kontrak",          "mulai": t5_mulai, "selesai": t5_selesai},
    ]


def hitung_jadwal_pl_24_jam(tgl_mulai: datetime) -> list[dict]:
    """Jadwal PL kalender penuh; tidak menggeser ke jam/hari kerja.

    Dipakai saat SPSE perlu menerima jadwal 24 jam. Semua batas tahap tetap
    berurutan dan berbasis durasi kalender sehingga input 21:30 tidak berubah
    diam-diam menjadi 08:00. Start mode ini diarahkan minimal pukul 17:00
    oleh UI.
    """
    t1_mulai = tgl_mulai.replace(second=0, microsecond=0)
    t1_selesai = t1_mulai + timedelta(days=5)
    # Start sore/malam tetap bebas, tetapi batas T1 mengikuti pola operasional:
    # paket yang mulai pukul 17:00–23:59 selesai H+5 pukul 10:00.
    if 17 <= t1_mulai.hour <= 23:
        t1_selesai = t1_selesai.replace(hour=10, minute=0)
    t2_mulai = t1_selesai + timedelta(minutes=1)
    t2_selesai = t1_selesai + timedelta(minutes=65)
    t3_mulai = t2_selesai + timedelta(minutes=1)
    t3_selesai = t3_mulai + timedelta(days=1)
    t4_mulai = t3_selesai + timedelta(minutes=1)
    t4_batas = t4_mulai.replace(hour=17, minute=0, second=0, microsecond=0)
    t4_selesai = min(t4_mulai + timedelta(hours=6, minutes=45), t4_batas)
    t5_mulai = t4_selesai + timedelta(minutes=1)
    t5_selesai = t5_mulai + timedelta(days=10)
    return [
        {"nama": "1. Upload Dokumen Penawaran",         "mulai": t1_mulai, "selesai": t1_selesai},
        {"nama": "2. Pembukaan Dokumen Penawaran",      "mulai": t2_mulai, "selesai": t2_selesai},
        {"nama": "3. Evaluasi Penawaran",               "mulai": t3_mulai, "selesai": t3_selesai},
        {"nama": "4. Klarifikasi Teknis dan Negosiasi", "mulai": t4_mulai, "selesai": t4_selesai},
        {"nama": "5. Penandatanganan Kontrak",          "mulai": t5_mulai, "selesai": t5_selesai},
    ]


def hitung_jadwal_pl_3_minggu(tgl_mulai: datetime) -> list[dict]:
    """Mode Normal dengan durasi T5 selama 21 hari kalender."""
    jadwal = hitung_jadwal_pl(tgl_mulai)
    t5_mulai = jadwal[4]["mulai"]
    t5_selesai_kand = (t5_mulai + timedelta(days=21)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    t5_selesai = geser_ke_hari_kerja(t5_selesai_kand).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    jadwal[4] = {"nama": jadwal[4]["nama"], "mulai": t5_mulai, "selesai": t5_selesai}
    return jadwal


def hitung_jadwal_pl_cepat(tgl_mulai: datetime) -> list[dict]:
    """
    Hitung 5 tahap PL cepat. Tayang Senin → Upload s.d. Rabu, Pembukaan Rabu
    (30 menit), Evaluasi Rabu→Kamis 16:00, Klarifikasi Kamis, Kontrak mulai
    hari sama +7 hari kalender.
    Tayang hari selain Senin: tiap checkpoint yang jatuh Sabtu/Minggu digeser
    maju ke hari kerja terdekat (jam dipertahankan), biar gak ada tahap di
    hari libur SPSE.
    - T1: mulai = tgl_mulai, selesai = mulai + 2 hari KALENDER jam sama (geser weekend)
    - T2: mulai = T1.selesai + 1 menit, selesai = T2.mulai + 30 menit (geser weekend)
    - T3: mulai = T2.selesai + 1 menit, selesai = T4.selesai + 30 menit (hari sama T4, geser weekend)
    - T4: hari berikutnya dari T2 (geser weekend), jam 08:30 - 13:00
    - T5: mulai satu menit setelah T4.selesai (hari sama), selesai = mulai + 7 hari jam 16:00
    """
    t1_mulai = geser_ke_jam_kerja(tgl_mulai)
    t1_selesai = geser_ke_hari_kerja(t1_mulai + timedelta(days=2))

    t2_mulai = geser_ke_hari_kerja(t1_selesai + timedelta(minutes=1))
    t2_selesai = geser_ke_hari_kerja(t1_selesai + timedelta(minutes=30))

    t3_mulai = geser_ke_hari_kerja(t2_selesai + timedelta(minutes=1))
    t4_hari = geser_ke_hari_kerja(t2_selesai + timedelta(days=1))

    t4_mulai = t4_hari.replace(hour=8, minute=30, second=0, microsecond=0)
    t4_selesai = t4_hari.replace(hour=13, minute=0, second=0, microsecond=0)

    t3_selesai = t4_selesai + timedelta(minutes=30)

    t5_mulai = _mulai_setelah_selesai(t4_selesai)
    t5_selesai_kand = (t5_mulai + timedelta(days=7)).replace(hour=16, minute=0, second=0, microsecond=0)
    t5_selesai = geser_ke_hari_kerja(t5_selesai_kand).replace(hour=16, minute=0, second=0, microsecond=0)

    return [
        {"nama": "1. Upload Dokumen Penawaran",         "mulai": t1_mulai, "selesai": t1_selesai},
        {"nama": "2. Pembukaan Dokumen Penawaran",      "mulai": t2_mulai, "selesai": t2_selesai},
        {"nama": "3. Evaluasi Penawaran",               "mulai": t3_mulai, "selesai": t3_selesai},
        {"nama": "4. Klarifikasi Teknis dan Negosiasi", "mulai": t4_mulai, "selesai": t4_selesai},
        {"nama": "5. Penandatanganan Kontrak",          "mulai": t5_mulai, "selesai": t5_selesai},
    ]


def hitung_jadwal_pl_standar(tgl_mulai: datetime) -> list[dict]:
    """
    Hitung 5 tahap PL mode Standar. Sama pola dengan mode Cepat, tapi T1
    selesai +3 hari KALENDER (bukan +2), jadi tiap tahap mundur 1 hari.
    Tayang Senin → Upload s.d. Kamis, Pembukaan Kamis, Evaluasi Kamis→Jumat
    16:00, Klarifikasi Jumat, Kontrak mulai Jumat (hari sama, +1 menit
    setelah Klarifikasi selesai) s.d. +7 hari jam 16:00.
    """
    t1_mulai = geser_ke_jam_kerja(tgl_mulai)
    t1_selesai = geser_ke_hari_kerja(t1_mulai + timedelta(days=3))

    t2_mulai = geser_ke_hari_kerja(t1_selesai + timedelta(minutes=1))
    t2_selesai = geser_ke_hari_kerja(t1_selesai + timedelta(minutes=30))

    t3_mulai = geser_ke_hari_kerja(t2_selesai + timedelta(minutes=1))
    t3_selesai = geser_ke_hari_kerja(
        (t2_selesai + timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
    )

    t4_mulai = t3_selesai.replace(hour=9, minute=0, second=0, microsecond=0)
    t4_selesai = t3_selesai.replace(hour=15, minute=30, second=0, microsecond=0)

    # T5 selalu mengikuti T4 secara langsung.
    t5_mulai = _mulai_setelah_selesai(t4_selesai)
    t5_selesai = (t5_mulai + timedelta(days=7)).replace(hour=16, minute=0, second=0, microsecond=0)

    return [
        {"nama": "1. Upload Dokumen Penawaran",         "mulai": t1_mulai, "selesai": t1_selesai},
        {"nama": "2. Pembukaan Dokumen Penawaran",      "mulai": t2_mulai, "selesai": t2_selesai},
        {"nama": "3. Evaluasi Penawaran",               "mulai": t3_mulai, "selesai": t3_selesai},
        {"nama": "4. Klarifikasi Teknis dan Negosiasi", "mulai": t4_mulai, "selesai": t4_selesai},
        {"nama": "5. Penandatanganan Kontrak",          "mulai": t5_mulai, "selesai": t5_selesai},
    ]


def hitung_jadwal_pl_custom(jadwal_list: list[dict]) -> list[dict]:
    """Validasi dan normalkan jadwal PL yang diisi manual per tahap.

    Mode Custom sengaja tidak menerapkan pola, geser hari kerja, atau
    koreksi urutan antar-tahap. Yang diwajibkan hanya lima tahap SPSE lengkap
    dan setiap tahap memiliki waktu mulai yang lebih awal daripada selesai.
    """
    if not isinstance(jadwal_list, list) or len(jadwal_list) != len(NAMA_TAHAP_PL):
        raise ValueError("Jadwal Custom harus berisi tepat 5 tahap (T1–T5).")

    hasil = []
    for index, row in enumerate(jadwal_list):
        if not isinstance(row, dict):
            raise ValueError(f"T{index + 1}: data jadwal tidak valid.")
        mulai = row.get("mulai")
        selesai = row.get("selesai")
        if not isinstance(mulai, datetime) or not isinstance(selesai, datetime):
            raise ValueError(f"T{index + 1}: tanggal/jam mulai dan selesai wajib diisi.")
        mulai = mulai.replace(second=0, microsecond=0)
        selesai = selesai.replace(second=0, microsecond=0)
        if mulai >= selesai:
            raise ValueError(f"T{index + 1}: waktu mulai harus sebelum selesai.")
        hasil.append({
            "nama": NAMA_TAHAP_PL[index],
            "mulai": mulai,
            "selesai": selesai,
        })
    return hasil


def hitung_jadwal_pl_mode(
    tgl_mulai: datetime | None,
    mode: str = "normal",
    jadwal_custom: list[dict] | None = None,
) -> list[dict]:
    """Hitung jadwal sesuai mode UI atau kembalikan input Custom tervalidasi."""
    mode_key = str(mode or "normal").strip().casefold()
    if mode_key == "custom":
        return hitung_jadwal_pl_custom(jadwal_custom or [])
    if not isinstance(tgl_mulai, datetime):
        raise ValueError("Tanggal mulai T1 wajib diisi untuk mode jadwal otomatis.")
    kalkulator = {
        "24_jam": hitung_jadwal_pl_24_jam,
        "santai": hitung_jadwal_pl_santai,
        "normal_3_minggu": hitung_jadwal_pl_3_minggu,
        "cepat": hitung_jadwal_pl_cepat,
        "standar": hitung_jadwal_pl_standar,
    }.get(mode_key, hitung_jadwal_pl)
    return kalkulator(tgl_mulai)


# ─────────────────────────────────────────────────────────────────────────────
# Scrape form fields PL
# ─────────────────────────────────────────────────────────────────────────────

def scrap_hidden_fields_pl(kode_paket: str) -> dict:
    """GET /jadwalnontender/{kode_paket}/list — scrap hidden fields + CSRF."""
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        raise RuntimeError("Cookie SPSE kosong — login PP di Brave dulu.")

    url = f"{BASE}/jadwalnontender/{kode_paket}/list"
    response = None
    last_error = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            response = requests.get(
                url,
                headers={**HDRS, "Cookie": cookie_str},
                timeout=20,
            )
            if response.status_code == 200:
                break
            last_error = f"HTTP {response.status_code}"
            if response.status_code not in _RETRYABLE_STATUS:
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt + 1 < _RETRY_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
            try:
                refreshed = spse_browser.get_spse_cookies(force=True)
                if refreshed:
                    cookie_str = refreshed
            except Exception:
                pass
    if response is None or response.status_code != 200:
        raise RuntimeError(
            f"GET jadwalnontender gagal setelah {_RETRY_ATTEMPTS} percobaan: "
            f"{last_error or 'respons kosong'}"
        )
    r = response

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
    paket_id_val = id_inp["value"] if id_inp else kode_paket

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
            "mulai":         form_jadwal.find("input", {"name": f"{prefix}dtj_tglawal"}).get("value", ""),
            "selesai":       form_jadwal.find("input", {"name": f"{prefix}dtj_tglakhir"}).get("value", ""),
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


def submit_jadwal_pl(kode_paket: str, payload: dict, cookie_str: str = None) -> dict:
    if not cookie_str:
        cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        raise RuntimeError("Cookie SPSE kosong.")

    url = f"{BASE}/simpanjadwalnontender?id={kode_paket}"
    headers = {
        **HDRS,
        "Cookie": cookie_str,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE.split("/tapinkab")[0] if "/tapinkab" in BASE else "https://spse.inaproc.id",
        "Referer": f"{BASE}/jadwalnontender/{kode_paket}/list",
    }

    r = requests.post(url, data=payload, headers=headers, allow_redirects=False, timeout=30)
    return {
        "ok":       r.status_code in (200, 302),
        "status":   r.status_code,
        "body":     (r.text or "")[:2000],
        "redirect": r.headers.get("Location", ""),
    }


def parse_jadwal_aktual_pl(scraped: dict) -> list[dict]:
    """Ubah nilai tanggal hasil scrape menjadi 5 baris jadwal editable."""
    hasil = []
    for row in scraped.get("rows", []):
        hasil.append({
            "nama": row.get("index", 0) + 1,
            "mulai": datetime.strptime(row["mulai"], "%d-%m-%Y %H:%M"),
            "selesai": datetime.strptime(row["selesai"], "%d-%m-%Y %H:%M"),
        })
    return hasil


def submit_perubahan_jadwal_pl(kode_paket: str, jadwal_list: list[dict], keterangan: str) -> dict:
    """Scrape jadwal live, pertahankan hidden ID, lalu submit perubahan."""
    if len((keterangan or "").strip()) < 30:
        raise ValueError("Alasan perubahan minimal 30 karakter.")
    scraped = scrap_hidden_fields_pl(kode_paket)
    payload = build_payload_pl(scraped, jadwal_list)
    payload.update({
        "harus_berubah": "true",
        "keterangan": keterangan.strip(),
        "simpan": "simpan",
    })
    result = submit_jadwal_pl(kode_paket, payload, cookie_str=scraped.get("cookie"))
    return {"scraped": scraped, "jadwal_list": jadwal_list, "payload": payload, "submit_result": result}


def auto_fill_jadwal_pl(
    kode_paket: str,
    tgl_mulai: datetime | None = None,
    mode: str = "normal",
    jadwal_custom: list[dict] | None = None,
) -> dict:
    """Full flow: scrap → hitung/custom → build payload."""
    scraped = scrap_hidden_fields_pl(kode_paket)
    jadwal_list = hitung_jadwal_pl_mode(
        tgl_mulai,
        mode=mode,
        jadwal_custom=jadwal_custom,
    )
    payload = build_payload_pl(scraped, jadwal_list)
    return {"scraped": scraped, "jadwal_list": jadwal_list, "payload": payload}


def submit_full_pl(
    kode_paket: str,
    tgl_mulai: datetime | None = None,
    mode: str = "normal",
    jadwal_custom: list[dict] | None = None,
) -> dict:
    result = auto_fill_jadwal_pl(
        kode_paket,
        tgl_mulai,
        mode=mode,
        jadwal_custom=jadwal_custom,
    )
    cookie = result["scraped"].get("cookie")
    sub = submit_jadwal_pl(kode_paket, result["payload"], cookie_str=cookie)
    result["submit_result"] = sub
    return result
