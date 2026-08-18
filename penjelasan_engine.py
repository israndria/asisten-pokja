"""
Engine Pemberian Penjelasan Tender.

Flow utama:
1. Baca jadwal resmi dari ``/lelang/{ID}/jadwal`` melalui fetch di browser
   yang sudah login. Tab user tidak dinavigasi.
2. Saat waktu mulai tiba, POST kata pembukaan ke
   ``/penjelasan/{ID}/pembukaan_pengadaan``.
3. Google Calendar hanya dipakai sebagai fallback bila jadwal SPSE belum bisa
   dibaca.

Alur ``fetch_pertanyaan``/``submit_jawaban`` tetap dipertahankan sebagai API
terpisah, tetapi bukan lagi mekanisme auto-post pembukaan.
"""

import json
from html import escape as html_escape
import os
import re
import threading
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from penjelasan_config import TEMPLATE, JENIS_PAKET
import spse_browser

# ─────────────────────────────────────────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────────────────────────────────────────

# SPSE Tapin menampilkan waktu WITA. Alias TZ_WIB dipertahankan agar import
# lama dari app.py dan modul lain tidak rusak.
TZ_WITA = ZoneInfo("Asia/Makassar")
TZ_WIB = TZ_WITA
BASE_DIR = Path(__file__).parent
try:
    from config import RUNTIME_ROOT, STATE_DIR
    JOBS_FILE = Path(RUNTIME_ROOT) / "state" / "pending_penjelasan.json"
except Exception:
    JOBS_FILE = BASE_DIR / "pending_penjelasan.json"
    STATE_DIR = BASE_DIR
LEGACY_JOBS_FILE = BASE_DIR / "pending_penjelasan.json"
WORKER_HEARTBEAT_FILE = Path(STATE_DIR) / "penjelasan_scheduler.heartbeat"
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
GCAL_SYNC_INTERVAL = timedelta(seconds=60)
GCAL_SYNC_HORIZON = timedelta(days=30)


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


def _post_spse(url: str, payload: dict, timeout=15, headers_extra=None) -> requests.Response:
    """POST ke SPSE dengan cookie browser + form-encoded."""
    headers = _get_headers({"Content-Type": "application/x-www-form-urlencoded"})
    if headers_extra:
        headers.update(headers_extra)
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
# Submit kata pembukaan Pokja
# ─────────────────────────────────────────────────────────────────────────────

