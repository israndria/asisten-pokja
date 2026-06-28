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
_LPSE = BASE_URL.rstrip("/").rsplit("/", 1)[-1]  # "tapinkab"


_CDP_RUNNER = None  # path ke script helper

def _get_cdp_runner() -> str:
    """Buat/kembalikan path script CDP runner."""
    import os, tempfile
    global _CDP_RUNNER
    if _CDP_RUNNER and os.path.exists(_CDP_RUNNER):
        return _CDP_RUNNER
    script = r"""
import sys, json
from playwright.sync_api import sync_playwright

js = sys.stdin.read()
with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://localhost:9222")
    ctx = browser.contexts[0]
    pages = ctx.pages
    page = None
    for p in pages:
        if "paketnontender" in p.url and "spse.inaproc.id" in p.url:
            page = p; break
    if page is None:
        for p in pages:
            if "spse.inaproc.id" in p.url:
                page = p; break
    if page is None and pages:
        page = pages[0]
    if page is None:
        print(json.dumps({"ok": False, "error": "Tidak ada tab aktif"}))
        sys.exit(0)
    try:
        result = page.evaluate(js)
        print(json.dumps({"ok": True, "value": result}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
"""
    fd, path = tempfile.mkstemp(suffix="_cdp_runner.py", prefix="pokja_")
    import os
    os.write(fd, script.encode())
    os.close(fd)
    _CDP_RUNNER = path
    return path


def _cdp_eval(js: str, timeout: int = 30) -> tuple[bool, object, str]:
    """
    Jalankan JS di tab SPSE via subprocess Playwright (process-isolated, thread-safe).
    Return (ok, result_value, error_msg).
    """
    import subprocess, sys, os

    python = sys.executable
    runner = _get_cdp_runner()

    try:
        proc = subprocess.run(
            [python, runner],
            input=js.encode(),
            capture_output=True,
            timeout=timeout + 10,
        )
        stdout = proc.stdout.decode(errors="replace").strip()
        if not stdout:
            stderr = proc.stderr.decode(errors="replace")[:300]
            return False, None, f"CDP runner no output: {stderr}"
        resp = json.loads(stdout)
        if resp.get("ok"):
            return True, resp.get("value"), ""
        return False, None, resp.get("error", "unknown")
    except subprocess.TimeoutExpired:
        return False, None, f"CDP runner timeout ({timeout}s)"
    except Exception as e:
        return False, None, str(e)

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
    Ambil daftar paket non-tender PPK via CDP WebSocket.
    Cookie HttpOnly tidak bisa diakses Python — fetch dari dalam browser.
    """
    import time as _time
    ts = int(_time.time() * 1000)
    js = f"""
    (async () => {{
        const r = await fetch('/{_LPSE}/dt/paketppknontender?draw=1&start=0&length=200&_={ts}',
                              {{credentials:'include'}});
        if (!r.ok) return [];
        const j = await r.json();
        return (j.data || []).map(row => ({{
            kode_paket: String(row[0]),
            nama_paket: String(row[1]),
            status:     String(row[2]),
        }}));
    }})()
    """
    ok, val, err = _cdp_eval(js, timeout=20)
    if not ok:
        return []
    return val or []

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
    Upload dokumen PPK via CDP page.evaluate (5 langkah).
    Cookie PPK ber-flag HttpOnly — seluruh flow dijalankan dari dalam browser.
    File bytes dikirim sebagai base64, di-decode di browser lalu di-upload.
    """
    import base64

    def _log(msg):
        if log_fn:
            log_fn(msg)

    sub_endpoint = _SUBMIT_ENDPOINTS.get(jenis)
    if not sub_endpoint:
        return {"ok": False, "error": f"Jenis '{jenis}' tidak dikenal."}

    _log(f"Langkah 1-5: Upload via browser (CDP)...")
    b64 = base64.b64encode(file_bytes).decode()

    js = f"""
    (async () => {{
        const lpse = "{_LPSE}";
        const kode = "{kode_paket}";
        const mime = "{mime_type}";
        const fname = "{file_name}";
        const subEndpoint = "{sub_endpoint}";
        const b64 = "{b64}";

        const binaryStr = atob(b64);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);

        await fetch('/' + lpse + '/otorisasiDataPaketPlUpload?id=' + kode, {{credentials:'include'}});

        const formData = new FormData();
        formData.append('input[uploadSignedUrlReq][0][contentType]', mime);
        formData.append('input[uploadSignedUrlReq][0][identifier]', '');
        formData.append('input[uploadSignedUrlReq][0][fileName]', fname);
        formData.append('input[uploadSignedUrlReq][0][isPublic]', 'false');
        formData.append('isArchieve', 'true');

        const r2 = await fetch('/' + lpse + '/paketnontender/' + kode + '/getSignedUrl', {{
            method: 'POST', credentials: 'include', body: formData
        }});
        if (!r2.ok) return {{ok: false, error: 'getSignedUrl HTTP ' + r2.status}};
        const res2 = await r2.json();
        const fileId = res2?.result?.data?.fileId;
        const signedUrl = res2?.result?.data?.signedUrl;
        const path = res2?.result?.data?.path || res2?.path;
        if (!fileId || !signedUrl || !path) return {{ok: false, error: 'getSignedUrl data tidak lengkap: ' + JSON.stringify(res2)}};

        const r3 = await fetch(signedUrl, {{
            method: 'PUT', headers: {{'Content-Type': mime}}, body: bytes
        }});
        if (!r3.ok) return {{ok: false, error: 'PUT storage HTTP ' + r3.status}};

        for (let i = 0; i < 5; i++) {{
            const fd4 = new FormData();
            fd4.append('input', fileId);
            const r4 = await fetch('/' + lpse + '/uploadCheckStatus', {{
                method: 'POST', credentials: 'include', body: fd4
            }});
            let d4 = null;
            try {{ d4 = await r4.json(); }} catch(e) {{ break; }}  // parse error = lanjut
            if (!d4 || d4?.errors === null) break;  // null errors = sukses
            if (d4?.errors) return {{ok: false, error: 'checkStatus error: ' + JSON.stringify(d4.errors)}};
            const st = d4?.data?.status;
            if (!st || st === 'UPLOAD_SUCCESS') break;
            if (st === 'UPLOAD_FAILED') return {{ok: false, error: 'Upload dinyatakan gagal server'}};
            await new Promise(r => setTimeout(r, 2000));
        }}

        const fd5 = new FormData();
        fd5.append('id', kode);
        fd5.append('path', path);
        fd5.append('fileId', fileId);
        const r5 = await fetch('/' + lpse + '/dokumennontender/' + kode + '/' + subEndpoint, {{
            method: 'POST', credentials: 'include', body: fd5
        }});
        if (!r5.ok) return {{ok: false, error: 'submit HTTP ' + r5.status}};

        return {{ok: true, path, fileId}};
    }})()
    """
    ok, result, err = _cdp_eval(js, timeout=120)
    if not ok:
        return {"ok": False, "error": err}
    if result and result.get("ok"):
        _log(f"✅ {file_name} berhasil diupload")
    else:
        _log(f"❌ {file_name} gagal: {result.get('error') if result else err}")
    return result or {"ok": False, "error": err}

