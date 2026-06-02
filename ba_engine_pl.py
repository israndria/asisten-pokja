"""
BA Engine PL (Nontender) — Upload Berita Acara untuk mode Pengadaan Langsung.

Endpoint mapping (hasil inspect 2026-05-21, paket latihan id=10000028000):

Controller: /beritacaranontender/{id_nontender}/...
  GET form    : /beritacaranontender/{id}/formba?jenis={JENIS}&aksi=upload
  POST submit : /beritacaranontender/{id}/uploadbasubmit
  POST cetak  : /beritacaranontender/{id}/cetak
  POST BA Lain: /beritacaranontender/{id}/uploadInformasiLainnya  (multipart/form-data LANGSUNG)

Token scrap dari: /nontender/{id}   (bukan dari formba - formba adalah partial/AJAX)

Upload PDF flow (sama dengan ba_engine.py tender):
  1. POST /nontender/{id}/getSignedUrl  -> GCS signedUrl + fileId + path
  2. PUT signedUrl (GCS)
  3. POST /uploadCheckStatus (polling)
  4. POST /beritacaranontender/{id}/uploadbasubmit (submit BA)

Jenis BA Nontender yang tersedia (dari btn-ba di halaman):
  UPLOAD_BA_EVALUASI_PENAWARAN  - BA Evaluasi Penawaran
  UPLOAD_BA_HASIL_LELANG        - BA Hasil Non Tender (BAHNT)
  UPLOAD_BA_PENJELASAN          - BA Penjelasan (jika ada tahap penjelasan)
  PENGUMUMAN_PEMENANG_AKHIR     - Pengumuman Pemenang (field tambahan: tempat)

BA Informasi Lainnya:
  Bukan via formba/uploadbasubmit.
  Upload file langsung ke /beritacaranontender/{id}/uploadInformasiLainnya (multipart).
  Flow GCS tetap berlaku (getSignedUrl -> GCS -> uploadInformasiLainnya).

CATATAN PERBEDAAN vs ba_engine.py (tender):
  - Controller: /beritacaranontender/ (bukan /berita_acara/)
  - Token scrap: dari /nontender/{id} (bukan /lelang/{id})
  - getSignedUrl: /nontender/{id}/getSignedUrl (tetap bisa, atau /beritacaranontender/{id}/getSignedUrl)
  - PENGUMUMAN_PEMENANG_AKHIR: ada field tambahan `tempat`
  - BERITA_ACARA_LAINNYA (tender) = TIDAK ADA di nontender
    -> Gantinya: uploadInformasiLainnya endpoint terpisah
"""

import re
import requests
from bs4 import BeautifulSoup
from kirimpesan_engine import upload_lampiran
import spse_browser
from config import SPSE_BASE_URL

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Origin": "https://spse.inaproc.id",
}

# Jenis BA nontender — nilai string yg dikirim ke server
JENIS_BA_PL = {
    "evaluasi":         "UPLOAD_BA_EVALUASI_PENAWARAN",
    "hasil":            "UPLOAD_BA_HASIL_LELANG",
    "penjelasan":       "UPLOAD_BA_PENJELASAN",
    "pengumuman":       "PENGUMUMAN_PEMENANG_AKHIR",
}

JENIS_DISPLAY_PL = {
    "evaluasi":         "BA Evaluasi Penawaran PL",
    "hasil":            "BA Hasil Non Tender (BAHNT)",
    "penjelasan":       "BA Penjelasan PL",
    "pengumuman":       "Pengumuman Pemenang Akhir PL",
}


# ─────────────────────────────────────────────────────────────────────
# Scrap token dari halaman nontender
# ─────────────────────────────────────────────────────────────────────

