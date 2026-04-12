"""
Checklist Dokumen Penawaran Engine — via pure requests.

Endpoint GET : /dokumen/[ID]/checklist
Endpoint POST: /dokumen/[ID]/checklistsubmit

Struktur form (dari hasil inspect):
- syaratAdmin[N] : Administrasi
- syarat[N]      : Teknis
- syaratHarga[N] : Harga

Yang di-CHECK (sesuai kebiasaan pokja):
  Teknis:
    - syarat[2] : Personel manajerial
    - syarat[4] : RKK (Elemen SMKK + Pakta Komitmen)
  Harga:
    - syaratHarga[0] : Daftar Kuantitas dan Harga
    - syaratHarga[1] : Kewajaran harga <80% HPS

Yang di-SKIP (tidak di-check):
  Administrasi:
    - syaratAdmin[2] : KSO
  Teknis:
    - syarat[0] : Metode pelaksanaan usaha besar
    - syarat[1] : Peralatan utama
    - syarat[3] : Subkontrak
    - syarat[5] : TKDN
    - syarat[6] : Daftar barang impor

Yang LOCKED oleh sistem (disabled, tidak perlu dikirim):
  - syaratAdmin[0] : Masa Berlaku Penawaran
  - syaratAdmin[1] : Surat Penawaran
"""

import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser

# 5 item yang WAJIB di-check (hardcode sesuai kebiasaan pokja konstruksi usaha kecil)
# Dicocokkan dengan startswith/contains pada label checkbox
_AUTO_CHECK_KEYWORDS = [
    "daftar isian peralatan utama",
    "daftar isian personel manajerial",
    "rencana keselamatan konstruksi",
    "daftar kuantitas dan harga",
    "khusus apabila ada evaluasi kewajaran harga",
]


def _get_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}dokumen/{paket_id}/checklist"


def _submit_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}dokumen/{paket_id}/checklistsubmit"


def scrap_checklist(paket_id: str, cookie_str: str) -> dict:
    """
    GET halaman checklist, parse semua checkbox + hidden inputs.
    Return: {
        "authenticityToken": str,
        "checkboxes": [{"name", "value", "label", "checked", "disabled"}],
        "hidden_inputs": {name: value},
    }
    """
    resp = requests.get(
        _get_url(paket_id),
        headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
        timeout=15,
        allow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GET checklist gagal: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")

    token_el = soup.find("input", {"name": "authenticityToken"})
    if not token_el:
        raise RuntimeError("authenticityToken tidak ditemukan di halaman checklist")

    # Semua hidden inputs (kecuali authenticityToken)
    hidden_inputs = {}
    for el in soup.find_all("input", type="hidden"):
        name = el.get("name")
        if name and name != "authenticityToken":
            hidden_inputs[name] = el.get("value", "")

    # Semua checkboxes
    checkboxes = []
    for el in soup.find_all("input", type="checkbox"):
        row = el.find_parent("tr")
        label = row.get_text(separator=" ", strip=True) if row else ""
        checkboxes.append({
            "name": el.get("name", ""),
            "value": el.get("value", ""),
            "label": label,
            "checked": el.get("checked") is not None,
            "disabled": el.get("disabled") is not None,
        })

    return {
        "authenticityToken": token_el.get("value", ""),
        "checkboxes": checkboxes,
        "hidden_inputs": hidden_inputs,
    }


def klasifikasi_checkbox(checkboxes: list[dict]) -> dict:
    """
    Klasifikasikan setiap checkbox: AUTO_CHECK / SKIP / LOCKED.
    Return: {"auto_check": [...], "skip": [...], "locked": [...]}
    """
    auto_check = []
    skip = []
    locked = []

    for cb in checkboxes:
        if cb["disabled"]:
            locked.append(cb)
            continue
        label_lower = cb["label"].lower()
        if any(label_lower.startswith(kw) or kw in label_lower for kw in _AUTO_CHECK_KEYWORDS):
            auto_check.append(cb)
        else:
            skip.append(cb)

    return {"auto_check": auto_check, "skip": skip, "locked": locked}


def build_payload(scraped: dict, klasifikasi: dict) -> dict:
    """Build form-encoded payload untuk POST checklistsubmit."""
    payload = {"authenticityToken": scraped["authenticityToken"]}

    # Sertakan semua hidden inputs
    payload.update(scraped["hidden_inputs"])

    # Checkbox yang di-check: sertakan name=value
    for cb in klasifikasi["auto_check"]:
        payload[cb["name"]] = cb["value"]

    return payload


def submit_checklist(paket_id: str) -> dict:
    """
    Auto-fill checklist dokumen penawaran via pure requests.
    Return: {"sukses": bool, "status_code": int, "pesan": str, "detail": dict}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung atau cookie kosong"}

    try:
        scraped = scrap_checklist(paket_id, cookie_str)
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e)}

    klasifikasi = klasifikasi_checkbox(scraped["checkboxes"])
    payload = build_payload(scraped, klasifikasi)

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
        "pesan": "Checklist berhasil disubmit" if sukses else f"Gagal: HTTP {resp.status_code}",
        "detail": {
            "auto_check": [cb["label"][:80] for cb in klasifikasi["auto_check"]],
            "skip": [cb["label"][:80] for cb in klasifikasi["skip"]],
            "locked": [cb["label"][:80] for cb in klasifikasi["locked"]],
        },
    }


def scan_saja(paket_id: str) -> dict:
    """Scan + klasifikasi tanpa submit. Untuk preview di UI."""
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung"}

    try:
        scraped = scrap_checklist(paket_id, cookie_str)
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e)}

    klasifikasi = klasifikasi_checkbox(scraped["checkboxes"])
    return {"sukses": True, "scraped": scraped, "klasifikasi": klasifikasi}
