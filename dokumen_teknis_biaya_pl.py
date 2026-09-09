"""Download dokumen teknis/biaya PL (Non-Tender) post-evaluasi admin+kualifikasi LULUS."""

import os
import re
import hashlib
import shutil
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


def _headers(referer: str = "", cookie: str | None = None) -> dict:
    if cookie is None:
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
    url_detail = f"{BASE}/evaluasinontender/{id_nontender}/detail"

    async def _fetch():
        page = await spse_browser._connect_cdp_async(url_detail, navigate=True)
        # Tunggu section dokumen/link hasil render. Delay tetap 2 detik tidak
        # menjamin AJAX selesai dan selalu menahan halaman yang sudah siap.
        try:
            await page.wait_for_function(
                """() => Boolean(
                    document.querySelector("#teknis, #harga") && (
                        document.querySelector("#teknis a[href*='/dlsec/'], #teknis a[href*='/dl/'], #harga a[href*='/dlsec/'], #harga a[href*='/dl/']") ||
                        document.querySelector(".alert-danger, .alert-warning")
                    )
                )""",
                timeout=10000,
            )
        except Exception:
            pass
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


def _same_file_contents(path_a: str, path_b: str) -> bool:
    try:
        if os.path.getsize(path_a) != os.path.getsize(path_b):
            return False
        digests = []
        for path in (path_a, path_b):
            digest = hashlib.sha256()
            with open(path, "rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            digests.append(digest.digest())
        return digests[0] == digests[1]
    except OSError:
        return False


def _promote_download(part_path: str, actual_path: str) -> None:
    try:
        os.replace(part_path, actual_path)
        return
    except OSError as replace_error:
        if os.path.isfile(actual_path) and _same_file_contents(
            part_path,
            actual_path,
        ):
            os.remove(part_path)
            return
        try:
            shutil.copyfile(part_path, actual_path)
            if not _same_file_contents(part_path, actual_path):
                raise OSError("fallback copy tidak identik")
            os.remove(part_path)
            return
        except OSError:
            raise replace_error


def _download_file(
    url: str,
    dest_path: str,
    max_attempts: int = 3,
    *,
    http_session=None,
    cookie_str: str | None = None,
) -> dict:
    """Download atomik dengan retry; file parsial tidak dianggap sukses."""
    errors = []
    client = http_session or requests
    for attempt in range(1, max_attempts + 1):
        response = None
        part_path = ""
        try:
            response = client.get(
                url,
                headers=_headers(
                    referer=BASE + "/evaluasinontender",
                    cookie=cookie_str,
                ),
                timeout=(20, 180),
                stream=True,
            )
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            if "text/html" in response.headers.get("Content-Type", ""):
                raise RuntimeError(
                    "session expired (server return HTML) — login ulang"
                )

            cd = response.headers.get("Content-Disposition", "")
            fname_match = re.search(
                r'filename[^;=\n]*=([\'"]?)([^\'";\n]+)\1',
                cd,
            )
            actual_path = dest_path
            if fname_match:
                fname_orig = (
                    fname_match.group(2)
                    .strip()
                    .strip('"')
                    .strip("'")
                    .replace("+", " ")
                    .strip()
                )
                if fname_orig:
                    actual_path = os.path.join(
                        os.path.dirname(dest_path),
                        _slug(fname_orig),
                    )

            os.makedirs(
                os.path.dirname(os.path.abspath(actual_path)),
                exist_ok=True,
            )
            part_path = actual_path + ".part"
            ukuran = 0
            with open(part_path, "wb") as output:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    ukuran += len(chunk)

            expected = response.headers.get("Content-Length", "").strip()
            if ukuran <= 0:
                raise RuntimeError("file kosong")
            if expected.isdigit() and ukuran != int(expected):
                raise RuntimeError(
                    f"ukuran tidak lengkap ({ukuran}/{expected} byte)"
                )

            _promote_download(part_path, actual_path)
            return {
                "ok": True,
                "pesan": "OK",
                "path": actual_path,
                "ukuran": ukuran,
                "attempts": attempt,
            }
        except Exception as exc:
            errors.append(str(exc))
            if part_path and os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    return {
        "ok": False,
        "pesan": (
            f"gagal setelah {max_attempts} percobaan: "
            f"{errors[-1] if errors else 'unknown error'}"
        ),
        "path": "",
        "attempts": max_attempts,
    }


class _OfficeConversionSession:
    """Reuse satu instance Word/Excel untuk konversi satu peserta."""

    def __init__(self):
        self._pythoncom = None
        self._word = None
        self._excel = None

    def _ensure_com(self):
        if self._pythoncom is not None:
            return
        import pythoncom

        pythoncom.CoInitialize()
        self._pythoncom = pythoncom

    def _word_app(self):
        self._ensure_com()
        if self._word is None:
            import win32com.client

            self._word = win32com.client.DispatchEx("Word.Application")
            self._word.Visible = False
            self._word.DisplayAlerts = False
        return self._word

    def _excel_app(self):
        self._ensure_com()
        if self._excel is None:
            import win32com.client

            self._excel = win32com.client.DispatchEx("Excel.Application")
            self._excel.Visible = False
            self._excel.DisplayAlerts = False
            self._excel.EnableEvents = False
            self._excel.AutomationSecurity = 3
        return self._excel

    def convert(self, src_path: str, dest_pdf: str) -> bool:
        ext = os.path.splitext(src_path)[1].lower()
        if ext in (".docx", ".doc"):
            doc = None
            try:
                word = self._word_app()
                doc = word.Documents.Open(os.path.abspath(src_path), ReadOnly=True)
                doc.SaveAs(os.path.abspath(dest_pdf), FileFormat=17)
                return True
            except Exception:
                return False
            finally:
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass

        if ext in (".xlsx", ".xls"):
            wb = None
            try:
                excel = self._excel_app()
                wb = excel.Workbooks.Open(os.path.abspath(src_path), ReadOnly=True)
                wb.ExportAsFixedFormat(0, os.path.abspath(dest_pdf))
                return True
            except Exception:
                return False
            finally:
                if wb is not None:
                    try:
                        wb.Close(False)
                    except Exception:
                        pass

        return False

    def close(self):
        for app_name in ("_word", "_excel"):
            app = getattr(self, app_name)
            if app is None:
                continue
            try:
                app.Quit()
            except Exception:
                pass
            setattr(self, app_name, None)
        if self._pythoncom is not None:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:
                pass
            self._pythoncom = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _convert_to_pdf(src_path: str, dest_pdf: str, office=None) -> bool:
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

    if office is not None and ext in (".docx", ".doc", ".xlsx", ".xls"):
        return office.convert(src_path, dest_pdf)

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


_7Z_EXE = r"C:\Users\MSI\scoop\shims\7z.exe"


def _ekstrak_arsip(arsip_path: str, dest_folder: str, log_cb=None) -> list:
    """
    Ekstrak file ZIP/RAR/7z ke dest_folder via 7z.exe.
    Return: list path file hasil ekstrak (rekursif, semua file di dalam arsip).
    """
    import subprocess
    import glob

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
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        if hasil.returncode != 0:
            _log(f"    [ekstrak gagal] {os.path.basename(arsip_path)}: {hasil.stderr.strip()[:200]}")
            return []
    except Exception as e:
        _log(f"    [ekstrak error] {e}")
        return []

    # Kumpulkan semua file hasil ekstrak (bukan folder)
    semua_file = []
    for root, dirs, files in os.walk(sub_dir):
        for fname in sorted(files):
            if not fname.startswith("~$"):
                semua_file.append(os.path.join(root, fname))

    _log(f"    Ekstrak {os.path.basename(arsip_path)} → {len(semua_file)} file")
    return semua_file


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
    *,
    http_session=None,
    office=None,
) -> dict:
    """Download satu peserta dengan resource HTTP/Office yang dapat dipakai ulang."""
    owns_http_session = http_session is None
    owns_office = office is None
    if http_session is None:
        http_session = requests.Session()
    if office is None:
        office = _OfficeConversionSession()
    try:
        try:
            cookie_str = spse_browser.get_spse_cookies()
        except Exception:
            # Pertahankan fallback lama: _download_file akan mencoba mengambil
            # cookie ulang per attempt jika snapshot cookie awal gagal.
            cookie_str = None
        return _download_teknis_biaya_peserta_impl(
            id_nontender=id_nontender,
            nama_peserta=nama_peserta,
            folder_paket=folder_paket,
            urutan=urutan,
            progress_cb=progress_cb,
            http_session=http_session,
            office=office,
            cookie_str=cookie_str,
        )
    finally:
        if owns_office:
            try:
                office.close()
            except Exception:
                pass
        if owns_http_session:
            try:
                http_session.close()
            except Exception:
                pass


