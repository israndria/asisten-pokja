"""
Penjelasan Engine — otomatisasi POST pemberian penjelasan.

Fitur:
- parse_jadwal(paket_id)    → cari datetime "Pemberian Penjelasan" dari /lelang/[ID]/jadwal
- scan_penjelasan_form(url) → scan form /penjelasan/[ID]/pengadaan
- submit_penjelasan(...)    → POST via fetch API (browser context)
- Scheduler: daftarkan job (paket_id + waktu + template), fire tepat waktu
"""

import json
import threading
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import spse_browser
from penjelasan_config import TEMPLATE

# ─────────────────────────────────────────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────────────────────────────────────────

TZ_WIB = ZoneInfo("Asia/Jakarta")
BASE_DIR = Path(__file__).parent
JOBS_FILE = BASE_DIR / "pending_penjelasan.json"

# Keyword jadwal yang dicari (case-insensitive)
_PENJELASAN_KEYWORDS = [
    "pemberian penjelasan",
    "penjelasan dokumen",
    "aanwijzing",
    "penjelasan kualifikasi",
    "penjelasan seleksi",
    "penjelasan pemilihan",
]

# ─────────────────────────────────────────────────────────────────────────────
# Parse Jadwal dari /lelang/[ID]/jadwal
# ─────────────────────────────────────────────────────────────────────────────

_JADWAL_JS = """() => {
    // Cari semua baris tabel jadwal
    const rows = [];
    document.querySelectorAll('table tr').forEach(tr => {
        const cells = Array.from(tr.querySelectorAll('td, th')).map(c => c.innerText.trim());
        if (cells.length >= 3) rows.push(cells);
    });
    // Juga cari dl/dt/dd pattern (kadang SPSE pakai definition list)
    const dls = [];
    document.querySelectorAll('dl').forEach(dl => {
        const items = {};
        let lastDt = '';
        dl.querySelectorAll('dt, dd').forEach(el => {
            if (el.tagName === 'DT') lastDt = el.innerText.trim();
            else items[lastDt] = el.innerText.trim();
        });
        if (Object.keys(items).length) dls.push(items);
    });
    return { rows, dls, html: document.body.innerText.substring(0, 8000) };
}"""


def _parse_datetime_str(s: str) -> datetime | None:
    """
    Coba parse string datetime dari SPSE.
    Format umum: '10/04/2026 10:00 WIB', '2026-04-10 10:00:00', '10 April 2026 10.00'
    """
    s = s.strip().replace("WIB", "").replace("WITA", "").replace("WIT", "").strip()

    BULAN_ID = {
        "januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,
        "juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12,
    }

    formats = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H.%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%m-%Y %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=TZ_WIB)
        except ValueError:
            pass

    # Format Indonesia: "10 April 2026 10.00"
    m = re.match(
        r'(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{1,2})[.:](\d{2})', s, re.IGNORECASE
    )
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