_LIST_ENDPOINTS = {
    "kak":     "spekppk",
    "kontrak": "uploadsskk",
    "uraian":  "uploaduraian",
    "lainnya": "lainnyappk",
}

def list_dokumen(kode_paket: str, jenis: str, cookies: dict = None) -> list[dict]:
    """
    Ambil daftar dokumen terunggah via CDP (cookie HttpOnly).
    Parse tabel HTML — versi dari atribut `versi` pada link .removeDok.
    """
    endpoint = _LIST_ENDPOINTS.get(jenis)
    if not endpoint:
        return []

    js = f"""
    (async () => {{
        const r = await fetch('/{_LPSE}/dokumennontender/{kode_paket}/{endpoint}',
                              {{credentials:'include'}});
        if (!r.ok) return [];
        const txt = await r.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(txt, 'text/html');
        const rows = doc.querySelectorAll('table tbody tr');
        const result = [];
        rows.forEach(tr => {{
            const a = tr.querySelector('td a');
            if (!a) return;
            const removeDok = tr.querySelector('.removeDok');
            const versi = removeDok ? parseInt(removeDok.getAttribute('versi') || '0') : 0;
            result.push({{
                nama_file: a.textContent.trim(),
                url_dl: a.href || '',
                versi: versi,
            }});
        }});
        return result;
    }})()
    """
    ok, val, _ = _cdp_eval(js, timeout=15)
    return val or []


def hapus_dokumen(kode_paket: str, jenis: str, versi: int, cookies: dict = None) -> bool:
    """
    Hapus dokumen via CDP (cookie HttpOnly).
    """
    del_endpoint = _DELETE_ENDPOINTS.get(jenis)
    if not del_endpoint:
        return False

    js = f"""
    (async () => {{
        const fd = new FormData();
        fd.append('versi', '{versi}');
        const r = await fetch('/{_LPSE}/dokumennontender/{kode_paket}/{del_endpoint}',
                              {{method:'POST', credentials:'include', body:fd}});
        return r.ok || r.status === 302;
    }})()
    """
    ok, val, _ = _cdp_eval(js, timeout=15)
    return bool(ok and val)

PPK_PL_BASE = r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Dinas Perdagangan\1 PERENCANAAN PENGADAAN\Dokumen Upload PPK PL"

FILE_PREFIX_MAP = {
    "1.":  "kak",      # KAK / Spesifikasi Teknis
    "9.":  "kak",      # List Personil (masuk KAK)
    "2.":  "uraian",   # Uraian Singkat
    "3.":  "kontrak",  # SPPBJ (masuk Rancangan Kontrak)
    "4.":  "kontrak",  # SPMK (masuk Rancangan Kontrak)
    "5.":  "kontrak",  # Rancangan Kontrak (SPK)
    "6.":  "kontrak",  # SUK (masuk Rancangan Kontrak)
    "11.": "lainnya",  # Diskresi / Informasi Lainnya
    # 7. HPS, 8. ND, 10. Survey — tidak diupload
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
