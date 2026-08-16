"""Engine Download Dokumen Kualifikasi Peserta Tender."""

import os
import re
import json
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


_OFFER_LINK_MARKERS = (
    "/cetaksuratpenawaran",
    "/rincian_adminteknis",
    "/rincian_penawaran",
)


def _row_has_submitted_offer(row) -> bool:
    """True jika baris penyedia menunjukkan dokumen penawaran sudah dikirim."""
    hrefs = [str(a.get("href") or "").lower() for a in row.find_all("a")]
    if any(marker in href for href in hrefs for marker in _OFFER_LINK_MARKERS):
        return True

    # Fallback untuk variasi HTML SPSE yang tidak memberi link rincian, tetapi
    # tetap menampilkan status pengiriman pada kolom dokumen penawaran.
    text = row.get_text(" ", strip=True).lower()
    return "belum dikirim" not in text and bool(re.search(r"\bdikirim\b", text))


# ── Last-used directory ─────────────────────────────────────────────────────────

def get_last_dir() -> str:
    try:
        if os.path.exists(_LAST_DIR_FILE):
            return open(_LAST_DIR_FILE, encoding="utf-8").read().strip()
    except Exception:
        pass
    from config import TENDER_ROOT
    return TENDER_ROOT


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
            pesan = "Paket belum memiliki data peserta di SPSE (belum tahap penawaran)" if r.status_code == 500 else f"HTTP {r.status_code}"
            return {"ok": False, "peserta": [], "pesan": pesan}

        soup = BeautifulSoup(r.text, "html.parser")

        # Tabel SPSE memuat pendaftar dan peserta penawar sekaligus. Untuk Tab
        # 6, hanya peserta yang benar-benar mengirim penawaran yang relevan.
        peserta_list = []
        seen_kualifikasi_ids = set()
        for a in soup.find_all("a", href=re.compile(r"/kualifikasi/\d+/preview")):
            # Ambil kualifikasi_id dari href
            km = re.search(r"/kualifikasi/(\d+)/preview", a["href"])
            if not km:
                continue
            kualifikasi_id = km.group(1)

            # Nama peserta: cari di baris tabel yang sama
            tr = a.find_parent("tr")
            if tr is None or not _row_has_submitted_offer(tr):
                continue
            if kualifikasi_id in seen_kualifikasi_ids:
                continue
            seen_kualifikasi_ids.add(kualifikasi_id)
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

        return {"ok": True, "peserta": peserta_list, "pesan": f"{len(peserta_list)} peserta penawar ditemukan"}

    except Exception as e:
        return {"ok": False, "peserta": [], "pesan": str(e)}


def fetch_peserta_by_kode(kode_tender: str) -> dict:
    """Wrapper fetch_peserta dari kode_tender (kolom 0 dt/paketpanitia, format 10072844000)."""
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/peserta/{kode_tender}/penawaran"
    return fetch_peserta(url)


def fetch_peserta_by_id_lelang(id_lelang: str) -> dict:
    """Wrapper fetch_peserta dari id_lelang (kolom 5 dt/paketpanitia) — dipakai untuk URL /peserta/."""
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/peserta/{id_lelang}/penawaran"
    return fetch_peserta(url)


