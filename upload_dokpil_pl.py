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


def _dokpil_failure(stage: str, error: object, status: int | None = None) -> dict:
    """Return failure dengan kontrak konsisten untuk UI batch dan audit."""
    message = str(error or "Unknown error").strip()
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status is None:
        match = re.search(r"HTTP\s+(\d{3})", message, re.IGNORECASE)
        status = int(match.group(1)) if match else None
    return {
        "ok": False,
        "status": status,
        "stage": stage,
        "error": message,
        "body": (getattr(response, "text", "") or "")[:1500],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Generate Nomor Dokpil
# ─────────────────────────────────────────────────────────────────────────────

_NOMOR_DOKPIL_RE = re.compile(
    r"^000\.3\.3(?:/PLU)?/\d+/PL/PP-\d+/[^/?\s]+/[^/?\s]+/\d{4}$"
)


def validate_nomor_dokpil(nomor: str | None) -> tuple[bool, str]:
    """Validasi nomor Dokpil authoritative dari ``@ Master Data!C20``."""
    value = str(nomor or "").strip()
    if not value:
        return False, "@ Master Data!C20 kosong"
    if "?" in value:
        return False, "@ Master Data!C20 masih mengandung tanda '?'"
    if any(not part or part != part.strip() for part in value.split("/")):
        return False, "@ Master Data!C20 memiliki komponen kosong/spasi"
    if not _NOMOR_DOKPIL_RE.fullmatch(value):
        return False, "format @ Master Data!C20 tidak sesuai pola nomor Dokpil PL"
    return True, ""


def _extract_digit_paket(nama_paket: str) -> str:
    """Ekstrak NN dari akhir nama paket. 'Paket 1' -> '01', 'Paket 12' -> '12'."""
    # Cari semua angka di nama paket, ambil yang terakhir
    matches = re.findall(r"\d+", nama_paket or "")
    if matches:
        n = matches[-1]
        return n.zfill(2)
    return "01"


def _sisip_plu(nomor: str) -> str:
    """Sisip '/PLU' tepat setelah prefix '000.3.3' (paket ulang). Idempoten.
    000.3.3/01/PL/... -> 000.3.3/PLU/01/PL/..."""
    if not nomor or "/PLU/" in nomor:
        return nomor
    if nomor.startswith("000.3.3"):
        return "000.3.3/PLU" + nomor[7:]
    return nomor


def generate_nomor_dokpil(
    nama_paket: str,
    kode_unik: str,
    skpd_singkat: str,
    tahun: str | int | None = None,
    paket_ulang: bool = False,
    nomor_urut: str | int | None = None,
) -> str:
    """
    Pattern: 000.3.3/01/PL/PP-{NN}/{KodeUnik}/{SkpdSingkat}/{Tahun}
    Contoh:  000.3.3/01/PL/PP-01/KPP1/DPUPR/2026
    paket_ulang=True → sisip /PLU/ setelah 000.3.3.
    """
    # Nomor urut paket dari database adalah sumber utama. Ekstraksi dari
    # nama paket hanya fallback legacy; nama paket bisa tidak memuat nomor
    # folder dan menghasilkan PP-01 yang salah.
    if nomor_urut is not None and str(nomor_urut).strip():
        m_urut = re.search(r"\d+", str(nomor_urut))
        pp_nn = m_urut.group(0).zfill(2) if m_urut else _extract_digit_paket(nama_paket)
    else:
        pp_nn = _extract_digit_paket(nama_paket)
    if not kode_unik:
        kode_unik = "KodeUnik"
    if not skpd_singkat:
        skpd_singkat = "DPUPR"
    if not tahun:
        tahun = datetime.now().year
    nomor = f"000.3.3/01/PL/PP-{pp_nn}/{kode_unik}/{skpd_singkat}/{tahun}"
    return _sisip_plu(nomor) if paket_ulang else nomor


# ─────────────────────────────────────────────────────────────────────────────
# Step 1-4: Upload file ke GCS via signed URL
# ─────────────────────────────────────────────────────────────────────────────

def _get_signed_url(kode_paket: str, file_name: str, cookie: str) -> dict:
    """Ambil signed URL; endpoint paketnontender adalah flow produksi terbaru."""
    payload = {
        "input[uploadSignedUrlReq][0][contentType]": "application/pdf",
        "input[uploadSignedUrlReq][0][identifier]": "",
        "input[uploadSignedUrlReq][0][fileName]": file_name,
        "input[uploadSignedUrlReq][0][isPublic]": "false",
        "isArchieve": "true",
    }
    errors = []
    for endpoint in ("paketnontender", "dokumennontender", "nontender"):
        try:
            r = requests.post(
                f"{BASE}/{endpoint}/{kode_paket}/getSignedUrl",
                data=payload,
                headers={**HDRS, "Cookie": cookie},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            item = data["result"]["data"]
            return {
                "fileId": item["fileId"],
                "signedUrl": item["signedUrl"],
                "path": data.get("path", item.get("path", "")),
            }
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
    raise RuntimeError("; ".join(errors))


def _otorisasi_data_pl(kode_paket: str, cookie: str) -> tuple[bool, str]:
    """Grant ACL; nama endpoint berubah pada flow SPSE produksi terbaru."""
    errors = []
    for url, data in (
        (f"{BASE}/otorisasiDataPaketPlUpload?id={kode_paket}", None),
        (f"{BASE}/otorisasiDataPlSeleksi", {"id": kode_paket}),
    ):
        try:
            r = requests.get(url, headers={**HDRS, "Cookie": cookie}, timeout=15) if data is None else requests.post(
                url, data=data, headers={**HDRS, "Cookie": cookie}, timeout=15
            )
            if r.status_code in (200, 204, 302):
                return True, f"HTTP {r.status_code}"
            errors.append(f"HTTP {r.status_code}")
        except Exception as exc:
            errors.append(str(exc))
    return False, "; ".join(errors)


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

def _resolve_id_dokpil(kode_paket: str, cookie: str) -> str:
    """
    Scrape /nontender/{kode_paket}/edit cari href '/dokumennontender/{id_dokpil}/uploaddoknontender'.

    PROD pakai id_dokpil terpisah (≠ id_nontender ≠ kode_paket). Contoh paket 10860847000:
    kode_paket=10860847000, id_nontender=11724277000, id_dokpil=10771412000.
    """
    url = f"{BASE}/nontender/{kode_paket}/edit"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Cookie": cookie,
                                    "Referer": f"{BASE}/admin/pegawai"}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"GET /nontender/{kode_paket}/edit fail: HTTP {r.status_code}")
    m = re.search(r"/dokumennontender/(\d+)/uploaddoknontender", r.text)
    if not m:
        raise RuntimeError("Link uploaddoknontender tidak ditemukan di /edit.")
    return m.group(1)


