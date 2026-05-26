"""Download dokumen teknis/biaya PL (Non-Tender) post-evaluasi admin+kualifikasi LULUS."""

import os
import re
import sys
import requests
from contextlib import contextmanager

import spse_browser
from config import SPSE_BASE_URL


@contextmanager
def _quiet():
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

BASE = SPSE_BASE_URL.rstrip("/")


def _headers(referer: str = "") -> dict:
    cookie = spse_browser.get_spse_cookies()
    return {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "Referer": referer or BASE,
    }


def _slug(nama: str) -> str:
    nama = re.sub(r'[\\/:*?"<>|]', "", nama)
    return nama.strip()[:80]


def fetch_dokumen_teknis_biaya_pl(id_nontender: str) -> dict:
    """
    Scrape link dokumen teknis/biaya dari /evaluasinontender/{id_nontender}/detail via CDP.
    Halaman hanya terbuka setelah evaluasi admin+kualifikasi LULUS.
    Return: {"ok": bool, "dokumen": [{"nama","url"}], "pesan": str}
    """
    import asyncio

    url_detail = f"{BASE}/evaluasinontender/{id_nontender}/detail"

    async def _fetch():
        page = await spse_browser._connect_cdp_async(url_detail, navigate=True)
        await asyncio.sleep(2)
        result = await page.evaluate("""() => {
            // Dokumen teknis/biaya PL pakai /dlsec/ bukan /dl/
            // Ambil dari section #teknis dan #harga saja
            var dokumen = [];
            ['teknis', 'harga'].forEach(function(secId) {
                var sec = document.getElementById(secId);
                if (!sec) return;
                Array.from(sec.querySelectorAll('a[href]')).forEach(function(a) {
                    var href = a.href || '';
                    var nama = a.innerText.trim();
                    if (!nama || !href) return;
                    // Hanya link download (dlsec atau dl) - bukan link navigasi
                    if (href.includes('/dlsec/') || href.includes('/dl/')) {
                        dokumen.push({nama: nama, url: href, section: secId});
                    }
                });
            });
            return dokumen;
        }""")
        return result

    try:
        with _quiet():
            dokumen_raw = spse_browser._run(_fetch())
        if not dokumen_raw:
            return {"ok": False, "dokumen": [], "pesan": "Tidak ada dokumen teknis/biaya ditemukan"}
        return {"ok": True, "dokumen": dokumen_raw, "pesan": f"{len(dokumen_raw)} dokumen"}
    except Exception as e:
        return {"ok": False, "dokumen": [], "pesan": str(e)}


def _download_file(url: str, dest_path: str) -> dict:
    """Download file ke dest_path via requests + cookie."""
    try:
        r = requests.get(url, headers=_headers(BASE + "/evaluasinontender"), timeout=60, stream=True)
        if r.status_code != 200:
            return {"ok": False, "pesan": f"HTTP {r.status_code}", "path": ""}

        # Deteksi nama file dari Content-Disposition
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
        return {"ok": True, "pesan": "OK", "path": dest_path, "ukuran": ukuran}
    except Exception as e:
        return {"ok": False, "pesan": str(e), "path": ""}


def _convert_to_pdf(src_path: str, dest_pdf: str) -> bool:
    """
    Konversi file ke PDF.
    .pdf: copy
    .docx/.doc: Word COM SaveAs wdFormatPDF
    .xlsx/.xls: Excel COM ExportAsFixedFormat
    .jpg/.jpeg/.png: img2pdf
    Return True jika sukses.
    """
    import shutil
    ext = os.path.splitext(src_path)[1].lower()

    if ext == ".pdf":
        if src_path != dest_pdf:
            shutil.copy2(src_path, dest_pdf)
        return True

    if ext in (".docx", ".doc"):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = False
            try:
                doc = word.Documents.Open(os.path.abspath(src_path), ReadOnly=True)
                doc.SaveAs(os.path.abspath(dest_pdf), FileFormat=17)  # wdFormatPDF
                doc.Close(False)
                return True
            finally:
                word.Quit()
                pythoncom.CoUninitialize()
        except Exception:
            return False

    if ext in (".xlsx", ".xls"):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            try:
                wb = xl.Workbooks.Open(os.path.abspath(src_path), ReadOnly=True)
                wb.ExportAsFixedFormat(0, os.path.abspath(dest_pdf))  # xlTypePDF = 0
                wb.Close(False)
                return True
            finally:
                xl.Quit()
                pythoncom.CoUninitialize()
        except Exception:
            return False

    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff"):
        try:
            import img2pdf
            with open(dest_pdf, "wb") as f:
                f.write(img2pdf.convert(src_path))
            return True
        except Exception:
            try:
                import fitz
                doc = fitz.open()
                img_doc = fitz.open(src_path)
                pdfbytes = img_doc.convert_to_pdf()
                img_doc.close()
                doc2 = fitz.open("pdf", pdfbytes)
                doc.insert_pdf(doc2)
                doc.save(dest_pdf)
                doc.close()
                return True
            except Exception:
                return False

    return False  # ekstensi tidak dikenal


