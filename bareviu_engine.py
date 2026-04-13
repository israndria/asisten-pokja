"""
BA Reviu DPP Engine — Upload Berita Acara Hasil Reviu Dokumen Persiapan Pemilihan.

Endpoint GET : /lelang/[ID]/uploadbareviu
Endpoint POST: /lelang/[ID]/submitbareviu

Payload POST:
  authenticityToken : dari hidden input
  tgl_dok_ba        : tanggal BA format "DD-MM-YYYY"
  path              : path GCS (dari upload_lampiran)
  fileId            : file ID (dari upload_lampiran)
  simpan            : "simpan"

Upload file menggunakan flow GCS yang sama dengan kirimpesan_engine.upload_lampiran().
"""

import requests
from datetime import date
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser
from kirimpesan_engine import upload_lampiran


def _get_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}lelang/{paket_id}/uploadbareviu"


def _submit_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}lelang/{paket_id}/submitbareviu"


def scrap_token(paket_id: str, cookie_str: str) -> dict:
    """GET halaman uploadbareviu, ambil authenticityToken + info existing BA."""
    resp = requests.get(
        _get_url(paket_id),
        headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
        timeout=15,
        allow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GET uploadbareviu gagal: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    token_el = soup.find("input", {"name": "authenticityToken"})
    if not token_el:
        raise RuntimeError("authenticityToken tidak ditemukan di halaman uploadbareviu")

    # Tanggal default dari form (biasanya hari ini)
    tgl_el = soup.find("input", {"name": "tgl_dok_ba"})
    tgl_default = tgl_el.get("value", "") if tgl_el else date.today().strftime("%d-%m-%Y")

    # Cek apakah sudah ada BA yang terupload
    existing = []
    for item in soup.find_all("div", class_="list-group-item"):
        txt = item.get_text(strip=True)
        if txt and "Tidak ada" not in txt:
            existing.append(txt)

    return {
        "authenticityToken": token_el.get("value", ""),
        "tgl_default": tgl_default,
        "existing": existing,
    }


def get_ba_info(paket_id: str) -> dict:
    """Ambil info BA Reviu yang sudah ada (untuk preview di UI)."""
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung", "existing": []}
    try:
        info = scrap_token(paket_id, cookie_str)
        return {"sukses": True, **info}
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e), "existing": []}


def upload_ba_reviu(
    paket_id: str,
    file_bytes: bytes,
    file_name: str,
    tgl_dok_ba: str = "",
) -> dict:
    """
    Upload BA Reviu DPP ke SPSE.

    Args:
        paket_id   : ID paket tender
        file_bytes : bytes file PDF
        file_name  : nama file (harus .pdf)
        tgl_dok_ba : tanggal BA format "DD-MM-YYYY" (default: hari ini)

    Return:
        {"sukses": bool, "status_code": int, "pesan": str}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung atau cookie kosong"}

    try:
        scraped = scrap_token(paket_id, cookie_str)
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e)}

    if not tgl_dok_ba:
        tgl_dok_ba = scraped["tgl_default"] or date.today().strftime("%d-%m-%Y")

    # Upload file ke GCS
    up = upload_lampiran(paket_id, file_bytes, file_name, cookie_str)
    if not up["sukses"]:
        return {"sukses": False, "pesan": f"Upload file gagal: {up['pesan']}"}

    payload = {
        "authenticityToken": scraped["authenticityToken"],
        "tgl_dok_ba": tgl_dok_ba,
        "path": up["path"],
        "fileId": up["fileId"],
        "simpan": "simpan",
    }

    resp = requests.post(
        _submit_url(paket_id),
        data=payload,
        headers={
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": _get_url(paket_id),
        },
        timeout=15,
        allow_redirects=True,
    )

    # Sukses jika redirect ke /edit (bukan kembali ke /uploadbareviu dengan error)
    sukses = resp.status_code == 200 and "edit" in resp.url

    pesan_server = ""
    if not sukses:
        soup = BeautifulSoup(resp.text, "html.parser")
        for el in soup.find_all("div", class_=lambda c: c and "alert" in str(c)):
            txt = el.get_text(strip=True)
            if txt and "JavaScript" not in txt and len(txt) > 5:
                pesan_server = txt[:200]
                break

    return {
        "sukses": sukses,
        "status_code": resp.status_code,
        "pesan": "BA Reviu berhasil diupload" if sukses else (pesan_server or f"Gagal: HTTP {resp.status_code}"),
    }
