"""Scrape Harga Penawaran + Harga Terkoreksi peserta dari halaman /evaluasi/{kode}
→ tulis langsung ke matrix Excel sheet '0. Input BA' baris 42 (penawaran) & 43 (terkoreksi).

Endpoint server-rendered HTML (bukan XHR), butuh sesi login (cookie CDP).
Tabel: header 'Harga Penawaran' + 'Harga Terkoreksi', kolom 1=No, 2=Nama Peserta.

Match peserta ke matrix kolom C:L (Peserta 1/2/…/10) lewat nama ternormalisasi
(nama Excel vs SPSE bisa beda spasi/titik) → tulis ke kolom yang cocok.
"""

import os
import re
import requests
import pythoncom
import win32com.client
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser


def _headers() -> dict:
    return {
        "Cookie": spse_browser.get_spse_cookies(),
        "User-Agent": "Mozilla/5.0",
    }


def _norm(nama: str) -> str:
    """Normalisasi nama perusahaan untuk match: upper + buang non-alfanumerik."""
    if not nama:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(nama).upper())


def _parse_rp(s: str):
    """'Rp. 1.274.895.526,14' → 1274895526.14. 'Tidak Ada Penawaran' → None."""
    if not s or "tidak" in s.lower():
        return None
    cleaned = re.sub(r"[Rp\s]", "", s).replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


MAX_PARTICIPANTS = 10
_INPUT_BA_PESERTA_COLS = tuple(range(3, 3 + MAX_PARTICIPANTS))  # C:L


def scrape_evaluasi(kode_tender: str) -> list:
    """GET /evaluasi/{kode} → list dict {nama, penawaran, terkoreksi}."""
    url = f"{SPSE_BASE_URL}evaluasi/{kode_tender}"
    resp = requests.get(url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    target = None
    for tbl in soup.find_all("table"):
        heads = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if "Harga Terkoreksi" in heads:
            target = tbl
            break
    if target is None:
        raise RuntimeError("Tabel evaluasi (Harga Terkoreksi) tidak ditemukan")

    hasil = []
    for tr in target.find_all("tr")[1:]:
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 4:
            continue
        hasil.append({
            "nama": tds[1],
            "penawaran": _parse_rp(tds[2]),
            "terkoreksi": _parse_rp(tds[3]),
        })
    return hasil


def tulis_harga_ke_input_ba(kode_tender: str, xlsm_path: str,
                            progress_cb=None) -> dict:
    """Scrape evaluasi → tulis harga ke matrix canonical C42:L43."""
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    data = scrape_evaluasi(kode_tender)
    # Tabel sudah ter-rank termurah di atas. Ambil seluruh peserta bernilai.
    bernilai = [d for d in data if d["penawaran"] is not None][:MAX_PARTICIPANTS]
    _log(f"Scrape evaluasi: {len(data)} peserta, ambil {len(bernilai)} peserta bernilai")
    lookup = {_norm(d["nama"]): d for d in bernilai}

    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    ditulis = []
    try:
        wb = xl.Workbooks.Open(os.path.abspath(xlsm_path), UpdateLinks=0)
        iba = wb.Sheets("0. Input BA")
        try:
            iba.Unprotect()
        except Exception:
            pass

        import input_ba_engine
        input_ba_engine._ensure_input_ba_layout(iba, len(bernilai))
        iba.Range("C42:L43").ClearContents()

        # Label
        iba.Range("B11").Value = "Harga Penawaran"
        iba.Range("B12").Value = "Harga Penawaran Terkoreksi"

        for col in _INPUT_BA_PESERTA_COLS:
            nama_xl = iba.Cells(38, col).Value  # matrix: baris 38 = Nama Perusahaan
            if not nama_xl:
                continue
            match = lookup.get(_norm(nama_xl))
            if not match:
                _log(f"  Kol {col}: '{nama_xl}' tak match di evaluasi")
                continue
            iba.Cells(42, col).Value = match["penawaran"]
            iba.Cells(43, col).Value = match["terkoreksi"]
            ditulis.append({
                "kolom": col, "nama": nama_xl,
                "penawaran": match["penawaran"],
                "terkoreksi": match["terkoreksi"],
            })
            _log(f"  Kol {col}: {nama_xl} -> "
                 f"P={match['penawaran']} K={match['terkoreksi']}")

        wb.Save()
        wb.Close(SaveChanges=True)
    finally:
        try:
            xl.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()

    return {"jumlah_scrape": len(data), "ditulis": ditulis}


if __name__ == "__main__":
    import sys
    kode = sys.argv[1] if len(sys.argv) > 1 else "10129575000"
    path = sys.argv[2] if len(sys.argv) > 2 else (
        "D:/Dokumen/@ POKJA 2026/1. Belanja Modal Bangunan Kesehatan "
        "(Pembangunan Cytotoxic) - Pokja 001/0. BAPK - 001.xlsm")
    res = tulis_harga_ke_input_ba(kode, path, progress_cb=print)
    print(res)