def _pembukaan_to_html(teks: str) -> str:
    """Ubah teks biasa menjadi HTML aman yang dipahami Trumbowyg SPSE."""
    normalized = str(teks or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    return "<br>".join(html_escape(line, quote=False) for line in normalized.split("\n"))


def _encode_uri(value: str) -> str:
    """Samakan encoding dengan JavaScript ``encodeURI`` di halaman SPSE."""
    return quote(value, safe=";/?:@&=+$,-_.!~*'()#")


def update_pembukaan(paket_id: str, teks: str) -> dict:
    """POST kata pembukaan ke endpoint resmi ``pembukaan_pengadaan``."""
    from config import SPSE_BASE_URL

    html_text = _pembukaan_to_html(teks)
    if not html_text:
        return {"ok": False, "status": 0, "pesan": "Teks pembukaan kosong."}

    url = f"{SPSE_BASE_URL}penjelasan/{paket_id}/pembukaan_pengadaan"
    try:
        response = _post_spse(
            url,
            {"uraian": _encode_uri(html_text)},
            timeout=20,
            headers_extra={
                "Referer": f"{SPSE_BASE_URL}penjelasan/{paket_id}/pengadaan",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
    except Exception as exc:
        return {"ok": False, "status": 0, "pesan": str(exc), "paket_id": paket_id}

    location = response.headers.get("Location", "")
    body_preview = (response.text or "")[:500]
    login_response = "BERANDA LOGIN" in body_preview or "Nama Pengguna" in body_preview
    ok = response.status_code in (200, 201, 202, 204, 302) and not login_response
    return {
        "ok": ok,
        "status": response.status_code,
        "location": location,
        "pesan": "Berhasil" if ok else f"HTTP {response.status_code}",
        "paket_id": paket_id,
    }


def auto_post_pembukaan(
    paket_id: str,
    jenis: str = "tender",
    teks_override: str | None = None,
) -> dict:
    """Post satu kata pembukaan; tidak menunggu/menjawab pertanyaan peserta."""
    teks = teks_override if teks_override else TEMPLATE.get(jenis, TEMPLATE["tender"])
    result = update_pembukaan(paket_id, teks)
    return {
        "total": 1,
        "sukses": 1 if result.get("ok") else 0,
        "gagal": 0 if result.get("ok") else 1,
        "details": [result],
        "status": result.get("status", 0),
        "pesan": result.get("pesan", ""),
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


_BROWSER_FETCH_JS = """
async ([url]) => {
    const response = await fetch(url, {
        credentials: 'include',
        headers: {'X-Requested-With': 'XMLHttpRequest'}
    });
    return {
        status: response.status,
        url: response.url,
        body: await response.text()
    };
}
"""


def _fetch_html_via_browser(url: str) -> str:
    """GET halaman SPSE dari session browser tanpa mengubah tab user."""
    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser Tender belum terhubung.")

    result = spse_browser._run(page.evaluate(_BROWSER_FETCH_JS, [url]), timeout=30)
    status = int(result.get("status", 0))
    body = result.get("body", "") or ""
    if status != 200:
        raise RuntimeError(f"GET jadwal SPSE gagal: HTTP {status}")
    if "BERANDA LOGIN" in body or "Nama Pengguna" in body:
        raise RuntimeError("Session SPSE tidak valid atau sudah logout.")
    return body


def _parse_jadwal_html(html_text: str) -> list[dict]:
    """Parse baris jadwal Tender dari HTML SPSE tanpa network/browser."""
    soup = BeautifulSoup(html_text, "html.parser")
    hasil = []
    for tr in soup.select("table tr"):
        row = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if len(row) < 3:
            continue
        row_text = " ".join(row).lower()
        if not any(keyword in row_text for keyword in _PENJELASAN_KEYWORDS):
            continue

        if len(row) >= 4:
            kegiatan, mulai_str, selesai_str = row[1], row[2], row[3]
        else:
            kegiatan, mulai_str, selesai_str = row[0], row[1], row[2]
        mulai_dt = _parse_datetime_str(mulai_str)
        if not mulai_dt:
            continue
        hasil.append({
            "kegiatan": kegiatan,
            "mulai": mulai_str,
            "selesai": selesai_str,
            "mulai_dt": mulai_dt,
            "selesai_dt": _parse_datetime_str(selesai_str),
        })
    return hasil


def parse_jadwal(paket_id: str) -> list[dict]:
    """Baca jadwal resmi dari ``/lelang/{ID}/jadwal`` via browser session."""
    from config import SPSE_BASE_URL

    url = f"{SPSE_BASE_URL}lelang/{paket_id}/jadwal"
    return _parse_jadwal_html(_fetch_html_via_browser(url))


def get_jadwal_pemberian_penjelasan(paket_id: str) -> dict | None:
    """Ambil jadwal pembukaan penjelasan; SPSE utama, GCal fallback."""
    spse_error = ""
    try:
        rows = parse_jadwal(paket_id)
        if rows:
            row = rows[0]
            return {**row, "sumber": "SPSE"}
        spse_error = "Baris Pemberian Penjelasan tidak ditemukan di SPSE."
    except Exception as exc:
        spse_error = str(exc)

    try:
        jadwal_gcal = get_jadwal_dari_gcalendar(paket_id=paket_id)
        mulai_dt = jadwal_gcal.get(paket_id)
        if mulai_dt:
            return {
                "kegiatan": "Pemberian Penjelasan",
                "mulai_dt": mulai_dt,
                "selesai_dt": None,
                "mulai": mulai_dt.strftime("%d/%m/%Y %H:%M"),
                "selesai": "",
                "sumber": "Google Calendar (fallback)",
                "spse_error": spse_error,
            }
    except Exception as exc:
        spse_error = f"{spse_error}; GCal: {exc}" if spse_error else str(exc)

    return None


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

    # Cari token.json di runtime instance aktif, lalu shared state. Scheduler
    # Tender/PP memakai profile SPSE terpisah, tetapi kalender tetap satu akun.
    try:
        from config import RUNTIME_ROOT, find_secret
        _runtime_root = Path(RUNTIME_ROOT)
        _shared_runtime_root = _runtime_root.parent
        _secret_credentials = Path(find_secret("credentials.json"))
    except Exception:
        _runtime_root = BASE_DIR
        _shared_runtime_root = BASE_DIR
        _secret_credentials = BASE_DIR / "credentials.json"

    token_candidates = [
        _runtime_root / "state" / "token.json",
        _shared_runtime_root / "state" / "token.json",
        BASE_DIR.parent / "V19_Scheduler" / "WPy64-313110" / "token.json",
        BASE_DIR / "token.json",
        Path.home() / ".credentials" / "token.json",
    ]
    cred_candidates = [
        _secret_credentials,
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


def _as_wita(value: datetime | None) -> datetime | None:
    """Normalisasi datetime GCal/SPSE ke timezone WITA."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ_WITA)
    return value.astimezone(TZ_WITA)


# ─────────────────────────────────────────────────────────────────────────────
# Persistent Jobs — simpan/load ke state runtime per instance
# ─────────────────────────────────────────────────────────────────────────────

def _load_jobs() -> list[dict]:
    source = JOBS_FILE if JOBS_FILE.exists() else LEGACY_JOBS_FILE
    if source.exists():
        try:
            jobs = json.loads(source.read_text(encoding="utf-8"))
            changed = False
            for job in jobs:
                result = job.get("result") or {}
                if (
                    job.get("status") == "fired"
                    and result.get("pesan") == "Tidak ada pertanyaan"
                ):
                    # Itu bukan keberhasilan pembukaan; reset agar engine baru
                    # mengirim kata pembukaan lewat endpoint yang benar.
                    job["status"] = "pending"
                    job["result"] = None
                    changed = True
            if source == LEGACY_JOBS_FILE and JOBS_FILE != LEGACY_JOBS_FILE:
                # Migrasi satu kali dari queue versi lama ke state instance.
                changed = True
            if changed:
                _save_jobs(jobs)
            return jobs
        except Exception:
            pass
    return []


def _save_jobs(jobs: list[dict]):
    JOBS_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def tambah_job(
    paket_id: str, nama_paket: str, jenis: str,
    waktu_fire: datetime, teks_override: str | None = None,
    auto_post: bool = True, waktu_selesai: datetime | None = None,
    event_id: str | None = None, sumber_jadwal: str = "manual",
) -> dict:
    """Daftarkan satu job penjelasan yang persisten di disk lokal."""
    jobs = _load_jobs()
    jobs = [j for j in jobs if not (j["paket_id"] == paket_id and j["jenis"] == jenis)]
    job = {
        "paket_id": paket_id, "nama_paket": nama_paket, "jenis": jenis,
        "waktu_fire": _as_wita(waktu_fire).isoformat(),
        "waktu_selesai": _as_wita(waktu_selesai).isoformat() if waktu_selesai else None,
        "teks_override": teks_override,
        "auto_post": auto_post,
        "event_id": event_id,
        "sumber_jadwal": sumber_jadwal,
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


def sync_jobs_from_gcal(
    now: datetime | None = None,
    horizon: timedelta = GCAL_SYNC_HORIZON,
) -> dict:
    """Enqueue upcoming event Pemberian Penjelasan dari Google Calendar.

    Sinkronisasi idempotent: event yang sudah ``fired`` tidak diulang, event
    ``pending`` mengikuti perubahan waktu di GCal, dan event baru hanya masuk
    sekali berdasarkan event_id/kode paket.
    """
    now = _as_wita(now or datetime.now(TZ_WITA))
    events = get_penjelasan_events(
        waktu_mulai=now - timedelta(hours=1),
        waktu_selesai=now + horizon,
    )
    jobs = _load_jobs()
    changed = False
    added = 0
    updated = 0
    skipped = 0

    for event in events:
        mulai = _as_wita(event.get("start"))
        if not mulai:
            continue
        paket_id = extract_paket_id_from_event(event)
        if not paket_id:
            skipped += 1
            continue

        event_id = str(event.get("event_id") or "").strip()
        existing = next(
            (
                job for job in jobs
                if (
                    event_id and job.get("event_id") == event_id
                ) or (
                    job.get("paket_id") == paket_id and job.get("jenis") == "tender"
                )
            ),
            None,
        )
        selesai = _as_wita(event.get("end")) or (mulai + timedelta(hours=3))

        if existing:
            if existing.get("status") == "pending":
                waktu_lama = existing.get("waktu_fire")
                waktu_baru = mulai.isoformat()
                selesai_lama = existing.get("waktu_selesai")
                updates = {
                    "waktu_fire": waktu_baru,
                    "waktu_selesai": selesai.isoformat(),
                    "nama_paket": event.get("summary") or existing.get("nama_paket", paket_id),
                    "event_id": event_id or existing.get("event_id"),
                    "sumber_jadwal": "Google Calendar",
                }
                if (
                    waktu_lama != waktu_baru
                    or selesai_lama != selesai.isoformat()
                    or any(existing.get(key) != value for key, value in updates.items())
                ):
                    existing.update(updates)
                    updated += 1
                    changed = True
            else:
                skipped += 1
            continue

        jobs.append({
            "paket_id": paket_id,
            "nama_paket": event.get("summary") or paket_id,
            "jenis": "tender",
            "waktu_fire": mulai.isoformat(),
            "waktu_selesai": selesai.isoformat(),
            "teks_override": None,
            "auto_post": True,
            "event_id": event_id or None,
            "sumber_jadwal": "Google Calendar",
            "status": "pending",
            "result": None,
        })
        added += 1
        changed = True

    if changed:
        _save_jobs(jobs)
    return {"ok": True, "added": added, "updated": updated, "skipped": skipped}


# ─────────────────────────────────────────────────────────────────────────────
# Background Scheduler untuk auto-post pembukaan
# ─────────────────────────────────────────────────────────────────────────────

_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_last_gcal_sync: datetime | None = None
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
    global _last_gcal_sync
    _log_append("Scheduler dimulai.")
    while not _scheduler_stop.is_set():
        now = datetime.now(TZ_WIB)

        if _last_gcal_sync is None or now - _last_gcal_sync >= GCAL_SYNC_INTERVAL:
            try:
                sync_result = sync_jobs_from_gcal(now=now)
                if sync_result["added"] or sync_result["updated"]:
                    _log_append(
                        "📅 GCal sync: "
                        f"{sync_result['added']} baru, {sync_result['updated']} berubah"
                    )
                _last_gcal_sync = now
            except Exception as exc:
                _log_append(f"⚠️ GCal sync error: {exc}")

        jobs = _load_jobs()

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
                    _log_append(f"🚀 Auto-post pembukaan: paket {paket_id} ({jenis}) ...")
                    try:
                        result = auto_post_pembukaan(
                            paket_id=paket_id,
                            jenis=jenis,
                            teks_override=job.get("teks_override"),
                        )
                        total = result.get("total", 0)
                        sukses = result.get("sukses", 0)
                        gagal = result.get("gagal", 0)
                        if gagal == 0:
                            status = "fired"
                        else:
                            batas_str = job.get("waktu_selesai")
                            try:
                                batas = datetime.fromisoformat(batas_str) if batas_str else waktu + timedelta(hours=3)
                                batas += timedelta(hours=3)
                            except Exception:
                                batas = waktu + timedelta(hours=6)
                            status = "pending" if now <= batas else "gagal"
                        _log_append(
                            f"{'✅' if gagal == 0 else '⚠️'} Paket {paket_id}: "
                            f"pembukaan {sukses}/{total}, {gagal} gagal"
                            + ("; akan retry" if status == "pending" else "")
                        )
                        update_job_status(paket_id, jenis, status, result)
                    except Exception as e:
                        _log_append(f"❌ Error paket {paket_id}: {e}")
                        update_job_status(paket_id, jenis, "gagal", {"error": str(e)})
                else:
                    _log_append(f"⏰ Jadwal tiba (manual mode): paket {paket_id}")
                    update_job_status(paket_id, jenis, "pending_manual")


        _scheduler_stop.wait(timeout=30)  # cek tiap 30 detik

    _log_append("Scheduler berhenti.")


def jadwalkan_pemberian_penjelasan(
    paket_id: str,
    nama_paket: str,
    jenis: str = "tender",
    teks_override: str | None = None,
    auto_post: bool = True,
) -> dict:
    """
    Cari jadwal resmi SPSE paket_id, GCal hanya fallback, lalu daftarkan job.
    Return: {ok: bool, waktu_fire: datetime|None, pesan: str}
    """
    jadwal = get_jadwal_pemberian_penjelasan(paket_id)
    if not jadwal or not jadwal.get("mulai_dt"):
        return {
            "ok": False,
            "waktu_fire": None,
            "pesan": "Jadwal Pemberian Penjelasan tidak ditemukan di SPSE/GCal.",
        }

    waktu_fire = jadwal["mulai_dt"]
    job = tambah_job(
        paket_id=paket_id,
        nama_paket=nama_paket,
        jenis=jenis,
        waktu_fire=waktu_fire,
        teks_override=teks_override if teks_override else None,
        auto_post=auto_post,
        waktu_selesai=jadwal.get("selesai_dt"),
        sumber_jadwal=jadwal.get("sumber", "SPSE"),
    )
    return {
        "ok": True,
        "waktu_fire": waktu_fire,
        "sumber": jadwal.get("sumber", "SPSE"),
        "pesan": f"Dijadwalkan dari {jadwal.get('sumber', 'SPSE')}: {waktu_fire.strftime('%d/%m/%Y %H:%M')} WITA",
        "job": job,
    }


def jadwalkan_dari_gcal(
    paket_id: str,
    nama_paket: str,
    jenis: str = "tender",
    teks_override: str | None = None,
    auto_post: bool = True,
) -> dict:
    """Alias kompatibilitas; kini SPSE primary dan GCal fallback."""
    return jadwalkan_pemberian_penjelasan(
        paket_id=paket_id,
        nama_paket=nama_paket,
        jenis=jenis,
        teks_override=teks_override,
        auto_post=auto_post,
    )


def start_scheduler():
    global _scheduler_thread, _scheduler_stop, _last_gcal_sync
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _last_gcal_sync = None
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="PenjelasanScheduler")
    _scheduler_thread.start()


def stop_scheduler():
    _scheduler_stop.set()


def is_scheduler_running() -> bool:
    return bool(_scheduler_thread and _scheduler_thread.is_alive())


def is_worker_alive(max_age_seconds: int = 90) -> bool:
    """True jika worker proses mandiri masih mengirim heartbeat baru."""
    try:
        age = time.time() - WORKER_HEARTBEAT_FILE.stat().st_mtime
        return 0 <= age <= max(10, int(max_age_seconds))
    except (FileNotFoundError, OSError, ValueError):
        return False
