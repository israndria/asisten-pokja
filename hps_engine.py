"""Scrape + upsert data HPS dari SPSE ke Supabase tabel hps_items."""

import os
import re
import time
from html import unescape
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
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


def _parse_amount_decimal(value) -> Decimal | None:
    """Parse nominal Indonesia tanpa kehilangan presisi.

    Nilai HPS resmi pada halaman edit dapat muncul sebagai ``Rp. 1.234.567,00``
    atau sebagai value input ``1234567``.  Jangan lewatkan nominal ini melalui
    float sebelum pembulatan karena satu rupiah dapat berubah pada angka besar.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None

    # Format Indonesia: titik ribuan, koma desimal.  Untuk angka mentah tanpa
    # pemisah, Decimal langsung mempertahankan nilai persisnya.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif "." in text:
        # Markdown/HTML kadang menulis nominal Rupiah bulat sebagai
        # ``Rp 1.235``. Satu titik dengan tepat tiga digit di belakangnya
        # adalah pemisah ribuan; dua digit tetap dianggap pecahan resmi.
        whole, fraction = text.split(".", 1)
        if len(fraction) == 3 and whole.isdigit() and fraction.isdigit():
            text = whole + fraction
    try:
        return Decimal(text)
    except Exception:
        return None


def _parse_official_hps_summary(html: str) -> Decimal | None:
    """Ambil Nilai HPS resmi dari halaman ``/nontender/{kode}/edit``.

    Parser sengaja konservatif: hanya menerima nominal pada window setelah
    label *Nilai HPS*. Jika label/nominal tidak ditemukan, caller wajib
    mempertahankan audit sum item dan tidak mengklaim angka resmi.
    """
    if not html:
        return None
    decoded = unescape(html)
    text = re.sub(r"<[^>]+>", " ", decoded)
    text = re.sub(r"\s+", " ", text)

    label = re.search(r"nilai\s+hps\b", text, re.IGNORECASE)
    if label:
        window = text[label.end():label.end() + 700]
        # Wajib ada prefix Rupiah pada teks tampilan agar angka lain di
        # sekitar form tidak keliru dianggap sebagai HPS.
        match = re.search(r"Rp\.?\s*([0-9][0-9.]*,?[0-9]{0,2})", window, re.IGNORECASE)
        if match:
            parsed = _parse_amount_decimal(match.group(1))
            if parsed is not None:
                # Nilai resmi SPSE dapat memiliki pecahan sen; pertahankan
                # sampai 2 desimal agar tidak berubah menjadi bilangan bulat.
                return parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Fallback untuk form yang menaruh nominal pada input bernama nilai_hps.
    for tag in re.findall(r"<input\b[^>]*>", decoded, re.IGNORECASE):
        if not re.search(r'name=["\'][^"\']*nilai[_-]?hps[^"\']*["\']', tag, re.IGNORECASE):
            continue
        match = re.search(r'value=["\']([^"\']+)', tag, re.IGNORECASE)
        if match:
            parsed = _parse_amount_decimal(match.group(1))
            if parsed is not None:
                return parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return None


def _format_rp(value: float) -> str:
    """Format angka ke format SPSE: Rp. 1.234.567,89."""
    formatted = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"Rp. {formatted}"


def _parse_hps_page(html: str) -> dict:
    """Parse JSON item HPS + TOTAL PAGU dari satu halaman HPS SPSE."""
    import json as _json

    m = re.search(r"var\s+data\s*=\s*(\[.*?\]);\s*(?:var|</script)", html, re.DOTALL)
    if not m:
        m = re.search(r"data\s*=\s*(\[\{.+?\}\])", html, re.DOTALL)
    if not m:
        return {"items": [], "nilai_pagu": ""}

    try:
        items = _json.loads(m.group(1))
    except _json.JSONDecodeError:
        return {"items": [], "nilai_pagu": ""}

    m_pagu = re.search(
        r"TOTAL\s+PAGU\s*:?.{0,300}?Rp\.\s*([\d.,]+)",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return {
        "items": items,
        "nilai_pagu": f"Rp. {m_pagu.group(1)}" if m_pagu else "",
    }


def _fetch_hps_page(kode_tender: str) -> dict:
    """
    Ambil halaman HPS Tender via requests + cookie CDP.
    Satu response membawa rincian HPS dan TOTAL PAGU.
    """
    import requests
    import spse_browser

    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"items": [], "nilai_pagu": ""}

    url = f"{SPSE_BASE_URL}dokumen/{kode_tender}/hps"
    r = requests.get(url, headers={
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"{SPSE_BASE_URL}paket",
    }, timeout=15)
    if r.status_code != 200:
        return {"items": [], "nilai_pagu": ""}
    return _parse_hps_page(r.text)


def _fetch_data_var(kode_tender: str) -> list:
    """Kompatibilitas lama: hanya kembalikan item HPS."""
    return _fetch_hps_page(kode_tender).get("items", [])


def scrape_hps(kode_tender: str, session=None) -> dict:
    """
    Scrape HPS dari variabel JS `data` di halaman /dokumen/{kode_tender}/hps.
    Halaman yang sama juga menjadi sumber `nilai_pagu`.
    """
    page = _fetch_hps_page(kode_tender)
    raw = page.get("items", [])

    if not raw:
        return {
            "items": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0,
            "nilai_pagu": page.get("nilai_pagu", ""), "nilai_hps": "",
        }

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
        "nilai_pagu":        page.get("nilai_pagu", ""),
        "nilai_hps":         _format_rp(total_nilai),
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


def _sync_tender_summary(kode_tender: str, hasil: dict) -> bool:
    """Sinkronkan Pagu/HPS live ke draft_paket setelah scrape HPS berhasil."""
    update = {}
    if hasil.get("nilai_pagu"):
        update["nilai_pagu"] = hasil["nilai_pagu"]
    if hasil.get("nilai_hps"):
        update["nilai_hps"] = hasil["nilai_hps"]
    if not update:
        return False
    try:
        _sb().table("draft_paket").update(update).eq("kode_tender", kode_tender).execute()
        return True
    except Exception:
        return False


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
        metadata_updated = _sync_tender_summary(kode_tender, hasil)
        return {
            "count":             r["count"],
            "warning":           r["warning"],
            "total_nilai":       hasil["total_nilai"],
            "total_nilai_bulat": hasil["total_nilai_bulat"],
            "nilai_pagu":        hasil.get("nilai_pagu", ""),
            "nilai_hps":         hasil.get("nilai_hps", ""),
            "metadata_updated":  metadata_updated,
            "error":             None,
        }
    except Exception as e:
        return {"count": 0, "warning": [], "total_nilai": 0.0,
                "total_nilai_bulat": 0.0, "error": str(e)}


# ============================================================
# Tulis HPS langsung ke Excel sheet "5. HPS" (tanpa Supabase)
# ============================================================

_SHEET_HPS = "5. HPS"


def _tulis_hps_ke_ws(ws, wb, hasil: dict, progress_cb=None) -> dict:
    """
    Tulis data HPS ke worksheet yang SUDAH dibuka (tanpa COM init/open/save/quit).
    Dipanggil dari sesi COM gabungan (HPS + Master Data) agar cukup 1x DispatchEx.

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
        ws.Unprotect()
    except Exception:
        pass

    # Bersih A2:I bawah + reset highlight
    last_a = ws.Cells(ws.Rows.Count, 1).End(-4162).Row  # xlUp
    last_b = ws.Cells(ws.Rows.Count, 2).End(-4162).Row
    last_row = max(last_a, last_b, 60)
    if last_row >= 2:
        rng = ws.Range(f"A2:I{last_row}")
        rng.ClearContents()
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

    # Header H-I jika kosong
    if not ws.Cells(1, 8).Value:
        ws.Cells(1, 8).Value = "Total (Hitung)"
        ws.Cells(1, 8).Font.Bold = True
    if not ws.Cells(1, 9).Value:
        ws.Cells(1, 9).Value = "Selisih"
        ws.Cells(1, 9).Font.Bold = True

    # Baris total
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

    _log(f"HPS ditulis: {len(items)} baris.")
    return {
        "ok": True,
        "pesan": f"{len(items)} baris HPS ditulis ke sheet '{_SHEET_HPS}'",
        "count": len(items),
        "warning": warning,
    }


