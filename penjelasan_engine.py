"""
Penjelasan Engine v2 — Pure requests, berdasarkan CDP inspection.

Arsitektur baru (confirmed dari script inline SPSE):
- GET  /penjelasan/{ID}/list_pengadaan  → daftar pertanyaan (AJAX, refresh 30s)
- GET  /penjelasan/{ID}/sisa_waktu      → countdown waktu (AJAX, refresh 5s)
- POST /penjelasan/{ID}/simpan          → submit jawaban
  Payload: authenticityToken + pertanyaan_id + penjelasan.dsl_uraian + (opsional: path, fileId)

Flow auto-post sapaan:
1. Fetch list_pengadaan → parse semua tombol .jawab → ambil pertanyaan_id
2. Scrap authenticityToken dari script inline di halaman /penjelasan/{ID}/pengadaan
3. POST template ke /simpan untuk setiap pertanyaan_id
4. 302 = sukses (pola SPSE)

Google Calendar integration:
- Baca event GCal untuk cari jadwal penjelasan
- Trigger auto-post saat waktu tiba
"""

import json
import os
import re
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from penjelasan_config import TEMPLATE, JENIS_PAKET
import spse_browser

# ─────────────────────────────────────────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────────────────────────────────────────

TZ_WIB = ZoneInfo("Asia/Jakarta")
BASE_DIR = Path(__file__).parent
JOBS_FILE = BASE_DIR / "pending_penjelasan.json"
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Origin": "https://spse.inaproc.id",
    "Referer": "https://spse.inaproc.id/",
}

# Keyword jadwal yang dicari di halaman /lelang/[ID]/jadwal
_PENJELASAN_KEYWORDS = [
    "pemberian penjelasan", "penjelasan dokumen", "aanwijzing",
    "penjelasan kualifikasi", "penjelasan seleksi", "penjelasan pemilihan",
]

# Google Calendar config
GCALENDAR_ID = "primary"
GCALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


# ─────────────────────────────────────────────────────────────────────────────
# Helper: HTTP requests ke SPSE dengan cookie dari browser
# ─────────────────────────────────────────────────────────────────────────────

def _get_headers(extra=None):
    h = dict(HEADERS_BASE)
    cookie_str = spse_browser.get_spse_cookies()
    h["Cookie"] = cookie_str
    if extra:
        h.update(extra)
    return h


def _get_spse(url: str, timeout=15, headers_extra=None) -> requests.Response:
    """GET ke SPSE dengan cookie browser."""
    return requests.get(url, headers=_get_headers(headers_extra), timeout=timeout)


