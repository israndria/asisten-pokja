"""Scrape harga penawaran peserta dari SPSE → tulis langsung ke Excel."""

import os
import re
import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
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


# ============================================================
# Tulis harga penawaran ke sheet "6. Harga Penawaran" via COM
# ============================================================

_SHEET_PENAWARAN = "6. Harga Penawaran"
MAX_PARTICIPANTS = 10

# Blok peserta berjarak 9 kolom: 8 kolom data + 1 kolom pemisah.
_BLOK_STRIDE = 9
_BLOK_START_COLS = [0, 9, 18]  # A, J, S — kompatibel template lama
_BLOK_LEBAR = 8  # kolom A-H, J-Q, S-Z
_TOTAL_ROW = 200  # baris ringkasan; sengaja di luar area item normal

# Header kolom dalam satu blok (urutan tetap)
_BLOK_HEADERS = [
    "No", "Jenis Barang/Jasa", "Satuan", "Volume",
    "Harga Satuan (Rp)", "Pajak (%)", "Nilai Pajak", "Total",
]


def _block_starts(count: int) -> list[int]:
    count = min(MAX_PARTICIPANTS, max(0, int(count or 0)))
    return [_BLOK_STRIDE * i for i in range(count)]


def _sheet6_block_lookup_formula(row: int, input_col: int, block_count: int) -> str:
    """Formula harga Sheet 0 berdasarkan nama dan seluruh blok Sheet 6."""
    input_letter = _col_idx_to_letter(input_col - 1)
    expr = '"-"'
    for start in reversed(_block_starts(block_count)):
        name_letter = _col_idx_to_letter(start)
        total_letter = _col_idx_to_letter(start + _BLOK_LEBAR - 1)
        expr = (
            f"IF(${input_letter}${row}='{_SHEET_PENAWARAN}'!${name_letter}$1,"
            f"'{_SHEET_PENAWARAN}'!${total_letter}${_TOTAL_ROW},{expr})"
        )
    return f'=IFERROR({expr},"-")'


