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

_TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
_RETRYABLE_GET_STATUS = _TRANSIENT_HTTP_STATUS | {404}


def _ba_failure(stage: str, error: object, status: int | None = None) -> dict:
    """Kontrak error konsisten untuk UI batch; jangan pernah jatuh menjadi '?'."""
    message = str(error or "Unknown error").strip()
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status is None:
        match = re.search(r"HTTP\s+(\d{3})", message, re.IGNORECASE)
        status = int(match.group(1)) if match else None
    body = (getattr(response, "text", "") or "")[:1500]
    return {
        "ok": False,
        "status": status,
        "stage": stage,
        "error": message,
        "body": body,
        "timeout": isinstance(error, requests.Timeout),
    }


def _get_with_retry(url: str, *, headers: dict, timeout=(10, 45), attempts: int = 2):
    """GET SPSE dengan retry singkat untuk timeout/HTTP transient intermiten."""
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code in _RETRYABLE_GET_STATUS and attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 3))
                continue
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 3))
    raise last_error


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
    errors = []
    for attempt in range(3):
        try:
            r = requests.post(
                f"{BASE}/nontender/{kode_paket}/getSignedUrl",
                data=payload,
                headers={**HDRS, "Cookie": cookie},
                timeout=(10, 30),
            )
            if r.status_code in _TRANSIENT_HTTP_STATUS and attempt < 2:
                time.sleep(min(2 ** attempt, 3))
                continue
            r.raise_for_status()
            data = r.json()
            item = data["result"]["data"]
            return {
                "fileId":    item["fileId"],
                "signedUrl": item["signedUrl"],
                "path":      data.get("path", item.get("path", "")),
            }
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc)[:300])
            if attempt < 2:
                time.sleep(min(2 ** attempt, 3))
    raise RuntimeError("; ".join(errors) or "respons getSignedUrl tidak valid")


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


def _scrap_upload_form(
    kode_paket: str,
    cookie: str,
    *,
    read_existing: bool = True,
) -> dict:
    """GET /nontender/{kode}/uploadbareviu → CSRF."""
    url = f"{BASE}/nontender/{kode_paket}/uploadbareviu"
    r = _get_with_retry(
        url,
        headers={**HDRS, "Cookie": cookie, "Referer": f"{BASE}/admin/pegawai"},
    )
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
    if not csrf:
        raise RuntimeError("authenticityToken form upload BA Reviu tidak ditemukan")

    # Endpoint upload hanya memuat form; daftar BA lama ada di halaman edit.
    # Ambil link resmi #hapusDokBa dari halaman paket yang sama. Hapus
    # descending agar indeks versi tidak bergeser.
    existing_versions = (
        _scrap_existing_ba_versions(kode_paket, cookie)
        if read_existing else []
    )

    return {
        "csrf":       csrf,
        "url_submit": f"{BASE}/nontender/{kode_paket}/submitbareviu",
        "url_form":   url,
        "existing_versions": sorted(set(existing_versions), reverse=True),
    }