def _download_teknis_biaya_peserta_impl(
    id_nontender: str,
    nama_peserta: str,
    folder_paket: str,
    urutan: int,
    progress_cb=None,
    *,
    http_session,
    office,
    cookie_str: str | None,
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
    dest_folder = os.path.join(folder_paket, "9. Dokumen Teknis Biaya", f"{urutan}. {slug_nama}")
    os.makedirs(dest_folder, exist_ok=True)

    _log(f"  Fetch dokumen teknis id={id_nontender}...")
    res_dok = fetch_dokumen_teknis_biaya_pl(id_nontender)
    if not res_dok["ok"]:
        return {"ok": False, "files_downloaded": 0, "pdf_gabungan_path": "", "pesan": res_dok["pesan"]}

    dokumen = res_dok["dokumen"]
    files_pdf = []
    n_dl = 0
    failed_documents = []

    for i, dok in enumerate(dokumen):
        _log(f"  [{i+1}/{len(dokumen)}] {dok['nama']}")
        nama_file = _slug(dok["nama"])
        if not any(nama_file.lower().endswith(ext) for ext in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".zip", ".rar", ".7z")):
            nama_file += ".pdf"
        dest_file = os.path.join(dest_folder, nama_file)
        res_dl = _download_file(
            dok["url"],
            dest_file,
            http_session=http_session,
            cookie_str=cookie_str,
        )
        if not res_dl["ok"]:
            _log(f"    [GAGAL] {res_dl['pesan']}")
            failed_documents.append(
                {
                    "nama": dok.get("nama", nama_file),
                    "section": dok.get("section", ""),
                    "pesan": res_dl["pesan"],
                }
            )
            continue
        actual_path = res_dl["path"]
        n_dl += 1

        ext = os.path.splitext(actual_path)[1].lower()

        # Ekstrak arsip ZIP/RAR/7z → proses tiap file di dalamnya
        if ext in (".zip", ".rar", ".7z"):
            extracted = _ekstrak_arsip(actual_path, dest_folder, _log)
            for ef in extracted:
                ef_ext = os.path.splitext(ef)[1].lower()
                if ef_ext == ".pdf":
                    files_pdf.append(ef)
                elif ef_ext in (".docx", ".doc", ".xlsx", ".xls", ".jpg", ".jpeg", ".png", ".bmp", ".tiff"):
                    ef_pdf = os.path.splitext(ef)[0] + ".pdf"
                    if _convert_to_pdf(ef, ef_pdf, office=office):
                        files_pdf.append(ef_pdf)
                        _log(f"    Konversi {ef_ext} -> PDF OK ({os.path.basename(ef)})")
                    else:
                        _log(f"    [skip] gagal konversi {ef_ext} ({os.path.basename(ef)})")
            continue

        # Konversi ke PDF jika perlu
        if ext != ".pdf":
            pdf_path = os.path.splitext(actual_path)[0] + ".pdf"
            ok_conv = _convert_to_pdf(actual_path, pdf_path, office=office)
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
    semua_pdf = []
    seen_pdf = set()
    for pdf_path in files_pdf:
        normalized = os.path.normcase(os.path.abspath(pdf_path))
        if (
            os.path.isfile(pdf_path)
            and normalized not in seen_pdf
            and os.path.basename(pdf_path) != gabungan_nama
            and not os.path.basename(pdf_path).startswith("~$")
        ):
            semua_pdf.append(pdf_path)
            seen_pdf.add(normalized)
    semua_pdf.extend(
        os.path.join(dest_folder, f)
        for f in sorted(os.listdir(dest_folder))
        if f.lower().endswith(".pdf")
        and f != gabungan_nama
        and not f.startswith("~$")
        and os.path.normcase(os.path.abspath(os.path.join(dest_folder, f)))
        not in seen_pdf
    )

    if semua_pdf:
        _log(f"  Gabung {len(semua_pdf)} PDF -> {gabungan_nama}...")
        ok_gabung = _gabung_pdf(gabungan_path, semua_pdf, _log)
        if not ok_gabung:
            gabungan_path = ""
            _log("  [skip] tidak ada halaman berhasil digabung")
    else:
        gabungan_path = ""
        _log("  Tidak ada PDF untuk digabung")

    marker_path = os.path.join(
        dest_folder,
        "_DOWNLOAD_TIDAK_LENGKAP.txt",
    )
    download_complete = (
        bool(dokumen)
        and n_dl == len(dokumen)
        and not failed_documents
    )
    if download_complete:
        if os.path.exists(marker_path):
            os.remove(marker_path)
    else:
        lines = [
            "DOWNLOAD DOKUMEN TEKNIS/BIAYA TIDAK LENGKAP",
            f"SPSE ditemukan: {len(dokumen)} dokumen",
            f"Berhasil: {n_dl} dokumen",
            "Gagal:",
        ]
        lines.extend(
            f"- {item['nama']}: {item['pesan']}"
            for item in failed_documents
        )
        with open(marker_path, "w", encoding="utf-8") as marker:
            marker.write("\n".join(lines) + "\n")

    return {
        "ok": download_complete,
        "files_expected": len(dokumen),
        "files_downloaded": n_dl,
        "failed_documents": failed_documents,
        "pdf_gabungan_path": gabungan_path,
        "pesan": (
            f"{n_dl}/{len(dokumen)} file didownload"
            + (
                f", {len(failed_documents)} gagal"
                if failed_documents
                else ""
            )
            + (
                f", gabungan: {gabungan_nama}"
                if gabungan_path
                else ""
            )
        ),
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
