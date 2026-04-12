"""
Kirim Pesan / Undangan Engine — via pure requests.

Endpoint GET : /lelang/[ID]/kirimpesan
Endpoint POST: /lelang/[ID]/submitkirimpesan

Payload:
  authenticityToken  : dari hidden input
  waktu              : format "DD/MM/YYYY HH:mm" (waktu mulai)
  sampai             : format "DD/MM/YYYY HH:mm" (waktu selesai)
  tempat             : string (lokasi undangan)
  is_online          : "false" (Offline) | "true" (Online)
  link_pembuktian    : URL (wajib jika Online, kosong jika Offline)
  dibawa             : string (dokumen yang harus dibawa)
  hadir              : string (yang harus hadir)
  path               : "" (kosong, opsional untuk lampiran)
  fileId             : "" (kosong, opsional untuk lampiran)

Response sukses: HTTP 302 redirect kembali ke /kirimpesan
"""

import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser


def _get_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}lelang/{paket_id}/kirimpesan"


def _submit_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}lelang/{paket_id}/submitkirimpesan"


def scrap_token(paket_id: str, cookie_str: str) -> dict:
    """GET halaman kirimpesan, ambil authenticityToken + info penerima."""
    resp = requests.get(
        _get_url(paket_id),
        headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
        timeout=15,
        allow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GET kirimpesan gagal: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    token_el = soup.find("input", {"name": "authenticityToken"})
    if not token_el:
        raise RuntimeError("authenticityToken tidak ditemukan di halaman kirimpesan")

    # Ambil nama penerima dari isi teks halaman
    penerima = ""
    inner = soup.find(class_="inner-form")
    if inner:
        p_el = inner.find("p")
        if p_el:
            lines = [ln.strip() for ln in p_el.get_text("\n").split("\n") if ln.strip()]
            # Baris ke-2 biasanya nama penerima (setelah "Kepada Yth.")
            if len(lines) >= 2:
                penerima = lines[1]

    # Ambil nama tender dari halaman
    nama_tender = ""
    for b in soup.find_all("b"):
        txt = b.get_text(strip=True)
        if len(txt) > 20 and txt != paket_id:
            nama_tender = txt
            break

    return {
        "authenticityToken": token_el.get("value", ""),
        "penerima": penerima,
        "nama_tender": nama_tender,
    }


def kirim_undangan(
    paket_id: str,
    waktu: str,
    sampai: str,
    tempat: str,
    dibawa: str,
    hadir: str,
    is_online: bool = False,
    link_pembuktian: str = "",
) -> dict:
    """
    Kirim undangan/pesan ke PPK via pure requests.

    Args:
        paket_id       : ID paket tender
        waktu          : waktu mulai format "DD/MM/YYYY HH:mm"
        sampai         : waktu selesai format "DD/MM/YYYY HH:mm"
        tempat         : lokasi undangan
        dibawa         : dokumen/hal yang harus dibawa
        hadir          : yang harus hadir
        is_online      : True jika Online, False jika Offline
        link_pembuktian: URL meeting (wajib jika is_online=True)

    Return:
        {"sukses": bool, "status_code": int, "pesan": str, "penerima": str}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung atau cookie kosong"}

    try:
        scraped = scrap_token(paket_id, cookie_str)
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e)}

    payload = {
        "authenticityToken": scraped["authenticityToken"],
        "waktu": waktu,
        "sampai": sampai,
        "tempat": tempat,
        "is_online": "true" if is_online else "false",
        "link_pembuktian": link_pembuktian if is_online else "",
        "dibawa": dibawa,
        "hadir": hadir,
        "path": "",
        "fileId": "",
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
        allow_redirects=False,
    )

    sukses = resp.status_code in (200, 302)
    return {
        "sukses": sukses,
        "status_code": resp.status_code,
        "pesan": "Undangan berhasil dikirim" if sukses else f"Gagal: HTTP {resp.status_code}",
        "penerima": scraped.get("penerima", ""),
        "nama_tender": scraped.get("nama_tender", ""),
    }


def preview_undangan(paket_id: str) -> dict:
    """Ambil info penerima dan nama tender tanpa submit."""
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung"}
    try:
        scraped = scrap_token(paket_id, cookie_str)
        return {"sukses": True, **scraped}
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e)}
