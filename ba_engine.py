"""
BA Engine — Upload 5 Berita Acara di SPSE.

Flow per BA:
1. POST /berita_acara/{ID}/uploadbasubmit
   Payload: authenticityToken + ref + jenis + no + tanggal + info + file PDF (path+fileId via GCS upload)

5 Jenis BA:
  UPLOAD_BA_PENJELASAN, UPLOAD_BA_EVALUASI_PENAWARAN, UPLOAD_BA_HASIL_LELANG,
  PENGUMUMAN_PEMENANG_AKHIR, BERITA_ACARA_LAINNYA
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from kirimpesan_engine import upload_lampiran
import spse_browser

SPSE_BASE_URL = "https://spse.inaproc.id/tapinkab/"
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Origin": "https://spse.inaproc.id",
}

JENIS_BA = {
    "penjelasan":       "UPLOAD_BA_PENJELASAN",
    "evaluasi":         "UPLOAD_BA_EVALUASI_PENAWARAN",
    "hasil_pemilihan":  "UPLOAD_BA_HASIL_LELANG",
    "negosiasi":        "PENGUMUMAN_PEMENANG_AKHIR",
    "lainnya":          "BERITA_ACARA_LAINNYA",
}

JENIS_DISPLAY = {
    "penjelasan":       "BA Pemberian Penjelasan",
    "evaluasi":         "BA Evaluasi Penawaran",
    "hasil_pemilihan":  "BA Hasil Pemilihan",
    "negosiasi":        "BA Negosiasi",
    "lainnya":          "BA Lainnya",
}


# ─────────────────────────────────────────────────────────────────────
# Scrap token + ref dari halaman lelang
# ─────────────────────────────────────────────────────────────────────

def scrap_ba_context(paket_id: str) -> dict:
    """
    GET halaman /lelang/{ID}, scrap authenticityToken + ref URL.
    Token ada di form-batalpra atau form-upload-ba.
    """
    url = f"{SPSE_BASE_URL}lelang/{paket_id}"
    cookie_str = spse_browser.get_spse_cookies()
    resp = requests.get(url, headers={
        **HEADERS_BASE, "Cookie": cookie_str,
        "Content-Type": "application/x-www-form-urlencoded",
    }, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"GET halaman lelang gagal: {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Cari token di salah satu form
    token = ""
    for inp in soup.find_all("input", {"name": "authenticityToken"}):
        token = inp.get("value", "")
        if token:
            break

    if not token:
        raise RuntimeError("authenticityToken tidak ditemukan.")

    return {
        "token": token,
        "ref": url,
        "cookie": cookie_str,
    }


# ─────────────────────────────────────────────────────────────────────
# Upload file PDF ke SPSE (GCS flow)
# ─────────────────────────────────────────────────────────────────────

def _upload_file_pdf(paket_id: str, file_bytes: bytes, file_name: str) -> dict:
    """Upload file PDF via GCS flow (pakai fungsi yang sama dengan BA Reviu)."""
    cookie_str = spse_browser.get_spse_cookies()
    return upload_lampiran(paket_id, file_bytes, file_name, cookie_str)


# ─────────────────────────────────────────────────────────────────────
# Upload BA ke SPSE
# ─────────────────────────────────────────────────────────────────────

def upload_ba(
    paket_id: str,
    jenis_key: str,
    nomor_ba: str,
    tanggal_ba: str,
    file_bytes: bytes,
    file_name: str,
    info: str = "",
) -> dict:
    """
    Full flow:
    1. Scrap token + ref
    2. Upload file PDF via GCS
    3. POST ke /berita_acara/{ID}/uploadbasubmit
    """
    # 1. Context
    ctx = scrap_ba_context(paket_id)

    # 2. Upload file
    upload_result = _upload_file_pdf(paket_id, file_bytes, file_name)

    # 3. Build payload
    jenis_val = JENIS_BA.get(jenis_key, jenis_key)
    payload = {
        "authenticityToken": ctx["token"],
        "ref": ctx["ref"],
        "jenis": jenis_val,
        "no": nomor_ba.strip(),
        "tanggal": tanggal_ba.strip(),
        "info": info.strip() if info else "",
        "path": upload_result.get("path", ""),
        "fileId": upload_result.get("fileId", ""),
    }

    # 4. POST
    url = f"{SPSE_BASE_URL}berita_acara/{paket_id}/uploadbasubmit"
    resp = requests.post(url, data=payload, headers={
        **HEADERS_BASE,
        "Cookie": ctx["cookie"],
        "Referer": ctx["ref"],
    }, allow_redirects=False, timeout=30)

    ok = resp.status_code in (200, 302)
    location = resp.headers.get("Location", "")
    # Sukses: redirect ke halaman lelang
    sukses = ok and ("lelang" in location.lower() or resp.status_code == 302)

    return {
        "ok": sukses,
        "status": resp.status_code,
        "location": location,
        "jenis": jenis_val,
        "nomor": nomor_ba,
        "tanggal": tanggal_ba,
    }


# ─────────────────────────────────────────────────────────────────────
# Multi-BA upload
# ─────────────────────────────────────────────────────────────────────

def upload_multi_ba(paket_id: str, ba_list: list[dict]) -> list[dict]:
    """
    Upload beberapa BA sekaligus ke 1 paket.
    ba_list: [{"jenis": "penjelasan", "nomor": "...", "tanggal": "...", "file_bytes": ..., "file_name": "...", "info": "..."}, ...]
    Return: list of result dict
    """
    results = []
    for ba in ba_list:
        try:
            r = upload_ba(
                paket_id=paket_id,
                jenis_key=ba["jenis"],
                nomor_ba=ba["nomor"],
                tanggal_ba=ba["tanggal"],
                file_bytes=ba["file_bytes"],
                file_name=ba["file_name"],
                info=ba.get("info", ""),
            )
            results.append({"jenis": ba["jenis"], "ok": True, "detail": r})
        except Exception as e:
            results.append({"jenis": ba.get("jenis", "?"), "ok": False, "error": str(e)})
    return results

# "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?
# Cetak BA dari SPSE
# "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?

def cetak_ba(
    paket_id: str,
    jenis_key: str,
    nomor_ba: str,
    tanggal_ba: str
) -> dict:
    """
    Cetak (Download PDF) BA dari SPSE.
    Return: {"ok": bool, "pdf_bytes": bytes, "status": int, "error": str}
    """
    try:
        ctx = scrap_ba_context(paket_id)
        jenis_val = JENIS_BA.get(jenis_key, jenis_key)
        
        payload = {
            "authenticityToken": ctx["token"],
            "ref": ctx["ref"],
            "jenis": jenis_val,
            "no": nomor_ba.strip(),
            "tanggal": tanggal_ba.strip(),
        }
        
        url = f"{SPSE_BASE_URL}berita_acara/{paket_id}/cetak"
        resp = requests.post(url, data=payload, headers={
            **HEADERS_BASE,
            "Cookie": ctx["cookie"],
            "Referer": ctx["ref"],
        }, allow_redirects=False, timeout=30)
        
        if resp.status_code == 200 and 'pdf' in resp.headers.get('Content-Type', '').lower():
            return {"ok": True, "pdf_bytes": resp.content, "status": 200, "error": ""}
        else:
            return {"ok": False, "pdf_bytes": b"", "status": resp.status_code, "error": f"Invalid Content-Type: {resp.headers.get('Content-Type')}"}
            
    except Exception as e:
        return {"ok": False, "pdf_bytes": b"", "status": 0, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────
# Scrape nomor dokpil + auto-derive nomor BA
# ─────────────────────────────────────────────────────────────────────

def get_nomor_dokpil(paket_id: str) -> str:
    """
    GET halaman /dokumen/{paket_id}, scrape nomor dokpil pertama.
    Contoh hasil: "000.3.3/01/T/PJ.D_HatungunRT06/POKJA086/UKPBJ/2025"
    Return: string nomor atau "" jika tidak ditemukan.
    """
    url = f"{SPSE_BASE_URL}dokumen/{paket_id}"
    cookie_str = spse_browser.get_spse_cookies()
    resp = requests.get(url, headers={**HEADERS_BASE, "Cookie": cookie_str}, timeout=20)
    if resp.status_code != 200:
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # Cari <th> atau <td> yang berisi "Nomor" dan ambil nilai setelahnya
    for th in soup.find_all(["th", "td"]):
        if th.get_text(strip=True) == "Nomor":
            sibling = th.find_next_sibling("td")
            if sibling:
                nomor = sibling.get_text(strip=True)
                if nomor:
                    return nomor

    # Fallback: cari pola teks numerik dengan garis miring
    text = soup.get_text(" ")
    m = re.search(r'\d{3}\.\d+\.\d+/\d+/T/[^\s]+', text)
    if m:
        return m.group(0)

    return ""


def derive_nomor_ba(nomor_dokpil: str, urut: str) -> str:
    """
    Ganti nomor urut /XX/ pertama pada nomor_dokpil dengan urut baru.
    Contoh: derive_nomor_ba("000.3.3/01/T/PJ...", "02") → "000.3.3/02/T/PJ..."
    """
    if not nomor_dokpil:
        return ""
    return re.sub(r'/\d+/', f'/{urut}/', nomor_dokpil, count=1)


