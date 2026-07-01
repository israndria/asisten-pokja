"""Engine Download Dokumen Kualifikasi Peserta Pengadaan Langsung (Non-Tender)."""

import os
import re
import sys
import requests
from bs4 import BeautifulSoup
from contextlib import contextmanager

import spse_browser
from config import SPSE_BASE_URL


@contextmanager
def _quiet():
    """Suppress stderr saat CDP call agar terminal tidak kedap-kedip."""
    _orig = sys.stderr
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        yield
    finally:
        try:
            sys.stderr.close()
        except Exception:
            pass
        sys.stderr = _orig


def _headers(referer: str = "") -> dict:
    cookie = spse_browser.get_spse_cookies()
    return {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "Referer": referer or SPSE_BASE_URL,
    }


def _slug(nama: str) -> str:
    nama = re.sub(r'[\\/:*?"<>|]', "", nama)
    return nama.strip()[:80]


def fetch_peserta_pl(kode_paket: str) -> dict:
    """
    Scrape daftar peserta dari /pesertanontender/{kode}/penawaran via CDP.
    Pakai CDP bukan requests — SPSE sering timeout via direct HTTP.
    Return: {"ok": bool, "peserta": [{"nama","kualifikasi_id","kode_paket"}], "pesan": str}
    """
    import asyncio

    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/pesertanontender/{kode_paket}/penawaran"

    async def _fetch():
        page = await spse_browser._connect_cdp_async(url, navigate=True)
        await asyncio.sleep(2)
        return await page.evaluate("""() => {
            var peserta = [];
            document.querySelectorAll('a[href]').forEach(function(a) {
                var m = a.href.match(/kualifikasinontender\\/(\\d+)\\/preview/);
                if (!m) return;
                var kualifikasi_id = m[1];
                var tr = a.closest('tr');
                var nama = '';
                if (tr) {
                    var tds = tr.querySelectorAll('td');
                    nama = tds.length > 1 ? tds[1].innerText.trim() : (tds[0] ? tds[0].innerText.trim() : '');
                }
                if (!nama) nama = 'Peserta ' + kualifikasi_id;
                if (!peserta.some(function(p) { return p.kualifikasi_id === kualifikasi_id; }))
                    peserta.push({nama: nama, kualifikasi_id: kualifikasi_id});
            });
            return peserta;
        }""")

    try:
        with _quiet():
            peserta_list = spse_browser._run(_fetch())
        if not peserta_list:
            return {"ok": False, "peserta": [], "pesan": "Tidak ada peserta ditemukan"}
        result = [dict(p, kode_paket=kode_paket) for p in peserta_list]
        return {"ok": True, "peserta": result, "pesan": f"{len(result)} peserta ditemukan"}
    except Exception as e:
        return {"ok": False, "peserta": [], "pesan": str(e)}


def fetch_dokumen_kualifikasi_pl(kualifikasi_id: str) -> dict:
    """
    Scrape daftar link dokumen dari /kualifikasinontender/{id}/preview via CDP.
    Return: {"ok": bool, "dokumen": [{"nama","url"}], "url_preview": str, "pesan": str}
    """
    import asyncio

    base = SPSE_BASE_URL.rstrip("/")
    url_preview = f"{base}/kualifikasinontender/{kualifikasi_id}/preview"

    async def _fetch():
        page = await spse_browser._connect_cdp_async(url_preview, navigate=True)
        await asyncio.sleep(2)
        result = await page.evaluate("""() => {
            var links = document.querySelectorAll('a[href*="/dl/"]');
            return Array.from(links).map(function(a) {
                return {nama: a.innerText.trim(), url: a.href};
            }).filter(function(d) { return d.nama.length > 0; });
        }""")
        return result

    try:
        with _quiet():
            dokumen_raw = spse_browser._run(_fetch())
        if not dokumen_raw:
            return {"ok": False, "dokumen": [], "url_preview": url_preview, "pesan": "Tidak ada dokumen ditemukan"}
        return {"ok": True, "dokumen": dokumen_raw, "url_preview": url_preview, "pesan": f"{len(dokumen_raw)} dokumen ditemukan"}
    except Exception as e:
        return {"ok": False, "dokumen": [], "url_preview": url_preview, "pesan": str(e)}