def scrap_ba_context_pl(
    id_nontender: str,
    jenis: str = "UPLOAD_BA_EVALUASI_PENAWARAN",
    aksi: str = "cetak",
) -> dict:
    """
    Scrap authenticityToken + ref dari halaman formba (partial form per-jenis).

    PENTING (hasil inspect CDP 2026-06-02, paket PROD 10860847000):
      - Token diambil dari GET /beritacaranontender/{id}/formba?jenis=...&aksi=...
        (BUKAN dari halaman utama /nontender/{id} — itu tidak punya form BA).
      - Header **Referer wajib** = halaman /nontender/{id}. Tanpa Referer → HTTP 500.

    Return: {token, ref, cookie, form_url}
      form_url dipakai sebagai Referer saat POST cetak/submit.
    """
    cookie_str = spse_browser.get_spse_cookies()
    halaman_ref = f"{SPSE_BASE_URL}nontender/{id_nontender}"
    form_url = (
        f"{SPSE_BASE_URL}beritacaranontender/{id_nontender}/formba"
        f"?jenis={jenis}&aksi={aksi}"
    )
    resp = requests.get(form_url, headers={
        **HEADERS_BASE, "Cookie": cookie_str,
        "Referer": halaman_ref,  # WAJIB — tanpa ini server balas 500
        "X-Requested-With": "XMLHttpRequest",
    }, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(
            f"GET formba BA gagal: {resp.status_code} "
            f"(jenis={jenis}, aksi={aksi})"
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    token = ""
    for inp in soup.find_all("input", {"name": "authenticityToken"}):
        token = inp.get("value", "")
        if token:
            break
    if not token:
        raise RuntimeError("authenticityToken tidak ditemukan di formba.")

    # ref dari hidden input form (fallback ke halaman nontender)
    ref_input = soup.find("input", {"name": "ref"})
    ref_val = (ref_input.get("value", "") if ref_input else "") or halaman_ref

    return {
        "token": token,
        "ref": ref_val,
        "cookie": cookie_str,
        "form_url": form_url,
    }


# ─────────────────────────────────────────────────────────────────────
# Upload PDF via GCS (sama dengan tender, pakai /nontender/{id}/getSignedUrl)
# ─────────────────────────────────────────────────────────────────────

def _upload_pdf_pl(id_nontender: str, file_bytes: bytes, file_name: str) -> dict:
    """Upload file PDF via GCS flow untuk PL. Pakai /nontender/{id}/getSignedUrl."""
    cookie_str = spse_browser.get_spse_cookies()
    # upload_lampiran dari kirimpesan_engine menggunakan /lelang/{id}/getSignedUrl
    # Kita perlu pakai /nontender/{id}/getSignedUrl — buat versi custom
    base = f"{SPSE_BASE_URL}nontender/{id_nontender}"
    ref_url = f"{SPSE_BASE_URL}nontender/{id_nontender}"
    headers = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": ref_url,
    }

    # Step 1: getSignedUrl
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

    # Step 2: PUT ke GCS
    try:
        r2 = requests.put(
            signed_url,
            data=file_bytes,
            headers={"Content-Type": "application/pdf"},
            timeout=60,
        )
        r2.raise_for_status()
    except Exception as e:
        return {"sukses": False, "path": "", "fileId": "", "pesan": f"Upload GCS gagal: {e}"}

    # Step 3: uploadCheckStatus (polling max 5x)
    import time as _time
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
        _time.sleep(2)

    return {"sukses": True, "path": path, "fileId": file_id, "pesan": "Upload berhasil"}


# ─────────────────────────────────────────────────────────────────────
# Upload BA PL ke SPSE
# ─────────────────────────────────────────────────────────────────────

def upload_ba_pl(
    id_nontender: str,
    jenis_key: str,
    nomor_ba: str,
    tanggal_ba: str,
    file_bytes: bytes,
    file_name: str,
    info: str = "",
    tempat: str = "",
) -> dict:
    """
    Full flow upload BA untuk Pengadaan Langsung (nontender):
    1. Scrap token dari /nontender/{id}
    2. Upload PDF via GCS (/nontender/{id}/getSignedUrl)
    3. POST ke /beritacaranontender/{id}/uploadbasubmit

    jenis_key: "evaluasi" | "hasil" | "penjelasan" | "pengumuman"
    tempat: wajib diisi untuk jenis "pengumuman" (PENGUMUMAN_PEMENANG_AKHIR)
    tanggal_ba: format "DD-MM-YYYY"
    """
    # 1. Context (token + ref) — formba aksi=upload per-jenis (Referer wajib)
    jenis_val = JENIS_BA_PL.get(jenis_key, jenis_key)
    ctx = scrap_ba_context_pl(id_nontender, jenis=jenis_val, aksi="upload")

    # 2. Upload file
    upload_result = _upload_pdf_pl(id_nontender, file_bytes, file_name)
    if not upload_result.get("sukses"):
        return {
            "ok": False,
            "error": f"Upload PDF gagal: {upload_result.get('pesan')}",
            "status": 0,
        }

    # 3. Build payload
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
    # Field tambahan untuk PENGUMUMAN_PEMENANG_AKHIR
    if jenis_val == "PENGUMUMAN_PEMENANG_AKHIR" and tempat:
        payload["tempat"] = tempat.strip()

    # 4. POST submit
    url = f"{SPSE_BASE_URL}beritacaranontender/{id_nontender}/uploadbasubmit"
    resp = requests.post(url, data=payload, headers={
        **HEADERS_BASE,
        "Cookie": ctx["cookie"],
        "Referer": ctx.get("form_url") or ctx["ref"],
    }, allow_redirects=False, timeout=30)

    ok = resp.status_code in (200, 302)
    location = resp.headers.get("Location", "")
    sukses = ok and ("nontender" in location.lower() or resp.status_code == 302)

    return {
        "ok": sukses,
        "status": resp.status_code,
        "location": location,
        "jenis": jenis_val,
        "nomor": nomor_ba,
        "tanggal": tanggal_ba,
    }


# ─────────────────────────────────────────────────────────────────────
# Cetak BA PL (download PDF dari SPSE)
# ─────────────────────────────────────────────────────────────────────

def cetak_ba_pl(
    id_nontender: str,
    jenis_key: str,
    nomor_ba: str,
    tanggal_ba: str,
    info: str = "",
) -> dict:
    """
    Download PDF BA dari SPSE (nontender).
    POST ke /beritacaranontender/{id}/cetak -> response langsung PDF.
    Return: {"ok": bool, "pdf_bytes": bytes, "status": int, "error": str}
    """
    try:
        jenis_val = JENIS_BA_PL.get(jenis_key, jenis_key)
        # Token + ref dari formba per-jenis (aksi=cetak), Referer wajib di PROD
        ctx = scrap_ba_context_pl(id_nontender, jenis=jenis_val, aksi="cetak")

        payload = {
            "authenticityToken": ctx["token"],
            "ref": ctx["ref"],
            "jenis": jenis_val,
            "no": nomor_ba.strip(),
            "tanggal": tanggal_ba.strip(),
            "info": info.strip() if info else "",
        }

        url = f"{SPSE_BASE_URL}beritacaranontender/{id_nontender}/cetak"
        resp = requests.post(url, data=payload, headers={
            **HEADERS_BASE,
            "Cookie": ctx["cookie"],
            "Referer": ctx.get("form_url") or ctx["ref"],
        }, allow_redirects=False, timeout=40)

        if resp.status_code == 200 and "pdf" in resp.headers.get("Content-Type", "").lower():
            return {"ok": True, "pdf_bytes": resp.content, "status": 200, "error": ""}
        else:
            return {
                "ok": False, "pdf_bytes": b"", "status": resp.status_code,
                "error": f"Content-Type: {resp.headers.get('Content-Type')}",
            }

    except Exception as e:
        return {"ok": False, "pdf_bytes": b"", "status": 0, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────
# Upload Informasi Lainnya PL (file attachment, bukan BA formal)
# ─────────────────────────────────────────────────────────────────────

def upload_informasi_lainnya_pl(
    id_nontender: str,
    file_bytes: bytes,
    file_name: str,
) -> dict:
    """
    Upload file "Informasi Lainnya" untuk paket PL.
    Endpoint: POST /beritacaranontender/{id}/uploadInformasiLainnya
    Flow: GCS signed URL -> PUT GCS -> POST uploadInformasiLainnya
    Return: {"ok": bool, "error": str}
    """
    # Upload ke GCS dulu
    upload_result = _upload_pdf_pl(id_nontender, file_bytes, file_name)
    if not upload_result.get("sukses"):
        return {"ok": False, "error": f"Upload GCS gagal: {upload_result.get('pesan')}"}

    ctx = scrap_ba_context_pl(id_nontender)
    url = f"{SPSE_BASE_URL}beritacaranontender/{id_nontender}/uploadInformasiLainnya"
    resp = requests.post(url, data={
        "authenticityToken": ctx["token"],
        "path": upload_result["path"],
        "fileId": upload_result["fileId"],
        "id": id_nontender,
    }, headers={
        **HEADERS_BASE,
        "Cookie": ctx["cookie"],
        "Referer": ctx["ref"],
        "X-Requested-With": "XMLHttpRequest",
    }, timeout=30)

    try:
        result = resp.json()
        ok = result.get("success", False)
        return {"ok": ok, "error": result.get("result", "") if not ok else ""}
    except Exception:
        return {"ok": resp.status_code == 200, "error": resp.text[:100]}


# ─────────────────────────────────────────────────────────────────────
# Multi-BA upload PL
# ─────────────────────────────────────────────────────────────────────

def upload_multi_ba_pl(id_nontender: str, ba_list: list[dict]) -> list[dict]:
    """
    Upload beberapa BA sekaligus ke 1 paket PL.
    ba_list: [{"jenis": "evaluasi", "nomor": "...", "tanggal": "...",
               "file_bytes": ..., "file_name": "...", "info": "", "tempat": ""}, ...]
    """
    results = []
    for ba in ba_list:
        try:
            r = upload_ba_pl(
                id_nontender=id_nontender,
                jenis_key=ba["jenis"],
                nomor_ba=ba["nomor"],
                tanggal_ba=ba["tanggal"],
                file_bytes=ba["file_bytes"],
                file_name=ba["file_name"],
                info=ba.get("info", ""),
                tempat=ba.get("tempat", ""),
            )
            results.append({"jenis": ba["jenis"], "ok": r.get("ok", False), "detail": r})
        except Exception as e:
            results.append({"jenis": ba.get("jenis", "?"), "ok": False, "error": str(e)})
    return results
