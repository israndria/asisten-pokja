"""
upload_dokpil_pl.py — Upload PDF Dokumen Pemilihan (Dokpil) ke SPSE PL.

Flow (S3 signed URL, dengan otorisasi ACL):
  1. POST /dokumennontender/{kode_paket}/getSignedUrl
  2. POST /otorisasiDataPlSeleksi  (id=kode_paket)
  3. PUT  {signedUrl}              (raw PDF bytes)
  4. POST /uploadCheckStatus       (input=fileId, poll)
  5. POST /dokumennontender/{kode_paket}/doknontendersubmit  (multipart)
     fields: authenticityToken, ref, nomorSDP, tglSDP (DD-MM-YYYY), path, fileId

Nomor Dokpil pattern: 000.3.3/01/PL/PP-NN/{KodeUnik}/{SkpdSingkat}/{Tahun}
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

import spse_browser
from config import SPSE_BASE_URL

BASE = SPSE_BASE_URL.rstrip("/")
HDRS = {
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://spse.inaproc.id",
}


# ─────────────────────────────────────────────────────────────────────────────
# Generate Nomor Dokpil
# ─────────────────────────────────────────────────────────────────────────────

def _extract_digit_paket(nama_paket: str) -> str:
    """Ekstrak NN dari akhir nama paket. 'Paket 1' -> '01', 'Paket 12' -> '12'."""
    # Cari semua angka di nama paket, ambil yang terakhir
    matches = re.findall(r"\d+", nama_paket or "")
    if matches:
        n = matches[-1]
        return n.zfill(2)
    return "01"


def generate_nomor_dokpil(
    nama_paket: str,
    kode_unik: str,
    skpd_singkat: str,
    tahun: str | int | None = None,
) -> str:
    """
    Pattern: 000.3.3/01/PL/PP-{NN}/{KodeUnik}/{SkpdSingkat}/{Tahun}
    Contoh:  000.3.3/01/PL/PP-01/KPP1/DPUPR/2026
    """
    pp_nn = _extract_digit_paket(nama_paket)
    if not kode_unik:
        kode_unik = "KodeUnik"
    if not skpd_singkat:
        skpd_singkat = "DPUPR"
    if not tahun:
        tahun = datetime.now().year
    return f"000.3.3/01/PL/PP-{pp_nn}/{kode_unik}/{skpd_singkat}/{tahun}"


# ─────────────────────────────────────────────────────────────────────────────
# Step 1-4: Upload file ke GCS via signed URL
# ─────────────────────────────────────────────────────────────────────────────

def _get_signed_url(kode_paket: str, file_name: str, cookie: str) -> dict:
    """POST /dokumennontender/{kode}/getSignedUrl → {fileId, signedUrl, path}."""
    payload = {
        "input[uploadSignedUrlReq][0][contentType]": "application/pdf",
        "input[uploadSignedUrlReq][0][identifier]": "",
        "input[uploadSignedUrlReq][0][fileName]": file_name,
        "input[uploadSignedUrlReq][0][isPublic]": "false",
        "isArchieve": "true",
    }
    r = requests.post(
        f"{BASE}/dokumennontender/{kode_paket}/getSignedUrl",
        data=payload,
        headers={**HDRS, "Cookie": cookie},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    return {
        "fileId":    data["result"]["data"]["fileId"],
        "signedUrl": data["result"]["data"]["signedUrl"],
        "path":      data.get("path", data["result"]["data"].get("path", "")),
    }


def _otorisasi_data_pl(kode_paket: str, cookie: str) -> bool:
    """POST /otorisasiDataPlSeleksi → grant ACL upload."""
    r = requests.post(
        f"{BASE}/otorisasiDataPlSeleksi",
        data={"id": kode_paket},
        headers={**HDRS, "Cookie": cookie},
        timeout=15,
    )
    return r.status_code == 200


def _put_to_gcs(signed_url: str, file_bytes: bytes) -> bool:
    """PUT file bytes ke GCS signed URL."""
    r = requests.put(
        signed_url,
        data=file_bytes,
        headers={"Content-Type": "multipart/formdata; charset=UTF-8"},
        timeout=120,
    )
    return r.status_code in (200, 201)


def _check_upload_status(file_id: str, cookie: str, max_retries: int = 8) -> bool:
    """POST /uploadCheckStatus → polling sampai UPLOAD_SUCCESS."""
    for _ in range(max_retries):
        try:
            r = requests.post(
                f"{BASE}/uploadCheckStatus",
                data={"input": file_id},
                headers={**HDRS, "Cookie": cookie},
                timeout=15,
            )
            d = r.json()
            if d.get("errors"):
                return False
            st = (d.get("data") or {}).get("status")
            if st == "UPLOAD_SUCCESS" or d.get("data") is None:
                return True
            if st == "UPLOAD_FAILED":
                return False
        except Exception:
            pass
        time.sleep(2)
    return True  # Asumsi sukses jika polling habis (server biasa konsisten)


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Submit form Dokpil
# ─────────────────────────────────────────────────────────────────────────────

def _scrap_upload_form(id_nontender: str, cookie: str) -> dict:
    """GET /dokumennontender/{id_nontender}/uploaddoknontender → CSRF + ref + kode_paket di action."""
    url = f"{BASE}/dokumennontender/{id_nontender}/uploaddoknontender"
    r = requests.get(url, headers={**HDRS, "Cookie": cookie, "Referer": f"{BASE}/admin/pegawai"}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"GET uploaddoknontender fail: HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", id="form-cetak-sdp") or soup.find("form")
    if not form:
        raise RuntimeError("Form upload Dokpil tidak ditemukan.")

    action = form.get("action") or ""
    # Action: /tapinkab/dokumennontender/{KODE_PAKET}/doknontendersubmit
    m = re.search(r"/dokumennontender/(\d+)/doknontendersubmit", action)
    kode_paket = m.group(1) if m else id_nontender

    csrf = ""
    ref = ""
    for inp in form.find_all("input", type="hidden"):
        n = inp.get("name", "")
        if n == "authenticityToken":
            csrf = inp.get("value", "")
        elif n == "ref":
            ref = inp.get("value", "")

    return {
        "csrf":       csrf,
        "ref":        ref,
        "kode_paket": kode_paket,
        "url_submit": f"{BASE}/dokumennontender/{kode_paket}/doknontendersubmit",
        "url_form":   url,
    }


def _submit_dokpil_form(
    ctx: dict,
    nomor_sdp: str,
    tgl_sdp: str,
    path: str,
    file_id: str,
    cookie: str,
) -> dict:
    """POST /doknontendersubmit (multipart)."""
    files = {
        "authenticityToken": (None, ctx["csrf"]),
        "ref":               (None, ctx["ref"]),
        "nomorSDP":          (None, nomor_sdp),
        "tglSDP":            (None, tgl_sdp),
        "path":              (None, path),
        "fileId":            (None, file_id),
    }
    r = requests.post(
        ctx["url_submit"],
        files=files,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
            "Origin": "https://spse.inaproc.id",
            "Referer": ctx["url_form"],
        },
        allow_redirects=False,
        timeout=60,
    )
    return {
        "ok":       r.status_code in (200, 302),
        "status":   r.status_code,
        "redirect": r.headers.get("Location", ""),
        "body":     (r.text or "")[:1500],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def upload_dokpil_pl(
    id_nontender: str,
    file_bytes: bytes,
    file_name: str,
    nomor_dokpil: str,
    tgl_dokpil: datetime | str,
) -> dict:
    """
    Upload PDF Dokumen Pemilihan ke paket PL.

    Args:
        id_nontender : ID internal paket (kolom 0 dt/paketpp). Dipakai untuk GET form upload.
        file_bytes   : isi PDF
        file_name    : nama file
        nomor_dokpil : nomor dokpil (generate_nomor_dokpil)
        tgl_dokpil   : datetime atau string DD-MM-YYYY

    Return:
        {"ok": bool, "status": int, "fileId": str, "path": str, "nomor": str, "tanggal": str, ...}
    """
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        return {"ok": False, "error": "Cookie SPSE kosong."}

    # Step 0: scrap form (dapatkan kode_paket dari action, CSRF, ref)
    try:
        ctx = _scrap_upload_form(id_nontender, cookie)
    except Exception as e:
        return {"ok": False, "error": f"Scrap form fail: {e}"}

    kode_paket = ctx["kode_paket"]

    # Step 1: getSignedUrl
    try:
        signed = _get_signed_url(kode_paket, file_name, cookie)
    except Exception as e:
        return {"ok": False, "error": f"getSignedUrl fail: {e}"}

    # Step 2: otorisasi ACL
    if not _otorisasi_data_pl(kode_paket, cookie):
        return {"ok": False, "error": "otorisasiDataPlSeleksi fail"}

    # Step 3: PUT ke GCS
    if not _put_to_gcs(signed["signedUrl"], file_bytes):
        return {"ok": False, "error": "PUT GCS fail"}

    # Step 4: polling status
    if not _check_upload_status(signed["fileId"], cookie):
        return {"ok": False, "error": "uploadCheckStatus fail"}

    # Step 5: submit form Dokpil
    if isinstance(tgl_dokpil, datetime):
        tgl_str = tgl_dokpil.strftime("%d-%m-%Y")
    else:
        tgl_str = str(tgl_dokpil)

    sub = _submit_dokpil_form(
        ctx,
        nomor_sdp=nomor_dokpil,
        tgl_sdp=tgl_str,
        path=signed["path"],
        file_id=signed["fileId"],
        cookie=cookie,
    )
    sub.update({
        "fileId":  signed["fileId"],
        "path":    signed["path"],
        "nomor":   nomor_dokpil,
        "tanggal": tgl_str,
    })
    return sub
