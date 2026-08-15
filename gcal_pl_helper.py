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
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from config import (
    OUTPUT_DIR_PL_JKK,
    OUTPUT_DIR_PL_PK,
    RUNTIME_ROOT,
    V19_ROOT,
)

try:
    from calendar_sync_targets import (
        TargetRegistryError,
        folder_identity_matches,
        load_targets,
        upsert_target,
    )
    from spse_public_http import get_public as _get_public_spse
except ImportError:
    if V19_ROOT not in sys.path:
        sys.path.insert(0, V19_ROOT)
    from calendar_sync_targets import (
        TargetRegistryError,
        folder_identity_matches,
        load_targets,
        upsert_target,
    )
    from spse_public_http import get_public as _get_public_spse

# State OAuth per-PC; gunakan lokasi runtime yang sama dengan app utama.
TOKEN_PATH = os.path.normpath(os.path.join(RUNTIME_ROOT, "state", "token.json"))
CALENDAR_ID = "primary"
TZ = "Asia/Makassar"
_SCHEDULE_STATE_PATH = os.path.normpath(
    os.path.join(RUNTIME_ROOT, "state", "pl_schedule_hashes.json")
)

_TOKEN_CHECK_CACHE = {"key": None, "until": 0.0, "ok": False}
_SPSE_SESSION = None


def _get_spse_session():
    global _SPSE_SESSION
    if _SPSE_SESSION is not None:
        return _SPSE_SESSION
    try:
        import cloudscraper
        _SPSE_SESSION = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    except ImportError:
        _SPSE_SESSION = requests
    return _SPSE_SESSION


def _get_spse(url: str, **kwargs):
    session = _get_spse_session()
    return _get_public_spse(
        session,
        url,
        fallback=requests,
        **kwargs,
    )


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

