"""Status evaluasi dan undangan pembuktian kualifikasi Tender PK.

Semua endpoint di sini berasal dari halaman evaluasi peserta SPSE.
Tidak ada POST saat membaca status; POST hanya dipanggil dari aksi eksplisit UI.
"""

from __future__ import annotations

import re
from datetime import datetime, date
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import spse_browser
from config import SPSE_BASE_URL

_STAGES = ("A", "K", "T", "H")
_STAGE_ENDPOINTS = {
    "A": "checklist_admin",
    "K": "checklist_kualifikasi",
    "T": "checklist_teknis",
    "H": "checklist_harga",
}
_GCAL_EVALUASI_KEYWORD = "evaluasi administrasi, kualifikasi, teknis, dan harga"
_GCAL_PEMBUKTIAN_KEYWORD = "pembuktian kualifikasi"


def _headers(cookie: str, referer: str = "") -> dict:
    h = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"}
    if referer:
        h["Referer"] = referer
    return h


def _resolve_spse_action(base: str, action: str) -> str:
    """Resolve action form tanpa menggandakan prefix `/tapinkab`."""
    action = str(action or "").strip()
    if action.startswith(("http://", "https://")):
        return action
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if action.startswith("/tapinkab/"):
        return f"{origin}{action}"
    if action.startswith("/"):
        return f"{base}{action}"
    return f"{base}/{action}"


def _status_cell(cell) -> str:
    cls = " ".join(cell.get("class", []))
    icon = cell.find("i")
    icls = " ".join(icon.get("class", [])) if icon else ""
    if "fa-check" in icls or "success" in cls:
        return "lulus"
    if "fa-times" in icls or "danger" in cls:
        return "gagal"
    return "belum"


def fetch_paket_evaluasi_gcal(paket_rows: list[dict]) -> dict:
    """Kembalikan hanya paket yang punya event tahap evaluasi di GCal.

    Satu kali GET daftar event; pencocokan utama memakai kode tender pada
    deskripsi event (URL SPSE), bukan nama paket yang bisa berubah/terpotong.
    Read-only.
    """
    try:
        import gcal_helper
        service = gcal_helper._build_service()
        time_min = datetime(date.today().year - 1, 1, 1).isoformat() + "Z"
        time_max = datetime(date.today().year + 1, 12, 31).isoformat() + "Z"
        events = []
        page_token = None
        while True:
            resp = service.events().list(
                calendarId="primary", timeMin=time_min, timeMax=time_max,
                maxResults=2500, singleEvents=True, orderBy="startTime",
                pageToken=page_token,
            ).execute()
            events.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        eval_events = [
            e for e in events
            if _GCAL_EVALUASI_KEYWORD in str(e.get("summary", "")).lower()
        ]
        pembuktian_events = [
            e for e in events
            if _GCAL_PEMBUKTIAN_KEYWORD in str(e.get("summary", "")).lower()
        ]
        result = []
        today = date.today()
        for paket in paket_rows:
            kode = str(paket.get("kode") or paket.get("kode_tender") or "").strip()
            if not kode:
                continue
            matches = [
                e for e in eval_events
                if kode in str(e.get("description", ""))
                or kode in str(e.get("summary", ""))
            ]
            proof_matches = [
                e for e in pembuktian_events
                if kode in str(e.get("description", ""))
                or kode in str(e.get("summary", ""))
            ]
            # Tab hanya aktif pada window evaluasi + pembuktian kualifikasi.
            if not matches or not proof_matches:
                continue
            event = matches[-1]
            proof_event = proof_matches[-1]
            def _event_date_range(item):
                start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date") or ""
                end_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date") or ""
                try:
                    start_date = datetime.fromisoformat(start_raw[:10]).date()
                    end_date = datetime.fromisoformat(end_raw[:10]).date()
                    # GCal all-day end bersifat eksklusif.
                    if len(end_raw) == 10:
                        from datetime import timedelta
                        end_date -= timedelta(days=1)
                    return start_date, end_date
                except ValueError:
                    return None, None
            eval_start, eval_end = _event_date_range(event)
            proof_start, proof_end = _event_date_range(proof_event)
            # Paket lama yang evaluasinya sudah selesai tidak tampil lagi.
            # Pembuktian boleh hari ini atau setelah hari ini.
            if not eval_start or not eval_end or not (eval_start <= today <= eval_end):
                continue
            if not proof_start or not proof_end or proof_end < today:
                continue
            start = event.get("start", {})
            end = event.get("end", {})
            result.append({
                **paket,
                "tgl_evaluasi_gcal": (start.get("dateTime") or start.get("date") or "")[:10],
                "sampai_evaluasi_gcal": (end.get("dateTime") or end.get("date") or "")[:10],
                "tgl_pembuktian_gcal": (proof_event.get("start", {}).get("dateTime") or proof_event.get("start", {}).get("date") or "")[:10],
            })
        return {"ok": True, "paket": result, "total_event": len(eval_events), "pesan": f"{len(result)} paket dalam tahap evaluasi + pembuktian kualifikasi GCal"}
    except Exception as exc:
        return {"ok": False, "paket": [], "total_event": 0, "pesan": str(exc)}