def _sync_harga_input_ba_from_sheet6(wb, progress_cb=None, participant_count: int = 0):
    """Jadikan Sheet 6 sumber harga untuk Sheet 0, berdasarkan nama peserta.

    Sheet 0 tidak boleh menerima angka harga dari parser/DB lama.  Harga
    penawaran diambil dari jumlah kolom Total pada blok peserta di Sheet 6.
    Pencocokan berdasarkan nama, bukan posisi kolom, agar sorting peserta di
    Sheet 6 tidak dapat menukar harga antar peserta.
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    ws0 = wb.Sheets("0. Input BA")
    ws6 = wb.Sheets(_SHEET_PENAWARAN)
    try:
        ws0.Unprotect()
    except Exception:
        pass

    participant_count = min(MAX_PARTICIPANTS, max(0, int(participant_count or 0)))
    block_count = min(MAX_PARTICIPANTS, max(3, participant_count))
    try:
        import input_ba_engine
        input_ba_engine._ensure_input_ba_layout(ws0, participant_count)
    except Exception as e_layout:
        _log(f"  ⚠️ Layout peserta tambahan Input BA tidak diperbarui: {e_layout}")

    # Matrix kanonik Sheet 0: C:L. Compatibility view C:E/I hanya formula
    # turunan dari matrix dan tidak pernah menjadi target tulis.
    try:
        ws0.Range("C42:L43").ClearContents()
    except Exception:
        pass
    for urutan in range(1, participant_count + 1):
        col = urutan + 2  # peserta 1..10 = C..L
        input_letter = _col_idx_to_letter(col - 1)
        ws0.Cells(42, col).Formula = _sheet6_block_lookup_formula(38, col, block_count)
        ws0.Cells(43, col).Formula = f"={input_letter}42"
        ws0.Cells(42, col).NumberFormat = '#,##0.00'
        ws0.Cells(43, col).NumberFormat = '#,##0.00'
        nama = ws0.Cells(38, col).Value
        if nama:
            _log(f"  Harga {nama}: Sheet 0 matrix <- Sheet 6 (berdasarkan nama)")

    _log("✅ Sheet 0 harga tersinkron dari Sheet 6; tidak memakai nilai parser/DB.")


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
    Tulis seluruh peserta secara horizontal ke worksheet yang sudah dibuka.

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

    peserta_data = list(peserta_data or [])[:MAX_PARTICIPANTS]

    # Bersih area data lama. Sheet lama hanya A:Z; blok tambahan memakai
    # AB:AI, BA:BH, dst dengan stride yang sama.
    last_row_clear = max(
        xl_ws.Cells(xl_ws.Rows.Count, 1).End(-4162).Row,  # xlUp
        xl_ws.Cells(xl_ws.Rows.Count, 2).End(-4162).Row,
        200,  # jangkau baris hantu lama
    )
    try:
        used = xl_ws.UsedRange
        used_last_col = int(used.Column + used.Columns.Count - 1)
    except Exception:
        used_last_col = 26
    requested_last_col = (_block_starts(max(3, len(peserta_data)))[-1] + _BLOK_LEBAR)
    clear_last_col = max(26, used_last_col, requested_last_col)
    if last_row_clear >= 1:
        rng_clear = xl_ws.Range(
            f"A1:{_col_idx_to_letter(clear_last_col - 1)}{last_row_clear}"
        )
        rng_clear.ClearContents()
        rng_clear.Interior.ColorIndex = -4142  # xlNone
        # Hapus merge lama di area tersebut
        try:
            rng_clear.UnMerge()
        except Exception:
            pass

    # Copy format block ketiga ke blok tambahan sebelum menulis. Copy isi lalu
    # clear aman untuk merge/header; format template tetap konsisten.
    for blok_idx, col_start in enumerate(_block_starts(len(peserta_data))):
        if blok_idx < 3:
            continue
        source_start = _BLOK_START_COLS[2]
        source = xl_ws.Range(
            f"{_col_idx_to_letter(source_start)}1:"
            f"{_col_idx_to_letter(source_start + _BLOK_LEBAR - 1)}{last_row_clear}"
        )
        target = xl_ws.Range(
            f"{_col_idx_to_letter(col_start)}1:"
            f"{_col_idx_to_letter(col_start + _BLOK_LEBAR - 1)}{last_row_clear}"
        )
        try:
            source.Copy(Destination=target)
            target.UnMerge()
            target.ClearContents()
        except Exception:
            pass

    for blok_idx, peserta in enumerate(peserta_data):
        col_start = _block_starts(len(peserta_data))[blok_idx]  # 0-based
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

    # Total SPSE ditulis eksplisit agar pembulatan per-item tidak mengubah
    # angka resmi (contoh selisih 0,02 rupiah pada cvrantingutamamakmur).
    for blok_idx, peserta in enumerate(peserta_data):
        col_start = _block_starts(len(peserta_data))[blok_idx]
        xl_ws.Cells(_TOTAL_ROW, col_start + 2).Value = "TOTAL PENAWARAN SPSE"
        xl_ws.Cells(_TOTAL_ROW, col_start + 8).Value = peserta.get("total_penawaran") or 0
        xl_ws.Cells(_TOTAL_ROW, col_start + 8).NumberFormat = '#,##0.00'


def scrape_penawaran_ke_excel(kode_tender: str, xlsm_path: str,
                               progress_cb=None, max_peserta: int | None = None,
                               peserta_override: list[dict] | None = None) -> dict:
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
    if peserta_override is not None:
        peserta_list = list(peserta_override)
        _log(f"Memakai {len(peserta_list)} peserta terpilih dari KK Evaluasi.")
    else:
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

    if peserta_override is None:
        _log(f"Ditemukan {len(peserta_list)} peserta dari SPSE.")

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
        except Exception as e:
            errors.append(f"{nama} ({pid}): {e}")
            _log(f"  ❌ {nama}: {e}")

    if not scrape_results:
        try: pythoncom.CoUninitialize()
        except Exception: pass
        return {"peserta": 0, "items_per_peserta": [], "nama_peserta": [],
                "errors": errors or ["Semua peserta gagal di-scrape"]}

    # ── 3. Sort by total_penawaran ascending, ambil seluruh peserta default ─
    scrape_results.sort(key=lambda x: x["total_penawaran"])
    requested_limit = len(scrape_results) if max_peserta is None else max(0, int(max_peserta))
    limit = min(MAX_PARTICIPANTS, requested_limit)
    top_peserta = scrape_results[:limit]
    if requested_limit > MAX_PARTICIPANTS:
        _log(f"⚠️ Peserta dibatasi maksimal {MAX_PARTICIPANTS} (dari {requested_limit}).")
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

        # Harga total di Sheet 0 harus selalu mengikuti rincian Sheet 6 yang
        # baru saja ditulis. Ini mencegah angka stale dari workbook/template.
        _sync_harga_input_ba_from_sheet6(
            wb, progress_cb=progress_cb, participant_count=len(top_peserta)
        )

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

    Juga setup Data Validation dropdown D5 dari seluruh blok peserta di Sheet 6.

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

        # Baca seluruh header blok: A1, J1, S1, AB1, ...
        try:
            used = ws6.UsedRange
            used_last_col = int(used.Column + used.Columns.Count - 1)
        except Exception:
            used_last_col = 26
        max_blocks = min(MAX_PARTICIPANTS, max(3, (used_last_col + _BLOK_STRIDE - 1) // _BLOK_STRIDE))
        blocks = []
        for idx in range(max_blocks):
            start = _BLOK_STRIDE * idx
            nama = ws6.Cells(1, start + 1).Value or ""
            if nama:
                blocks.append((str(nama), start))
        nama_valid = [n for n, _ in blocks]
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
                _log(f"  Catatan: dropdown D5 tidak diperbarui; nilai tetap diatur manual ({_dv_e})")
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
            # Rumus US-locale (pakai .Formula, koma sebagai separator).
            # Nested IF menjaga kompatibilitas Excel lama tanpa CHOOSECOLS.
            expr = '"-"'
            for _nama, _start in reversed(blocks):
                _name_col = _col_idx_to_letter(_start)
                _price_col = _col_idx_to_letter(_start + 4)
                expr = (
                    f"IF($D$5='{_SHEET_6}'!${_name_col}$1,"
                    f"INDEX('{_SHEET_6}'!${_price_col}:${_price_col},"
                    f"MATCH(A{r},'{_SHEET_6}'!${_name_col}:${_name_col},0)),{expr})"
                )
            rumus = f'=IFERROR({expr},"-")'
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
