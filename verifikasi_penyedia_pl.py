"""
Kirim Verifikasi Penyedia PL ke SPSE non-tender.
Endpoint hasil bedah CDP 2026-05-22 — lihat memory/spse-pl-verifikasi-endpoints.md

Prefix: /evaluasinontender/{id_nontender}/ (bukan /nontender/)
ID yang dipakai: id_nontender (kolom 0 dt/paketpp), bukan kode_paket.
"""

import re
import requests
from datetime import date, timedelta
from typing import Optional

from config import SPSE_BASE_URL

TEMPAT_DEFAULT = (
    "Kantor UKPBJ Kabupaten Tapin, Jl. Datu Suban RT. 01, "
    "Kelurahan Rangda Malingkung, Kecamatan Tapin Utara, Rantau, "
    "Kabupaten Tapin"
)

YANG_HARUS_HADIR_DEFAULT = (
    "1. Direksi yang namanya ada dalam akta pendirian/perubahan atau "
    "pihak yang sah menurut akta pendirian/perubahan; "
    "2. Penerima kuasa dari direksi yang nama penerima kuasanya tercantum "
    "dalam akta pendirian/perubahan; "
    "3. Pihak lain yang bukan direksi dapat menghadiri pembuktian kualifikasi "
    "selama berstatus sebagai tenaga kerja tetap (yang dibuktikan dengan "
    "bukti lapor/potong pajak PPh Pasal 21 Form 1721 atau Form 1721-A1) "
    "dan memperoleh kuasa dari Direksi yang namanya ada dalam akta "
    "pendirian/perubahan atau pihak yang sah menurut akta pendirian/perubahan; "
    "4. Kepala Cabang perusahaan yang diangkat oleh kantor pusat yang "
    "dibuktikan dengan dokumen otentik."
)

YANG_HARUS_DIBAWA_DEFAULT = (
    "Dokumen (asli dan copy) sebagaimana disampaikan dalam penawaran "
    "dan pada isian kualifikasi serta dokumen/data dukungnya"
)


def hitung_waktu_verifikasi(
    kode_nontender: str,
    fallback_tgl: Optional[date] = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Hitung waktu mulai dan selesai verifikasi dari GCal.
    Return: (start_dt, end_dt, warning_msg)
      start_dt / end_dt: format "DD-MM-YYYY HH:MM" atau None
      warning_msg: pesan jika fallback dipakai, None jika dari GCal
    """
    from gcal_helper import get_jadwal_klarifikasi_pl

    warning_msg = None
    jadwal = None
    try:
        jadwal = get_jadwal_klarifikasi_pl(kode_nontender)
    except Exception:
        pass

    if jadwal:
        start_date = jadwal["start_date"]
        end_date = jadwal["end_date"]
        # Clamp max 2 hari (selisih max 1 hari)
        max_end = start_date + timedelta(days=1)
        if end_date > max_end:
            end_date = max_end
    elif fallback_tgl:
        start_date = fallback_tgl
        end_date = fallback_tgl
        warning_msg = (
            "Jadwal klarifikasi belum di-sync ke GCal. "
            "Pakai fallback dari draft_paket_pl.tgl_negosiasi."
        )
    else:
        return None, None, "GCal miss dan tgl_negosiasi kosong — isi waktu manual."

    start_dt = f"{start_date:%d-%m-%Y} 09:00"
    end_dt = f"{end_date:%d-%m-%Y} 15:00"
    return start_dt, end_dt, warning_msg


def scrap_verifikasi_context(id_nontender: str, cookie_str: str) -> dict:
    """
    GET form verifikasi → scrape authenticityToken.
    Return: {"token": str} atau {"error": str}
    """
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/evaluasinontender/{id_nontender}/kirimundanganverifikasi"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_str,
    }
    try:
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        if r.status_code != 200:
            return {"error": f"GET form gagal: HTTP {r.status_code}"}
        m = re.search(r'name="authenticityToken"\s+value="([^"]+)"', r.text)
        if not m:
            return {"error": "authenticityToken tidak ditemukan di halaman form verifikasi"}
        return {"token": m.group(1)}
    except Exception as e:
        return {"error": str(e)}


def kirim_verifikasi(
    id_nontender: str,
    waktu_start: str,
    waktu_end: str,
    tempat: str = TEMPAT_DEFAULT,
    yang_harus_hadir: str = YANG_HARUS_HADIR_DEFAULT,
    yang_harus_dibawa: str = YANG_HARUS_DIBAWA_DEFAULT,
    cookie_str: Optional[str] = None,
) -> dict:
    """
    POST kirim undangan verifikasi penyedia PL ke SPSE.

    Args:
        id_nontender: kolom 0 dt/paketpp (bukan kode_paket)
        waktu_start: "DD-MM-YYYY HH:MM"
        waktu_end: "DD-MM-YYYY HH:MM"
        cookie_str: dari spse_browser.get_spse_cookies() — jika None, auto-fetch

    Return: {"ok": bool, "msg": str, "status_code": int}
    """
    import spse_browser

    if not cookie_str:
        cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"ok": False, "msg": "Cookie SPSE kosong — login dulu", "status_code": 0}

    # Scrape authenticityToken
    ctx = scrap_verifikasi_context(id_nontender, cookie_str)
    if "error" in ctx:
        return {"ok": False, "msg": ctx["error"], "status_code": 0}

    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/evaluasinontender/{id_nontender}/submitkirimundanganverifikasipl"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_str,
        "Referer": f"{base}/evaluasinontender/{id_nontender}/kirimundanganverifikasi",
    }

    # multipart/form-data — server TIDAK terima urlencoded
    files = {
        "authenticityToken": (None, ctx["token"]),
        "waktu":             (None, waktu_start),
        "sampai":            (None, waktu_end),
        "tempat":            (None, tempat),
        "is_online":         (None, "false"),
        "link_pembuktian":   (None, ""),
        "dibawa":            (None, yang_harus_dibawa),
        "hadir":             (None, yang_harus_hadir),
        "simpan":            (None, "simpan"),
    }

    try:
        r = requests.post(
            url,
            files=files,
            headers=headers,
            timeout=30,
            allow_redirects=True,
        )
        # Sukses: redirect kembali ke halaman form + ada alert sukses di HTML
        if "berhasil terkirim" in r.text.lower() or "berhasil" in r.text.lower():
            return {"ok": True, "msg": "Undangan verifikasi berhasil terkirim", "status_code": r.status_code}
        # Cari pesan error di HTML
        m = re.search(r'class="alert[^"]*"[^>]*>\s*<[^>]+>([^<]{5,200})', r.text)
        err_msg = m.group(1).strip() if m else f"HTTP {r.status_code}"
        return {"ok": False, "msg": err_msg, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "msg": str(e), "status_code": 0}