def _scrap_existing_ba_versions(kode_paket: str, cookie: str) -> list[int]:
    """Baca semua versi BA Reviu dari halaman edit paket scoped."""
    url = f"{BASE}/nontender/{kode_paket}/edit"
    r = _get_with_retry(
        url,
        headers={
            **HDRS,
            "Cookie": cookie,
            "Referer": f"{BASE}/nontender/{kode_paket}/uploadbareviu",
        },
    )
    if r.status_code != 200:
        raise RuntimeError(f"GET edit paket untuk verifikasi BA gagal: HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    versions = []
    for link in soup.select("a#hapusDokBa[href]"):
        match = re.search(r"[?&]versi=(\d+)", link.get("href", ""))
        if match:
            versions.append(int(match.group(1)))
    return sorted(set(versions), reverse=True)


def _delete_existing_ba_reviu(kode_paket: str, versions: list[int], cookie: str) -> dict:
    """Hapus seluruh versi BA Reviu lama, aman terhadap pergeseran indeks."""
    results = []
    for versi in sorted({int(v) for v in versions}, reverse=True):
        r = None
        last_error = None
        for attempt in range(2):
            try:
                r = requests.get(
                    f"{BASE}/nontender/{kode_paket}/bataluploadbareviu",
                    params={"versi": str(versi)},
                    headers={
                        **HDRS,
                        "Cookie": cookie,
                        "Referer": f"{BASE}/nontender/{kode_paket}/edit",
                    },
                    allow_redirects=False,
                    timeout=(10, 45),
                )
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1)
        if r is None:
            results.append({"versi": versi, "status": 0, "ok": False, "error": str(last_error)[:240]})
            return {"ok": False, "results": results}
        ok = r.status_code in (200, 302)
        item = {
            "versi": versi,
            "status": r.status_code,
            "ok": ok,
            "body": (getattr(r, "text", "") or "")[:500],
            "redirect": getattr(r, "headers", {}).get("Location", ""),
        }
        if not ok:
            detail = " ".join(str(item.get(key) or "").strip() for key in ("body", "redirect"))
            item["error"] = (
                f"bataluploadbareviu mengembalikan HTTP {r.status_code}"
                + (f" — {detail[:300]}" if detail else "")
            )
        results.append(item)
        if not ok:
            return {"ok": False, "results": results}
    return {"ok": True, "results": results}


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
    try:
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
            timeout=(10, 60),
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": 0,
            "timeout": True,
            "stage": "submitbareviu",
            "error": f"Submit BA timeout/gagal: {str(exc)[:240]}",
        }
    result = {
        "ok":       r.status_code in (200, 302),
        "status":   r.status_code,
        "redirect": r.headers.get("Location", ""),
        "body":     (r.text or "")[:1500],
    }
    if not result["ok"]:
        detail = " ".join(
            str(result.get(key) or "").strip()
            for key in ("body", "redirect")
        )
        result["error"] = (
            f"submitbareviu mengembalikan HTTP {r.status_code}"
            + (f" — {detail[:500]}" if detail else "")
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def upload_ba_reviu_pl(
    kode_paket: str,
    file_bytes: bytes,
    file_name: str,
    tgl_ba: datetime | str | None = None,
    replace_existing: bool = True,
) -> dict:
    """
    Upload PDF BA Reviu DPP ke paket PL.

    Args:
        kode_paket : kode paket (kolom 5 dt/paketpp). Endpoint pakai kode_paket.
        file_bytes : isi PDF
        file_name  : nama file
        tgl_ba     : datetime atau "DD-MM-YYYY". Default hari ini.

    replace_existing : jika True, hapus seluruh versi BA lama sebelum submit.

    Return:
        {"ok": bool, "status": int, "fileId": str, "path": str, "tanggal": str, ...}
    """
    try:
        cookie = spse_browser.get_spse_cookies()
    except Exception as exc:
        return _ba_failure("session browser", exc)
    if not cookie:
        return _ba_failure("session browser", "Cookie SPSE kosong.")

    try:
        ctx = _scrap_upload_form(kode_paket, cookie)
    except Exception as e:
        return _ba_failure("scrap form", f"Scrap form fail: {e}")

    try:
        signed = _get_signed_url(kode_paket, file_name, cookie)
    except Exception as e:
        return _ba_failure("getSignedUrl", f"getSignedUrl fail: {e}")

    try:
        put_ok = _put_to_gcs(signed["signedUrl"], file_bytes)
    except Exception as exc:
        return _ba_failure("PUT GCS", exc)
    if not put_ok:
        return _ba_failure("PUT GCS", "PUT GCS fail")

    try:
        status_ok = _check_upload_status(signed["fileId"], cookie)
    except Exception as exc:
        return _ba_failure("uploadCheckStatus", exc)
    if not status_ok:
        return _ba_failure("uploadCheckStatus", "uploadCheckStatus fail")

    # Replacement policy untuk Tab 3: file baru menjadi satu-satunya BA Reviu.
    # File baru sudah aman di storage sebelum versi lama dihapus. Jika salah
    # satu penghapusan gagal, jangan submit dan laporkan kondisi parsial.
    old_versions = ctx.get("existing_versions", [])
    deleted_results = []
    if replace_existing and old_versions:
        try:
            deleted = _delete_existing_ba_reviu(kode_paket, old_versions, cookie)
        except Exception as exc:
            failure = _ba_failure("hapus BA lama", f"Penghapusan BA Reviu lama gagal: {exc}")
            failure["delete_results"] = deleted_results
            return failure
        if not deleted["ok"]:
            last_delete = (deleted.get("results") or [{}])[-1]
            failure = _ba_failure(
                "hapus BA lama",
                last_delete.get(
                    "error",
                    "Penghapusan BA Reviu lama gagal; file baru belum disubmit.",
                ),
                status=last_delete.get("status"),
            )
            failure["delete_results"] = deleted.get("results", [])
            return failure
        deleted_results = deleted.get("results", [])
        # Jangan meminta halaman /edit kedua di titik kritis ini. Pada SPSE,
        # endpoint itu kadang 404/timeout sesaat setelah cancel, padahal form
        # upload tetap tersedia. Ambil CSRF dari form upload langsung agar
        # file baru tidak tertinggal setelah BA lama berhasil dihapus.
        try:
            refreshed_ctx = _scrap_upload_form(kode_paket, cookie, read_existing=False)
        except Exception as e:
            # Token awal biasanya tetap valid; gunakan sebagai fallback agar
            # timeout/404 sesaat setelah cancel tidak meninggalkan paket tanpa BA.
            refreshed_ctx = {**ctx, "existing_versions": []}
            refreshed_ctx["refresh_warning"] = f"refresh form setelah delete gagal: {e}"
        ctx = refreshed_ctx

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
    if sub.get("timeout"):
        # POST bisa sudah diterima server sebelum koneksi timeout. Jangan
        # mengulang POST; rekonsiliasi state live terlebih dahulu.
        try:
            remaining = _scrap_existing_ba_versions(kode_paket, cookie)
        except Exception:
            remaining = None
        if remaining == [0]:
            sub.update({"ok": True, "verified_after_timeout": True, "status": 200})
            sub["message"] = "BA Reviu tersimpan; respons submit timeout tetapi state live terverifikasi."
    sub.update({
        "fileId":  signed["fileId"],
        "path":    signed["path"],
        "tanggal": tgl_str,
        "delete_results": deleted_results,
    })
    if ctx.get("refresh_warning"):
        sub["warning"] = ctx["refresh_warning"]
    if not sub.get("ok") and not sub.get("error"):
        detail = " ".join(str(sub.get(k) or "").strip() for k in ("body", "redirect"))
        sub["error"] = (
            f"Submit BA gagal: HTTP {sub.get('status', 0)}"
            + (f" — {detail[:240]}" if detail else "")
        )
    return sub


def _ba_result_is_retryable(result: object) -> bool:
    """Tentukan error jaringan/transient yang aman dicoba sebagai siklus baru."""
    if not isinstance(result, dict) or result.get("ok"):
        return False
    if result.get("timeout"):
        return True
    status = result.get("status")
    if status in (0, 404, 408, 429, 500, 502, 503, 504):
        return True
    if status not in (None, 0):
        return False
    stage = str(result.get("stage") or "").casefold()
    return stage in {
        "scrap form",
        "getsignedurl",
        "put gcs",
        "uploadcheckstatus",
        "hapus ba lama",
        "submitbareviu",
    }


def upload_ba_reviu_pl_with_retry(
    *,
    max_attempts: int = 2,
    retry_delay: float = 2.0,
    **kwargs,
) -> dict:
    """Jalankan ulang siklus replacement pada error transient secara bounded.

    Retry memanggil API publik dari awal agar versi BA lama dibaca ulang.
    Dengan demikian retry setelah timeout submit tidak mengirim POST yang sama
    secara buta dan tetap menghasilkan maksimal satu BA versi 0.
    """
    attempts = max(1, int(max_attempts))
    last = {"ok": False, "stage": "upload BA Reviu", "error": "tidak ada hasil"}
    for attempt in range(1, attempts + 1):
        try:
            result = upload_ba_reviu_pl(**kwargs)
        except Exception as exc:
            result = _ba_failure("upload BA Reviu", exc)
        if not isinstance(result, dict):
            result = _ba_failure("upload BA Reviu", f"hasil tidak valid: {result!r}")
        result = {**result, "attempts": attempt}
        last = result
        if result.get("ok") or attempt >= attempts or not _ba_result_is_retryable(result):
            return result
        if retry_delay > 0:
            time.sleep(retry_delay)
    return last


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