def resolve_folder_paket(kode_tender: str) -> dict:
    """
    Lookup folder paket dari Supabase draft_paket.folder_dibuat.
    Return: {"ok": bool, "path": str, "pesan": str}
    path = POKJA_ROOT / folder_dibuat / 1. Dokumen Kualifikasi  (dibuat jika belum ada)
    """
    from config import sb, POKJA_ROOT, TENDER_ROOT
    try:
        r = sb().table("draft_paket").select("folder_dibuat").eq("kode_tender", kode_tender).maybe_single().execute()
        if not r.data:
            return {"ok": False, "path": "", "pesan": "Paket tidak ditemukan di database"}
        folder_dibuat = r.data.get("folder_dibuat")
        if not folder_dibuat:
            return {"ok": False, "path": "", "pesan": "Folder paket belum dibuat (tab 0)"}
        # Windows tidak izinkan '/' dalam nama folder — sanitasi sama seperti saat folder dibuat
        folder_dibuat_safe = re.sub(r'[/\\:*?"<>|]', "-", folder_dibuat).strip()
        path = os.path.join(TENDER_ROOT, folder_dibuat_safe, "1. Dokumen Kualifikasi")
        os.makedirs(path, exist_ok=True)
        return {"ok": True, "path": path, "pesan": folder_dibuat}
    except Exception as e:
        return {"ok": False, "path": "", "pesan": str(e)}


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
    total_peserta: int = 1,
    progress_cb=None,
) -> dict:
    """
    Download semua dokumen kualifikasi 1 peserta + generate checklist PDF, lalu zip.

    Args:
        peserta       : {"nama", "kualifikasi_id", "lelang_id"}
        folder_output : path 1. Dokumen Kualifikasi/ (sudah resolved)
        urutan        : nomor urut peserta (1, 2, 3)
        total_peserta : jumlah total peserta — menentukan apakah pakai subfolder
                        1 peserta → file langsung di folder_output (flat)
                        ≥2 peserta → subfolder "{urutan}. {nama_perusahaan}/"
        progress_cb   : callback(pesan: str)

    Return: {"ok": bool, "pesan": str, "zip_path": str}
    """
    nama = peserta["nama"]
    kualifikasi_id = peserta["kualifikasi_id"]
    slug_nama = _slug(nama)

    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _log(f"Memproses: {nama}")

    # Tentukan folder tujuan akhir
    dest_folder = os.path.join(folder_output, f"{urutan}. {slug_nama}")
    os.makedirs(dest_folder, exist_ok=True)

    # 1. Fetch daftar dokumen
    result_dok = fetch_dokumen_kualifikasi(kualifikasi_id)
    if not result_dok["ok"]:
        return {"ok": False, "pesan": f"Gagal fetch dokumen: {result_dok['pesan']}", "path": ""}

    dokumen = result_dok["dokumen"]

    # 2. Download tiap dokumen langsung ke dest_folder
    file_didownload = []
    for i, dok in enumerate(dokumen):
        _log(f"  Downloading ({i+1}/{len(dokumen)}): {dok['nama']}")
        nama_file = _slug(dok["nama"])
        if not nama_file.lower().endswith(".pdf"):
            nama_file += ".pdf"
        dest_file = os.path.join(dest_folder, nama_file)
        res = _download_file(dok["url"], dest_file)
        if res["ok"]:
            file_didownload.append(res.get("path", dest_file))
        else:
            _log(f"  [GAGAL] {dok['nama']} - {res['pesan']}")

    # 3. Generate checklist PDF langsung ke dest_folder
    _log("  Membuat checklist PDF...")
    checklist_path = os.path.join(dest_folder, f"checklist_kualifikasi_{slug_nama}.pdf")
    res_pdf = generate_checklist_pdf(kualifikasi_id, checklist_path)
    if res_pdf["ok"]:
        file_didownload.append(checklist_path)
    else:
        _log(f"  ⚠️ Gagal buat checklist PDF: {res_pdf['pesan']}")

    # 4. Gabung semua jadi 1 PDF
    gabungan_path = os.path.join(dest_folder, f"Kualifikasi {slug_nama}.pdf")
    _log(f"  Menggabung {len(file_didownload)} file → Kualifikasi {slug_nama}.pdf")
    try:
        import inbox_engine
        inbox_engine.gabung_pdf(gabungan_path, file_didownload, _log)
        _log(f"  ✅ Selesai: Kualifikasi {slug_nama}.pdf")
    except Exception as e:
        _log(f"  ⚠️ Gagal gabung PDF: {e}")
        gabungan_path = ""

    return {"ok": True, "pesan": f"✅ {len(file_didownload)} file + gabungan", "path": gabungan_path}