def _post_spse(url: str, payload: dict, timeout=15) -> requests.Response:
    """POST ke SPSE dengan cookie browser + form-encoded."""
    headers = _get_headers({"Content-Type": "application/x-www-form-urlencoded"})
    return requests.post(url, data=payload, headers=headers, allow_redirects=False, timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────────
# Scrap authenticityToken dari halaman /penjelasan/{ID}/pengadaan
# ─────────────────────────────────────────────────────────────────────────────

def scrap_token(paket_id: str) -> str:
    """
    GET halaman /penjelasan/{ID}/pengadaan, scrap authenticityToken dari script inline.
    Token hardcoded di JS saat build form .jawab.
    """
    from config import SPSE_BASE_URL
    url = f"{SPSE_BASE_URL}penjelasan/{paket_id}/pengadaan"
    resp = _get_spse(url)
    if resp.status_code != 200:
        raise RuntimeError(f"GET halaman penjelasan gagal: status {resp.status_code}")

    # Cari pattern: name="authenticityToken" value="XXXX"
    soup = BeautifulSoup(resp.text, "html.parser")
    token_input = soup.find("input", {"name": "authenticityToken"})
    if token_input and token_input.get("value"):
        return token_input["value"]

    # Fallback: cari di script inline
    # Pattern: name="authenticityToken" value="a4c6e4d821dcef28e9bd06df702a4824a53545a0"
    m = re.search(r'name="authenticityToken"\s+value="([a-f0-9]+)"', resp.text)
    if m:
        return m.group(1)

    raise RuntimeError("authenticityToken tidak ditemukan di halaman penjelasan.")


# ─────────────────────────────────────────────────────────────────────────────
# Fetch daftar pertanyaan dari AJAX endpoint
# ─────────────────────────────────────────────────────────────────────────────

def fetch_pertanyaan(paket_id: str) -> list[dict]:
    """
    GET /penjelasan/{ID}/list_pengadaan (AJAX endpoint).
    Parse HTML response → extract semua tombol .jawab → ambil pertanyaan_id.
    Return: list of {pertanyaan_id, text, html}
    """
    from config import SPSE_BASE_URL
    url = f"{SPSE_BASE_URL}penjelasan/{paket_id}/list_pengadaan"
    resp = _get_spse(url, headers_extra={"X-Requested-With": "XMLHttpRequest"})

    if resp.status_code != 200:
        raise RuntimeError(f"GET list_pengadaan gagal: status {resp.status_code}")

    if not resp.text.strip():
        return []  # Tidak ada pertanyaan atau masa penjelasan belum/sudah lewat

    soup = BeautifulSoup(resp.text, "html.parser")
    pertanyaan_list = []

    # Cari semua tombol .jawab
    for btn in soup.find_all(class_="jawab"):
        pid = btn.get("value", "")
        text = btn.get_text(separator=" ", strip=True)[:200]
        pertanyaan_list.append({
            "pertanyaan_id": pid,
            "text": text,
            "html": str(btn)[:500],
        })

    # Fallback: cari element dengan attribute value di dalam context pertanyaan
    if not pertanyaan_list:
        for el in soup.find_all(attrs={"value": True}):
            parent = el.find_parent(["tr", "td", "div"])
            if parent:
                text = parent.get_text(separator=" ", strip=True)[:200]
                if text and el["value"]:
                    pertanyaan_list.append({
                        "pertanyaan_id": el["value"],
                        "text": text,
                        "html": str(el)[:500],
                    })

    return pertanyaan_list


# ─────────────────────────────────────────────────────────────────────────────
# Submit jawaban penjelasan
# ─────────────────────────────────────────────────────────────────────────────

def submit_jawaban(paket_id: str, pertanyaan_id: str, teks: str, token: str | None = None) -> dict:
    """
    POST ke /penjelasan/{ID}/simpan
    Payload: authenticityToken + pertanyaan_id + penjelasan.dsl_uraian
    """
    from config import SPSE_BASE_URL

    # Scrap token jika tidak diberikan
    if token is None:
        token = scrap_token(paket_id)

    payload = {
        "authenticityToken": token,
        "pertanyaan_id": pertanyaan_id,
        "penjelasan.dsl_uraian": teks,
    }

    url = f"{SPSE_BASE_URL}penjelasan/{paket_id}/simpan"
    headers = _get_headers({
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"{SPSE_BASE_URL}penjelasan/{paket_id}/pengadaan",
        "X-Requested-With": "XMLHttpRequest",
    })

    resp = requests.post(url, data=payload, headers=headers, allow_redirects=False, timeout=20)

    # 302 = sukses (redirect setelah submit)
    # 200 dengan HTML = mungkin error, cek body
    ok = resp.status_code in (302, 200)
    return {
        "ok": ok,
        "status": resp.status_code,
        "location": resp.headers.get("Location", ""),
        "pertanyaan_id": pertanyaan_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-post sapaan ke semua pertanyaan
# ─────────────────────────────────────────────────────────────────────────────

def auto_post_sapaan(paket_id: str, jenis: str = "tender", teks_override: str | None = None) -> dict:
    """
    Full flow:
    1. Fetch pertanyaan dari list_pengadaan
    2. Scrap authenticityToken
    3. POST template ke semua pertanyaan
    Return: {total, sukses, gagal, details: [...]}
    """
    # 1. Fetch pertanyaan
    pertanyaan_list = fetch_pertanyaan(paket_id)
    if not pertanyaan_list:
        return {"total": 0, "sukses": 0, "gagal": 0, "details": [], "pesan": "Tidak ada pertanyaan"}

    # 2. Scrap token
    try:
        token = scrap_token(paket_id)
    except Exception as e:
        return {"total": len(pertanyaan_list), "sukses": 0, "gagal": 0, "details": [], "pesan": f"Token gagal: {e}"}

    # 3. Template
    teks = teks_override if teks_override else TEMPLATE.get(jenis, TEMPLATE["tender"])

    # 4. POST ke semua pertanyaan
    details = []
    sukses_count = 0
    gagal_count = 0

    for p in pertanyaan_list:
        try:
            result = submit_jawaban(paket_id, p["pertanyaan_id"], teks, token)
            if result["ok"]:
                sukses_count += 1
                details.append({"pertanyaan_id": p["pertanyaan_id"], "status": "✅", "http": result["status"]})
            else:
                gagal_count += 1
                details.append({"pertanyaan_id": p["pertanyaan_id"], "status": "❌", "http": result["status"]})
        except Exception as e:
            gagal_count += 1
            details.append({"pertanyaan_id": p["pertanyaan_id"], "status": "❌", "error": str(e)})

    return {
        "total": len(pertanyaan_list),
        "sukses": sukses_count,
        "gagal": gagal_count,
        "details": details,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Parse jadwal dari /lelang/[ID]/jadwal (existing, diperbaiki)
# ─────────────────────────────────────────────────────────────────────────────

_JADWAL_JS = """() => {
    const rows = [];
    document.querySelectorAll('table tr').forEach(tr => {
        const cells = Array.from(tr.querySelectorAll('td, th')).map(c => c.innerText.trim());
        if (cells.length >= 3) rows.push(cells);
    });
    return { rows, html: document.body.innerText.substring(0, 8000) };
}"""


def _parse_datetime_str(s: str) -> datetime | None:
    s = s.strip().replace("WIB", "").replace("WITA", "").replace("WIT", "").strip()
    BULAN_ID = {
        "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
        "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    }
    formats = ["%d/%m/%Y %H:%M", "%d/%m/%Y %H.%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=TZ_WIB)
        except ValueError:
            pass
    m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{1,2})[.:](\d{2})', s, re.IGNORECASE)
    if m:
        day, month_str, year, hour, minute = m.groups()
        month = BULAN_ID.get(month_str.lower())
        if month:
            try:
                dt = datetime(int(year), month, int(day), int(hour), int(minute))
                return dt.replace(tzinfo=TZ_WIB)
            except ValueError:
                pass
    return None


def get_jadwal_dari_gcalendar(paket_id: str | None = None) -> dict[str, datetime]:
    """
    Baca jadwal penjelasan dari Google Calendar.
    Return dict: {paket_id: datetime_mulai_penjelasan}
    Jika paket_id diberikan, filter hanya untuk paket tersebut.
    """
    service = _get_gcalendar_service()
    if not service:
        return {}

    now = datetime.now(TZ_WIB)
    time_min = (now - timedelta(days=1)).isoformat()
    time_max = (now + timedelta(days=30)).isoformat()

    try:
        events_result = service.events().list(
            calendarId=GCALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            q="penjelasan",
        ).execute()
    except Exception:
        return {}

    result = {}
    for event in events_result.get("items", []):
        start_str = event["start"].get("dateTime", event["start"].get("date"))
        if "T" not in start_str:
            continue
        start_dt = datetime.fromisoformat(start_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=TZ_WIB)

        # Extract paket_id
        pid = extract_paket_id_from_event(event)
        if pid:
            # Jika user request paket_id spesifik, filter
            if paket_id is None or paket_id == pid:
                # Simpan yang paling awal jika ada duplikat
                if pid not in result or start_dt < result[pid]:
                    result[pid] = start_dt

    return result


def parse_jadwal(paket_id: str) -> list[dict]:
    """Scrape jadwal penjelasan dari /lelang/[ID]/jadwal."""
    from config import SPSE_BASE_URL
    url = f"{SPSE_BASE_URL}lelang/{paket_id}/jadwal"
    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terhubung.")
    spse_browser._run(page.goto(url, wait_until="domcontentloaded", timeout=30000))
    data = spse_browser._run(page.evaluate(_JADWAL_JS))

    hasil = []
    for row in data["rows"]:
        row_text = " ".join(row).lower()
        if not any(kw in row_text for kw in _PENJELASAN_KEYWORDS):
            continue
        kegiatan, mulai_str, selesai_str = "", "", ""
        if len(row) >= 4:
            kegiatan, mulai_str, selesai_str = row[1], row[2], row[3]
        elif len(row) == 3:
            kegiatan, mulai_str, selesai_str = row[0], row[1], row[2]
        mulai_dt = _parse_datetime_str(mulai_str)
        if mulai_dt:
            hasil.append({"kegiatan": kegiatan, "mulai": mulai_str, "selesai": selesai_str,
                          "mulai_dt": mulai_dt, "selesai_dt": _parse_datetime_str(selesai_str)})
    return hasil


# ─────────────────────────────────────────────────────────────────────────────
# Google Calendar Integration
# ─────────────────────────────────────────────────────────────────────────────

def _get_gcalendar_service():
    """
    Lazy import Google Calendar service.
    Pola: baca token.json dari V19_Scheduler folder.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None

    # Cari token.json di beberapa lokasi
    token_candidates = [
        BASE_DIR.parent / "V19_Scheduler" / "WPy64-313110" / "token.json",
        BASE_DIR / "token.json",
        Path.home() / ".credentials" / "token.json",
    ]
    cred_candidates = [
        BASE_DIR.parent / "V19_Scheduler" / "WPy64-313110" / "credentials.json",
        BASE_DIR / "credentials.json",
    ]

    token_path = None
    for p in token_candidates:
        if p.exists():
            token_path = p
            break

    cred_path = None
    for p in cred_candidates:
        if p.exists():
            cred_path = p
            break

    if not token_path or not cred_path:
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), GCALENDAR_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Simpan token yang sudah di-refresh
            with open(str(token_path), "w") as f:
                f.write(creds.to_json())
        return build("calendar", "v3", credentials=creds)
    except Exception:
        return None


def get_penjelasan_events(waktu_mulai: datetime | None = None, waktu_selesai: datetime | None = None) -> list[dict]:
    """
    Baca event Google Calendar yang mengandung kata "penjelasan" atau "aanwijzing".
    Return: list of {summary, start, end, description, event_id}
    """
    service = _get_gcalendar_service()
    if not service:
        return []

    now = datetime.now(TZ_WIB)
    if waktu_mulai is None:
        waktu_mulai = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if waktu_selesai is None:
        waktu_selesai = waktu_mulai + timedelta(days=7)

    time_min = waktu_mulai.isoformat()
    time_max = waktu_selesai.isoformat()

    try:
        events_result = service.events().list(
            calendarId=GCALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            q="penjelasan",  # search keyword
        ).execute()
    except Exception:
        return []

    results = []
    for event in events_result.get("items", []):
        start_str = event["start"].get("dateTime", event["start"].get("date"))
        end_str = event["end"].get("dateTime", event["end"].get("date"))
        results.append({
            "event_id": event.get("id", ""),
            "summary": event.get("summary", ""),
            "start": datetime.fromisoformat(start_str) if "T" in start_str else None,
            "end": datetime.fromisoformat(end_str) if "T" in end_str else None,
            "description": event.get("description", ""),
        })
    return results


def extract_paket_id_from_event(event: dict) -> str | None:
    """
    Extract paket_id dari event description atau summary.
    Pola: deskripsi event dari V19 Scheduler biasanya mengandung kode tender / URL SPSE.
    """
    desc = (event.get("description", "") or "") + " " + (event.get("summary", "") or "")

    # Cari pattern: angka 13 digit (format paket SPSE: 10096884000)
    m = re.search(r'\b(\d{11,13})\b', desc)
    if m:
        return m.group(1)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Persistent Jobs — simpan/load ke JSON (existing, tidak diubah)
# ─────────────────────────────────────────────────────────────────────────────

def _load_jobs() -> list[dict]:
    if JOBS_FILE.exists():
        try:
            return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_jobs(jobs: list[dict]):
    JOBS_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def tambah_job(
    paket_id: str, nama_paket: str, jenis: str,
    waktu_fire: datetime, teks_override: str | None = None,
    auto_post: bool = True,
) -> dict:
    """Daftarkan satu job penjelasan."""
    jobs = _load_jobs()
    jobs = [j for j in jobs if not (j["paket_id"] == paket_id and j["jenis"] == jenis)]
    job = {
        "paket_id": paket_id, "nama_paket": nama_paket, "jenis": jenis,
        "waktu_fire": waktu_fire.isoformat(), "teks_override": teks_override,
        "auto_post": auto_post,
        "status": "pending", "result": None,
    }
    jobs.append(job)
    _save_jobs(jobs)
    return job


def hapus_job(paket_id: str, jenis: str):
    jobs = _load_jobs()
    jobs = [j for j in jobs if not (j["paket_id"] == paket_id and j["jenis"] == jenis)]
    _save_jobs(jobs)


def get_jobs() -> list[dict]:
    return _load_jobs()


def update_job_status(paket_id: str, jenis: str, status: str, result: dict | None = None):
    jobs = _load_jobs()
    for j in jobs:
        if j["paket_id"] == paket_id and j["jenis"] == jenis:
            j["status"] = status
            if result:
                j["result"] = result
            break
    _save_jobs(jobs)


# ─────────────────────────────────────────────────────────────────────────────
# Background Scheduler (diperbaiki untuk auto-post)
# ─────────────────────────────────────────────────────────────────────────────

_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_log: list[str] = []
_log_lock = threading.Lock()


def _log_append(msg: str):
    ts = datetime.now(TZ_WIB).strftime("%H:%M:%S")
    with _log_lock:
        _log.append(f"[{ts}] {msg}")
        if len(_log) > 200:
            _log.pop(0)


def get_log() -> list[str]:
    with _log_lock:
        return list(_log)


def _scheduler_loop():
    _log_append("Scheduler dimulai.")
    while not _scheduler_stop.is_set():
        now = datetime.now(TZ_WIB)
        jobs = _load_jobs()
        changed = False

        for job in jobs:
            if job["status"] != "pending":
                continue
            try:
                waktu = datetime.fromisoformat(job["waktu_fire"])
            except Exception:
                continue

            if now >= waktu:
                paket_id = job["paket_id"]
                jenis = job["jenis"]
                auto_post = job.get("auto_post", True)

                if auto_post:
                    _log_append(f"🚀 Auto-post sapaan: paket {paket_id} ({jenis}) ...")
                    try:
                        result = auto_post_sapaan(
                            paket_id=paket_id,
                            jenis=jenis,
                            teks_override=job.get("teks_override"),
                        )
                        total = result.get("total", 0)
                        sukses = result.get("sukses", 0)
                        gagal = result.get("gagal", 0)
                        status = "fired" if gagal == 0 else "gagal"
                        _log_append(f"{'✅' if gagal == 0 else '⚠️'} Paket {paket_id}: {sukses}/{total} berhasil, {gagal} gagal")
                        update_job_status(paket_id, jenis, status, result)
                    except Exception as e:
                        _log_append(f"❌ Error paket {paket_id}: {e}")
                        update_job_status(paket_id, jenis, "gagal", {"error": str(e)})
                else:
                    _log_append(f"⏰ Jadwal tiba (manual mode): paket {paket_id}")
                    update_job_status(paket_id, jenis, "pending_manual")

                changed = True

        # Juga cek GCalendar events untuk auto-discover jadwal penjelasan
        try:
            events = get_penjelasan_events(
                waktu_mulai=now - timedelta(hours=1),
                waktu_selesai=now + timedelta(hours=3),
            )
            for ev in events:
                if ev["start"] and now >= ev["start"] and now <= (ev["end"] or ev["start"] + timedelta(hours=3)):
                    paket_id = extract_paket_id_from_event(ev)
                    if paket_id:
                        # Cek apakah sudah ada job untuk paket ini
                        existing = _load_jobs()
                        sudah_ada = any(
                            j["paket_id"] == paket_id and j["status"] in ("fired", "pending")
                            for j in existing
                        )
                        if not sudah_ada:
                            _log_append(f"📅 GCalendar auto-discover: {ev['summary']} → paket {paket_id}")
                            # Auto-post langsung
                            try:
                                result = auto_post_sapaan(paket_id, "tender")
                                _log_append(f"{'✅' if result['gagal'] == 0 else '⚠️'} Auto-post {paket_id}: {result['sukses']}/{result['total']}")
                            except Exception as e:
                                _log_append(f"❌ GCalendar auto-post {paket_id}: {e}")
        except Exception as e:
            _log_append(f"⚠️ GCalendar check error: {e}")

        _scheduler_stop.wait(timeout=30)  # cek tiap 30 detik

    _log_append("Scheduler berhenti.")


def jadwalkan_dari_gcal(
    paket_id: str,
    nama_paket: str,
    jenis: str = "tender",
    teks_override: str | None = None,
    auto_post: bool = True,
) -> dict:
    """
    Cari jadwal penjelasan paket_id di GCal, lalu daftarkan ke job queue.
    Return: {ok: bool, waktu_fire: datetime|None, pesan: str}
    """
    jadwal = get_jadwal_dari_gcalendar(paket_id=paket_id)
    if not jadwal:
        return {"ok": False, "waktu_fire": None, "pesan": "Jadwal penjelasan tidak ditemukan di Google Calendar"}

    waktu_fire = jadwal[paket_id]
    job = tambah_job(
        paket_id=paket_id,
        nama_paket=nama_paket,
        jenis=jenis,
        waktu_fire=waktu_fire,
        teks_override=teks_override if teks_override else None,
        auto_post=auto_post,
    )
    return {"ok": True, "waktu_fire": waktu_fire, "pesan": f"Dijadwalkan: {waktu_fire.strftime('%d/%m/%Y %H:%M')} WIB", "job": job}


def start_scheduler():
    global _scheduler_thread, _scheduler_stop
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="PenjelasanScheduler")
    _scheduler_thread.start()


def stop_scheduler():
    _scheduler_stop.set()


def is_scheduler_running() -> bool:
    return bool(_scheduler_thread and _scheduler_thread.is_alive())
