"""Scrape harga penawaran peserta dari SPSE → upsert ke Supabase tabel harga_penawaran."""

import os
import re
import requests
from bs4 import BeautifulSoup
from config import sb as _sb, SPSE_BASE_URL
import spse_browser


def _headers() -> dict:
    return {
        "Cookie": spse_browser.get_spse_cookies(),
        "User-Agent": "Mozilla/5.0",
    }


def _parse_rp(s: str) -> float:
    if not s:
        return 0.0
    cleaned = re.sub(r"[Rp.\s]", "", s).replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def fetch_peserta_ids(kode_tender: str) -> list:
    """
    GET /peserta/{kode_tender}/penawaran → list {peserta_id, nama_peserta}.
    Hanya peserta yang sudah kirim penawaran (ada link rincian_penawaran).
    """
    url = f"{SPSE_BASE_URL}peserta/{kode_tender}/penawaran"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    hasil = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/rincian_penawaran" not in href:
            continue
        # href: /tapinkab/peserta/{peserta_id}/rincian_penawaran
        parts = href.rstrip("/").split("/")
        peserta_id = parts[-2]
        if peserta_id in seen:
            continue
        seen.add(peserta_id)

        # Ambil nama peserta dari baris tabel yang sama
        td = a.find_parent("td")
        tr = td.find_parent("tr") if td else None
        nama = ""
        if tr:
            cells = tr.find_all("td")
            if len(cells) >= 2:
                nama = cells[1].get_text(strip=True)

        hasil.append({"peserta_id": peserta_id, "nama_peserta": nama})

    return hasil


def scrape_rincian_penawaran(peserta_id: str) -> dict:
    """
    GET /peserta/{peserta_id}/rincian_penawaran → parse tblRincian.
    Return: {"items": [...], "total_penawaran": float, "nama_peserta": str}

    Mapping kolom tblRincian (13 kolom, verified):
      0=jenis_bj, 1=satuan, 2=vol,
      3-7=PPK (harga_satuan, total_sbl_pajak, pajak, total_stlh_pajak, ket),
      8=Peserta harga_satuan, 9=total_sbl_pajak, 10=pajak_pct,
      11=total_stlh_pajak, 12=keterangan
    """
    url = f"{SPSE_BASE_URL}peserta/{peserta_id}/rincian_penawaran"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Nama peserta dari tblTeknis
    nama_peserta = ""
    tbl_teknis = soup.find("table", id="tblTeknis")
    if tbl_teknis:
        for row in tbl_teknis.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2 and "Nama Peserta" in cells[0].get_text():
                nama_peserta = cells[1].get_text(strip=True)
                break

    tbl = soup.find("table", id="tblRincian")
    if not tbl:
        return {"items": [], "total_penawaran": 0.0, "nama_peserta": nama_peserta}

    rows = tbl.find_all("tr")
    items = []
    total_penawaran = 0.0
    urutan = 0

    for row in rows[2:]:  # skip 2 header rows
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            continue

        # Baris Total Penawaran
        if len(cells) >= 4 and "Total Penawaran" in cells[2]:
            total_penawaran = _parse_rp(cells[3])
            continue

        # Baris divisi/header section (colspan → sedikit cell, teks mengandung "DIVISI")
        if len(cells) < 11:
            teks = " ".join(cells)
            if not teks.strip():
                continue
            if "Produk Dalam Negeri" in teks or "PDN" in teks:
                continue
            if teks.strip():
                urutan += 1
                items.append({
                    "urutan":           urutan,
                    "jenis_bj":         teks,
                    "satuan":           None,
                    "vol":              None,
                    "harga_satuan":     None,
                    "pajak_pct":        None,
                    "total_stlh_pajak": None,
                    "is_divisi":        True,
                })
            continue

        jenis_bj  = cells[0]
        satuan    = cells[1]
        vol_raw   = cells[2]
        harga_raw = cells[8]
        pajak_raw = cells[10]
        total_raw = cells[11]

        is_divisi = (satuan == "" and vol_raw == "" and harga_raw == "")

        urutan += 1
        items.append({
            "urutan":          urutan,
            "jenis_bj":        jenis_bj,
            "satuan":          satuan or None,
            "vol":             _parse_rp(vol_raw) or None,
            "harga_satuan":    _parse_rp(harga_raw) or None,
            "pajak_pct":       _parse_rp(pajak_raw) or None,
            "total_stlh_pajak": _parse_rp(total_raw) or None,
            "is_divisi":       is_divisi,
        })

    return {
        "items":           items,
        "total_penawaran": total_penawaran,
        "nama_peserta":    nama_peserta,
    }


