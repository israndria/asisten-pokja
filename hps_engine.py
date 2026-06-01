"""Scrape + upsert data HPS dari SPSE ke Supabase tabel hps_items."""

import os
import re
from decimal import Decimal, ROUND_HALF_UP
from config import sb as _sb, SPSE_BASE_URL


def _parse_rp(s: str) -> float:
    """'7.689.500,00' → 7689500.0"""
    if not s:
        return 0.0
    cleaned = re.sub(r"[Rp.\s]", "", s).replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _fetch_data_var(kode_tender: str) -> list:
    """
    Ambil variabel JS `data` dari halaman HPS — berisi semua item sebagai JSON array.
    Jauh lebih andal daripada parse DOM tabel yang dibatasi 20 baris.
    """
    import spse_browser

    url = f"{SPSE_BASE_URL}dokumen/{kode_tender}/hps"
    spse_browser.buka_browser(navigate=False)

    # Cari tab yang sudah buka halaman HPS ini
    page = next((p for p in spse_browser._context.pages if f"/{kode_tender}/hps" in p.url), None)
    if page is not None:
        spse_browser._run(page.reload(wait_until="networkidle", timeout=30000))
    else:
        # Buka tab baru — jangan pakai pages[0] yang mungkin sedang navigasi (→ frame detach)
        page = spse_browser._run(spse_browser._context.new_page())
        try:
            spse_browser._run(page.goto(url, wait_until="networkidle", timeout=30000))
        except Exception:
            # Fallback: domcontentloaded lebih toleran kalau networkidle timeout
            spse_browser._run(page.goto(url, wait_until="domcontentloaded", timeout=30000))

    result = spse_browser._run(page.evaluate("() => typeof data !== 'undefined' ? data : []"))
    # Tutup tab sementara biar tidak numpuk
    try:
        spse_browser._run(page.close())
    except Exception:
        pass
    return result