def _scrap_edit_upload_context(kode_paket: str, cookie: str) -> dict:
    """Fallback flow baru: form Dokpil tidak lagi ditautkan pada halaman /edit."""
    url = f"{BASE}/nontender/{kode_paket}/edit"
    r = requests.get(url, headers={**HDRS, "Cookie": cookie, "Referer": f"{BASE}/admin/pegawai"}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"GET /nontender/{kode_paket}/edit fail: HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    csrf = ""
    for inp in soup.find_all("input", type="hidden"):
        if inp.get("name") == "authenticityToken" and inp.get("value"):
            csrf = inp.get("value")
            break
    if not csrf:
        raise RuntimeError("authenticityToken tidak ditemukan di /edit")
    return {
        "csrf": csrf,
        "ref": url,
        "kode_paket": kode_paket,
        "url_submit": f"{BASE}/dokumennontender/{kode_paket}/doknontendersubmit",
        "url_form": url,
    }


def _scrap_upload_form(id_dokpil: str, cookie: str) -> dict:
    """GET /dokumennontender/{id_dokpil}/uploaddoknontender → CSRF + ref + kode_paket di action."""
    url = f"{BASE}/dokumennontender/{id_dokpil}/uploaddoknontender"
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
    kode_paket = m.group(1) if m else id_dokpil

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
    kode_paket: str,
    file_bytes: bytes,
    file_name: str,
    nomor_dokpil: str,
    tgl_dokpil: datetime | str,
) -> dict:
    """
    Upload PDF Dokumen Pemilihan ke paket PL.

    Args:
        kode_paket   : kode paket (kolom 5 dt/paketpp). Engine resolve id_dokpil dari /nontender/{kode}/edit.
        file_bytes   : isi PDF
        file_name    : nama file
        nomor_dokpil : nomor dokpil (generate_nomor_dokpil)
        tgl_dokpil   : datetime atau string DD-MM-YYYY

    Return:
        {"ok": bool, "status": int, "fileId": str, "path": str, "nomor": str, "tanggal": str, ...}
    """
    nomor_ok, nomor_error = validate_nomor_dokpil(nomor_dokpil)
    if not nomor_ok:
        return _dokpil_failure("validasi nomor Dokpil", f"Nomor Dokpil tidak valid: {nomor_error}")

    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        return _dokpil_failure("session browser", "Cookie SPSE kosong.")

    # Step 0: flow legacy bila link masih tersedia; produksi baru memakai token /edit.
    try:
        id_dokpil = _resolve_id_dokpil(kode_paket, cookie)
        ctx = _scrap_upload_form(id_dokpil, cookie)
    except Exception as e:
        try:
            ctx = _scrap_edit_upload_context(kode_paket, cookie)
        except Exception as fallback_error:
            return _dokpil_failure(
                "resolve/upload context Dokpil",
                f"Flow legacy: {e}; flow terbaru: {fallback_error}",
            )

    # kode_paket override dari action (untuk safety)
    kode_paket = ctx["kode_paket"] or kode_paket

    # Step 1: getSignedUrl
    try:
        signed = _get_signed_url(kode_paket, file_name, cookie)
    except Exception as e:
        return _dokpil_failure("getSignedUrl", f"getSignedUrl fail: {e}")

    # Step 2: otorisasi ACL (opsional — endpoint mungkin tidak ada di semua LPSE)
    _otor_ok, _otor_dbg = _otorisasi_data_pl(kode_paket, cookie)
    # Tidak abort jika 404 — lanjut, GCS mungkin sudah public/pre-signed

    # Step 3: PUT ke GCS
    if not _put_to_gcs(signed["signedUrl"], file_bytes):
        return _dokpil_failure("PUT GCS", "PUT GCS fail")

    # Step 4: polling status
    if not _check_upload_status(signed["fileId"], cookie):
        return _dokpil_failure("uploadCheckStatus", "uploadCheckStatus fail")

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