def upsert_harga_penawaran(kode_tender: str, peserta_id: str,
                           nama_peserta: str, hasil: dict) -> int:
    """Upsert semua item ke tabel harga_penawaran. Return jumlah record."""
    records = []
    for it in hasil["items"]:
        records.append({
            "kode_tender":     kode_tender,
            "peserta_id":      peserta_id,
            "nama_peserta":    nama_peserta,
            "urutan":          it["urutan"],
            "jenis_bj":        it["jenis_bj"],
            "satuan":          it["satuan"],
            "vol":             it["vol"],
            "harga_satuan":    it["harga_satuan"],
            "pajak_pct":       it["pajak_pct"],
            "total_stlh_pajak": it["total_stlh_pajak"],
            "is_divisi":       it["is_divisi"],
            "total_penawaran": hasil["total_penawaran"],
        })

    if records:
        _sb().table("harga_penawaran").upsert(records).execute()

    return len(records)


def scrape_dan_upsert_semua(kode_tender: str, progress_cb=None,
                            peserta_override: list[dict] | None = None) -> dict:
    """
    Entry point utama: scrape semua peserta → upsert ke Supabase.
    peserta_override: [{"peserta_id", "nama_peserta"}] — jika diisi, skip fetch_peserta_ids.
    Return: {"peserta": int, "items": int, "errors": [...]}
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    if peserta_override:
        peserta_list = peserta_override
        log(f"HP: scrape {len(peserta_list)} peserta dari KK Evaluasi")
    else:
        peserta_list = fetch_peserta_ids(kode_tender)
        if not peserta_list:
            return {"peserta": 0, "items": 0, "errors": ["Tidak ada peserta yang sudah kirim penawaran"]}
        log(f"Ditemukan {len(peserta_list)} peserta dengan penawaran")

    total_items = 0
    errors = []

    for p in peserta_list:
        pid   = p["peserta_id"]
        nama  = p["nama_peserta"]
        try:
            log(f"Scraping: {nama} ({pid})...")
            hasil = scrape_rincian_penawaran(pid)
            # Gunakan nama dari tblTeknis jika nama dari tabel peserta kosong
            nama_final = hasil["nama_peserta"] or nama
            count = upsert_harga_penawaran(kode_tender, pid, nama_final, hasil)
            total_items += count
            log(f"  ✅ {nama_final}: {count} item, total Rp {hasil['total_penawaran']:,.0f}")
        except Exception as e:
            errors.append(f"{nama} ({pid}): {e}")
            log(f"  ❌ {nama}: {e}")

    return {
        "peserta": len(peserta_list),
        "items":   total_items,
        "errors":  errors,
    }


# ============================================================
# Tulis harga penawaran ke sheet "6. Harga Penawaran" via COM
# ============================================================

_SHEET_PENAWARAN = "6. Harga Penawaran"

# Kolom awal tiap blok peserta (0-based: 0=A, 9=J, 18=S)
_BLOK_START_COLS = [0, 9, 18]  # A, J, S
_BLOK_LEBAR = 8  # kolom A-H, J-Q, S-Z

# Header kolom dalam satu blok (urutan tetap)
_BLOK_HEADERS = [
    "No", "Jenis Barang/Jasa", "Satuan", "Volume",
    "Harga Satuan (Rp)", "Pajak (%)", "Nilai Pajak", "Total",
]


def _col_idx_to_letter(col_0based: int) -> str:
    """Convert 0-based col index ke huruf Excel (0→A, 25→Z, 26→AA, dst)."""
    result = ""
    n = col_0based + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _tulis_penawaran_ke_sheet(xl_ws, peserta_data: list, progress_cb=None):
    """
    Tulis max 3 peserta secara horizontal ke worksheet yang sudah dibuka.

    peserta_data: [{"nama_peserta": str, "items": [...], "total_penawaran": float}, ...]
    Item fields: urutan, jenis_bj, satuan, vol, harga_satuan, pajak_pct,
                 total_stlh_pajak, is_divisi
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    # Bersih area data lama (A1:Z + cukup baris)
    last_row_clear = max(
        xl_ws.Cells(xl_ws.Rows.Count, 1).End(-4162).Row,  # xlUp
        xl_ws.Cells(xl_ws.Rows.Count, 2).End(-4162).Row,
        200,  # jangkau baris hantu lama
    )
    if last_row_clear >= 1:
        rng_clear = xl_ws.Range(f"A1:Z{last_row_clear}")
        rng_clear.ClearContents()
        rng_clear.Interior.ColorIndex = -4142  # xlNone
        # Hapus merge lama di area tersebut
        try:
            rng_clear.UnMerge()
        except Exception:
            pass

    for blok_idx, peserta in enumerate(peserta_data[:3]):
        col_start = _BLOK_START_COLS[blok_idx]  # 0-based
        nama = peserta.get("nama_peserta") or f"Peserta {blok_idx + 1}"
        items = peserta.get("items", [])

        _log(f"Tulis blok {blok_idx + 1}: {nama} ({len(items)} item)")

        # ── Baris 1: nama peserta (merge 8 kolom) ────────────────────────────
        col_end = col_start + _BLOK_LEBAR - 1  # 0-based end
        letter_start = _col_idx_to_letter(col_start)
        letter_end = _col_idx_to_letter(col_end)

        xl_ws.Range(f"{letter_start}1:{letter_end}1").Merge()
        xl_ws.Cells(1, col_start + 1).Value = nama  # Cells pakai 1-based

        # ── Baris 2: header kolom ─────────────────────────────────────────────
        for h_idx, header in enumerate(_BLOK_HEADERS):
            xl_ws.Cells(2, col_start + h_idx + 1).Value = header

        # ── Baris 3+: data item ───────────────────────────────────────────────
        baris = 3
        for it in items:
            col1 = col_start + 1  # 1-based kolom pertama blok

            if it.get("is_divisi"):
                # Baris divisi: gabungkan kolom 2-8, tulis teks di kolom 1
                xl_ws.Cells(baris, col1).Value = it.get("urutan")
                div_letter_s = _col_idx_to_letter(col_start + 1)  # kolom B-rel
                div_letter_e = _col_idx_to_letter(col_start + 7)  # kolom H-rel
                xl_ws.Range(f"{div_letter_s}{baris}:{div_letter_e}{baris}").Merge()
                xl_ws.Cells(baris, col_start + 2).Value = it.get("jenis_bj") or ""
            else:
                harga = it.get("harga_satuan") or 0
                pajak_pct = it.get("pajak_pct") or 0
                vol = it.get("vol") or 0
                total = it.get("total_stlh_pajak") or 0

                # Nilai pajak = harga * vol * pajak_pct / 100
                nilai_pajak = round(harga * vol * pajak_pct / 100, 2) if harga and vol else 0

                xl_ws.Cells(baris, col1 + 0).Value = it.get("urutan")
                xl_ws.Cells(baris, col1 + 1).Value = it.get("jenis_bj") or ""
                xl_ws.Cells(baris, col1 + 2).Value = it.get("satuan") or ""
                xl_ws.Cells(baris, col1 + 3).Value = vol
                xl_ws.Cells(baris, col1 + 4).Value = harga
                xl_ws.Cells(baris, col1 + 5).Value = pajak_pct
                xl_ws.Cells(baris, col1 + 6).Value = nilai_pajak
                xl_ws.Cells(baris, col1 + 7).Value = total

                # NumberFormat: harga_satuan + nilai_pajak + total → Indonesian
                xl_ws.Cells(baris, col1 + 4).NumberFormat = "#.##0"
                xl_ws.Cells(baris, col1 + 5).NumberFormat = "0"
                xl_ws.Cells(baris, col1 + 6).NumberFormat = "#.##0"
                xl_ws.Cells(baris, col1 + 7).NumberFormat = '#.##0,00'

            baris += 1


