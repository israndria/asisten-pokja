"""
gcal_pl_helper.py — Google Calendar sync untuk jadwal Pengadaan Langsung (PL).

Format event GCal PL:
  summary: "{Nama Tahap} - {nama_paket}"
  extendedProperties.private.source_pl = kode_paket  (key untuk delete-before-insert)

5 tahap PL:
  1. Upload Dokumen Penawaran
  2. Pembukaan Dokumen Penawaran
  3. Evaluasi Penawaran           → tgl_evaluasi  (hari selesai T3)
  4. Klarifikasi Teknis dan Negosiasi → tgl_negosiasi (hari T4)
  5. Penandatanganan Kontrak      → tgl_penetapan (hari mulai T5)
"""

import os
import json
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from config import RUNTIME_ROOT

# State OAuth per-PC; gunakan lokasi runtime yang sama dengan app utama.
TOKEN_PATH = os.path.normpath(os.path.join(RUNTIME_ROOT, "state", "token.json"))
CALENDAR_ID = "primary"
TZ = "Asia/Makassar"
_SCHEDULE_STATE_PATH = os.path.normpath(
    os.path.join(RUNTIME_ROOT, "state", "pl_schedule_hashes.json")
)

_TOKEN_CHECK_CACHE = {"key": None, "until": 0.0, "ok": False}


def _parse_token_expiry(value):
    """Konversi expiry token.json (RFC3339 string) ke datetime aware."""
    if not value or isinstance(value, datetime):
        return value
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        # google-auth membandingkan expiry dengan utcnow() naive.
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def _token_cache_key():
    try:
        stat = os.stat(TOKEN_PATH)
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _cache_token_result(ok: bool, ttl: float = 60.0) -> bool:
    _TOKEN_CHECK_CACHE.update(key=_token_cache_key(), until=time.monotonic() + ttl, ok=ok)
    return ok


