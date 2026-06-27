"""
ppk_upload_engine.py — Engine upload dokumen persiapan pengadaan untuk role PPK ke SPSE.
"""

import json
import re
import urllib.request
import requests
from bs4 import BeautifulSoup
import spse_browser
from config import SPSE_BASE_URL

BASE_URL = SPSE_BASE_URL.rstrip("/")

_SUBMIT_ENDPOINTS = {
    "kak":     "spekPpkSubmit",
    "kontrak": "uploadSskkSubmit",
    "uraian":  "uploadUraianSubmit",
    "lainnya": "lainnyaPpkSubmit",
}

_DELETE_ENDPOINTS = {
    "kak":     "hapusspekppk",
    "kontrak": "hapussskkattachment",
    "uraian":  "hapusuraianattachment",
    "lainnya": "hapuslainnyappk",
}

def _headers(referer: str = "") -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer or BASE_URL,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }

def get_cookies_from_browser() -> str:
    """Ambil cookie SPSE via spse_browser"""
    return spse_browser.get_spse_cookies()



def fetch_paket_ppk() -> list[dict]:
    """
    Ambil daftar paket non-tender PPK dari SPSE.
    Endpoint: GET /dt/paketppknontender (DataTables, tidak butuh token).
    row[0]=kode_paket, row[1]=nama_paket, row[2]=status/tahapan.
    """
    cookie_str = get_cookies_from_browser()
    if not cookie_str:
        return []

    import time as _time
    url = f"{BASE_URL}/dt/paketppknontender"
    params = {"draw": "1", "start": "0", "length": "200", "_": str(int(_time.time() * 1000))}
    headers = {**_headers(), "Cookie": cookie_str}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception:
        return []

    return [
        {"kode_paket": str(row[0]), "nama_paket": str(row[1]), "status": str(row[2])}
        for row in rows
    ]

def fetch_detail_paket(kode_paket: str) -> dict:
    """
    Scrape detail paket PPK dari edit?step=1 dan step=2.
    Return dict berisi: kode_rup, mak, nilai_pagu, nilai_hps, tahun_anggaran,
    sumber_dana, lokasi, jenis_kontrak, nama_ppk, instansi, satker.
    """
    cookie_str = get_cookies_from_browser()
    if not cookie_str:
        return {}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_str,
        "Referer": f"{BASE_URL}/paketnontender/{kode_paket}/edit?step=1",
    }
    result: dict = {}

    # ── Step 1 ────────────────────────────────────────────────────────────────
    try:
        r1 = requests.get(f"{BASE_URL}/paketnontender/{kode_paket}/edit?step=1", headers=headers, timeout=15)
        soup1 = BeautifulSoup(r1.text, "html.parser")

        # Tabel RUP (kolom: kode_rup, nama_paket_rup, sumber_dana)
        for tbl in soup1.find_all("table"):
            rows = tbl.find_all("tr")
            for tr in rows:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) >= 2 and re.match(r"^\d{8,}$", cells[0]):
                    result["kode_rup"] = cells[0]
                    break

        # Tabel Anggaran (kolom: tahun, sumber_dana, kode_rekening, nilai_pagu, nama_ppk)
        tbl_rows_all = []
        for tbl in soup1.find_all("table"):
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
                tbl_rows_all.append(cells)

        for cells in tbl_rows_all:
            if len(cells) >= 3 and re.match(r"^\d{4}$", cells[0]):  # tahun anggaran
                result["tahun_anggaran"] = cells[0]
                if len(cells) > 1: result["sumber_dana"] = cells[1]
                if len(cells) > 2: result["mak"] = cells[2].rstrip(".")
                if len(cells) > 3:
                    # "Rp. 44.950.000,00" → hapus titik ribuan, ambil sebelum koma
                    raw = cells[3].replace("Rp.", "").replace("Rp", "").strip()
                    raw = raw.replace(".", "").split(",")[0]
                    if raw.isdigit(): result["nilai_pagu"] = int(raw)
                if len(cells) > 4: result["nama_ppk"] = cells[4]
                break

        # K/L/PD (Instansi) & Satker
        for label in soup1.find_all(["label", "th", "td"]):
            txt = label.get_text(strip=True)
            if "K/L/PD" in txt or "Instansi" in txt:
                sib = label.find_next_sibling()
                if sib: result["instansi"] = sib.get_text(strip=True)
            if "Satuan Kerja" in txt:
                sib = label.find_next_sibling()
                if sib: result["satker"] = sib.get_text(strip=True)

        # Lokasi: input textlokasi
        inp_lok = soup1.find("input", {"id": "textlokasi"})
        if inp_lok:
            result["lokasi"] = inp_lok.get("value", "")
        sel_kab = soup1.find("select", {"id": "kabupaten"})
        if sel_kab:
            sel_opt = sel_kab.find("option", {"selected": True})
            if sel_opt:
                kab_txt = sel_opt.get_text(strip=True)
                lok = result.get("lokasi", "")
                result["lokasi"] = f"{kab_txt}, {lok}".strip(", ") if lok else kab_txt

    except Exception as e:
        result["_error_step1"] = str(e)

    # ── Step 2: nilai HPS + jenis kontrak ─────────────────────────────────────
    try:
        r2 = requests.get(f"{BASE_URL}/paketnontender/{kode_paket}/edit?step=2", headers=headers, timeout=15)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        # Nilai HPS dari tabel row "Nilai HPS"
        for tr in soup2.find_all("tr"):
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
            if cells and "Nilai HPS" in cells[0] and len(cells) > 1:
                raw = cells[1].replace("Rp.", "").replace("Rp", "").strip()
                raw = raw.split()[0].replace(".", "").split(",")[0]
                if raw.isdigit(): result["nilai_hps"] = int(raw)
                break

        # Jenis kontrak
        sel_k = soup2.find("select", {"name": "kontrak_pembayaran"})
        if sel_k:
            opt = sel_k.find("option", {"selected": True})
            if opt: result["jenis_kontrak"] = opt.get_text(strip=True)

    except Exception as e:
        result["_error_step2"] = str(e)

    return result