def scrape_penawaran_ke_excel(kode_tender: str, xlsm_path: str,
                               progress_cb=None, max_peserta: int = 3) -> dict:
    """
    Scrape harga penawaran top-N peserta termurah → tulis ke sheet '6. Harga Penawaran'.

    Returns: {"peserta": int, "items_per_peserta": [int,...],
              "nama_peserta": [str,...], "errors": [...]}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
    except ImportError:
        return {"peserta": 0, "items_per_peserta": [], "nama_peserta": [],
                "errors": ["win32com tidak tersedia"]}

    xlsm_path = os.path.abspath(xlsm_path)
    if not os.path.isfile(xlsm_path):
        return {"peserta": 0, "items_per_peserta": [], "nama_peserta": [],
                "errors": [f"File tidak ditemukan: {xlsm_path}"]}

    errors = []

    # ── 1. Ambil daftar peserta ───────────────────────────────────────────────
    _log("Mengambil daftar peserta dari SPSE...")
    try:
        peserta_list = fetch_peserta_ids(kode_tender)
    except Exception as e:
        errors.append(f"fetch_peserta_ids: {e}")
        try: pythoncom.CoUninitialize()
        except Exception: pass
        return {"peserta": 0, "items_per_peserta": [], "nama_peserta": [], "errors": errors}

    if not peserta_list:
        try: pythoncom.CoUninitialize()
        except Exception: pass
        return {"peserta": 0, "items_per_peserta": [], "nama_peserta": [],
                "errors": ["Tidak ada peserta yang sudah kirim penawaran"]}

    _log(f"Ditemukan {len(peserta_list)} peserta")

    # ── 2. Scrape rincian tiap peserta ───────────────────────────────────────
    scrape_results = []
    for p in peserta_list:
        pid = p["peserta_id"]
        nama = p["nama_peserta"]
        try:
            _log(f"Scraping: {nama} ({pid})...")
            hasil = scrape_rincian_penawaran(pid)
            nama_final = hasil["nama_peserta"] or nama
            scrape_results.append({
                "peserta_id":     pid,
                "nama_peserta":   nama_final,
                "items":          hasil["items"],
                "total_penawaran": hasil["total_penawaran"],
            })
            # Tetap upsert ke Supabase (dipakai komponen lain)
            try:
                upsert_harga_penawaran(kode_tender, pid, nama_final, hasil)
            except Exception as e_db:
                _log(f"  ⚠ upsert DB: {e_db}")
        except Exception as e:
            errors.append(f"{nama} ({pid}): {e}")
            _log(f"  ❌ {nama}: {e}")

    if not scrape_results:
        try: pythoncom.CoUninitialize()
        except Exception: pass
        return {"peserta": 0, "items_per_peserta": [], "nama_peserta": [],
                "errors": errors or ["Semua peserta gagal di-scrape"]}

    # ── 3. Sort by total_penawaran ascending, ambil top N ────────────────────
    scrape_results.sort(key=lambda x: x["total_penawaran"])
    top_peserta = scrape_results[:max_peserta]
    _log(f"Top {len(top_peserta)} peserta termurah: "
         + ", ".join(p["nama_peserta"] for p in top_peserta))

    # ── 4. Tulis ke Excel via COM ─────────────────────────────────────────────
    xl = None
    wb = None
    try:
        _log(f"Membuka Excel: {os.path.basename(xlsm_path)}")
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(xlsm_path)

        try:
            ws = wb.Sheets(_SHEET_PENAWARAN)
        except Exception:
            raise RuntimeError(f"Sheet '{_SHEET_PENAWARAN}' tidak ditemukan di workbook")

        try:
            ws.Unprotect()
        except Exception:
            pass

        _tulis_penawaran_ke_sheet(ws, top_peserta, progress_cb=progress_cb)

        wb.Save()
        _log("Tersimpan.")

    except Exception as e:
        errors.append(f"COM Excel: {e}")
        _log(f"❌ COM error: {e}")
    finally:
        if wb:
            try: wb.Close(SaveChanges=False)
            except Exception: pass
        if xl:
            try: xl.Quit()
            except Exception: pass
        try: pythoncom.CoUninitialize()
        except Exception: pass

    return {
        "peserta":          len(top_peserta),
        "items_per_peserta": [len(p["items"]) for p in top_peserta],
        "nama_peserta":     [p["nama_peserta"] for p in top_peserta],
        "errors":           errors,
    }


# ============================================================
# Update rumus kolom L di sheet "7.2 Dengan Nego" via COM
# ============================================================

_SHEET_72 = "7.2 Dengan Nego"
_SHEET_6  = "6. Harga Penawaran"


def update_rumus_penawaran_72(xlsm_path: str, progress_cb=None) -> dict:
    """
    Update rumus kolom L di sheet '7.2 Dengan Nego' agar baca langsung dari
    sheet '6. Harga Penawaran' berdasarkan dropdown D5, bukan middleman sheet 7.

    Juga setup Data Validation dropdown D5 dari nama peserta di sheet 6 (A1, J1, S1).

    Returns: {"ok": bool, "rows_updated": int, "error": str|None}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
    except ImportError:
        return {"ok": False, "rows_updated": 0, "error": "win32com tidak tersedia"}

    xlsm_path = os.path.abspath(xlsm_path)
    if not os.path.isfile(xlsm_path):
        return {"ok": False, "rows_updated": 0, "error": f"File tidak ditemukan: {xlsm_path}"}

    xl = None
    wb = None
    rows_updated = 0
    try:
        _log(f"Buka Excel untuk update rumus 7.2: {os.path.basename(xlsm_path)}")
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(xlsm_path)

        # Buka sheet 6 dan 7.2
        try:
            ws6 = wb.Sheets(_SHEET_6)
        except Exception:
            raise RuntimeError(f"Sheet '{_SHEET_6}' tidak ditemukan")
        try:
            ws72 = wb.Sheets(_SHEET_72)
        except Exception:
            raise RuntimeError(f"Sheet '{_SHEET_72}' tidak ditemukan")

        try:
            ws72.Unprotect()
        except Exception:
            pass

        # Baca nama 3 peserta dari sheet 6 (A1, J1, S1)
        nama1 = ws6.Cells(1, 1).Value or ""   # A1
        nama2 = ws6.Cells(1, 10).Value or ""  # J1
        nama3 = ws6.Cells(1, 19).Value or ""  # S1
        nama_valid = [n for n in [nama1, nama2, nama3] if n]
        _log(f"Peserta dari sheet 6: {nama_valid}")

        # Setup Data Validation dropdown D5
        if nama_valid:
            dv_list = ",".join(nama_valid)
            d5 = ws72.Range("D5")
            try:
                d5.Validation.Delete()
                d5.Validation.Add(
                    Type=3,       # xlValidateList
                    AlertStyle=1, # xlValidAlertStop
                    Formula1=dv_list,
                )
            except Exception as _dv_e:
                _log(f"⚠ DV D5: {_dv_e}")
            # Default ke peserta 1 jika D5 kosong atau tidak cocok
            if not d5.Value or d5.Value not in nama_valid:
                d5.Value = nama_valid[0]
            _log(f"D5 = {d5.Value}")

        # Scan baris terakhir dari kolom A (mulai baris 9)
        last_row = int(ws72.Cells(ws72.Rows.Count, 1).End(-4162).Row)  # xlUp
        if last_row < 9:
            _log("Tidak ada data di kolom A baris 9+ — skip update rumus")
            wb.Close(SaveChanges=False)
            return {"ok": True, "rows_updated": 0, "error": None}

        _log(f"Update rumus kolom L baris 9–{last_row}...")
        for r in range(9, last_row + 1):
            # Cek kolom A ada isi (skip baris kosong)
            if ws72.Cells(r, 1).Value is None:
                continue
            # Rumus US-locale (pakai .Formula, koma sebagai separator)
            rumus = (
                f"=IFERROR(IF($D$5='{_SHEET_6}'!$A$1,"
                f"INDEX('{_SHEET_6}'!$E:$E,MATCH(A{r},'{_SHEET_6}'!$A:$A,0)),"
                f"IF($D$5='{_SHEET_6}'!$J$1,"
                f"INDEX('{_SHEET_6}'!$N:$N,MATCH(A{r},'{_SHEET_6}'!$J:$J,0)),"
                f"INDEX('{_SHEET_6}'!$W:$W,MATCH(A{r},'{_SHEET_6}'!$S:$S,0)))),"
                f'"-")'
            )
            ws72.Cells(r, 12).Formula = rumus
            rows_updated += 1

        wb.Save()
        _log(f"Tersimpan. {rows_updated} rumus diupdate.")
        return {"ok": True, "rows_updated": rows_updated, "error": None}

    except Exception as e:
        _log(f"❌ COM error: {e}")
        return {"ok": False, "rows_updated": rows_updated, "error": str(e)}
    finally:
        if wb:
            try: wb.Close(SaveChanges=False)
            except Exception: pass
        if xl:
            try: xl.Quit()
            except Exception: pass
        try: pythoncom.CoUninitialize()
        except Exception: pass