def fetch_evaluasi_paket(kode_tender: str) -> dict:
    """Baca peserta + status A/K/T/H dari halaman ringkasan evaluasi."""
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        return {"ok": False, "peserta": [], "pesan": "Cookie SPSE kosong — login dulu."}
    url = f"{SPSE_BASE_URL.rstrip('/')}/evaluasi/{kode_tender}"
    try:
        r = requests.get(url, headers=_headers(cookie), timeout=20)
        if r.status_code != 200:
            return {"ok": False, "peserta": [], "pesan": f"GET evaluasi HTTP {r.status_code}"}
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.select("table.table-hover")
        if not tables:
            return {"ok": False, "peserta": [], "pesan": "Tabel hasil evaluasi tidak ditemukan."}
        rows = tables[-1].find_all("tr")[1:]
        result = []
        for row in rows:
            cells = row.find_all("td")
            link = row.find("a", href=re.compile(r"/evaluasi/\d+/detail"))
            if not link or len(cells) < 10:
                continue
            harga_text = cells[2].get_text(" ", strip=True)
            # Peserta terdaftar tetapi tidak mengirim penawaran muncul di
            # ringkasan sebagai "Tidak Ada Penawaran". Jangan tampilkan di
            # Tab 5 karena tidak punya dokumen untuk dievaluasi.
            if "tidak ada penawaran" in harga_text.lower():
                continue
            pid = str(link.get("value") or "").strip()
            if not pid:
                m = re.search(r"/evaluasi/(\d+)/detail", link.get("href", ""))
                pid = m.group(1) if m else ""
            result.append({
                "peserta_id": pid,
                "nama": link.get_text(" ", strip=True),
                "harga": harga_text,
                "status": {stage: _status_cell(cells[4 + i]) for i, stage in enumerate(_STAGES)},
                "undangan": None,
            })
        return {"ok": True, "peserta": result, "pesan": f"{len(result)} peserta mengirim penawaran"}
    except Exception as exc:
        return {"ok": False, "peserta": [], "pesan": str(exc)}


def _scrape_stage_form(html: str, stage: str) -> tuple[str, list[tuple[str, str]]] | None:
    soup = BeautifulSoup(html, "html.parser")
    endpoint = _STAGE_ENDPOINTS[stage]
    form = soup.find("form", action=lambda a: a and endpoint in a)
    if not form:
        return None
    fields: list[tuple[str, str]] = []
    for el in form.find_all(["input", "textarea", "select"]):
        name = el.get("name")
        if not name:
            continue
        typ = (el.get("type") or "").lower()
        if typ in {"submit", "button", "file"}:
            continue
        if typ == "checkbox":
            # Lulus = seluruh syarat checklist dicentang.
            value = el.get("value")
            if value is not None:
                fields.append((name, value))
            continue
        if typ == "radio":
            if name == "lulus":
                fields.append((name, "true"))
            elif el.has_attr("checked"):
                fields.append((name, el.get("value", "")))
            continue
        if el.name == "select":
            option = el.find("option", selected=True) or el.find("option")
            fields.append((name, option.get("value", "") if option else ""))
            continue
        fields.append((name, el.get("value", "") if el.name == "input" else el.get_text()))
    return str(form.get("action")), fields


def _detail_html(peserta_id: str, cookie: str) -> tuple[str, str]:
    url = f"{SPSE_BASE_URL.rstrip('/')}/evaluasi/{peserta_id}/detail"
    r = requests.get(url, headers=_headers(cookie, url), timeout=20)
    r.raise_for_status()
    return r.text, url