def generate_checklist_pdf_pl(kualifikasi_id: str, dest_path: str) -> dict:
    """Render /kualifikasinontender/{id}/preview sebagai PDF via Playwright."""
    import asyncio

    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/kualifikasinontender/{kualifikasi_id}/preview"

    async def _pdf():
        page = await spse_browser._connect_cdp_async(url, navigate=True)
        await asyncio.sleep(2)
        await page.pdf(
            path=dest_path,
            format="A4",
            print_background=True,
            margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
        )
        return True

    try:
        with _quiet():
            spse_browser._run(_pdf())
        return {"ok": True, "pesan": f"PDF disimpan: {dest_path}"}
    except Exception as e:
        return {"ok": False, "pesan": str(e)}


def resolve_folder_paket_pl(kode_paket: str, buat_subfolder: bool = True) -> dict:
    """
    Lookup folder paket PL dari draft_paket_pl, resolve via parse_kak_pl._resolve_folder_pl.
    Return: {"ok": bool, "path": str, "pesan": str}
    path = folder_paket / 1. Dokumen Kualifikasi/ (dibuat jika buat_subfolder=True)
    Jika buat_subfolder=False, pesan = folder_paket root (tidak buat subfolder).
    """
    try:
        from config import sb
        r = sb().table("draft_paket_pl").select(
            "kode_paket,nama_paket,jenis_pl,nomor_urut,is_ulang"
        ).eq("kode_paket", kode_paket).maybe_single().execute()
        if not r.data:
            return {"ok": False, "path": "", "pesan": "Paket tidak ditemukan di database"}

        row = r.data
        import parse_kak_pl as _pkl
        folder_paket, _ = _pkl._resolve_folder_pl(
            row.get("nomor_urut", ""), row.get("nama_paket", ""), row.get("jenis_pl", "PK"),
            is_ulang=row.get("is_ulang", False)
        )
        if not folder_paket:
            return {"ok": False, "path": "", "pesan": "Folder paket belum dibuat (tab 4)"}

        if not buat_subfolder:
            return {"ok": True, "path": folder_paket, "pesan": folder_paket}

        path = os.path.join(folder_paket, "8. Dokumen Kualifikasi")
        os.makedirs(path, exist_ok=True)
        return {"ok": True, "path": path, "pesan": folder_paket}
    except Exception as e:
        return {"ok": False, "path": "", "pesan": str(e)}


def _download_file(url: str, dest_path: str) -> dict:
    """Download file ke dest_path via requests + cookie."""
    base = SPSE_BASE_URL.rstrip("/")
    try:
        r = requests.get(url, headers=_headers(base + "/paket"), timeout=60, stream=True)
        if r.status_code != 200:
            return {"ok": False, "pesan": f"HTTP {r.status_code}", "ukuran": 0}

        cd = r.headers.get("Content-Disposition", "")
        fname_match = re.search(r'filename[^;=\n]*=([\'"]?)([^\'";\n]+)\1', cd)
        if fname_match:
            fname_orig = fname_match.group(2).strip().strip('"').strip("'").replace("+", " ").strip()
            if fname_orig:
                dest_path = os.path.join(os.path.dirname(dest_path), _slug(fname_orig))

        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        ukuran = 0
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                ukuran += len(chunk)
        return {"ok": True, "pesan": "OK", "ukuran": ukuran, "path": dest_path}
    except Exception as e:
        return {"ok": False, "pesan": str(e), "ukuran": 0}


_7Z_EXE = r"C:\Users\MSI\scoop\shims\7z.exe"


def _ekstrak_arsip(arsip_path: str, dest_folder: str, log_cb=None) -> list:
    """Ekstrak ZIP/RAR/7z ke subfolder via 7z.exe. Return list path file hasil ekstrak."""
    import subprocess

    def _log(msg):
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    ext = os.path.splitext(arsip_path)[1].lower()
    if ext not in (".zip", ".rar", ".7z"):
        return []

    sub_dir = os.path.join(dest_folder, os.path.splitext(os.path.basename(arsip_path))[0])
    os.makedirs(sub_dir, exist_ok=True)

    try:
        hasil = subprocess.run(
            [_7Z_EXE, "x", arsip_path, f"-o{sub_dir}", "-y", "-bd"],
            capture_output=True, text=True,
            creationflags=0x08000000,
        )
        if hasil.returncode != 0:
            _log(f"    [ekstrak gagal] {os.path.basename(arsip_path)}: {hasil.stderr.strip()[:200]}")
            return []
    except Exception as e:
        _log(f"    [ekstrak error] {e}")
        return []

    semua_file = []
    for root, dirs, files in os.walk(sub_dir):
        for fname in sorted(files):
            if not fname.startswith("~$"):
                semua_file.append(os.path.join(root, fname))

    _log(f"    Ekstrak {os.path.basename(arsip_path)} → {len(semua_file)} file")
    return semua_file


