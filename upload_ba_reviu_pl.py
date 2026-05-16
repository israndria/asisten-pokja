"""
upload_ba_reviu_pl.py — Upload PDF BA Reviu DPP (Berita Acara Reviu Dokumen Persiapan Pemilihan) ke paket PL.

Flow (S3 signed URL, TANPA otorisasi — uploadFlowFormNoACL):
  1. POST /nontender/{kode_paket}/getSignedUrl
  2. PUT  {signedUrl}              (raw PDF bytes)
  3. POST /uploadCheckStatus       (input=fileId, poll)
  4. POST /nontender/{kode_paket}/submitbareviu  (multipart)
     fields: authenticityToken, flow=5, tgl_dok_ba (DD-MM-YYYY), path, fileId

Cancel: GET /nontender/{kode_paket}/bataluploadbareviu?versi=0
Download existing: GET /download/ba-reviu-dpp-pl?versi=0&id={kode_paket}
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
# Helpers (S3 signed URL flow, share dengan upload_dokpil_pl.py polanya)
# ─────────────────────────────────────────────────────────────────────────────

def _get_signed_url(kode_paket: str, file_name: str, cookie: str) -> dict:
    """POST /nontender/{kode}/getSignedUrl → {fileId, signedUrl, path}."""
    payload = {
        "input[uploadSignedUrlReq][0][contentType]": "application/pdf",
        "input[uploadSignedUrlReq][0][identifier]": "",
        "input[uploadSignedUrlReq][0][fileName]": file_name,
        "input[uploadSignedUrlReq][0][isPublic]": "false",
        "isArchieve": "true",
    }
    r = requests.post(
        f"{BASE}/nontender/{kode_paket}/getSignedUrl",
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


def _put_to_gcs(signed_url: str, file_bytes: bytes) -> bool:
    r = requests.put(
        signed_url,
        data=file_bytes,
        headers={"Content-Type": "multipart/formdata; charset=UTF-8"},
        timeout=120,
    )
    return r.status_code in (200, 201)


def _check_upload_status(file_id: str, cookie: str, max_retries: int = 8) -> bool:
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
    return True


def _scrap_upload_form(kode_paket: str, cookie: str) -> dict:
    """GET /nontender/{kode}/uploadbareviu → CSRF."""
    url = f"{BASE}/nontender/{kode_paket}/uploadbareviu"
    r = requests.get(url, headers={**HDRS, "Cookie": cookie, "Referer": f"{BASE}/admin/pegawai"}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"GET uploadbareviu fail: HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form")
    if not form:
        raise RuntimeError("Form upload BA Reviu tidak ditemukan.")

    csrf = ""
    csrf_inp = form.find("input", {"name": "authenticityToken"})
    if csrf_inp:
        csrf = csrf_inp.get("value", "")

    return {
        "csrf":       csrf,
        "url_submit": f"{BASE}/nontender/{kode_paket}/submitbareviu",
        "url_form":   url,
    }


def _submit_bareviu_form(
    ctx: dict,
    tgl_ba: str,
    path: str,
    file_id: str,
    cookie: str,
) -> dict:
    files = {
        "authenticityToken": (None, ctx["csrf"]),
        "flow":              (None, "5"),
        "tgl_dok_ba":        (None, tgl_ba),
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

def upload_ba_reviu_pl(
    kode_paket: str,
    file_bytes: bytes,
    file_name: str,
    tgl_ba: datetime | str | None = None,
) -> dict:
    """
    Upload PDF BA Reviu DPP ke paket PL.

    Args:
        kode_paket : kode paket (kolom 5 dt/paketpp). Endpoint pakai kode_paket.
        file_bytes : isi PDF
        file_name  : nama file
        tgl_ba     : datetime atau "DD-MM-YYYY". Default hari ini.

    Return:
        {"ok": bool, "status": int, "fileId": str, "path": str, "tanggal": str, ...}
    """
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        return {"ok": False, "error": "Cookie SPSE kosong."}

    try:
        ctx = _scrap_upload_form(kode_paket, cookie)
    except Exception as e:
        return {"ok": False, "error": f"Scrap form fail: {e}"}

    try:
        signed = _get_signed_url(kode_paket, file_name, cookie)
    except Exception as e:
        return {"ok": False, "error": f"getSignedUrl fail: {e}"}

    if not _put_to_gcs(signed["signedUrl"], file_bytes):
        return {"ok": False, "error": "PUT GCS fail"}

    if not _check_upload_status(signed["fileId"], cookie):
        return {"ok": False, "error": "uploadCheckStatus fail"}

    if tgl_ba is None:
        tgl_str = datetime.now().strftime("%d-%m-%Y")
    elif isinstance(tgl_ba, datetime):
        tgl_str = tgl_ba.strftime("%d-%m-%Y")
    else:
        tgl_str = str(tgl_ba)

    sub = _submit_bareviu_form(
        ctx,
        tgl_ba=tgl_str,
        path=signed["path"],
        file_id=signed["fileId"],
        cookie=cookie,
    )
    sub.update({
        "fileId":  signed["fileId"],
        "path":    signed["path"],
        "tanggal": tgl_str,
    })
    return sub


def batal_ba_reviu_pl(kode_paket: str, versi: int = 0) -> dict:
    """GET /nontender/{kode}/bataluploadbareviu?versi=N — batalkan upload BA Reviu."""
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        return {"ok": False, "error": "Cookie SPSE kosong."}

    r = requests.get(
        f"{BASE}/nontender/{kode_paket}/bataluploadbareviu",
        params={"versi": str(versi)},
        headers={"User-Agent": "Mozilla/5.0", "Cookie": cookie},
        allow_redirects=False,
        timeout=30,
    )
    return {
        "ok":       r.status_code in (200, 302),
        "status":   r.status_code,
        "redirect": r.headers.get("Location", ""),
    }