def evaluasi_lulus_otomatis(
    kode_tender: str,
    peserta_id: str,
    progress_cb: Callable[[str], None] | None = None,
) -> dict:
    """Submit A→K→T→H, re-fetching after each stage for SPSE gating."""
    def log(msg: str):
        if progress_cb:
            progress_cb(msg)

    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        return {"ok": False, "pesan": "Cookie SPSE kosong — login dulu."}
    for stage in _STAGES:
        current = fetch_evaluasi_paket(kode_tender)
        row = next((x for x in current.get("peserta", []) if x["peserta_id"] == str(peserta_id)), None)
        if row and row["status"].get(stage) == "lulus":
            log(f"  {stage}: sudah LULUS, skip")
            continue
        try:
            html, referer = _detail_html(str(peserta_id), cookie)
            scraped = _scrape_stage_form(html, stage)
            if not scraped:
                return {"ok": False, "pesan": f"Form tahap {stage} belum tersedia (SPSE gating atau tahap tidak aktif)."}
            action, fields = scraped
            token = next((v for n, v in fields if n == "authenticityToken"), "")
            if not token:
                return {"ok": False, "pesan": f"Token tahap {stage} tidak ditemukan."}
            if stage == "H" and not any(n == "lulus" for n, _ in fields):
                fields.append(("lulus", "true"))
            resp = requests.post(
                action if action.startswith("http") else f"{SPSE_BASE_URL.rstrip('/')}{action}",
                files=[(n, (None, v)) for n, v in fields],
                headers=_headers(cookie, referer),
                timeout=30,
                allow_redirects=True,
            )
            if resp.status_code not in (200, 302, 303):
                return {"ok": False, "pesan": f"Submit tahap {stage} HTTP {resp.status_code}."}
            verify = fetch_evaluasi_paket(kode_tender)
            verified = next((x for x in verify.get("peserta", []) if x["peserta_id"] == str(peserta_id)), None)
            if not verified or verified["status"].get(stage) != "lulus":
                return {"ok": False, "pesan": f"Submit {stage} selesai tetapi status SPSE belum LULUS."}
            log(f"  {stage}: LULUS terverifikasi")
        except Exception as exc:
            return {"ok": False, "pesan": f"Tahap {stage}: {exc}"}
    return {"ok": True, "pesan": "A/K/T/H LULUS terverifikasi."}


def kirim_undangan_pembuktian(
    peserta_id: str,
    waktu: str,
    sampai: str,
    tempat: str,
    dibawa: str,
    hadir: str,
    is_online: bool = False,
    link_pembuktian: str = "",
) -> dict:
    """Kirim undangan pembuktian jenis 8 setelah A/K/T/H LULUS.

    Di SPSE, jenis halaman ``18`` adalah Klarifikasi Administrasi,
    Kualifikasi, Teknis, dan Harga. Undangan Pembuktian Kualifikasi memakai
    jenis halaman ``8``.
    """
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        return {"ok": False, "pesan": "Cookie SPSE kosong — login dulu."}
    base = SPSE_BASE_URL.rstrip("/")
    form_url = f"{base}/kirim_pesan/{peserta_id}/8"
    try:
        r = requests.get(form_url, headers=_headers(cookie, f"{base}/evaluasi/{peserta_id}/detail"), timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form", action=re.compile(r"kirim_pesan"))
        token = form.find("input", {"name": "authenticityToken"}).get("value") if form else ""
        if not token:
            return {"ok": False, "pesan": "Token undangan tidak ditemukan."}
        action = form.get("action") if form else ""
        action = _resolve_spse_action(base, action)
        fields = {
            "authenticityToken": token,
            # Form SPSE memakai tipe pesan 2 = UNDANGAN; 8 adalah jenis
            # halaman Undangan Pembuktian Kualifikasi.
            "tipe_pesan": "2",
            "waktu": waktu,
            "sampai": sampai,
            "tempat": tempat,
            "is_online": "true" if is_online else "false",
            "link_pembuktian": link_pembuktian if is_online else "",
            "dibawa": dibawa,
            "hadir": hadir,
            "simpan": "Kirim",
        }
        resp = requests.post(
            action,
            params={"jenisUndangan": "8", "id": str(peserta_id)},
            files=[(n, (None, v)) for n, v in fields.items()],
            headers=_headers(cookie, form_url),
            timeout=30,
            allow_redirects=True,
        )
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True).lower()
        ok = resp.status_code in (200, 302, 303) and any(x in text for x in ("berhasil", "terkirim", "sukses"))
        return {"ok": ok, "pesan": "Undangan berhasil terkirim." if ok else f"HTTP {resp.status_code}; pesan SPSE tidak terdeteksi."}
    except Exception as exc:
        return {"ok": False, "pesan": str(exc)}
