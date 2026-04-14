"""Engine Download Dokumen Kualifikasi Peserta Tender."""

import os
import re
import zipfile
import json
import tempfile
from pathlib import Path
from bs4 import BeautifulSoup

import requests

import spse_browser
from config import SPSE_BASE_URL

# ── Konstanta ──────────────────────────────────────────────────────────────────
_LAST_DIR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_kualifikasi_dir")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _headers(referer: str = "") -> dict:
    cookie = spse_browser.get_spse_cookies()
    h = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "Referer": referer or SPSE_BASE_URL,
    }
    return h


def _slug(nama: str) -> str:
    """Bersihkan nama untuk nama folder/file."""
    nama = re.sub(r'[\\/:*?"<>|]', "", nama)
    return nama.strip()[:80]


# ── Last-used directory ─────────────────────────────────────────────────────────

def get_last_dir() -> str:
    try:
        if os.path.exists(_LAST_DIR_FILE):
            return open(_LAST_DIR_FILE, encoding="utf-8").read().strip()
    except Exception:
        pass
    return r"D:\Dokumen\@ POKJA 2026"


def save_last_dir(path: str):
    try:
        with open(_LAST_DIR_FILE, "w", encoding="utf-8") as f:
            f.write(path)
    except Exception:
        pass


# ── Fetch daftar peserta dari /peserta/{lelang_id}/penawaran ───────────────────

def fetch_peserta(url_penawaran: str) -> dict:
    """
    Scrape daftar peserta dari halaman /penawaran.
    Return: {"ok": bool, "peserta": [{"nama", "kualifikasi_id", "peserta_id"}], "pesan": str}
    """
    # Ekstrak lelang_id dari URL
    m = re.search(r"/peserta/(\d+)/penawaran", url_penawaran)
    if not m:
        return {"ok": False, "peserta": [], "pesan": "URL tidak valid. Format: .../peserta/{ID}/penawaran"}

    lelang_id = m.group(1)
    base = SPSE_BASE_URL.rstrip("/")

    try:
        r = requests.get(
            url_penawaran,
            headers=_headers(f"{base}/paket"),
            timeout=15,
        )
        if r.status_code != 200:
            return {"ok": False, "peserta": [], "pesan": f"HTTP {r.status_code}"}

        soup = BeautifulSoup(r.text, "html.parser")

        # Tabel peserta — cari kolom "Dokumen Kualifikasi" yang berisi link /kualifikasi/.../preview
        peserta_list = []
        for a in soup.find_all("a", href=re.compile(r"/kualifikasi/\d+/preview")):
            # Ambil kualifikasi_id dari href
            km = re.search(r"/kualifikasi/(\d+)/preview", a["href"])
            if not km:
                continue
            kualifikasi_id = km.group(1)

            # Nama peserta: cari di baris tabel yang sama
            tr = a.find_parent("tr")
            nama = ""
            if tr:
                tds = tr.find_all("td")
                if tds:
                    nama = tds[1].get_text(strip=True) if len(tds) > 1 else tds[0].get_text(strip=True)

            if not nama:
                nama = f"Peserta {kualifikasi_id}"

            peserta_list.append({
                "nama": nama,
                "kualifikasi_id": kualifikasi_id,
                "lelang_id": lelang_id,
            })

        if not peserta_list:
            return {"ok": False, "peserta": [], "pesan": "Tidak ada peserta ditemukan di halaman ini"}

        return {"ok": True, "peserta": peserta_list, "pesan": f"{len(peserta_list)} peserta ditemukan"}

    except Exception as e:
        return {"ok": False, "peserta": [], "pesan": str(e)}


# ── Fetch daftar dokumen dari /kualifikasi/{id}/preview ───────────────────────

def fetch_dokumen_kualifikasi(kualifikasi_id: str) -> dict:
    """
    Scrape daftar link dokumen dari halaman preview kualifikasi via CDP (Playwright).
    URL /dl/ di DOM berisi session token lengkap — tidak bisa dari requests biasa.
    Return: {"ok": bool, "dokumen": [{"nama", "url"}], "url_preview": str, "pesan": str}
    """
    import asyncio

    base = SPSE_BASE_URL.rstrip("/")
    url_preview = f"{base}/kualifikasi/{kualifikasi_id}/preview"

    async def _fetch():
        page = await spse_browser._connect_cdp_async(url_preview, navigate=True)
        await asyncio.sleep(2)
        result = await page.evaluate("""() => {
            var links = document.querySelectorAll('a[href*=\"/dl/\"]');
            return Array.from(links).map(function(a) {
                return {nama: a.innerText.trim(), url: a.href};
            }).filter(function(d) { return d.nama.length > 0; });
        }""")
        return result

    try:
        dokumen_raw = spse_browser._run(_fetch())
        if not dokumen_raw:
            return {"ok": False, "dokumen": [], "url_preview": url_preview, "pesan": "Tidak ada dokumen ditemukan"}
        return {
            "ok": True,
            "dokumen": dokumen_raw,
            "url_preview": url_preview,
            "pesan": f"{len(dokumen_raw)} dokumen ditemukan",
        }
    except Exception as e:
        return {"ok": False, "dokumen": [], "url_preview": url_preview, "pesan": str(e)}


# ── Download satu file ─────────────────────────────────────────────────────────