def parse_jadwal(paket_id: str) -> list[dict]:
    """
    Navigate ke /lelang/[ID]/jadwal, scrape tabel jadwal.
    Return: list of {kegiatan, mulai, selesai, mulai_dt, selesai_dt}
    Hanya baris yang mengandung keyword penjelasan yang dikembalikan.
    """
    from config import SPSE_BASE_URL
    url = f"{SPSE_BASE_URL}lelang/{paket_id}/jadwal"

    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")

    spse_browser._run(page.goto(url, wait_until="domcontentloaded", timeout=30000))
    data = spse_browser._run(page.evaluate(_JADWAL_JS))

    hasil = []

    # Parse dari tabel rows
    for row in data["rows"]:
        # Gabungkan semua cell untuk cek keyword
        row_text = " ".join(row).lower()
        if not any(kw in row_text for kw in _PENJELASAN_KEYWORDS):
            continue

        # Kegiatan biasanya kolom ke-2 (setelah nomor), mulai & selesai setelahnya
        # Coba berbagai kemungkinan posisi kolom
        kegiatan = ""
        mulai_str = ""
        selesai_str = ""

        if len(row) >= 4:
            # Format: No | Kegiatan | Mulai | Selesai
            kegiatan   = row[1]
            mulai_str  = row[2]
            selesai_str = row[3]
        elif len(row) == 3:
            kegiatan   = row[0]
            mulai_str  = row[1]
            selesai_str = row[2]

        mulai_dt   = _parse_datetime_str(mulai_str)
        selesai_dt = _parse_datetime_str(selesai_str)

        if mulai_dt:  # hanya masukkan jika berhasil parse tanggal
            hasil.append({
                "kegiatan":   kegiatan,
                "mulai":      mulai_str,
                "selesai":    selesai_str,
                "mulai_dt":   mulai_dt,
                "selesai_dt": selesai_dt,
            })

    # Fallback: scan teks bebas jika tabel kosong
    if not hasil:
        raw = data["html"]
        for kw in _PENJELASAN_KEYWORDS:
            idx = raw.lower().find(kw)
            if idx != -1:
                snippet = raw[max(0, idx-20):idx+200]
                # Cari datetime di snippet
                # Format dd/mm/yyyy hh:mm
                matches = re.findall(r'\d{2}/\d{2}/\d{4}\s+\d{2}[.:]\d{2}', snippet)
                for m in matches:
                    dt = _parse_datetime_str(m)
                    if dt:
                        hasil.append({
                            "kegiatan": kw.title(),
                            "mulai": m,
                            "selesai": "",
                            "mulai_dt": dt,
                            "selesai_dt": None,
                        })
                        break
                if hasil:
                    break

    return hasil


# ─────────────────────────────────────────────────────────────────────────────
# Scan Form Penjelasan
# ─────────────────────────────────────────────────────────────────────────────

_FORM_JS = """() => {
    const form = document.querySelector('form');
    const csrfMeta  = document.querySelector('meta[name="csrf-token"]');
    const csrfInput = document.querySelector('input[name="_token"]');
    const csrf = csrfMeta ? csrfMeta.content : csrfInput ? csrfInput.value : '';

    const fields = [];
    document.querySelectorAll('input, textarea, select').forEach(el => {
        fields.push({
            type:  el.type || el.tagName.toLowerCase(),
            name:  el.name  || '',
            id:    el.id    || '',
            value: el.tagName === 'TEXTAREA' ? el.value : (el.value || ''),
        });
    });
    return {
        action: form ? form.action : window.location.href,
        method: form ? form.method.toUpperCase() : 'POST',
        csrf:   csrf,
        fields: fields,
    };
}"""


def scan_penjelasan_form(paket_id: str) -> dict:
    """Navigate ke form penjelasan dan scan field-nya."""
    from config import SPSE_BASE_URL
    url = f"{SPSE_BASE_URL}penjelasan/{paket_id}/pengadaan"

    page = spse_browser.halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")

    spse_browser._run(page.goto(url, wait_until="domcontentloaded", timeout=30000))
    return spse_browser._run(page.evaluate(_FORM_JS))


# ─────────────────────────────────────────────────────────────────────────────
# Submit Penjelasan
# ─────────────────────────────────────────────────────────────────────────────

