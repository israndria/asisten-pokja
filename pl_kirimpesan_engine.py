"""
Kirim Pesan / Undangan Engine — Mode Pengadaan Langsung (Non-Tender).

Endpoint GET : /nontender/{kode}/kirimpesan
Endpoint POST: /nontender/{kode}/submitkirimpesan

Payload identik dengan mode Tender (/lelang/), hanya prefix berbeda.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser


DEFAULT_TEMPAT = (
    "Ruang Aula Rapat Lantai 2 Kantor UKPBJ Kabupaten Tapin, "
    "Jl. Datu Suban RT. 01, Kelurahan Rangda Malingkung, "
    "Kecamatan Tapin Utara, Rantau, Kabupaten Tapin. Kode Pos : 71111"
)
DEFAULT_DIBAWA = (
    "Dokumen Persiapan Pengadaan yang tidak terbatas pada :\n"
    "1. Spesifikasi Teknis 2. Dokumen HPS. 3. Rancangan Kontrak. 4. Dokumen Anggaran Belanja"
)
DEFAULT_HADIR = (
    "Pejabat Pembuat Komitmen (PPK), Tim Teknis PPK, "
    "dan Konsultan Perancana/Konsultan Perencanaan"
)


def _get_url(kode: str) -> str:
    return f"{SPSE_BASE_URL}nontender/{kode}/kirimpesan"


def _submit_url(kode: str) -> str:
    return f"{SPSE_BASE_URL}nontender/{kode}/submitkirimpesan"


def scrap_token_pl(kode: str, cookie_str: str) -> dict:
    """GET halaman kirimpesan PL, ambil authenticityToken + penerima + nama paket."""
    resp = requests.get(
        _get_url(kode),
        headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
        timeout=15,
        allow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GET kirimpesan gagal: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    token_el = soup.find("input", {"name": "authenticityToken"})
    if not token_el:
        raise RuntimeError("authenticityToken tidak ditemukan")

    # Penerima dari paragraf pertama inner-form
    penerima = ""
    inner = soup.find(class_="inner-form") or soup.find("div", class_="container")
    if inner:
        p_el = inner.find("p")
        if p_el:
            lines = [ln.strip() for ln in p_el.get_text("\n").split("\n") if ln.strip()]
            if len(lines) >= 2:
                penerima = lines[1]

    # Nama paket dari <b>
    nama_paket = ""
    for b in soup.find_all("b"):
        txt = b.get_text(strip=True)
        if len(txt) > 10 and txt != kode:
            nama_paket = txt
            break

    return {
        "authenticityToken": token_el.get("value", ""),
        "penerima": penerima,
        "nama_paket": nama_paket,
    }


def upload_lampiran_pl(kode: str, file_bytes: bytes, file_name: str, cookie_str: str) -> dict:
    """Upload lampiran PDF ke GCS via endpoint nontender."""
    base = f"{SPSE_BASE_URL}nontender/{kode}"
    headers = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": _get_url(kode),
    }

    try:
        r1 = requests.post(
            f"{base}/getSignedUrl",
            data={
                "input[uploadSignedUrlReq][0][contentType]": "application/pdf",
                "input[uploadSignedUrlReq][0][identifier]": "",
                "input[uploadSignedUrlReq][0][fileName]": file_name,
                "input[uploadSignedUrlReq][0][isPublic]": "false",
                "isArchieve": "true",
            },
            headers=headers,
            timeout=15,
        )
        r1.raise_for_status()
        data = r1.json()
        file_id = data["result"]["data"]["fileId"]
        signed_url = data["result"]["data"]["signedUrl"]
        path = data["path"]
    except Exception as e:
        return {"sukses": False, "path": "", "fileId": "", "pesan": f"getSignedUrl gagal: {e}"}

    try:
        r2 = requests.put(
            signed_url,
            data=file_bytes,
            headers={"Content-Type": "multipart/formdata; charset=UTF-8"},
            timeout=60,
        )
        r2.raise_for_status()
    except Exception as e:
        return {"sukses": False, "path": "", "fileId": "", "pesan": f"Upload GCS gagal: {e}"}

    for _ in range(5):
        try:
            r3 = requests.post(
                f"{SPSE_BASE_URL}uploadCheckStatus",
                data={"input": file_id},
                headers=headers,
                timeout=10,
            )
            status_data = r3.json()
            if status_data.get("errors"):
                return {"sukses": False, "path": "", "fileId": "", "pesan": "Upload check error"}
            st = (status_data.get("data") or {}).get("status", "UPLOAD_SUCCESS")
            if st == "UPLOAD_SUCCESS" or status_data.get("data") is None:
                break
            if st == "UPLOAD_FAILED":
                return {"sukses": False, "path": "", "fileId": "", "pesan": "Upload gagal di server"}
        except Exception:
            pass
        time.sleep(2)

    return {"sukses": True, "path": path, "fileId": file_id, "pesan": "Upload berhasil"}


def kirim_undangan_pl(
    kode: str,
    waktu: str,
    sampai: str,
    tempat: str,
    dibawa: str,
    hadir: str,
    is_online: bool = False,
    link_pembuktian: str = "",
    lampiran_bytes: bytes | None = None,
    lampiran_nama: str = "",
) -> dict:
    """
    Kirim undangan/pesan ke penyedia PL via pure requests.

    Args:
        kode            : kode_paket non-tender
        waktu           : waktu mulai format "DD-MM-YYYY HH:mm"
        sampai          : waktu selesai format "DD-MM-YYYY HH:mm"
        tempat          : lokasi undangan
        dibawa          : dokumen yang harus dibawa
        hadir           : yang harus hadir
        is_online       : True = Online, False = Offline
        link_pembuktian : URL pembuktian (wajib jika Online)
        lampiran_bytes  : bytes PDF lampiran (opsional)
        lampiran_nama   : nama file lampiran

    Returns:
        {"sukses": bool, "pesan": str, "penerima": str}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Cookie SPSE kosong — login PP dulu.", "penerima": ""}

    # Ambil token + info penerima
    try:
        scraped = scrap_token_pl(kode, cookie_str)
    except Exception as e:
        return {"sukses": False, "pesan": str(e), "penerima": ""}

    # Upload lampiran jika ada
    path = ""
    file_id = ""
    if lampiran_bytes and lampiran_nama:
        up = upload_lampiran_pl(kode, lampiran_bytes, lampiran_nama, cookie_str)
        if not up["sukses"]:
            return {"sukses": False, "pesan": up["pesan"], "penerima": scraped["penerima"]}
        path = up["path"]
        file_id = up["fileId"]

    # Submit
    payload = {
        "authenticityToken": scraped["authenticityToken"],
        "flow": "4",
        "waktu": waktu,
        "sampai": sampai,
        "tempat": tempat,
        "is_online": "true" if is_online else "false",
        "link_pembuktian": link_pembuktian if is_online else "",
        "dibawa": dibawa,
        "hadir": hadir,
        "path": path,
        "fileId": file_id,
    }

    try:
        resp = requests.post(
            _submit_url(kode),
            data=payload,
            headers={
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "Referer": _get_url(kode),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=20,
            allow_redirects=True,
        )
    except Exception as e:
        return {"sukses": False, "pesan": f"POST gagal: {e}", "penerima": scraped["penerima"]}

    # Sukses: redirect ke halaman lain (bukan kembali ke kirimpesan dengan error)
    final_url = resp.url
    if "kirimpesan" in final_url and "error" in resp.text.lower():
        soup = BeautifulSoup(resp.text, "html.parser")
        alert = soup.find(class_="alert")
        pesan_err = alert.get_text(strip=True) if alert else "Pengiriman gagal"
        return {"sukses": False, "pesan": pesan_err, "penerima": scraped["penerima"]}

    return {
        "sukses": True,
        "pesan": f"Undangan berhasil dikirim ke {scraped['penerima']}",
        "penerima": scraped["penerima"],
    }