def _tulis_hps_ke_sheet(excel_path: str, hasil: dict, progress_cb=None) -> dict:
    """
    Tulis hasil scrape HPS ke sheet '5. HPS' via COM (buka Excel sendiri).
    Wrapper: DispatchEx -> Open -> _tulis_hps_ke_ws -> Save -> Close/Quit.
    Dipakai oleh scrape_hps_ke_excel (tender) dan scrape_hps_pl_ke_excel (PL single).
    Untuk bulk-create folder PL, gunakan proses_hps_dan_master_data() di isi_master_data_pl.

    Return: {"ok": bool, "pesan": str, "count": int, "warning": list}
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
        # HPS writer menyimpan .xlsm; pastikan fungsi VBA sudah terdaftar
        # sebelum Excel menghitung formula turunan.
        try:
            xl.AutomationSecurity = 1  # msoAutomationSecurityLow
        except Exception as exc:
            raise RuntimeError(
                "Excel AutomationSecurity gagal diatur ke macro-enabled; "
                "writer dibatalkan agar cache UDF tidak rusak."
            ) from exc
        xl.EnableEvents = False
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
        r = _tulis_hps_ke_ws(ws, wb, hasil, progress_cb)
        _log("Menyimpan Excel...")
        wb.Save()
        return r
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
        r["nilai_pagu"] = hasil.get("nilai_pagu", "")
        r["nilai_hps"] = hasil.get("nilai_hps", "")
        r["metadata_updated"] = _sync_tender_summary(kode_tender, hasil)

        # Auto-generate markdown sebagai sumber data AI
        try:
            md_path = _tulis_hps_ke_md(kode_tender, excel_path, hasil, mode="tender")
            r["md_path"] = md_path
        except Exception as e:
            print(f"Warning: Gagal tulis MD HPS Tender: {e}")

        return r
    except Exception as e:
        return {"ok": False, "pesan": str(e), "count": 0, "warning": [],
                "total_nilai": 0.0, "total_nilai_bulat": 0.0}


def _build_uraian_singkat_pk(items: list, excel_path: str) -> str:
    """Bangun kalimat 'Uraian Singkat Pekerjaan' untuk PK (konstruksi) dari divisi BoQ.

    Format: "Mengerjakan paket pekerjaan {Nama Paket} yaitu : {Divisi A}, {Divisi B} DAN {Divisi C}"
    Divisi diambil dari item is_divisi=True (baris tanpa satuan & harga di BoQ HPS).
    Return "" kalau tidak ada divisi terdeteksi (biar VBA fallback ke template JKK).
    """
    divisi_list = []
    for item in items:
        value = str(item.get("jenis_bj") or "").strip()
        if item.get("is_divisi") and value and value not in divisi_list:
            divisi_list.append(value)
    if not divisi_list:
        return ""

    # Nama paket dari nama folder (parent dari excel_path), bersihkan prefix "N. PLPK - "
    import re as _re
    nama_folder = os.path.basename(os.path.dirname(os.path.abspath(excel_path)))
    # Unit test dan beberapa flow staging menaruh workbook langsung di folder
    # sementara; gunakan nama workbook bila nama parent bukan nama paket.
    if not _re.search(r"\bPL(?:JKK|PK)\b", nama_folder, flags=_re.IGNORECASE):
        nama_folder = os.path.splitext(os.path.basename(excel_path))[0]
    nama_paket = _re.sub(r'^\d+\.\s*(PLJKK|PLPK)\s*-\s*', '', nama_folder).strip()
    nama_paket = _re.sub(r'\s*\(PL\s*-?\s*Ulang\)\s*$', '', nama_paket, flags=_re.IGNORECASE).strip()

    if len(divisi_list) == 1:
        daftar = divisi_list[0]
    else:
        daftar = ", ".join(divisi_list[:-1]) + " DAN " + divisi_list[-1]

    return f"Mengerjakan paket pekerjaan {nama_paket} yaitu : {daftar}"


def scrape_hps_pl_ke_excel(kode_paket: str, excel_path: str, progress_cb=None) -> dict:
    """PL: scrape HPS non-tender via kode_paket (resolve DOKID live) → tulis sheet '5. HPS'."""
    try:
        hasil = scrape_hps_pl(kode_paket)
        if not hasil["items"]:
            return {"ok": False, "pesan": "Tidak ada item HPS", "count": 0,
                    "warning": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}
        r = _tulis_hps_ke_sheet(excel_path, hasil, progress_cb)
        r["total_nilai"] = hasil["total_nilai"]
        r["total_nilai_bulat"] = hasil["total_nilai_bulat"]
        r["nilai_pagu"] = hasil.get("nilai_pagu", "")
        r["nilai_hps"] = hasil.get("nilai_hps", "")
        r["metadata_updated"] = _sync_pl_summary(kode_paket, hasil)

        # Auto-generate markdown sebagai sumber data AI
        try:
            md_path = _tulis_hps_ke_md(kode_paket, excel_path, hasil)
            r["md_path"] = md_path
        except Exception as e:
            print(f"Warning: Gagal tulis MD HPS: {e}")

        # Upsert uraian_singkat_pk ke Supabase (HANYA untuk PK konstruksi, bukan JKK)
        try:
            from config import sb as _sb
            _row = _sb().table("draft_paket_pl").select("jenis_pl").eq("kode_paket", kode_paket).limit(1).execute()
            _jenis = (_row.data[0].get("jenis_pl") or "").upper() if _row.data else ""
            if _jenis == "PK":
                uraian = _build_uraian_singkat_pk(hasil["items"], excel_path)
                if uraian:
                    _sb().table("draft_paket_pl").update({"uraian_singkat": uraian}).eq("kode_paket", kode_paket).execute()
                    r["uraian_singkat"] = uraian
        except Exception as e:
            print(f"Warning: Gagal upsert uraian_singkat: {e}")

        return r
    except Exception as e:
        return {"ok": False, "pesan": str(e), "count": 0, "warning": [],
                "total_nilai": 0.0, "total_nilai_bulat": 0.0}


def tulis_prompt_audit_hps_agy(
    kode_paket: str,
    package_path: str,
    mode: str = "pl",
) -> str:
    """Tulis prompt audit HPS read-only untuk Agent Agy di folder paket PL.

    ``package_path`` boleh berupa folder paket atau path workbook ``.xlsm``.
    Prompt sengaja dibuat terpisah dari ``_HPS_*.md`` supaya tetap tersedia
    ketika fetch HPS gagal atau bulk-create tidak mengisi Excel.
    """
    if mode != "pl":
        raise ValueError("Prompt audit HPS Agy hanya berlaku untuk mode PL")

    path = os.path.abspath(os.fspath(package_path))
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if not folder or not os.path.isdir(folder):
        raise FileNotFoundError(f"Folder paket tidak ditemukan: {folder or path}")

    folder_name = os.path.basename(folder)
    family_match = re.search(r"(?:^|\s)(PLJKK|PLPK)(?:\s*-|\s|$)", folder_name, re.IGNORECASE)
    family = family_match.group(1).upper() if family_match else "PLJKK/PLPK"
    nama_paket = re.sub(r"^\d+\.\s*(PLJKK|PLPK)\s*-\s*", "", folder_name, flags=re.IGNORECASE).strip()
    nama_paket = re.sub(r"\s*\(PL\s*-?\s*Ulang\)\s*$", "", nama_paket, flags=re.IGNORECASE).strip()
    if not nama_paket:
        nama_paket = folder_name

    prompt_path = os.path.join(folder, "_PROMPT_AUDIT_PERUBAHAN_HPS_AGY.md")
    generated_at = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# PROMPT AGY — AUDIT PERUBAHAN HPS PL",
        "",
        "> File ini dibuat otomatis oleh Streamlit. Jalankan instruksi di bawah sebagai Agent Agy.",
        "> Audit bersifat read-only terhadap workbook dan XML. Jangan mengubah data sumber.",
        "",
        "## KONTEKS PAKET",
        f"- Nama paket: **{nama_paket}**",
        f"- Kode paket: `{kode_paket}`",
        f"- Family yang diharapkan: `{family}`",
        f"- Folder paket: `{folder}`",
        f"- Prompt dibuat: `{generated_at}`",
        "",
        "## TUGAS UTAMA",
        "",
        "Periksa apakah HPS terbaru pada paket ini berubah dibandingkan snapshot/XML yang",
        "sudah tersedia di folder paket. Hasil akhir harus membedakan perubahan angka HPS,",
        "perubahan rincian BoQ, XML yang tertinggal, konflik identitas, dan bukti yang belum cukup.",
        "Jangan menganggap adanya file baru otomatis berarti nilai HPS berubah.",
        "",
        "## BATASAN KERAS",
        "",
        "1. Audit ini **read-only** terhadap sumber. Jangan membuka workbook dalam mode edit.",
        "2. Jangan menjalankan `openpyxl.save()`, Excel COM Save, macro `LoadDataPL`, atau VBA.",
        "3. Jangan mengubah atau menghapus `input_data_baseline.xml`.",
        "4. Jangan mengubah `input_data_snapshot.xml` atau membuat `input_data_proposal.xml`.",
        "5. Jangan menjalankan `seed-proposal` atau `promote`; command validasi/compare saja.",
        "6. Jangan menyimpulkan rincian BoQ dari XML. XML snapshot berisi `@ Master Data`,",
        "   bukan seluruh tabel item HPS. Rincian BoQ harus dibaca dari sheet `5. HPS`,",
        "   `_HPS_*.md`, dan/atau sumber HPS live yang tersedia.",
        "7. Jika identitas atau family tidak cocok, berhenti pada status konflik dan jangan",
        "   memaksakan perbandingan antar-paket.",
        "",
        "## SUMBER YANG WAJIB DIPERIKSA",
        "",
        "Cari sumber berikut di folder paket. Catat status ada/tidak ada, path, ukuran,",
        "dan waktu modifikasi setiap sumber dalam laporan:",
        "",
        "1. Workbook `.xlsm` di root folder paket; baca sheet `5. HPS` secara read-only.",
        "   Jika memakai Python, gunakan `openpyxl.load_workbook(..., read_only=True, data_only=True, keep_vba=True)` dan jangan save.",
        "2. File `_HPS_*.md` di root folder; ini ringkasan HPS yang terakhir diserap dari SPSE.",
        "3. `11. XML Data\\input_data_baseline.xml`; snapshot awal dan immutable.",
        "4. `11. XML Data\\input_data_snapshot.xml`; current terakhir yang diterima Excel.",
        "5. `11. XML Data\\input_data_proposal.xml`, jika ada; hanya proposal tertunda, bukan current.",
        "6. `11. XML Data\\input_data_snapshot.bak-*.xml`, jika ada; hanya histori/backup, bukan sumber current.",
        "   Untuk paket legacy tanpa folder itu, resolver boleh fallback ke file root dan tidak boleh menghapusnya.",
        "7. Dokumen pendukung HPS/RAB/KAK di folder paket bila diperlukan untuk menjelaskan",
        "   penyebab perbedaan. Sebutkan nama file dan halaman/worksheet sebagai bukti.",
        "",
        "## SOP RUJUKAN",
        "",
        "Baca SOP yang disalin ke `0. Draft Dokumen PPK` sebelum mengambil kesimpulan:",
        "",
        "- `SOP_REKONSILIASI_XML_DOKUMEN_PPK_CORE.md`.",
        "- `SOP_REKONSILIASI_XML_DOKUMEN_PPK_PLJKK.md` untuk family PLJKK.",
        "- `SOP_REKONSILIASI_XML_DOKUMEN_PPK_PLPK.md` untuk family PLPK.",
        "",
        "Jika SOP paket belum tersedia, gunakan versi kanonik di folder `%POKJA_DRIVE_ROOT%\\_SOP Evaluator`.",
        "",
        "## VALIDASI IDENTITAS DAN PROFILE XML",
        "",
        "1. Pastikan nama folder menunjukkan `PLJKK` atau `PLPK`. Jika tidak jelas, gunakan",
        "   `KONFLIK SUMBER` dan jelaskan alasan.",
        "2. Cocokkan kode paket dari prompt dengan root XML `kode_paket` dan cell `C3`.",
        "3. Cocokkan nama pekerjaan dengan root XML/cell `C5` dan nama workbook bila tersedia.",
        "4. Cocokkan family XML dan layout: `PLJKK-MASTER-DATA-v1` atau `PLPK-MASTER-DATA-v1`.",
        "5. Jalankan validasi lokal berikut dari folder paket (sesuaikan path jika env berbeda):",
        "",
        "```powershell",
        f"$family = '{family}'",
        f"$kode = '{kode_paket}'",
        "$cli = Join-Path $env:POKJA_CODE_ROOT 'procurement_core\\pl_snapshot_revision.py'",
        "if ($env:POKJA_PYTHON) { $py = $env:POKJA_PYTHON } else { $py = 'python' }",
        "$xmlDir = Join-Path (Get-Location) '11. XML Data'",
        "if (!(Test-Path -LiteralPath $xmlDir) ) { $xmlDir = (Get-Location).Path }",
        "foreach ($name in @('input_data_baseline.xml', 'input_data_snapshot.xml', 'input_data_proposal.xml')) {",
        "    $xml = Join-Path $xmlDir $name",
        "    if (Test-Path -LiteralPath $xml) {",
        "        & $py $cli validate $xml --expected-kode-paket $kode --expected-family $family",
        "    }",
        "}",
        "```",
        "",
        "Jika baseline dan current tersedia, buat perbandingan XML read-only:",
        "",
        "```powershell",
        "$baseline = Join-Path $xmlDir 'input_data_baseline.xml'",
        "$current = Join-Path $xmlDir 'input_data_snapshot.xml'",
        "if ((Test-Path -LiteralPath $baseline) -and (Test-Path -LiteralPath $current)) {",
        "    & $py $cli compare $baseline $current --output audit_hps_xml_report.md",
        "}",
        "```",
        "",
        "## PERBANDINGAN HPS YANG WAJIB DILAKUKAN",
        "",
        "### A. XML baseline versus XML current",
        "",
        "Bandingkan sekurang-kurangnya:",
        "",
        "- `C13` = Pagu.",
        "- `C14` = HPS.",
        "- identitas `C3`, `C5`, atribut `family`, dan `layout_version`.",
        "- field lain yang berubah menurut `audit_hps_xml_report.md`, tetapi jangan menyebut",
        "  perubahan non-HPS sebagai perubahan HPS tanpa bukti terkait.",
        "",
        "### B. HPS current dari workbook dan Markdown versus XML current",
        "",
        "Baca sheet `5. HPS` dengan mapping standar:",
        "",
        "- baris data mulai row 2;",
        "- kolom A:I = urutan, jenis B/J, satuan, volume, harga, pajak %, total SPSE, total hitung, selisih;",
        "- baris `TOTAL NILAI (SPSE)`, `TOTAL NILAI (Setelah Pembulatan SPSE)`, dan `TOTAL HITUNG MANUAL` adalah ringkasan;",
        "- bedakan row divisi dari row item.",
        "",
        "Dari `_HPS_*.md`, baca jumlah item, total nilai, total nilai bulat, serta setiap row BoQ.",
        "Bandingkan dengan workbook dan XML current `C14`. Normalisasi nominal secara numerik",
        "(format Rupiah, titik ribuan, koma desimal), lalu tetap laporkan nilai raw dan nilai",
        "setelah pembulatan. Jangan menyamakan total raw dengan total resmi yang sudah dibulatkan.",
        "",
        "Bandingkan item-level jika sumber tersedia:",
        "",
        "- jumlah item dan row divisi;",
        "- urutan dan uraian/jenis B/J;",
        "- satuan;",
        "- volume;",
        "- harga satuan;",
        "- pajak %;",
        "- total SPSE;",
        "- total hitung/manual;",
        "- selisih dan anomali aritmatika.",
        "",
        "Jika workbook, `_HPS_*.md`, dan XML current berbeda, jangan memilih salah satu",
        "secara diam-diam. Jelaskan sumber mana yang lebih baru berdasarkan mtime/metadata",
        "dan nyatakan XML tertinggal atau bukti tidak cukup bila tidak dapat dipastikan.",
        "",
        "## ATURAN VERDICT",
        "",
        "Gunakan tepat satu verdict utama berikut:",
        "",
        "1. `TIDAK ADA PERUBAHAN TERBUKTI` — baseline/current sama pada field HPS yang relevan,",
        "   dan sumber HPS current konsisten dengan XML current tanpa perbedaan item yang terbukti.",
        "2. `ADA PERUBAHAN HPS` — ada perubahan terbukti pada C14, total HPS, atau rincian item",
        "   (uraian/volume/harga/pajak/total) dengan bukti file yang jelas.",
        "3. `PERLU SINKRONISASI / BUKTI TIDAK CUKUP` — sumber penting hilang, XML tertinggal,",
        "   workbook belum pernah di-refresh, atau perbedaan waktu tidak dapat dibuktikan.",
        "4. `KONFLIK SUMBER` — kode paket, nama pekerjaan, family, layout, atau workbook tidak",
        "   cocok sehingga perbandingan tidak aman.",
        "",
        "## OUTPUT WAJIB AGY",
        "",
        "Tulis laporan baru di root folder paket dengan nama:",
        "",
        f"`audit_hps_agy_{kode_paket}.md`",
        "",
        "Laporan minimal memuat:",
        "",
        "- verdict utama di baris pertama setelah judul;",
        "- identitas paket dan hasil validasi family/kode;",
        "- tabel inventaris sumber (path, ada/tidak, mtime, peran);",
        "- tabel perbandingan XML baseline versus current;",
        "- tabel perbandingan workbook `5. HPS`, `_HPS_*.md`, dan XML current;",
        "- daftar perubahan item-level atau pernyataan eksplisit bahwa tidak ada perubahan",
        "  item-level yang terbukti;",
        "- perbedaan raw versus pembulatan;",
        "- bukti sumber file/worksheet/baris/field dan halaman jika dokumen PDF dipakai;",
        "- keterbatasan pemeriksaan;",
        "- rekomendasi tindakan berikutnya tanpa mengubah file sumber.",
        "",
        "## CHECKLIST SEBELUM SELESAI",
        "",
        "- [ ] Family PLJKK/PLPK sudah valid.",
        "- [ ] Kode paket cocok di prompt, XML, dan workbook/sumber HPS.",
        "- [ ] Baseline tidak diubah.",
        "- [ ] Current/proposal tidak diubah.",
        "- [ ] Workbook tidak disimpan.",
        "- [ ] C13/C14 sudah dibandingkan secara numerik.",
        "- [ ] Rincian BoQ dibaca dari sumber HPS, bukan ditebak dari XML.",
        "- [ ] Verdict tepat satu dari empat pilihan.",
        "- [ ] Laporan `audit_hps_agy_<kode_paket>.md` sudah ditulis.",
    ]

    # Rapikan item multiline yang sengaja ditulis sebagai satu blok agar hasil
    # Markdown tetap mudah dibaca tanpa mengubah isi prompt.
    normalized = []
    for line in lines:
        normalized.extend(line.splitlines() or [""])
    with open(prompt_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(normalized) + "\n")
    return prompt_path


def _tulis_hps_ke_md(kode_paket: str, excel_path: str, hasil: dict, mode: str = "pl") -> str:
    """Auto-generate file markdown sebagai sumber data HPS untuk AI pra-reviu.

    mode="pl"     — Pengadaan Langsung JKK/PK (default, backward compat)
    mode="tender" — Tender Pokja (folder naming berbeda, skip auto-parse personil PL)
    """
    folder = os.path.dirname(os.path.abspath(excel_path))

    items = hasil.get("items", [])
    total_nilai = hasil.get("total_nilai", 0)
    total_bulat = hasil.get("total_nilai_bulat", 0)

    # Helper format Rp: pertahankan pecahan sen resmi dari /viewdraft/edit.
    def _rp(n):
        amount = Decimal(str(n or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        formatted = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"Rp {formatted}"

    non_divisi = [it for it in items if not it["is_divisi"]]
    divisi = [it for it in items if it["is_divisi"]]

    # Ambil nama paket dari nama folder (parent langsung dari excel_path)
    nama_folder = os.path.basename(folder)
    import re as _re

    # Deteksi paket ulang dari suffix "(PL - Ulang)" di nama folder
    is_ulang = "(PL - Ulang)" in nama_folder or "(PL-Ulang)" in nama_folder

    if mode == "tender":
        # Folder tender lama: "N. Nama Paket - Pokja XXX";
        # format baru: "N. [Pokja-XXX] Nama Paket".
        nama_paket = _re.sub(r'^\d+\.\s*', '', nama_folder).strip()
        nama_paket = _re.sub(r'^\[Pokja\s*[-]?\s*\d+\]\s*', '', nama_paket, flags=_re.IGNORECASE).strip()
        nama_paket = _re.sub(r'\s*-\s*Pokja\s*\d+\s*$', '', nama_paket, flags=_re.IGNORECASE).strip()
    else:
        # Folder PL: "N. PLJKK - Nama Paket" atau "N. PLPK - Nama Paket"
        nama_paket = _re.sub(r'^\d+\.\s*(PLJKK|PLPK)\s*-\s*', '', nama_folder).strip()
        nama_paket = _re.sub(r'\s*\(PL\s*-?\s*Ulang\)\s*$', '', nama_paket, flags=_re.IGNORECASE).strip()

    # Nama file pakai nama paket (bukan kode), sanitasi karakter Windows
    nama_md = _re.sub(r'[/<>:"\|?*]', "-", nama_paket).strip()
    md_path = os.path.join(folder, f"_HPS_{nama_md}.md")
    status_paket = " **(PAKET ULANG)**" if is_ulang else ""

    lines = [
        f"# DATA HPS — {nama_paket}{status_paket}",
        f"Kode Paket: `{kode_paket}`  |  Auto-generated dari SPSE saat Serap HPS",
        "",
        "## RINGKASAN",
        f"- **Jumlah Item (total rows)**: {len(items)} ({len(non_divisi)} item + {len(divisi)} divisi)",
        f"- **Total Nilai**: {_rp(total_nilai)}",
        f"- **Total Nilai Bulat**: {_rp(total_bulat)}",
        f"- **Status Paket**: {'🔁 Ulang' if is_ulang else '🆕 Baru'}",
        "- **Prompt audit Agy**: `_PROMPT_AUDIT_PERUBAHAN_HPS_AGY.md`",
        "",
        "## ⚠️ ANOMALI TERDETEKSI",
    ]

    anomali = []
    for it in items:
        u, bj = it["urutan"], it["jenis_bj"]
        if not it["selisih_ok"]:
            anomali.append(f"- Item {u} '{bj}': total_spse={it['total_spse']} vs total_hitung={it['total_hitung']}, selisih={it['selisih']}")
        if not it["is_divisi"] and (it["harga"] == 0 or it["vol"] == 0):
            anomali.append(f"- Item {u} '{bj}': harga/vol nol (cek)")

    if anomali:
        lines.extend(anomali)
    else:
        lines.append("_Tidak ada anomali aritmatika terdeteksi._")

    lines.extend([
        "",
        "## TABEL BoQ LENGKAP",
        "No | Jenis B/J | Satuan | Vol | Harga | Pajak% | Total SPSE | Total Hitung | Selisih OK",
        "---|---|---|---|---|---|---|---|---"
    ])

    for it in items:
        u = it["urutan"]
        bj = it["jenis_bj"]
        ok = "✅" if it["selisih_ok"] else "❌"

        if it["is_divisi"]:
            lines.append(f"{u} | **{bj}** | - | - | - | - | - | - | -")
        else:
            v = it["vol"]
            # Vol: tampilkan tanpa .0 jika bulat
            v_str = f"{v:,.0f}".replace(",", ".") if float(v).is_integer() else f"{v:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
            p = it["pajak_pct"]
            lines.append(
                f"{u} | {bj} | {it['satuan']} | {v_str} | {_rp(it['harga'])} | "
                f"{p:g}% | {_rp(it['total_spse'])} | {_rp(it['total_hitung'])} | {ok}"
            )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Prompt audit Agy selalu disegarkan bersama ringkasan HPS PL.
    if mode == "pl":
        try:
            tulis_prompt_audit_hps_agy(kode_paket, folder, mode="pl")
        except Exception as e:
            print(f"Warning: Gagal tulis prompt audit HPS Agy: {e}")

    # Auto-generate PDF tabel BoQ (tanpa header ringkasan)
    try:
        from _hps_to_pdf import md_to_pdf
        # Utamakan Pagu live dari halaman HPS; DB hanya fallback.
        _nilai_pagu = hasil.get("nilai_pagu") or None
        if not _nilai_pagu:
            try:
                from config import sb as _sb
                _table = "draft_paket_pl" if mode == "pl" else "draft_paket"
                _key = "kode_paket" if mode == "pl" else "kode_tender"
                _row = _sb().table(_table).select("nilai_pagu").eq(_key, kode_paket).maybe_single().execute()
                if _row and _row.data:
                    _nilai_pagu = _row.data.get("nilai_pagu")
            except Exception:
                pass
        md_to_pdf(md_path, nama_paket=nama_paket, total_hps=total_bulat, nilai_pagu=_nilai_pagu)
    except Exception:
        pass  # best-effort, jangan block HPS flow

    # Auto re-parse personil dari HPS yang baru ditulis → update Supabase langsung
    # Ini memastikan sertifikat selalu up-to-date tanpa perlu klik Refresh manual
    try:
        from parse_kak_pl import ekstrak_personil_3layer
        from pl_engine import simpan_paket_pl
        # HPS JKK biasanya membawa section Tenaga Ahli sehingga strict HPS
        # aman. HPS PK adalah BoQ; personil wajib diambil dari
        # ListPersonilAlat.pdf bila section itu tidak ada.
        _is_pk_folder = "PLPK" in os.path.basename(folder).upper()
        personil = ekstrak_personil_3layer(folder, require_hps=not _is_pk_folder)
        if personil:
            simpan_paket_pl({"kode_paket": kode_paket, "personil_json": personil})
    except Exception:
        pass  # best-effort, jangan block HPS flow

    return md_path


def parse_hps_md(md_path: str, expected_kode: str = "") -> dict:
    """Baca ulang ringkasan ``_HPS_*.md`` sebagai fallback offline.

    Fallback hanya menerima file yang memiliki tabel BoQ dan, bila diminta,
    kode paket yang sama. Nilai ini dipakai untuk menyelesaikan finalisasi
    Excel ketika fetch live gagal sesaat; tidak dipromosikan sebagai HPS resmi
    baru dan tidak menimpa summary SPSE.
    """
    if not md_path or not os.path.isfile(md_path):
        return {}
    with open(md_path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    if expected_kode:
        code_match = None
        for line in lines:
            code_match = re.search(r"Kode Paket:\s*`([^`]+)`", line, re.IGNORECASE)
            if code_match:
                break
        if not code_match or code_match.group(1).strip() != str(expected_kode).strip():
            return {}

    def _summary(label):
        for line in lines:
            m = re.search(rf"^[-*]\s*\*\*{label}\*\*:\s*(.+)$", line, re.IGNORECASE)
            if m:
                parsed = _parse_amount_decimal(m.group(1))
                if parsed is not None:
                    return float(parsed)
        return 0.0

    table_start = next((i for i, line in enumerate(lines) if line.startswith("No | Jenis B/J |")), -1)
    if table_start < 0:
        return {}

    items = []
    for line in lines[table_start + 2:]:
        if not line.strip() or "|" not in line:
            continue
        fields = [part.strip() for part in line.split("|")]
        if len(fields) < 9:
            continue
        try:
            urutan = int(fields[0])
        except ValueError:
            continue
        jenis = fields[1].replace("**", "").strip()
        is_divisi = all(fields[i] == "-" for i in (2, 3, 4, 5, 6, 7, 8))
        if is_divisi:
            items.append({
                "urutan": urutan, "jenis_bj": jenis, "satuan": "", "vol": 0.0,
                "harga": 0.0, "pajak_pct": 0.0, "total_spse": 0.0,
                "total_hitung": 0.0, "kbki": "", "is_divisi": True,
                "selisih": 0.0, "selisih_ok": True,
            })
            continue
        vol = _parse_amount_decimal(fields[3]) or Decimal("0")
        harga = _parse_amount_decimal(fields[4]) or Decimal("0")
        pajak = _parse_amount_decimal(fields[5].replace("%", "")) or Decimal("0")
        total_spse = _parse_amount_decimal(fields[6]) or Decimal("0")
        total_hitung = _parse_amount_decimal(fields[7]) or Decimal("0")
        selisih = abs(total_spse - total_hitung).quantize(Decimal("0.01"))
        items.append({
            "urutan": urutan, "jenis_bj": jenis, "satuan": fields[2],
            "vol": float(vol), "harga": float(harga), "pajak_pct": float(pajak),
            "total_spse": float(total_spse), "total_hitung": float(total_hitung),
            "kbki": "", "is_divisi": False, "selisih": float(selisih),
            "selisih_ok": selisih <= Decimal("1.00"),
        })

    if not items:
        return {}
    total_nilai = _summary("Total Nilai")
    total_bulat = _summary("Total Nilai Bulat") or total_nilai
    return {
        "items": items,
        "total_nilai": total_nilai,
        "total_nilai_bulat": total_bulat,
        "nilai_pagu": "",
        "nilai_hps": _format_rp(total_bulat),
        "nilai_hps_official": "",
        "nilai_hps_source": "local_hps_md_fallback",
    }


# ============================================================
# PL Mode — HPS Non-Tender
# Endpoint: /dokumennontender/{DOKID}/hps (DOKID resolve dari kode_paket)
# Tabel Supabase: hps_items_pl (PK: kode_paket, urutan)
# ============================================================

def _resolve_dokid_hps_pl(kode_paket: str, cookie_str: str) -> str:
    """Resolve DOKID dokumen HPS dari kode_paket via link /surveyhargappk di halaman nontender.
    Return DOKID string, atau '' jika tidak ketemu."""
    import requests
    from spse_retry import request_with_retry
    url = f"{SPSE_BASE_URL}nontender/{kode_paket}"
    r = request_with_retry(
        lambda: requests.get(
            url,
            headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
            timeout=30,
        ),
        label=f"resolve HPS {kode_paket}",
    )
    if r.status_code != 200:
        return ""
    m = re.search(r'dokumennontender/(\d+)/surveyhargappk', r.text)
    return m.group(1) if m else ""


def _fetch_hps_page_pl(kode_paket: str) -> dict:
    """Ambil rincian HPS + TOTAL PAGU non-tender via requests + cookie PP."""
    import requests
    import spse_browser
    from spse_retry import request_with_retry

    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"items": [], "nilai_pagu": ""}

    # Resolve DOKID dulu — id_nontender di DB adalah ID peserta, bukan DOKID HPS
    dokid = request_with_retry(
        lambda: _resolve_dokid_hps_pl(kode_paket, cookie_str),
        label=f"resolve HPS {kode_paket}",
    )
    if not dokid:
        return {"items": [], "nilai_pagu": ""}

    url = f"{SPSE_BASE_URL}dokumennontender/{dokid}/hps"
    r = request_with_retry(lambda: requests.get(
        url,
        headers={
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0",
            # Referer wajib — tanpa ini server return 500
            "Referer": f"{SPSE_BASE_URL}nontender/{kode_paket}",
        },
        timeout=30,
    ), label=f"HPS {kode_paket}")
    if r.status_code != 200:
        return {"items": [], "nilai_pagu": ""}
    page = _parse_hps_page(r.text)

    # Rincian /dokumennontender/.../hps dapat menyimpan total item dengan
    # pecahan (contoh 313292323.48), sedangkan SPSE menampilkan nilai HPS
    # resmi yang sudah dibulatkan di /nontender/{kode}/edit. Ambil sumber
    # otoritatif itu bila tersedia; rincian item tetap dipertahankan untuk
    # audit dan rekonsiliasi.
    try:
        edit = request_with_retry(lambda: requests.get(
            f"{SPSE_BASE_URL}nontender/{kode_paket}/edit",
            headers={
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{SPSE_BASE_URL}nontender/{kode_paket}",
            },
            timeout=30,
        ), label=f"HPS resmi {kode_paket}")
        if edit.status_code == 200:
            official = _parse_official_hps_summary(edit.text)
            if official is not None:
                page["nilai_hps_official"] = official
    except Exception:
        # Rincian HPS tetap dapat dipakai bila halaman ringkasan gagal diambil.
        pass
    return page


def _fetch_data_var_pl(kode_paket: str) -> list:
    """Kompatibilitas lama: hanya kembalikan item HPS non-tender."""
    return _fetch_hps_page_pl(kode_paket).get("items", [])


def scrape_hps_pl(kode_paket: str) -> dict:
    """Scrape HPS PL via kode_paket (resolve DOKID live). Struktur sama dengan tender."""
    # Pada bulk paralel SPSE kadang mengembalikan halaman 200 tanpa tabel item
    # walau endpoint sebenarnya siap. Jangan menganggap itu HPS kosong permanen;
    # ulangi fetch penuh (termasuk resolve DOKID) secara bounded.
    page = {"items": []}
    raw = []
    for attempt in range(3):
        page = _fetch_hps_page_pl(kode_paket) or {"items": []}
        raw = page.get("items", []) or []
        if raw:
            break
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    if not raw:
        return {
            "items": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0,
            "nilai_pagu": page.get("nilai_pagu", ""), "nilai_hps": "",
        }

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

    # Audit total: jumlah raw total_harga dari endpoint rincian, dibulatkan
    # hanya ke 2 desimal. Ini bukan nilai HPS resmi.
    total_nilai_decimal = sum(
        (_parse_amount_decimal(d.get("total_harga") or 0) or Decimal("0"))
        for d in raw
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_nilai = float(total_nilai_decimal)

    official = page.get("nilai_hps_official")
    if official is not None:
        # Untuk sumber resmi /edit, "bulat" mengikuti nominal resmi apa adanya;
        # pecahan sen tidak boleh hilang sebelum ditulis ke Master Data.
        total_nilai_bulat_decimal = official.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        nilai_hps_source = "official_edit_page"
    else:
        # Backward-compatible fallback, tetapi eksplisit sebagai hasil
        # pembulatan audit; tidak disebut sebagai angka resmi SPSE.
        total_nilai_bulat_decimal = total_nilai_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        nilai_hps_source = "line_item_sum_rounded_fallback"
    total_nilai_bulat = float(total_nilai_bulat_decimal)

    return {
        "items":             items,
        "total_nilai":       total_nilai,
        "total_nilai_bulat": total_nilai_bulat,
        "nilai_pagu":        page.get("nilai_pagu", ""),
        "nilai_hps":         _format_rp(total_nilai_bulat),
        "nilai_hps_official": float(official) if official is not None else "",
        "nilai_hps_source":  nilai_hps_source,
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


def _sync_pl_summary(kode_paket: str, hasil: dict) -> bool:
    """Sinkronkan Pagu/HPS live ke draft_paket_pl setelah scrape HPS berhasil."""
    update = {}
    if hasil.get("nilai_pagu"):
        update["nilai_pagu"] = hasil["nilai_pagu"]
    if hasil.get("nilai_hps"):
        update["nilai_hps"] = hasil["nilai_hps"]
    if not update:
        return False
    try:
        _sb().table("draft_paket_pl").update(update).eq("kode_paket", kode_paket).execute()
        return True
    except Exception:
        return False


def scrape_dan_upsert_hps_pl(kode_paket: str) -> dict:
    """Scrape HPS PL → upsert. Resolve DOKID langsung dari kode_paket (tanpa lookup DB)."""
    try:
        hasil = scrape_hps_pl(kode_paket)
        if not hasil["items"]:
            return {"count": 0, "warning": [], "total_nilai": 0.0,
                    "total_nilai_bulat": 0.0, "error": "Tidak ada item HPS"}

        r = upsert_hps_pl(kode_paket, hasil)
        metadata_updated = _sync_pl_summary(kode_paket, hasil)
        return {
            "count":             r["count"],
            "warning":           r["warning"],
            "total_nilai":       hasil["total_nilai"],
            "total_nilai_bulat": hasil["total_nilai_bulat"],
            "nilai_pagu":        hasil.get("nilai_pagu", ""),
            "nilai_hps":         hasil.get("nilai_hps", ""),
            "metadata_updated":  metadata_updated,
            "error":             None,
        }
    except Exception as e:
        return {"count": 0, "warning": [], "total_nilai": 0.0,
                "total_nilai_bulat": 0.0, "error": str(e)}