def submit_penjelasan(paket_id: str, jenis: str, teks_override: str | None = None) -> dict:
    """
    Submit penjelasan ke SPSE.
    1. Buka form /penjelasan/[ID]/pengadaan
    2. Scan field textarea/input
    3. Build payload (teks template + hidden fields)
    4. POST via fetch API
    """
    form_info = scan_penjelasan_form(paket_id)

    teks = teks_override if teks_override else TEMPLATE.get(jenis, TEMPLATE["tender"])

    payload: dict = {}
    if form_info.get("csrf"):
        payload["_token"] = form_info["csrf"]

    # Sertakan hidden inputs
    page = spse_browser.halaman_aktif()
    if page:
        hidden = spse_browser._run(page.evaluate("""() =>
            Array.from(document.querySelectorAll('input[type="hidden"]'))
            .map(el => ({ name: el.name, value: el.value }))
        """))
        for h in hidden:
            if h["name"] and h["name"] != "_token":
                payload[h["name"]] = h["value"]

    # Isi textarea penjelasan — cari field yang paling mungkin
    textarea_name = None
    for f in form_info.get("fields", []):
        t = f.get("type", "")
        n = f.get("name", "").lower()
        if t == "textarea":
            textarea_name = f["name"]
            break
        # Fallback: text field dengan nama "penjelasan" / "isi" / "keterangan"
        if t == "text" and any(kw in n for kw in ["penjelasan", "isi", "keterangan", "uraian", "content"]):
            textarea_name = f["name"]
            break

    if textarea_name:
        payload[textarea_name] = teks
    else:
        # Last resort: nama field pertama yang bukan hidden/token
        for f in form_info.get("fields", []):
            if f["name"] and f["name"] != "_token" and f.get("type") not in ("hidden", "submit", "button"):
                payload[f["name"]] = teks
                textarea_name = f["name"]
                break

    result = spse_browser.submit_via_fetch(
        endpoint_url=form_info["action"],
        payload=payload,
        method=form_info.get("method", "POST"),
    )
    result["field_used"] = textarea_name
    result["paket_id"]   = paket_id
    result["jenis"]      = jenis
    result["fired_at"]   = datetime.now(TZ_WIB).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Persistent Jobs — simpan/load ke JSON
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
    paket_id:   str,
    nama_paket: str,
    jenis:      str,
    waktu_fire: datetime,
    teks_override: str | None = None,
) -> dict:
    """
    Daftarkan satu job penjelasan.
    Return: job dict yang ditambahkan.
    """
    jobs = _load_jobs()

    # Hindari duplikat paket_id + jenis
    jobs = [j for j in jobs if not (j["paket_id"] == paket_id and j["jenis"] == jenis)]

    job = {
        "paket_id":      paket_id,
        "nama_paket":    nama_paket,
        "jenis":         jenis,
        "waktu_fire":    waktu_fire.isoformat(),
        "teks_override": teks_override,
        "status":        "pending",   # pending | fired | gagal
        "result":        None,
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
# Background Scheduler
# ─────────────────────────────────────────────────────────────────────────────

_scheduler_thread: threading.Thread | None = None
_scheduler_stop   = threading.Event()
_log: list[str]   = []          # in-memory log (bisa dibaca dari UI)
_log_lock         = threading.Lock()


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
                jenis    = job["jenis"]
                _log_append(f"🚀 Firing: paket {paket_id} ({jenis}) ...")
                try:
                    result = submit_penjelasan(
                        paket_id      = paket_id,
                        jenis         = jenis,
                        teks_override = job.get("teks_override"),
                    )
                    ok = result.get("ok", False)
                    status = "fired" if ok else "gagal"
                    _log_append(
                        f"{'✅' if ok else '❌'} Paket {paket_id} ({jenis}): "
                        f"HTTP {result.get('status')} — {status}"
                    )
                    update_job_status(paket_id, jenis, status, result)
                except Exception as e:
                    _log_append(f"❌ Error paket {paket_id}: {e}")
                    update_job_status(paket_id, jenis, "gagal", {"error": str(e)})

                changed = True

        _scheduler_stop.wait(timeout=15)   # cek tiap 15 detik

    _log_append("Scheduler berhenti.")


def start_scheduler():
    global _scheduler_thread, _scheduler_stop
    if _scheduler_thread and _scheduler_thread.is_alive():
        return  # sudah jalan
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="PenjelasanScheduler")
    _scheduler_thread.start()


def stop_scheduler():
    _scheduler_stop.set()


def is_scheduler_running() -> bool:
    return bool(_scheduler_thread and _scheduler_thread.is_alive())
