"""
Dokumen Pemilihan Engine — Upload Dokumen Pemilihan di SPSE.

Flow:
1. POST file ke SPSE (via GCS/internal upload endpoint) -> dapat path & fileId
2. Ambil authenticityToken dari /dokumen/{paket_id}/uploaddoktender
3. POST ke /dokumen/{paket_id}/doktendersubmit dengan payload lengkap
"""

import requests
from bs4 import BeautifulSoup
import spse_browser
from config import SPSE_BASE_URL
from kirimpesan_engine import upload_lampiran

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Origin": "https://spse.inaproc.id",
    "X-Requested-With": "XMLHttpRequest",
}

def scrap_dokpil_context(paket_id: str) -> dict:
    """
    GET halaman edit tender, scrap authenticityToken.
    """
    url = f"{SPSE_BASE_URL}lelang/{paket_id}/edit"
    cookie_str = spse_browser.get_spse_cookies()
    
    resp = requests.get(url, headers={
        **HEADERS_BASE, 
        "Cookie": cookie_str,
    }, timeout=20)
    
    if resp.status_code != 200:
        raise RuntimeError(f"GET halaman edit tender gagal: {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Cari token di form
    token = ""
    for inp in soup.find_all("input", {"name": "authenticityToken"}):
        token = inp.get("value", "")
        if token:
            break

    if not token:
        raise RuntimeError("authenticityToken tidak ditemukan pada halaman edit tender.")

    return {
        "token": token,
        "ref": url,
        "cookie": cookie_str,
    }


def _upload_file_pdf(paket_id: str, file_bytes: bytes, file_name: str) -> dict:
    """Upload file PDF via upload lampiran (GCS flow)."""
    cookie_str = spse_browser.get_spse_cookies()
    return upload_lampiran(paket_id, file_bytes, file_name, cookie_str)


def upload_dokumen_pemilihan(
    paket_id: str,
    nomor_sdp: str,
    tanggal_sdp: str,
    file_bytes: bytes,
    file_name: str,
) -> dict:
    """
    Full flow upload Dokumen Pemilihan.
    """
    # 1. Context
    ctx = scrap_dokpil_context(paket_id)

    # 2. Upload file
    upload_result = _upload_file_pdf(paket_id, file_bytes, file_name)

    # 3. Build payload
    payload = {
        "authenticityToken": ctx["token"],
        "nomorSDP": nomor_sdp.strip(),
        "tglSDP": tanggal_sdp.strip(),
        "path": upload_result.get("path", ""),
        "fileId": upload_result.get("fileId", ""),
    }

    # 4. POST
    url = f"{SPSE_BASE_URL}dokumen/{paket_id}/doktendersubmit"
    resp = requests.post(url, data=payload, headers={
        **HEADERS_BASE,
        "Cookie": ctx["cookie"],
        "Referer": f"{SPSE_BASE_URL}dokumen/{paket_id}/uploaddoktender",
    }, allow_redirects=False, timeout=30)

    ok = resp.status_code in (200, 302)
    
    return {
        "ok": ok,
        "status": resp.status_code,
        "nomor": nomor_sdp,
        "tanggal": tanggal_sdp,
    }
