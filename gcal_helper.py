"""Helper GCal — ambil tanggal tahapan dari Google Calendar untuk Tab 5 BA."""

import os
import json
from datetime import datetime, date

_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "V19_Scheduler", "WPy64-313110")
TOKEN_PATH = os.path.normpath(os.path.join(_BASE, "token.json"))
CRED_PATH  = os.path.normpath(os.path.join(_BASE, "credentials.json"))

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def generate_token():
    """Buka browser OAuth → simpan token.json baru. Panggil saat token expired/hilang."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not os.path.isfile(CRED_PATH):
        raise FileNotFoundError(f"credentials.json tidak ditemukan: {CRED_PATH}")
    if os.path.isfile(TOKEN_PATH):
        os.remove(TOKEN_PATH)
    flow = InstalledAppFlow.from_client_secrets_file(CRED_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    return TOKEN_PATH

# Mapping jenis_key → keyword yang dicari di judul event GCal
_TAHAP_KEYWORD = {
    "penjelasan":      "Pemberian Penjelasan",
    "evaluasi":        "Evaluasi Administrasi, Kualifikasi, Teknis, dan Harga",
    "hasil_pemilihan": "Penetapan Pemenang",
    "negosiasi":       "Pembuktian Kualifikasi",
}

# Untuk evaluasi, ambil tanggal END (hari terakhir); sisanya ambil START
_PAKAI_END = {"evaluasi"}


def _build_service():
    """Buat Google Calendar service dari token.json."""
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


def get_tanggal_ba_dari_gcal(nama_paket: str) -> dict:
    """
    Cari event GCal yang judulnya mengandung nama_paket, lalu petakan
    ke tanggal per jenis BA.

    Returns dict: {jenis_key: date_obj or None}
    """
    service = _build_service()

    hasil = {k: None for k in _TAHAP_KEYWORD}

    # Ambil events 1 tahun ke belakang dan 1 tahun ke depan
    time_min = datetime(date.today().year - 1, 1, 1).isoformat() + "Z"
    time_max = datetime(date.today().year + 1, 12, 31).isoformat() + "Z"

    page_token = None
    events_found = []
    while True:
        resp = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=2500,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        events_found.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Filter event yang judulnya mengandung nama_paket (case-insensitive)
    nama_lower = nama_paket.lower()
    paket_events = [e for e in events_found if nama_lower in e.get("summary", "").lower()]

    for jenis_key, keyword in _TAHAP_KEYWORD.items():
        kw_lower = keyword.lower()
        matched = [e for e in paket_events if kw_lower in e.get("summary", "").lower()]
        if not matched:
            continue

        ev = matched[0]  # ambil yang pertama ditemukan
        pakai_end = jenis_key in _PAKAI_END

        if pakai_end:
            dt_str = ev.get("end", {}).get("date") or ev.get("end", {}).get("dateTime", "")
        else:
            dt_str = ev.get("start", {}).get("date") or ev.get("start", {}).get("dateTime", "")

        if not dt_str:
            continue

        try:
            # Format bisa "YYYY-MM-DD" atau "YYYY-MM-DDTHH:MM:SS..."
            d = datetime.fromisoformat(dt_str[:10]).date()
            # Untuk evaluasi (end), GCal end date eksklusif → kurangi 1 hari
            if pakai_end:
                from datetime import timedelta
                d = d - timedelta(days=1)
            hasil[jenis_key] = d
        except ValueError:
            pass

    return hasil


def get_jadwal_klarifikasi_pl(kode_nontender: str) -> dict | None:
    """
    Cari event GCal 'Klarifikasi Teknis dan Negosiasi' untuk paket PL.
    Match via description yang mengandung kode_nontender (lebih akurat dari nama_paket).

    Returns: {"start_date": date, "end_date": date} atau None jika tidak ditemukan.
    GCal end date eksklusif → end_date = end_date - 1 hari.
    """
    from datetime import timedelta

    service = _build_service()

    time_min = datetime(date.today().year, 1, 1).isoformat() + "Z"
    time_max = datetime(date.today().year + 1, 12, 31).isoformat() + "Z"

    resp = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=2500,
        singleEvents=True,
        q="Klarifikasi Teknis dan Negosiasi",
    ).execute()

    for ev in resp.get("items", []):
        desc = ev.get("description", "") or ""
        if kode_nontender not in desc:
            continue
        summary = ev.get("summary", "")
        if "Klarifikasi Teknis dan Negosiasi" not in summary:
            continue

        start_str = ev.get("start", {}).get("date") or ev.get("start", {}).get("dateTime", "")
        end_str = ev.get("end", {}).get("date") or ev.get("end", {}).get("dateTime", "")
        if not start_str or not end_str:
            continue

        try:
            start_date = datetime.fromisoformat(start_str[:10]).date()
            end_date = datetime.fromisoformat(end_str[:10]).date()
            # GCal all-day event: end eksklusif → kurangi 1 hari
            if len(end_str) == 10:  # format date (all-day), bukan dateTime
                end_date = end_date - timedelta(days=1)
            return {"start_date": start_date, "end_date": end_date}
        except ValueError:
            continue

    return None