def scrape_hps(kode_tender: str, session=None) -> dict:
    """
    Scrape HPS dari variabel JS `data` di halaman /dokumen/{kode_tender}/hps.
    Return dict: {"items": [...], "total_nilai": float, "total_nilai_bulat": float}
    """
    raw = _fetch_data_var(kode_tender)

    if not raw:
        return {"items": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}

    items = []
    for i, d in enumerate(raw):
        jenis_bj  = (d.get("item") or "").strip()
        satuan    = (d.get("unit") or "").strip()
        vol       = float(d.get("vol") or 0)
        harga     = float(d.get("harga") or 0)
        pajak_pct = float(d.get("pajak") or 0)
        total_spse = float(d.get("total_harga") or 0)
        kbki      = (d.get("kbki") or "").strip()

        is_divisi = (satuan == "" and harga == 0)

        if not is_divisi and vol > 0 and harga > 0:
            total_hitung = float(
                (Decimal(str(vol)) * Decimal(str(harga)) * (1 + Decimal(str(pajak_pct)) / 100))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
            selisih    = round(abs(total_spse - total_hitung), 2)
            selisih_ok = selisih <= 1.0
        else:
            total_hitung = 0.0
            selisih      = 0.0
            selisih_ok   = True

        urutan = i + 1  # posisi asli 1-based, sama untuk item maupun divisi

        items.append({
            "urutan":       urutan,
            "jenis_bj":     jenis_bj,
            "satuan":       satuan,
            "vol":          vol,
            "harga":        harga,
            "pajak_pct":    pajak_pct,
            "total_spse":   total_spse,
            "total_hitung": total_hitung,
            "kbki":         kbki,
            "is_divisi":    is_divisi,
            "selisih":      selisih,
            "selisih_ok":   selisih_ok,
        })

    # Total nilai dari sum total_harga item (exclude divisi yang total_harga=0)
    total_nilai = round(sum(float(d.get("total_harga") or 0) for d in raw), 2)
    from math import ceil
    total_nilai_bulat = float(ceil(total_nilai))

    return {
        "items":             items,
        "total_nilai":       total_nilai,
        "total_nilai_bulat": total_nilai_bulat,
    }


def upsert_hps(kode_tender: str, hasil: dict) -> dict:
    """
    Upsert semua item HPS ke Supabase tabel hps_items.
    PK: (kode_tender, urutan)
    """
    sb = _sb()
    records = []
    for it in hasil["items"]:
        records.append({
            "kode_tender":        kode_tender,
            "urutan":             it["urutan"],
            "jenis_bj":           it["jenis_bj"],
            "satuan":             it["satuan"] or None,
            "vol":                it["vol"] or None,
            "harga":              it["harga"] or None,
            "pajak_pct":          it["pajak_pct"] or None,
            "total_spse":         it["total_spse"] or None,
            "total_hitung":       it["total_hitung"] or None,
            "kbki":               it["kbki"] or None,
            "is_divisi":          it["is_divisi"],
            "selisih":            it["selisih"],
            "selisih_ok":         it["selisih_ok"],
            "total_nilai":        hasil["total_nilai"],
            "total_nilai_bulat":  hasil["total_nilai_bulat"],
        })

    # Hapus dulu semua row lama paket ini — cegah baris hantu kalau BoQ
    # menyusut (upsert PK (kode_tender,urutan) cuma overwrite, surplus urutan
    # lama tidak ikut terhapus).
    sb.table("hps_items").delete().eq("kode_tender", kode_tender).execute()

    if records:
        sb.table("hps_items").upsert(records).execute()

    return {
        "count":   len(records),
        "warning": [it for it in hasil["items"] if not it["selisih_ok"]],
    }


def scrape_dan_upsert_hps(kode_tender: str, session=None) -> dict:
    """
    Fungsi utama: scrape HPS dari SPSE → upsert ke Supabase.
    Return: {"count", "warning", "total_nilai", "total_nilai_bulat", "error"}
    """
    try:
        hasil = scrape_hps(kode_tender, session)
        if not hasil["items"]:
            return {"count": 0, "warning": [], "total_nilai": 0.0,
                    "total_nilai_bulat": 0.0, "error": "Tidak ada item HPS ditemukan"}
        r = upsert_hps(kode_tender, hasil)
        return {
            "count":             r["count"],
            "warning":           r["warning"],
            "total_nilai":       hasil["total_nilai"],
            "total_nilai_bulat": hasil["total_nilai_bulat"],
            "error":             None,
        }
    except Exception as e:
        return {"count": 0, "warning": [], "total_nilai": 0.0,
                "total_nilai_bulat": 0.0, "error": str(e)}


# ============================================================
# Tulis HPS langsung ke Excel sheet "5. HPS" (tanpa Supabase)
# ============================================================

_SHEET_HPS = "5. HPS"


def _tulis_hps_ke_sheet(excel_path: str, hasil: dict, progress_cb=None) -> dict:
    """
    Tulis hasil scrape HPS ke sheet '5. HPS' via COM. Pola identik input_ba_engine.

    Layout sheet (port dari VBA MuatHPS):
      Header baris 1, data dari baris 2.
      A=urutan, B=jenis_bj, C=satuan, D=vol, E=harga, F=pajak_pct,
      G=total_spse, H=total_hitung, I=selisih.
      Divisi: hanya A+B terisi. Baris selisih>1 di-highlight kuning.
      Setelah item: TOTAL NILAI (SPSE) / (Setelah Pembulatan SPSE) / HITUNG MANUAL.

    Return: {"ok": bool, "pesan": str, "count": int, "warning": list}
    """
    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    items = hasil["items"]

    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
    except ImportError:
        return {"ok": False, "pesan": "win32com tidak tersedia", "count": 0, "warning": []}

    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        return {"ok": False, "pesan": f"File tidak ditemukan: {excel_path}", "count": 0, "warning": []}

    _log(f"Membuka Excel: {os.path.basename(excel_path)}")

    xl = None
    wb = None
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(excel_path)
        try:
            ws = wb.Sheets(_SHEET_HPS)
        except Exception:
            raise RuntimeError(f"Sheet '{_SHEET_HPS}' tidak ditemukan")
    except Exception as e:
        if wb:
            try: wb.Close(SaveChanges=False)
            except Exception: pass
        if xl:
            try: xl.Quit()
            except Exception: pass
        try: pythoncom.CoUninitialize()
        except Exception: pass
        return {"ok": False, "pesan": f"Gagal buka Excel: {e}", "count": 0, "warning": []}

    try:
        try: ws.Unprotect()
        except Exception: pass

        # ── Bersih A2:I bawah + highlight ────────────────────────────────────
        # Ambil baris terakhir dari kolom A DAN B (data lama bisa lebih panjang
        # di salah satunya), pakai yang terbesar agar baris hantu ikut terhapus.
        last_a = ws.Cells(ws.Rows.Count, 1).End(-4162).Row  # xlUp
        last_b = ws.Cells(ws.Rows.Count, 2).End(-4162).Row
        last_row = max(last_a, last_b, 60)  # min 60: jangkau baris total lama
        if last_row >= 2:
            rng = ws.Range(f"A2:I{last_row}")
            rng.ClearContents()   # WAJIB pakai () — tanpa kurung = property, tidak eksekusi
            rng.Interior.ColorIndex = -4142  # xlNone

        RGB_KUNING = 65535  # RGB(255,255,0)
        baris = 2
        total_hitung_all = 0.0
        total_nilai = hasil["total_nilai"]
        total_bulat = hasil["total_nilai_bulat"]
        warning = []

        for it in items:
            ws.Cells(baris, 1).Value = it["urutan"]
            ws.Cells(baris, 2).Value = it["jenis_bj"]
            if not it["is_divisi"]:
                if it["satuan"]:
                    ws.Cells(baris, 3).Value = it["satuan"]
                if it["vol"]:
                    ws.Cells(baris, 4).Value = it["vol"]
                    ws.Cells(baris, 4).NumberFormat = "#,##0.00"
                if it["harga"]:
                    ws.Cells(baris, 5).Value = it["harga"]
                    ws.Cells(baris, 5).NumberFormat = "#,##0.00"
                if it["pajak_pct"]:
                    ws.Cells(baris, 6).Value = it["pajak_pct"]
                    ws.Cells(baris, 6).NumberFormat = "0.00"
                if it["total_spse"]:
                    ws.Cells(baris, 7).Value = it["total_spse"]
                    ws.Cells(baris, 7).NumberFormat = "#,##0.00"
                if it["total_hitung"]:
                    ws.Cells(baris, 8).Value = it["total_hitung"]
                    ws.Cells(baris, 8).NumberFormat = "#,##0.00"
                ws.Cells(baris, 9).Value = it["selisih"]
                ws.Cells(baris, 9).NumberFormat = "#,##0.00"
                total_hitung_all += it["total_hitung"] or 0.0
                if not it["selisih_ok"]:
                    ws.Range(ws.Cells(baris, 1), ws.Cells(baris, 9)).Interior.Color = RGB_KUNING
                    warning.append(it)
            baris += 1

        # Header H–I jika kosong
        if not ws.Cells(1, 8).Value:
            ws.Cells(1, 8).Value = "Total (Hitung)"
            ws.Cells(1, 8).Font.Bold = True
        if not ws.Cells(1, 9).Value:
            ws.Cells(1, 9).Value = "Selisih"
            ws.Cells(1, 9).Font.Bold = True

        # ── Baris total ──────────────────────────────────────────────────────
        bt = baris + 1
        ws.Cells(bt, 2).Value = "TOTAL NILAI (SPSE)"
        ws.Cells(bt, 2).Font.Bold = True
        ws.Cells(bt, 7).Value = total_nilai
        ws.Cells(bt, 7).NumberFormat = "#,##0.00"

        ws.Cells(bt + 1, 2).Value = "TOTAL NILAI (Setelah Pembulatan SPSE)"
        ws.Cells(bt + 1, 2).Font.Bold = True
        ws.Cells(bt + 1, 7).Value = total_bulat
        ws.Cells(bt + 1, 7).NumberFormat = "#,##0.00"

        ws.Cells(bt + 2, 2).Value = "TOTAL HITUNG MANUAL"
        ws.Cells(bt + 2, 2).Font.Bold = True
        ws.Cells(bt + 2, 8).Value = total_hitung_all
        ws.Cells(bt + 2, 8).NumberFormat = "#,##0.00"

        _log("Menyimpan Excel...")
        wb.Save()
        _log(f"HPS berhasil ditulis: {len(items)} baris.")
        return {
            "ok": True,
            "pesan": f"{len(items)} baris HPS ditulis ke sheet '{_SHEET_HPS}'",
            "count": len(items),
            "warning": warning,
        }
    except Exception as e:
        return {"ok": False, "pesan": f"Error saat menulis: {e}", "count": 0, "warning": []}
    finally:
        if wb:
            try: wb.Close(SaveChanges=False)
            except Exception: pass
        if xl:
            try: xl.Quit()
            except Exception: pass
        try: pythoncom.CoUninitialize()
        except Exception: pass


def scrape_hps_ke_excel(kode_tender: str, excel_path: str, progress_cb=None) -> dict:
    """Tender: scrape HPS dari SPSE → tulis langsung sheet '5. HPS'. Tanpa DB."""
    try:
        hasil = scrape_hps(kode_tender)
        if not hasil["items"]:
            return {"ok": False, "pesan": "Tidak ada item HPS ditemukan", "count": 0,
                    "warning": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}
        r = _tulis_hps_ke_sheet(excel_path, hasil, progress_cb)
        r["total_nilai"] = hasil["total_nilai"]
        r["total_nilai_bulat"] = hasil["total_nilai_bulat"]
        return r
    except Exception as e:
        return {"ok": False, "pesan": str(e), "count": 0, "warning": [],
                "total_nilai": 0.0, "total_nilai_bulat": 0.0}


def scrape_hps_pl_ke_excel(kode_paket: str, excel_path: str, progress_cb=None) -> dict:
    """PL: scrape HPS non-tender (cari id_nontender dari draft_paket_pl) → tulis sheet '5. HPS'."""
    try:
        row = _sb().table("draft_paket_pl").select("id_nontender").eq("kode_paket", kode_paket).maybe_single().execute()
        id_nt = (row.data or {}).get("id_nontender") if row else None
        if not id_nt:
            return {"ok": False, "pesan": "id_nontender tidak ditemukan", "count": 0,
                    "warning": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}
        hasil = scrape_hps_pl(id_nt)
        if not hasil["items"]:
            return {"ok": False, "pesan": "Tidak ada item HPS", "count": 0,
                    "warning": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}
        r = _tulis_hps_ke_sheet(excel_path, hasil, progress_cb)
        r["total_nilai"] = hasil["total_nilai"]
        r["total_nilai_bulat"] = hasil["total_nilai_bulat"]
        return r
    except Exception as e:
        return {"ok": False, "pesan": str(e), "count": 0, "warning": [],
                "total_nilai": 0.0, "total_nilai_bulat": 0.0}


# ============================================================
# PL Mode — HPS Non-Tender
# Endpoint: /dokumennontender/{id_nontender}/hps
# Tabel Supabase: hps_items_pl (PK: kode_paket, urutan)
# ============================================================

def _fetch_data_var_pl(id_nontender: str) -> list:
    """Ambil var JS `data` dari halaman HPS non-tender via requests + cookie PP."""
    import requests
    import json as _json
    import spse_browser

    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return []

    url = f"{SPSE_BASE_URL}dokumennontender/{id_nontender}/hps"
    r = requests.get(
        url,
        headers={
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0",
            "Referer": SPSE_BASE_URL + "admin/pegawai",
        },
        timeout=15,
    )
    if r.status_code != 200:
        return []

    # Parse var data = [...]; dari script tag
    m = re.search(r"var\s+data\s*=\s*(\[.*?\]);\s*(?:var|</script)", r.text, re.DOTALL)
    if not m:
        m = re.search(r"data\s*=\s*(\[\{.+?\}\])", r.text, re.DOTALL)
    if not m:
        return []

    try:
        return _json.loads(m.group(1))
    except _json.JSONDecodeError:
        return []


def scrape_hps_pl(id_nontender: str) -> dict:
    """Scrape HPS PL via id_nontender. Struktur sama dengan tender."""
    raw = _fetch_data_var_pl(id_nontender)
    if not raw:
        return {"items": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}

    items = []
    for i, d in enumerate(raw):
        jenis_bj   = (d.get("item") or "").strip()
        satuan     = (d.get("unit") or "").strip()
        vol        = float(d.get("vol") or 0)
        harga      = float(d.get("harga") or 0)
        pajak_pct  = float(d.get("pajak") or 0)
        total_spse = float(d.get("total_harga") or 0)
        kbki       = (d.get("kbki") or "").strip()

        is_divisi = (satuan == "" and harga == 0)

        if not is_divisi and vol > 0 and harga > 0:
            total_hitung = float(
                (Decimal(str(vol)) * Decimal(str(harga)) * (1 + Decimal(str(pajak_pct)) / 100))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
            selisih    = round(abs(total_spse - total_hitung), 2)
            selisih_ok = selisih <= 1.0
        else:
            total_hitung = 0.0
            selisih      = 0.0
            selisih_ok   = True

        items.append({
            "urutan":       i + 1,
            "jenis_bj":     jenis_bj,
            "satuan":       satuan,
            "vol":          vol,
            "harga":        harga,
            "pajak_pct":    pajak_pct,
            "total_spse":   total_spse,
            "total_hitung": total_hitung,
            "kbki":         kbki,
            "is_divisi":    is_divisi,
            "selisih":      selisih,
            "selisih_ok":   selisih_ok,
        })

    total_nilai = round(sum(float(d.get("total_harga") or 0) for d in raw), 2)
    from math import ceil
    total_nilai_bulat = float(ceil(total_nilai))

    return {
        "items":             items,
        "total_nilai":       total_nilai,
        "total_nilai_bulat": total_nilai_bulat,
    }


def upsert_hps_pl(kode_paket: str, hasil: dict) -> dict:
    """Upsert ke hps_items_pl. PK: (kode_paket, urutan)."""
    sb = _sb()
    records = []
    for it in hasil["items"]:
        records.append({
            "kode_paket":        kode_paket,
            "urutan":            it["urutan"],
            "jenis_bj":          it["jenis_bj"],
            "satuan":            it["satuan"] or None,
            "vol":               it["vol"] or None,
            "harga":             it["harga"] or None,
            "pajak_pct":         it["pajak_pct"] or None,
            "total_spse":        it["total_spse"] or None,
            "total_hitung":      it["total_hitung"] or None,
            "kbki":              it["kbki"] or None,
            "is_divisi":         it["is_divisi"],
            "selisih":           it["selisih"],
            "selisih_ok":        it["selisih_ok"],
            "total_nilai":       hasil["total_nilai"],
            "total_nilai_bulat": hasil["total_nilai_bulat"],
        })

    # Hapus row lama dulu — cegah baris hantu saat BoQ menyusut (lihat upsert_hps).
    sb.table("hps_items_pl").delete().eq("kode_paket", kode_paket).execute()

    if records:
        sb.table("hps_items_pl").upsert(records).execute()

    return {
        "count":   len(records),
        "warning": [it for it in hasil["items"] if not it["selisih_ok"]],
    }


def scrape_dan_upsert_hps_pl(kode_paket: str) -> dict:
    """Scrape HPS PL → upsert. kode_paket dari draft_paket_pl; cari id_nontender otomatis."""
    try:
        row = _sb().table("draft_paket_pl").select("id_nontender").eq("kode_paket", kode_paket).maybe_single().execute()
        id_nt = (row.data or {}).get("id_nontender") if row else None
        if not id_nt:
            return {"count": 0, "warning": [], "total_nilai": 0.0,
                    "total_nilai_bulat": 0.0, "error": "id_nontender tidak ditemukan"}

        hasil = scrape_hps_pl(id_nt)
        if not hasil["items"]:
            return {"count": 0, "warning": [], "total_nilai": 0.0,
                    "total_nilai_bulat": 0.0, "error": "Tidak ada item HPS"}

        r = upsert_hps_pl(kode_paket, hasil)
        return {
            "count":             r["count"],
            "warning":           r["warning"],
            "total_nilai":       hasil["total_nilai"],
            "total_nilai_bulat": hasil["total_nilai_bulat"],
            "error":             None,
        }
    except Exception as e:
        return {"count": 0, "warning": [], "total_nilai": 0.0,
                "total_nilai_bulat": 0.0, "error": str(e)}