def _gabung_pdf_kualifikasi(output_path: str, file_list: list, progress_cb=None) -> str:
    """
    Gabung PDF kualifikasi peserta PL tanpa limit ukuran file.
    Berbeda dengan inbox_engine.gabung_pdf yang skip file >5MB.
    """
    import fitz

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    merged = fitz.open()
    for fpath in file_list:
        if not os.path.isfile(fpath):
            log(f"  [skip] tidak ditemukan: {os.path.basename(fpath)}")
            continue
        ext = os.path.splitext(fpath)[1].lower()
        size_mb = os.path.getsize(fpath) / 1024 / 1024
        try:
            if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff"):
                img_doc = fitz.open(fpath)
                pdfbytes = img_doc.convert_to_pdf()
                img_doc.close()
                doc = fitz.open("pdf", pdfbytes)
            elif ext == ".pdf":
                doc = fitz.open(fpath)
            elif ext in (".docx", ".doc", ".xlsx", ".xls"):
                # Konversi via subprocess COM terpisah (anti-hang Streamlit)
                import tempfile, subprocess, sys
                tmp_pdf = tempfile.mktemp(suffix=".pdf")
                ok_conv = False
                py_exe = sys.executable
                if ext in (".docx", ".doc"):
                    script = (
                        "import sys, pythoncom, win32com.client\n"
                        "pythoncom.CoInitialize()\n"
                        "word = win32com.client.DispatchEx('Word.Application')\n"
                        "word.Visible = False\n"
                        "word.DisplayAlerts = 0\n"
                        "word.AutomationSecurity = 3\n"  # msoAutomationSecurityForceDisable
                        "try:\n"
                        f"    d = word.Documents.Open(r'{os.path.abspath(fpath)}', ReadOnly=True, OpenAndRepair=True)\n"
                        f"    d.SaveAs(r'{os.path.abspath(tmp_pdf)}', FileFormat=17)\n"
                        "    d.Close(False)\n"
                        "finally:\n"
                        "    word.Quit()\n"
                        "    pythoncom.CoUninitialize()\n"
                    )
                else:
                    script = (
                        "import sys, pythoncom, win32com.client\n"
                        "pythoncom.CoInitialize()\n"
                        "xl = win32com.client.DispatchEx('Excel.Application')\n"
                        "xl.Visible = False\n"
                        "xl.DisplayAlerts = False\n"
                        "try:\n"
                        f"    wb = xl.Workbooks.Open(r'{os.path.abspath(fpath)}', ReadOnly=True)\n"
                        f"    wb.ExportAsFixedFormat(0, r'{os.path.abspath(tmp_pdf)}')\n"
                        "    wb.Close(False)\n"
                        "finally:\n"
                        "    xl.Quit()\n"
                        "    pythoncom.CoUninitialize()\n"
                    )
                try:
                    result = subprocess.run(
                        [py_exe, "-c", script],
                        timeout=60,
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0 and os.path.isfile(tmp_pdf):
                        ok_conv = True
                    else:
                        err_msg = (result.stderr or "").strip().splitlines()[-1] if result.stderr else "exit non-zero"
                        log(f"  [skip] gagal konversi {ext} {os.path.basename(fpath)}: {err_msg}")
                except subprocess.TimeoutExpired:
                    log(f"  [skip] timeout konversi {ext} {os.path.basename(fpath)} (>60s)")
                except Exception as ce:
                    log(f"  [skip] gagal konversi {ext} {os.path.basename(fpath)}: {ce}")
                if not ok_conv:
                    try:
                        os.remove(tmp_pdf)
                    except Exception:
                        pass
                    continue
                doc = fitz.open(tmp_pdf)
                try:
                    n_hal = doc.page_count
                    merged.insert_pdf(doc)
                finally:
                    doc.close()
                    try:
                        os.remove(tmp_pdf)
                    except Exception:
                        pass
                log(f"  OK {os.path.basename(fpath)} ({size_mb:.1f}MB, {n_hal} hal, via COM)")
                continue
            else:
                log(f"  [skip] format tidak didukung: {os.path.basename(fpath)}")
                continue
            n_hal = doc.page_count
            merged.insert_pdf(doc)
            doc.close()
            log(f"  OK {os.path.basename(fpath)} ({size_mb:.1f}MB, {n_hal} hal)")
        except Exception as e:
            log(f"  GAGAL {os.path.basename(fpath)}: {e}")

    if merged.page_count == 0:
        raise ValueError("Tidak ada halaman berhasil digabung")

    merged.save(output_path)
    merged.close()
    return output_path


def download_kualifikasi_peserta_pl(
    peserta: dict,
    folder_output: str,
    urutan: int,
    total_peserta: int = 1,
    progress_cb=None,
) -> dict:
    """
    Download semua dokumen kualifikasi 1 peserta PL + checklist PDF, lalu gabung.

    Args:
        peserta       : {"nama", "kualifikasi_id", "kode_paket"}
        folder_output : path 1. Dokumen Kualifikasi/ (sudah resolved)
        urutan        : nomor urut peserta (1, 2, ...)
        total_peserta : 1 peserta → flat, ≥2 → subfolder "{urutan}. {nama}/"
        progress_cb   : callback(pesan: str)

    Return: {"ok": bool, "pesan": str, "path": str}
    """
    nama = peserta["nama"]
    kualifikasi_id = peserta["kualifikasi_id"]
    slug_nama = _slug(nama)

    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    _log(f"Memproses: {nama}")

    dest_folder = os.path.join(folder_output, f"{urutan}. {slug_nama}")
    os.makedirs(dest_folder, exist_ok=True)

    # 1. Fetch daftar dokumen via CDP
    result_dok = fetch_dokumen_kualifikasi_pl(kualifikasi_id)
    if not result_dok["ok"]:
        return {"ok": False, "pesan": f"Gagal fetch dokumen: {result_dok['pesan']}", "path": ""}

    dokumen = result_dok["dokumen"]

    # 2. Download tiap dokumen
    file_didownload = []
    for i, dok in enumerate(dokumen):
        _log(f"  Downloading ({i+1}/{len(dokumen)}): {dok['nama']}")
        nama_file = _slug(dok["nama"])
        _ext = os.path.splitext(nama_file)[1].lower()
        if not _ext:
            nama_file += ".pdf"  # tidak ada ekstensi sama sekali → asumsi PDF
        dest_file = os.path.join(dest_folder, nama_file)
        res = _download_file(dok["url"], dest_file)
        if not res["ok"]:
            _log(f"  [GAGAL] {dok['nama']} — {res['pesan']}")
            continue
        actual_path = res.get("path", dest_file)
        actual_ext = os.path.splitext(actual_path)[1].lower()

        # Ekstrak arsip ZIP/RAR/7z
        if actual_ext in (".zip", ".rar", ".7z"):
            extracted = _ekstrak_arsip(actual_path, dest_folder, _log)
            file_didownload.extend(extracted)
        else:
            file_didownload.append(actual_path)

    # 3. Generate checklist PDF
    _log("  Membuat checklist PDF...")
    checklist_path = os.path.join(dest_folder, f"checklist_kualifikasi_{slug_nama}.pdf")
    res_pdf = generate_checklist_pdf_pl(kualifikasi_id, checklist_path)
    if res_pdf["ok"]:
        file_didownload.append(checklist_path)
    else:
        _log(f"  ⚠️ Gagal buat checklist PDF: {res_pdf['pesan']}")

    # 4. Gabung semua file yang bisa dikonversi di dest_folder (rekursif — termasuk subfolder arsip)
    gabungan_nama = f"Kualifikasi {slug_nama}.pdf"
    gabungan_path = os.path.join(dest_folder, gabungan_nama)
    _EXT_DIDUKUNG = (".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff",
                     ".docx", ".doc", ".xlsx", ".xls")
    semua_pdf = sorted([
        os.path.join(root, fname)
        for root, _, files in os.walk(dest_folder)
        for fname in files
        if os.path.splitext(fname)[1].lower() in _EXT_DIDUKUNG
        and fname != gabungan_nama
        and not fname.startswith("~$")
    ])
    _log(f"  Menggabung {len(semua_pdf)} PDF di folder → {gabungan_nama}")
    if semua_pdf:
        try:
            _gabung_pdf_kualifikasi(gabungan_path, semua_pdf, _log)
            _log(f"  Gabungan selesai: {gabungan_nama}")
        except Exception as e:
            _log(f"  Gagal gabung PDF: {e}")
            gabungan_path = ""
    else:
        _log("  Tidak ada PDF untuk digabung.")
        gabungan_path = ""

    return {"ok": True, "pesan": f"✅ {len(file_didownload)} file + gabungan", "path": gabungan_path}