def _gabung_pdf(output_path: str, file_list: list, progress_cb=None) -> bool:
    """Gabung file_list PDF jadi satu output_path. Tanpa limit ukuran."""
    import fitz

    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    merged = fitz.open()
    for fpath in file_list:
        if not os.path.isfile(fpath):
            continue
        try:
            doc = fitz.open(fpath)
            n = doc.page_count
            merged.insert_pdf(doc)
            doc.close()
            _log(f"    OK {os.path.basename(fpath)} ({n} hal)")
        except Exception as e:
            _log(f"    GAGAL {os.path.basename(fpath)}: {e}")

    if merged.page_count == 0:
        merged.close()
        return False
    merged.save(output_path)
    merged.close()
    return True


def download_teknis_biaya_peserta(
    id_nontender: str,
    nama_peserta: str,
    folder_paket: str,
    urutan: int,
    progress_cb=None,
) -> dict:
    """
    Download dokumen teknis/biaya 1 peserta → konversi ke PDF → gabung pengepul.

    folder_paket: root folder paket PL (parent dari '2. Dokumen Teknis Biaya/')
    Return: {"ok": bool, "files_downloaded": int, "pdf_gabungan_path": str, "pesan": str}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    slug_nama = _slug(nama_peserta)
    dest_folder = os.path.join(folder_paket, "2. Dokumen Teknis Biaya", f"{urutan}. {slug_nama}")
    os.makedirs(dest_folder, exist_ok=True)

    _log(f"  Fetch dokumen teknis id={id_nontender}...")
    res_dok = fetch_dokumen_teknis_biaya_pl(id_nontender)
    if not res_dok["ok"]:
        return {"ok": False, "files_downloaded": 0, "pdf_gabungan_path": "", "pesan": res_dok["pesan"]}

    dokumen = res_dok["dokumen"]
    files_pdf = []
    n_dl = 0

    for i, dok in enumerate(dokumen):
        _log(f"  [{i+1}/{len(dokumen)}] {dok['nama']}")
        nama_file = _slug(dok["nama"])
        if not any(nama_file.lower().endswith(ext) for ext in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".jpg", ".png")):
            nama_file += ".pdf"
        dest_file = os.path.join(dest_folder, nama_file)
        res_dl = _download_file(dok["url"], dest_file)
        if not res_dl["ok"]:
            _log(f"    [GAGAL] {res_dl['pesan']}")
            continue
        actual_path = res_dl["path"]
        n_dl += 1

        # Konversi ke PDF jika perlu
        ext = os.path.splitext(actual_path)[1].lower()
        if ext != ".pdf":
            pdf_path = os.path.splitext(actual_path)[0] + ".pdf"
            ok_conv = _convert_to_pdf(actual_path, pdf_path)
            if ok_conv:
                files_pdf.append(pdf_path)
                _log(f"    Konversi {ext} -> PDF OK")
            else:
                _log(f"    [skip gabung] gagal konversi {ext}")
        else:
            files_pdf.append(actual_path)

    # Gabung semua PDF
    gabungan_nama = f"Teknis Biaya {slug_nama}.pdf"
    gabungan_path = os.path.join(dest_folder, gabungan_nama)

    # Scan ulang folder — include PDF yang mungkin sudah ada sebelumnya
    semua_pdf = sorted([
        os.path.join(dest_folder, f)
        for f in os.listdir(dest_folder)
        if f.lower().endswith(".pdf") and f != gabungan_nama and not f.startswith("~$")
    ])

    if semua_pdf:
        _log(f"  Gabung {len(semua_pdf)} PDF -> {gabungan_nama}...")
        ok_gabung = _gabung_pdf(gabungan_path, semua_pdf, _log)
        if not ok_gabung:
            gabungan_path = ""
            _log("  [skip] tidak ada halaman berhasil digabung")
    else:
        gabungan_path = ""
        _log("  Tidak ada PDF untuk digabung")

    return {
        "ok": n_dl > 0,
        "files_downloaded": n_dl,
        "pdf_gabungan_path": gabungan_path,
        "pesan": f"{n_dl} file didownload" + (f", gabungan: {gabungan_nama}" if gabungan_path else ""),
    }


def download_teknis_biaya_batch(
    paket_peserta_list: list,
    progress_cb=None,
) -> dict:
    """
    Batch download dokumen teknis/biaya.

    paket_peserta_list: [
        {
            "kode_paket": str,
            "folder_paket": str,  # root folder paket PL
            "peserta": [{"nama", "id_nontender"}, ...]
        },
        ...
    ]
    Return: {"ok": bool, "ringkasan": str, "detail": [...]}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    detail = []
    n_ok = 0
    n_total = 0

    for item in paket_peserta_list:
        kode = item["kode_paket"]
        folder_paket = item["folder_paket"]
        peserta_list = item.get("peserta", [])
        _log(f"=== Paket {kode} ({len(peserta_list)} peserta) ===")

        for urut, p in enumerate(peserta_list, 1):
            n_total += 1
            _log(f"Peserta {urut}: {p['nama']}")
            res = download_teknis_biaya_peserta(
                id_nontender=p["id_nontender"],
                nama_peserta=p["nama"],
                folder_paket=folder_paket,
                urutan=urut,
                progress_cb=progress_cb,
            )
            if res["ok"]:
                n_ok += 1
            detail.append({
                "kode_paket": kode,
                "nama": p["nama"],
                **res,
            })

    ringkasan = f"{n_ok}/{n_total} peserta berhasil didownload"
    return {"ok": n_ok == n_total, "ringkasan": ringkasan, "detail": detail}