def _schedule_hash(jadwal_list: list[dict]) -> str:
    """Hash jadwal SPSE untuk menghindari write GCal berulang oleh scheduler."""
    payload = [
        {
            "nama": str(tahap.get("nama", "")),
            "mulai": tahap["mulai"].isoformat(),
            "selesai": tahap["selesai"].isoformat(),
        }
        for tahap in jadwal_list
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_schedule_state() -> dict[str, str]:
    try:
        with open(_SCHEDULE_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_schedule_state(state: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(_SCHEDULE_STATE_PATH), exist_ok=True)
    temp_path = f"{_SCHEDULE_STATE_PATH}.{os.getpid()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(temp_path, _SCHEDULE_STATE_PATH)

# Mapping index tahap → kolom Supabase yang di-upsert
# index 0-based sesuai urutan 5 tahap
_SUPABASE_COL = {
    1: "tgl_pembukaan",   # T2 Pembukaan → ambil tanggal mulai
    2: "tgl_evaluasi",    # T3 Evaluasi → ambil tanggal selesai
    3: "tgl_negosiasi",   # T4 Klarifikasi+Nego → ambil tanggal mulai
    4: "tgl_penetapan",   # T5 Penandatanganan → ambil tanggal mulai
}


# ─────────────────────────────────────────────────────────────────────────────
# GCal service
# ─────────────────────────────────────────────────────────────────────────────

def _build_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(f"token.json tidak ditemukan: {TOKEN_PATH}")

    with open(TOKEN_PATH, "r") as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/calendar"]),
        expiry=_parse_token_expiry(token_data.get("expiry")),
    )

    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def check_gcal_token() -> bool:
    """Cek token GCal valid. Auto-refresh kalau expired tapi refresh_token masih ada.
    Return False kalau token tidak ada / revoked / perlu re-auth."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_key = _token_cache_key()
    if token_key is None:
        return _cache_token_result(False, ttl=15.0)
    if (
        _TOKEN_CHECK_CACHE.get("key") == token_key
        and time.monotonic() < _TOKEN_CHECK_CACHE.get("until", 0.0)
    ):
        return bool(_TOKEN_CHECK_CACHE.get("ok"))
    try:
        with open(TOKEN_PATH, "r") as f:
            token_data = json.load(f)
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/calendar"]),
            expiry=_parse_token_expiry(token_data.get("expiry")),
        )
        if creds.valid:
            return _cache_token_result(True)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            return _cache_token_result(True)
    except Exception:
        pass
    return _cache_token_result(False, ttl=15.0)


# ─────────────────────────────────────────────────────────────────────────────
# Delete event lama milik paket ini
# ─────────────────────────────────────────────────────────────────────────────

def _delete_events_by_kode(service, kode_paket: str):
    """Hapus semua event GCal yang punya extendedProperties.private.source_pl = kode_paket."""
    page_token = None
    ids_to_delete = []
    while True:
        resp = service.events().list(
            calendarId=CALENDAR_ID,
            privateExtendedProperty=f"source_pl={kode_paket}",
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            ids_to_delete.append(ev["id"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    for eid in ids_to_delete:
        try:
            service.events().delete(calendarId=CALENDAR_ID, eventId=eid).execute()
        except Exception:
            pass
    return len(ids_to_delete)


# ─────────────────────────────────────────────────────────────────────────────
# Push 5 event PL ke GCal
# ─────────────────────────────────────────────────────────────────────────────

def push_jadwal_pl_ke_gcal(
    kode_paket: str,
    nama_paket: str,
    jadwal_list: list[dict],
) -> dict:
    """
    Insert/update 5 event GCal untuk 1 paket PL.
    jadwal_list: [{"nama": str, "mulai": datetime, "selesai": datetime}, ...]

    Returns: {"ok": bool, "inserted": int, "deleted": int, "error": str}
    """
    try:
        service = _build_service()
        deleted = _delete_events_by_kode(service, kode_paket)

        inserted = 0
        errors = []
        for index, tahap in enumerate(jadwal_list, 1):
            mulai: datetime = tahap["mulai"]
            selesai: datetime = tahap["selesai"]
            evt = {
                "summary": f"{tahap['nama']} - {nama_paket}",
                "description": f"Paket PL: {kode_paket}\n{nama_paket}",
                "start": {"dateTime": mulai.isoformat(), "timeZone": TZ},
                "end":   {"dateTime": selesai.isoformat(), "timeZone": TZ},
                "extendedProperties": {
                    "private": {"source_pl": kode_paket}
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": 60}],
                },
            }
            try:
                service.events().insert(calendarId=CALENDAR_ID, body=evt).execute()
                inserted += 1
            except Exception as e:
                errors.append(f"Tahap {index} ({tahap.get('nama', '-')}) gagal: {e}")

        return {
            "ok": not errors and inserted == len(jadwal_list),
            "inserted": inserted,
            "deleted": deleted,
            "error": " | ".join(errors)[:1000],
        }
    except Exception as e:
        return {"ok": False, "inserted": 0, "deleted": 0, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Parse jadwal aktual dari halaman SPSE (bukan hitung, tapi baca nilai existing)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_datetime_spse(s: str) -> datetime | None:
    """Parse 'DD-MM-YYYY HH:mm' atau 'YYYY-MM-DDTHH:mm:ss'."""
    s = s.strip()
    if not s:
        return None
    for fmt in ("%d-%m-%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def parse_jadwal_pl_dari_spse(kode_paket: str) -> list[dict]:
    """
    Scrape /nontender/{kode_paket}/jadwal — public endpoint, tidak butuh login.
    Returns: [{"nama": str, "mulai": datetime, "selesai": datetime}, ...]
    """
    from config import SPSE_BASE_URL
    from bs4 import BeautifulSoup as _BS

    _BULAN = {"Januari":1,"Februari":2,"Maret":3,"April":4,"Mei":5,"Juni":6,
              "Juli":7,"Agustus":8,"September":9,"Oktober":10,"November":11,"Desember":12}

    def _parse_tgl(s: str):
        s = s.strip()
        try:
            parts = s.split()  # ['12','Juni','2026','15:15']
            d, bln, y, t = int(parts[0]), _BULAN[parts[1]], int(parts[2]), parts[3]
            h, m = map(int, t.split(":"))
            return datetime(y, bln, d, h, m)
        except Exception:
            return None

    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/nontender/{kode_paket}/jadwal"
    r = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"GET jadwal gagal: HTTP {r.status_code}")

    soup = _BS(r.text, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("Tabel jadwal tidak ditemukan di halaman SPSE.")

    hasil = []
    for tr in table.find_all("tr")[1:]:  # skip header
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= 4:
            mulai = _parse_tgl(tds[2])
            selesai = _parse_tgl(tds[3])
            if mulai and selesai:
                hasil.append({"nama": tds[1], "mulai": mulai, "selesai": selesai})
    return hasil

def sync_jadwal_pl(
    kode_paket: str,
    nama_paket: str,
    *,
    skip_unchanged: bool = False,
) -> dict:
    """
    1. Baca jadwal aktual dari SPSE /nontender/{kode}/jadwal
    2. Push ke GCal (delete lama + insert baru)
    3. Upsert tgl_evaluasi/tgl_negosiasi/tgl_penetapan ke Supabase

    Returns: {"ok": bool, "gcal": dict, "supabase": dict, "jadwal": list, "error": str}
    """
    try:
        jadwal_list = parse_jadwal_pl_dari_spse(kode_paket)
    except Exception as e:
        return {"ok": False, "gcal": {}, "supabase": {}, "jadwal": [], "error": str(e)}

    if not jadwal_list:
        return {"ok": False, "gcal": {}, "supabase": {}, "jadwal": [], "error": "Jadwal kosong di SPSE (belum diisi)."}

    schedule_hash = _schedule_hash(jadwal_list)
    if skip_unchanged and _load_schedule_state().get(str(kode_paket)) == schedule_hash:
        return {
            "ok": True,
            "skipped": True,
            "gcal": {"ok": True, "inserted": 0, "deleted": 0, "error": ""},
            "supabase": {"ok": True, "updated": {}},
            "jadwal": jadwal_list,
            "error": "",
        }

    # Push GCal
    gcal_result = push_jadwal_pl_ke_gcal(kode_paket, nama_paket, jadwal_list)

    # Upsert Supabase — ambil tanggal dari tahap index 1..4.
    # Tanggal pembukaan punya dua nama kolom historis; sinkronkan keduanya.
    sb_update = {}
    for i, tahap in enumerate(jadwal_list):
        col = _SUPABASE_COL.get(i)
        if not col:
            continue
        # T3 evaluasi → ambil selesai; T4 nego + T5 penetapan → ambil mulai
        if i == 2:
            dt = tahap["selesai"]   # T3 Evaluasi → selesai
        else:
            dt = tahap["mulai"]     # T2/T4/T5 → mulai
        nilai_tanggal = dt.date().isoformat()
        sb_update[col] = nilai_tanggal
        if col == "tgl_pembukaan":
            sb_update["tgl_buka_penawaran"] = nilai_tanggal

    sb_result = {"ok": False, "error": ""}
    if sb_update:
        try:
            from config import sb as _sb
            _sb().table("draft_paket_pl").update(sb_update).eq("kode_paket", kode_paket).execute()
            sb_result = {"ok": True, "updated": sb_update}
        except Exception as e:
            sb_result = {"ok": False, "error": str(e)}

    result = {
        "ok": gcal_result["ok"] and sb_result["ok"],
        "skipped": False,
        "gcal": gcal_result,
        "supabase": sb_result,
        "jadwal": jadwal_list,
        "error": gcal_result.get("error") or sb_result.get("error") or "",
    }
    if result["ok"]:
        state = _load_schedule_state()
        state[str(kode_paket)] = schedule_hash
        try:
            _save_schedule_state(state)
        except OSError:
            # State hanya optimasi; kegagalan simpan tidak membatalkan sync GCal.
            pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Bulk sync semua paket PL
# ─────────────────────────────────────────────────────────────────────────────

def sync_semua_paket_pl(
    progress_cb=None,
    *,
    skip_unchanged: bool = False,
) -> list[dict]:
    """
    Loop semua paket dari Supabase draft_paket_pl → sync_jadwal_pl per paket.
    progress_cb(frac, msg) opsional.
    """
    from config import sb as _sb

    rows = _sb().table("draft_paket_pl").select("kode_paket,nama_paket") \
        .or_("tahap_spse.neq.Paket Sudah Selesai,tahap_spse.is.null") \
        .execute().data or []
    total = max(len(rows), 1)
    results = []

    for i, row in enumerate(rows):
        kode = row["kode_paket"]
        nama = row["nama_paket"] or kode
        if progress_cb:
            progress_cb((i + 1) / total, f"Sync {kode} — {nama[:40]}")
        r = sync_jadwal_pl(kode, nama, skip_unchanged=skip_unchanged)
        results.append({
            "kode_paket": kode,
            "nama_paket": nama[:50],
            "ok": r["ok"],
            "skipped": r.get("skipped", False),
            "gcal_inserted": r["gcal"].get("inserted", 0),
            "gcal_deleted": r["gcal"].get("deleted", 0),
            "tgl_evaluasi": r["supabase"].get("updated", {}).get("tgl_evaluasi", ""),
            "tgl_negosiasi": r["supabase"].get("updated", {}).get("tgl_negosiasi", ""),
            "tgl_penetapan": r["supabase"].get("updated", {}).get("tgl_penetapan", ""),
            "error": r["error"],
        })

    return results
