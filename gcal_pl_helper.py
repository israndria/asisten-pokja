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
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

TOKEN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "V19_Scheduler", "WPy64-313110", "token.json",
)
CALENDAR_ID = "primary"
TZ = "Asia/Jakarta"

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
    )

    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


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
        for tahap in jadwal_list:
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
                pass

        return {"ok": True, "inserted": inserted, "deleted": deleted, "error": ""}
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
    Scrape /jadwalnontender/{kode_paket}/list, baca nilai tglawal+tglakhir
    dari input fields yang sudah terisi (bukan hidden form submit).
    Returns: [{"nama": str, "mulai": datetime, "selesai": datetime}, ...]
    """
    import spse_browser
    from config import SPSE_BASE_URL

    base = SPSE_BASE_URL.rstrip("/")
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        raise RuntimeError("Cookie SPSE kosong.")

    url = f"{base}/jadwalnontender/{kode_paket}/list"
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_str,
    }, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"GET jadwalnontender gagal: HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Cari form simpanjadwalnontender
    form_jadwal = None
    for f in soup.find_all("form"):
        if "simpanjadwalnontender" in (f.get("action") or ""):
            form_jadwal = f
            break
    if not form_jadwal:
        raise RuntimeError("Form jadwal tidak ditemukan.")

    # Baca semua rows jadwalList[N]
    seen = {}
    for inp in form_jadwal.find_all("input"):
        name = inp.get("name", "")
        m = re.match(r"jadwalList\[(\d+)\]\.(dtj_tglawal|dtj_tglakhir|thp_nama)", name)
        if not m:
            continue
        idx = int(m.group(1))
        field = m.group(2)
        if idx not in seen:
            seen[idx] = {}
        seen[idx][field] = inp.get("value", "")

    # Fallback: nama tahap dari label/td teks di baris
    # Ambil nama dari thp_nama input, atau dari teks td di tabel
    nama_fallback = [
        "Upload Dokumen Penawaran",
        "Pembukaan Dokumen Penawaran",
        "Evaluasi Penawaran",
        "Klarifikasi Teknis dan Negosiasi",
        "Penandatanganan Kontrak",
    ]

    hasil = []
    for idx in sorted(seen.keys()):
        row = seen[idx]
        mulai_str = row.get("dtj_tglawal", "")
        selesai_str = row.get("dtj_tglakhir", "")
        nama = row.get("thp_nama", "") or (nama_fallback[idx] if idx < len(nama_fallback) else f"Tahap {idx+1}")
        mulai = _parse_datetime_spse(mulai_str)
        selesai = _parse_datetime_spse(selesai_str)
        if mulai and selesai:
            hasil.append({"nama": nama, "mulai": mulai, "selesai": selesai})

    return hasil


# ─────────────────────────────────────────────────────────────────────────────
# Sync satu paket: SPSE → GCal + Supabase tgl_*
# ─────────────────────────────────────────────────────────────────────────────

def sync_jadwal_pl(kode_paket: str, nama_paket: str) -> dict:
    """
    1. Baca jadwal aktual dari SPSE /jadwalnontender/{kode}/list
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

    # Push GCal
    gcal_result = push_jadwal_pl_ke_gcal(kode_paket, nama_paket, jadwal_list)

    # Upsert Supabase — ambil tanggal dari tahap index 2,3,4
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
        sb_update[col] = dt.date().isoformat()

    sb_result = {"ok": False, "error": ""}
    if sb_update:
        try:
            from config import sb as _sb
            _sb().table("draft_paket_pl").update(sb_update).eq("kode_paket", kode_paket).execute()
            sb_result = {"ok": True, "updated": sb_update}
        except Exception as e:
            sb_result = {"ok": False, "error": str(e)}

    return {
        "ok": gcal_result["ok"] and sb_result["ok"],
        "gcal": gcal_result,
        "supabase": sb_result,
        "jadwal": jadwal_list,
        "error": gcal_result.get("error") or sb_result.get("error") or "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bulk sync semua paket PL
# ─────────────────────────────────────────────────────────────────────────────

def sync_semua_paket_pl(progress_cb=None) -> list[dict]:
    """
    Loop semua paket dari Supabase draft_paket_pl → sync_jadwal_pl per paket.
    progress_cb(frac, msg) opsional.
    """
    from config import sb as _sb

    rows = _sb().table("draft_paket_pl").select("kode_paket,nama_paket").execute().data or []
    total = max(len(rows), 1)
    results = []

    for i, row in enumerate(rows):
        kode = row["kode_paket"]
        nama = row["nama_paket"] or kode
        if progress_cb:
            progress_cb((i + 1) / total, f"Sync {kode} — {nama[:40]}")
        r = sync_jadwal_pl(kode, nama)
        results.append({
            "kode_paket": kode,
            "nama_paket": nama[:50],
            "ok": r["ok"],
            "gcal_inserted": r["gcal"].get("inserted", 0),
            "gcal_deleted": r["gcal"].get("deleted", 0),
            "tgl_evaluasi": r["supabase"].get("updated", {}).get("tgl_evaluasi", ""),
            "tgl_negosiasi": r["supabase"].get("updated", {}).get("tgl_negosiasi", ""),
            "tgl_penetapan": r["supabase"].get("updated", {}).get("tgl_penetapan", ""),
            "error": r["error"],
        })

    return results