def _list_events_by_kode(service, kode_paket: str) -> list[dict]:
    """Ambil event baru dan event PL legacy yang hanya punya kode di deskripsi."""
    found = {}
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=CALENDAR_ID,
            privateExtendedProperty=f"source_pl={kode_paket}",
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            found[ev.get("id")] = ev
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    page_token = None
    needle = f"Paket PL: {kode_paket}"
    while True:
        resp = service.events().list(
            calendarId=CALENDAR_ID,
            q=needle,
            singleEvents=True,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            if needle in (ev.get("description", "") or ""):
                found[ev.get("id")] = ev
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return [ev for ev in found.values() if ev.get("id")]


def _delete_events_by_kode(service, kode_paket: str):
    """Kompatibilitas helper lama; hapus event setelah caller memastikan sukses."""
    ids_to_delete = [ev["id"] for ev in _list_events_by_kode(service, kode_paket)]
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
        existing = _list_events_by_kode(service, kode_paket)
        by_index = {}
        by_summary = {}
        for ev in existing:
            private = ev.get("extendedProperties", {}).get("private", {})
            if private.get("source_stage_index") is not None:
                by_index.setdefault(str(private["source_stage_index"]), []).append(ev)
            if ev.get("summary"):
                by_summary.setdefault(ev["summary"], []).append(ev)

        inserted = updated = deleted = 0
        used_ids = set()
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
                    "private": {
                        "source_pl": kode_paket,
                        "source_stage_index": str(index),
                    }
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": 60}],
                },
            }
            try:
                candidates = by_index.get(str(index), []) or by_summary.get(evt["summary"], [])
                event = next((ev for ev in candidates if ev.get("id") not in used_ids), None)
                if event:
                    service.events().update(
                        calendarId=CALENDAR_ID, eventId=event["id"], body=evt,
                    ).execute()
                    used_ids.add(event["id"])
                    updated += 1
                else:
                    response = service.events().insert(calendarId=CALENDAR_ID, body=evt).execute()
                    if isinstance(response, dict) and response.get("id"):
                        used_ids.add(response["id"])
                    inserted += 1
            except Exception as e:
                errors.append(f"Tahap {index} ({tahap.get('nama', '-')}) gagal: {e}")

        if not errors:
            for ev in existing:
                if ev.get("id") in used_ids:
                    continue
                try:
                    service.events().delete(calendarId=CALENDAR_ID, eventId=ev["id"]).execute()
                    deleted += 1
                except Exception as e:
                    errors.append(f"Hapus event stale gagal: {e}")

        return {
            "ok": not errors and inserted + updated == len(jadwal_list),
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted,
            "error": " | ".join(errors)[:1000],
        }
    except Exception as e:
        return {"ok": False, "inserted": 0, "updated": 0, "deleted": 0, "error": str(e)}


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
    r = _get_spse(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{base}/nontender/{kode_paket}/pengumuman",
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


def _gcal_schedule_complete(kode_paket: str, jadwal_list: list[dict]) -> bool:
    """Hash lokal hanya boleh skip bila event remote masih lengkap."""
    try:
        service = _build_service()
        events = _list_events_by_kode(service, kode_paket)
        actual = {ev.get("summary") for ev in events}
        # Nama paket tidak tersedia di sini; validasi minimal gunakan stage index.
        indexes = {
            str(ev.get("extendedProperties", {}).get("private", {}).get("source_stage_index"))
            for ev in events
        }
        return all(str(i) in indexes for i in range(1, len(jadwal_list) + 1)) or len(actual) >= len(jadwal_list)
    except Exception:
        return False


def _pl_folder_identity_valid(folder_name: str, kode_paket: str) -> bool:
    return folder_identity_matches(
        folder_name,
        kode_paket,
        (OUTPUT_DIR_PL_JKK, OUTPUT_DIR_PL_PK),
        "@ Master Data",
        ("C3", "F2"),
    )


def _auto_enroll_folder_pl() -> None:
    """Enroll PL yang foldernya dibuat user, termasuk jadwal yang dibuat teman."""
    from config import sb as _sb

    all_targets = load_targets("pl", enabled_only=False)
    known = {
        str(target.get("kode_paket") or "").strip(): target
        for target in all_targets
    }
    rows = _sb().table("draft_paket_pl").select(
        "kode_paket,nama_paket,folder_dibuat,jenis_pl"
    ).execute().data or []
    for row in rows:
        code = str(row.get("kode_paket") or "").strip()
        folder_name = str(row.get("folder_dibuat") or "").strip()
        if (
            not code
            or not folder_name
            or code in known
            or not _pl_folder_identity_valid(folder_name, code)
        ):
            continue
        upsert_target(
            "pl", code,
            name=str(row.get("nama_paket") or code).strip(),
            folder_name=folder_name,
            source="folder-auto",
            note="Auto-enrolled karena folder paket ada di root PL lokal.",
        )


def _load_owned_pl_rows() -> list[dict]:
    """Ambil PL hanya bila kodenya ada di allowlist aktif."""
    from config import sb as _sb

    _auto_enroll_folder_pl()
    targets = load_targets("pl")
    if not targets:
        return []
    codes = [str(target.get("kode_paket") or "").strip() for target in targets]
    rows = _sb().table("draft_paket_pl").select(
        "kode_paket,nama_paket,tahap_spse"
    ).in_("kode_paket", codes).execute().data or []
    by_code = {str(row.get("kode_paket") or "").strip(): row for row in rows}
    result = []
    for target in targets:
        code = str(target.get("kode_paket") or "").strip()
        row = by_code.get(code)
        if not row:
            continue
        if (
            str(target.get("source") or "").strip() == "folder-auto"
            and not _pl_folder_identity_valid(target.get("folder_name", ""), code)
        ):
            continue
        if str(row.get("tahap_spse") or "").strip() == "Paket Sudah Selesai":
            continue
        result.append({
            "kode_paket": code,
            "nama_paket": target.get("nama_paket") or row.get("nama_paket") or code,
        })
    return result


def register_pl_calendar_targets(rows: list[dict]) -> list[str]:
    """Daftarkan paket PL yang sedang dipilih user ke allowlist aktif."""
    errors = []
    for row in rows or []:
        code = str(row.get("kode_paket") or row.get("kode") or "").strip()
        if not code:
            continue
        try:
            upsert_target(
                "pl",
                code,
                name=str(row.get("nama_paket") or row.get("nama") or code).strip(),
                source="asisten-ui",
            )
        except (TargetRegistryError, ValueError) as exc:
            errors.append(f"{code}: {exc}")
    return errors

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
        if _gcal_schedule_complete(kode_paket, jadwal_list):
            return {
                "ok": True,
                "skipped": True,
                "gcal": {"ok": True, "inserted": 0, "updated": 0, "deleted": 0, "error": ""},
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

    rows = _load_owned_pl_rows()
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
