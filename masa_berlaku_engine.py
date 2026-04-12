"""
Masa Berlaku Penawaran Engine — set masa berlaku = 40 hari via pure requests.

Endpoint GET : /dokumen/[ID]/masaberlakupenawaran
Endpoint POST: /dokumen/[ID]/masaberlakupenawaransubmit
Payload      : authenticityToken + masaberlaku=40
"""

import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser

MASA_BERLAKU_HARI = 40


def _get_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}dokumen/{paket_id}/masaberlakupenawaran"


def _submit_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}dokumen/{paket_id}/masaberlakupenawaransubmit"


def scrap_token(paket_id: str, cookie_str: str) -> dict:
    """GET halaman masa berlaku, ambil authenticityToken + nilai saat ini."""
    resp = requests.get(
        _get_url(paket_id),
        headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
        timeout=15,
        allow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GET masa berlaku gagal: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    token_el = soup.find("input", {"name": "authenticityToken"})
    if not token_el:
        raise RuntimeError("authenticityToken tidak ditemukan di halaman masa berlaku")

    nilai_el = soup.find("input", {"name": "masaberlaku"})
    nilai_saat_ini = nilai_el.get("value", "") if nilai_el else ""

    return {
        "authenticityToken": token_el.get("value", ""),
        "masaberlaku_saat_ini": nilai_saat_ini,
    }


def submit_masa_berlaku(paket_id: str, hari: int = MASA_BERLAKU_HARI) -> dict:
    """
    Set masa berlaku penawaran ke `hari` hari via pure requests.
    Return: {"sukses": bool, "status_code": int, "pesan": str, "sebelumnya": str}
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
        "masaberlaku": str(hari),
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
        "pesan": f"Masa berlaku {hari} hari berhasil diset" if sukses else f"Gagal: HTTP {resp.status_code}",
        "sebelumnya": scraped["masaberlaku_saat_ini"],
    }