def upload_dokumen(
    kode_paket: str,
    jenis: str,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    cookies: dict = None,
    log_fn=None
) -> dict:
    """
    5 langkah upload dokumen PPK ke SPSE:
    1. GET /otorisasiDataPaketPlUpload?id={kode_paket}
    2. POST /getSignedUrl
    3. PUT {signedUrl}
    4. POST /uploadCheckStatus
    5. POST /dokumennontender/{kode_paket}/{submit_endpoint}
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    cookie_str = get_cookies_from_browser()
    if not cookie_str:
        return {"ok": False, "error": "Cookie SPSE tidak ditemukan. Pastikan browser terhubung dan login."}

    headers = {**_headers(), "Cookie": cookie_str}

    # Step 1: Otorisasi
    try:
        _log("Langkah 1: Memeriksa otorisasi paket...")
        auth_url = f"{BASE_URL}/otorisasiDataPaketPlUpload?id={kode_paket}"
        r1 = requests.get(auth_url, headers=headers, timeout=15)
        _log(f"Status otorisasi: {r1.status_code}")
    except Exception as e:
        return {"ok": False, "error": f"Langkah 1 otorisasi gagal: {e}"}

    # Step 2: getSignedUrl
    try:
        _log("Langkah 2: Meminta Signed URL upload...")
        url_sig = f"{BASE_URL}/getSignedUrl"

        # Format payload JSON
        payload = {
            "input": {
                "uploadSignedUrlReq": [{
                    "contentType": mime_type,
                    "identifier": "",
                    "fileName": file_name,
                    "isPublic": False
                }]
            },
            "isArchieve": True
        }

        headers_json = {**headers, "Content-Type": "application/json"}
        r2 = requests.post(url_sig, json=payload, headers=headers_json, timeout=15)
        r2.raise_for_status()

        res_data = r2.json()
        result_inner = res_data.get("result", {}).get("data", {})
        file_id = result_inner.get("fileId")
        signed_url = result_inner.get("signedUrl")
        path = res_data.get("path")

        if not signed_url or not file_id or not path:
            return {"ok": False, "error": f"Signed URL data tidak lengkap: {res_data}"}

        _log("Signed URL berhasil diperoleh.")
    except Exception as e:
        return {"ok": False, "error": f"Langkah 2 (getSignedUrl) gagal: {e}"}

    # Step 3: PUT ke GCS/S3
    try:
        _log("Langkah 3: Mengunggah file ke storage...")
        r3 = requests.put(
            signed_url,
            data=file_bytes,
            headers={"Content-Type": mime_type},
            timeout=60
        )
        r3.raise_for_status()
        _log("File berhasil diunggah.")
    except Exception as e:
        return {"ok": False, "error": f"Langkah 3 (upload storage) gagal: {e}"}

    # Step 4: Check Status
    try:
        _log("Langkah 4: Memverifikasi status upload...")
        status_url = f"{BASE_URL}/uploadCheckStatus"

        import time as _time
        for attempt in range(5):
            r4 = requests.post(
                status_url,
                data={"input": file_id},
                headers=headers,
                timeout=10
            )
            status_data = r4.json()
            if status_data.get("errors"):
                return {"ok": False, "error": f"Verifikasi upload error: {status_data.get('errors')}"}

            st = (status_data.get("data") or {}).get("status", "UPLOAD_SUCCESS")
            if st == "UPLOAD_SUCCESS" or status_data.get("data") is None:
                break
            if st == "UPLOAD_FAILED":
                return {"ok": False, "error": "Upload dinyatakan gagal oleh server."}
            _time.sleep(2)
        _log("Verifikasi selesai.")
    except Exception as e:
        return {"ok": False, "error": f"Langkah 4 (uploadCheckStatus) gagal: {e}"}

    # Step 5: Submit ke DB SPSE
    try:
        _log("Langkah 5: Menyimpan dokumen ke SPSE...")
        sub_endpoint = _SUBMIT_ENDPOINTS.get(jenis)
        if not sub_endpoint:
            return {"ok": False, "error": f"Jenis dokumen '{jenis}' tidak dikenal."}

        submit_url = f"{BASE_URL}/dokumennontender/{kode_paket}/{sub_endpoint}"

        submit_payload = {
            "id": int(kode_paket),
            "path": path,
            "fileId": file_id
        }

        r5 = requests.post(submit_url, json=submit_payload, headers={**headers, "Content-Type": "application/json"}, timeout=15)
        r5.raise_for_status()
        _log("Dokumen berhasil disimpan ke SPSE!")
        return {"ok": True, "path": path, "fileId": file_id}
    except Exception as e:
        return {"ok": False, "error": f"Langkah 5 (submit) gagal: {e}"}

def list_dokumen(kode_paket: str, jenis: str, cookies: dict = None) -> list[dict]:
    """
    Mengambil daftar dokumen persiapan pengadaan terunggah.
    """
    cookie_str = get_cookies_from_browser()
    if not cookie_str:
        return []

    # Map list endpoints
    list_endpoints = {
        "kak": "spekppk",
        "kontrak": "docsskk",
        "uraian": "uraianppk",
        "lainnya": "lainnyappk",
    }

    endpoint = list_endpoints.get(jenis)
    if not endpoint:
        return []

    url = f"{BASE_URL}/dokumennontender/{kode_paket}/{endpoint}"
    headers = {**_headers(), "Cookie": cookie_str}

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 404:
            # Kembalikan list kosong jika endpoint 404 (misal belum di-discover)
            return []
        r.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    tbl = soup.find("table")
    if not tbl:
        return []

    hasil = []
    # SPSE standard table rows
    for tr in tbl.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        a = tds[0].find("a")
        if not a:
            continue

        nama_file = a.get_text(strip=True)
        url_dl = a.get("href", "")
        if url_dl.startswith("/"):
            url_dl = f"https://spse.inaproc.id{url_dl}"

        # Parse version dari link hapus jika ada, atau default ke 0
        versi = 0
        btn_hapus = tr.find("button", onclick=True)
        if btn_hapus:
            onclick_text = btn_hapus.get("onclick", "")
            match = re.search(r"\d+", onclick_text)
            if match:
                versi = int(match.group())
        else:
            # Cari dari input / action parameter
            for inp in tr.find_all("input", {"name": "versi"}):
                val = inp.get("value", "")
                if val.isdigit():
                    versi = int(val)
                    break

        hasil.append({
            "nama_file": nama_file,
            "url_dl": url_dl,
            "versi": versi
        })

    return hasil

def hapus_dokumen(kode_paket: str, jenis: str, versi: int, cookies: dict = None) -> bool:
    """
    Menghapus dokumen dari SPSE
    """
    cookie_str = get_cookies_from_browser()
    if not cookie_str:
        return False

    del_endpoint = _DELETE_ENDPOINTS.get(jenis)
    if not del_endpoint:
        return False

    url = f"{BASE_URL}/dokumennontender/{kode_paket}/{del_endpoint}"
    headers = {**_headers(), "Cookie": cookie_str}

    try:
        # Kirim versi file yang akan dihapus
        r = requests.post(url, data={"versi": versi}, headers=headers, timeout=15)
        return r.status_code in (200, 302)
    except Exception:
        return False

PPK_PL_BASE = r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Dinas Perdagangan\1 PERENCANAAN PENGADAAN\Dokumen Upload PPK PL"

FILE_PREFIX_MAP = {
    "1.":  "kak",
    "2.":  "uraian",
    "5.":  "kontrak",
    "11.": "lainnya",
}

def scan_folder(folder_path: str) -> list[dict]:
    """
    Scan folder → return list file yang akan diupload.
    [{"path": str, "nama": str, "jenis": str, "mime": str}]
    Skip file yang prefixnya tidak ada di FILE_PREFIX_MAP.
    """
    import os, mimetypes
    hasil = []
    if not os.path.isdir(folder_path):
        return []
    for fname in sorted(os.listdir(folder_path)):
        fpath = os.path.join(folder_path, fname)
        if not os.path.isfile(fpath):
            continue
        jenis = None
        for prefix, j in FILE_PREFIX_MAP.items():
            if fname.startswith(prefix + " ") or fname == prefix.rstrip(".") + ".pdf":
                jenis = j
                break
        if not jenis:
            continue
        mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        hasil.append({"path": fpath, "nama": fname, "jenis": jenis, "mime": mime})
    return hasil


def list_subfolder_ppk() -> list[str]:
    """
    List subfolder di PPK_PL_BASE yang bukan _* atau .*
    Return sorted list nama folder.
    """
    import os
    if not os.path.isdir(PPK_PL_BASE):
        return []
    return sorted([
        d for d in os.listdir(PPK_PL_BASE)
        if os.path.isdir(os.path.join(PPK_PL_BASE, d))
        and not d.startswith('_') and not d.startswith('.')
    ])


def auto_match_folder(nama_paket_spse: str, subfolder_list: list[str]) -> str | None:
    """
    Fuzzy match nama paket SPSE ke subfolder PPK PL.
    Return nama subfolder yang paling cocok, atau None.
    """
    import re
    from difflib import SequenceMatcher

    STRIP_PREFIXES = [
        'Belanja Jasa Konsultansi Perencanaan Arsitektur-Jasa Arsitektur Lainnya ',
        'Belanja Jasa Konsultansi Perencanaan Arsitektur-Jasa Arsitektur ',
        'Belanja Jasa Konsultansi Perencanaan Rekayasa-Jasa Desain Rekayasa untuk Konstruksi ',
        'Belanja Jasa Konsultansi Perencanaan ',
        'Belanja Jasa Konsultansi ',
        'Belanja Jasa ',
    ]

    def _strip(nama):
        for pfx in STRIP_PREFIXES:
            if nama.startswith(pfx):
                return nama[len(pfx):]
        return nama

    def _strip_num(folder):
        return re.sub(r'^\d+\.\s*', '', folder)

    target = _strip(nama_paket_spse).lower().strip()
    best, best_score = None, 0.0
    for folder in subfolder_list:
        candidate = _strip_num(folder).lower().strip()
        # substring check dulu
        if target in candidate or candidate in target:
            return folder
        score = SequenceMatcher(None, target, candidate).ratio()
        if score > best_score:
            best_score = score
            best = folder
    return best if best_score > 0.65 else None


def upload_dari_folder(
    kode_paket: str,
    folder_path: str,
    log_fn=None,
) -> dict:
    """
    Upload semua file yang cocok dari folder ke SPSE.
    Return {"results": [{"jenis", "nama", "ok", "error"}], "total_ok": int, "total_err": int}
    """
    def _log(msg):
        if log_fn: log_fn(msg)

    files = scan_folder(folder_path)
    if not files:
        return {"results": [], "total_ok": 0, "total_err": 0, "error": "Tidak ada file yang cocok di folder ini."}

    results = []
    for f in files:
        _log(f"⬆️ Upload [{f['jenis']}] {f['nama']}...")
        try:
            with open(f["path"], "rb") as fh:
                file_bytes = fh.read()
            res = upload_dokumen(
                kode_paket=kode_paket,
                jenis=f["jenis"],
                file_bytes=file_bytes,
                file_name=f["nama"],
                mime_type=f["mime"],
                log_fn=log_fn,
            )
            ok = res.get("ok", False)
            results.append({"jenis": f["jenis"], "nama": f["nama"], "ok": ok, "error": res.get("error", "")})
            if ok:
                _log(f"  ✅ {f['nama']} berhasil")
            else:
                _log(f"  ❌ {f['nama']} gagal: {res.get('error')}")
        except Exception as e:
            results.append({"jenis": f["jenis"], "nama": f["nama"], "ok": False, "error": str(e)})
            _log(f"  ❌ Exception: {e}")

    total_ok  = sum(1 for r in results if r["ok"])
    total_err = sum(1 for r in results if not r["ok"])
    return {"results": results, "total_ok": total_ok, "total_err": total_err}