def _download_file(url: str, dest_path: str) -> dict:
    """Download file ke dest_path. Return {"ok": bool, "pesan": str, "ukuran": int}"""
    base = SPSE_BASE_URL.rstrip("/")
    try:
        r = requests.get(
            url,
            headers=_headers(base + "/paket"),
            timeout=60,
            stream=True,
        )
        if r.status_code != 200:
            return {"ok": False, "pesan": f"HTTP {r.status_code}", "ukuran": 0}

        # Cek Content-Disposition untuk nama file asli
        cd = r.headers.get("Content-Disposition", "")
        fname_match = re.search(r'filename[^;=\n]*=([\'"]?)([^\'";\n]+)\1', cd)
        if fname_match:
            # CD bisa ada spasi: filename= "nama+file.pdf" — decode + sign dan strip
            fname_orig = fname_match.group(2).strip().strip('"').strip("'")
            fname_orig = fname_orig.replace("+", " ").strip()
            if fname_orig:
                dest_dir = os.path.dirname(dest_path)
                dest_path = os.path.join(dest_dir, _slug(fname_orig))

        dest_dir = os.path.dirname(os.path.abspath(dest_path))
        os.makedirs(dest_dir, exist_ok=True)
        ukuran = 0
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                ukuran += len(chunk)

        return {"ok": True, "pesan": "OK", "ukuran": ukuran, "path": dest_path}

    except Exception as e:
        return {"ok": False, "pesan": str(e), "ukuran": 0}


# ── Generate PDF checklist kualifikasi via Playwright ─────────────────────────

def generate_checklist_pdf(kualifikasi_id: str, dest_path: str) -> dict:
    """
    Render halaman /kualifikasi/{id}/preview sebagai PDF via Playwright.
    Return: {"ok": bool, "pesan": str}
    """
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/kualifikasi/{kualifikasi_id}/preview"

    try:
        import asyncio

        async def _pdf():
            page = await spse_browser._connect_cdp_async(url, navigate=True)
            await asyncio.sleep(2)  # tunggu render
            await page.pdf(
                path=dest_path,
                format="A4",
                print_background=True,
                margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
            )
            return True

        spse_browser._run(_pdf())
        return {"ok": True, "pesan": f"PDF disimpan: {dest_path}"}

    except Exception as e:
        return {"ok": False, "pesan": str(e)}


# ── Download semua dokumen 1 peserta → ZIP ─────────────────────────────────────

def download_kualifikasi_peserta(
    peserta: dict,
    folder_output: str,
    urutan: int,
    progress_cb=None,
) -> dict:
    """
    Download semua dokumen kualifikasi 1 peserta + generate checklist PDF,
    lalu zip semuanya.

    Args:
        peserta: {"nama", "kualifikasi_id", "lelang_id"}
        folder_output: path folder tujuan (folder paket user)
        urutan: nomor urut untuk nama file (1, 2, 3, ...)
        progress_cb: callback(pesan: str) untuk update progress

    Return: {"ok": bool, "pesan": str, "zip_path": str}
    """
    nama = peserta["nama"]
    kualifikasi_id = peserta["kualifikasi_id"]
    slug_nama = _slug(nama)

    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _log(f"Memproses: {nama}")

    # 1. Fetch daftar dokumen
    result_dok = fetch_dokumen_kualifikasi(kualifikasi_id)
    if not result_dok["ok"]:
        return {"ok": False, "pesan": f"Gagal fetch dokumen: {result_dok['pesan']}", "zip_path": ""}

    dokumen = result_dok["dokumen"]
    url_preview = result_dok["url_preview"]

    # 2. Buat folder temp untuk kumpulkan file
    tmp_dir = os.path.join(
        tempfile.gettempdir(),
        f"kualifikasi_{kualifikasi_id}_{urutan}",
    )
    os.makedirs(tmp_dir, exist_ok=True)

    # 3. Download tiap dokumen
    for i, dok in enumerate(dokumen):
        _log(f"  Downloading ({i+1}/{len(dokumen)}): {dok['nama']}")
        # Nama file: pakai nama dari server, fallback ke nama link
        ext = ".pdf"
        nama_file = _slug(dok["nama"])
        if not nama_file.lower().endswith(".pdf"):
            nama_file += ext
        dest = os.path.join(tmp_dir, nama_file)
        res = _download_file(dok["url"], dest)
        if not res["ok"]:
            _log(f"  [GAGAL] {dok['nama']} - {res['pesan']}")

    # 4. Generate checklist PDF
    _log("  Membuat checklist PDF...")
    checklist_path = os.path.join(tmp_dir, f"checklist_kualifikasi_{slug_nama}.pdf")
    res_pdf = generate_checklist_pdf(kualifikasi_id, checklist_path)
    if not res_pdf["ok"]:
        _log(f"  ⚠️ Gagal buat PDF: {res_pdf['pesan']}")

    # 5. ZIP semua file
    zip_name = f"{urutan}. Dokumen Kualifikasi ({slug_nama}).zip"
    zip_path = os.path.join(folder_output, zip_name)
    os.makedirs(folder_output, exist_ok=True)

    _log(f"  Membuat ZIP: {zip_name}")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in os.listdir(tmp_dir):
                fpath = os.path.join(tmp_dir, f)
                if os.path.isfile(fpath):
                    zf.write(fpath, f)
        _log(f"  ✅ Selesai: {zip_name}")
    except Exception as e:
        return {"ok": False, "pesan": f"Gagal ZIP: {e}", "zip_path": ""}

    # 6. Cleanup temp
    import shutil
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    return {"ok": True, "pesan": f"✅ {zip_name}", "zip_path": zip_path}
