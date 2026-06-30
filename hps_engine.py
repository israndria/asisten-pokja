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
    Ambil variabel JS `data` dari halaman HPS via requests + cookie CDP.
    Data di-embed di HTML — tidak butuh Playwright/CDP browser launch.
    """
    import requests
    import json as _json
    import spse_browser

    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return []

    url = f"{SPSE_BASE_URL}dokumen/{kode_tender}/hps"
    r = requests.get(url, headers={
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"{SPSE_BASE_URL}paket",
    }, timeout=15)
    if r.status_code != 200:
        return []

    m = re.search(r"var\s+data\s*=\s*(\[.*?\]);\s*(?:var|</script)", r.text, re.DOTALL)
    if not m:
        m = re.search(r"data\s*=\s*(\[\{.+?\}\])", r.text, re.DOTALL)
    if not m:
        return []

    try:
        return _json.loads(m.group(1))
    except _json.JSONDecodeError:
        return []


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

    Format: "Mengerjakan {Nama Paket} meliputi: 1. {Divisi A}, 2. {Divisi B}, dan 3. {Divisi C}"
    Divisi diambil dari item is_divisi=True (baris tanpa satuan & harga di BoQ HPS).
    Return "" kalau tidak ada divisi terdeteksi (biar VBA fallback ke template JKK).
    """
    divisi_list = [it["jenis_bj"].strip() for it in items if it.get("is_divisi") and it.get("jenis_bj", "").strip()]
    if not divisi_list:
        return ""

    # Nama paket dari nama folder (parent dari excel_path), bersihkan prefix "N. PLPK - "
    import re as _re
    nama_folder = os.path.basename(os.path.dirname(os.path.abspath(excel_path)))
    nama_paket = _re.sub(r'^\d+\.\s*(PLJKK|PLPK)\s*-\s*', '', nama_folder).strip()
    nama_paket = _re.sub(r'\s*\(PL\s*-?\s*Ulang\)\s*$', '', nama_paket, flags=_re.IGNORECASE).strip()

    # Susun list bernomor: "1. A, 2. B, dan 3. C"
    n = len(divisi_list)
    bagian = [f"{i+1}. {d}" for i, d in enumerate(divisi_list)]
    if n == 1:
        daftar = bagian[0]
    else:
        daftar = ", ".join(bagian[:-1]) + ", dan " + bagian[-1]

    return f"Mengerjakan {nama_paket} meliputi: {daftar}"


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

        # Auto-generate markdown sebagai sumber data AI
        try:
            md_path = _tulis_hps_ke_md(kode_paket, excel_path, hasil)
            r["md_path"] = md_path
        except Exception as e:
            print(f"Warning: Gagal tulis MD HPS: {e}")

        # Upsert uraian_singkat_pk ke Supabase (untuk PK konstruksi)
        try:
            uraian = _build_uraian_singkat_pk(hasil["items"], excel_path)
            if uraian:
                from config import sb as _sb
                _sb().table("draft_paket_pl").update({"uraian_singkat": uraian}).eq("kode_paket", kode_paket).execute()
                r["uraian_singkat"] = uraian
        except Exception as e:
            print(f"Warning: Gagal upsert uraian_singkat: {e}")

        return r
    except Exception as e:
        return {"ok": False, "pesan": str(e), "count": 0, "warning": [],
                "total_nilai": 0.0, "total_nilai_bulat": 0.0}


def _tulis_hps_ke_md(kode_paket: str, excel_path: str, hasil: dict, mode: str = "pl") -> str:
    """Auto-generate file markdown sebagai sumber data HPS untuk AI pra-reviu.

    mode="pl"     — Pengadaan Langsung JKK/PK (default, backward compat)
    mode="tender" — Tender Pokja (folder naming berbeda, skip auto-parse personil PL)
    """
    folder = os.path.dirname(os.path.abspath(excel_path))

    items = hasil.get("items", [])
    total_nilai = hasil.get("total_nilai", 0)
    total_bulat = hasil.get("total_nilai_bulat", 0)

    # Helper format Rp ribuan titik
    def _rp(n): return f"Rp {int(round(n)):,}".replace(",", ".")

    non_divisi = [it for it in items if not it["is_divisi"]]
    divisi = [it for it in items if it["is_divisi"]]

    # Ambil nama paket dari nama folder (parent langsung dari excel_path)
    nama_folder = os.path.basename(folder)
    import re as _re

    # Deteksi paket ulang dari suffix "(PL - Ulang)" di nama folder
    is_ulang = "(PL - Ulang)" in nama_folder or "(PL-Ulang)" in nama_folder

    if mode == "tender":
        # Folder tender: "N. Nama Paket - Pokja XXX"
        # Buang prefix "N. " dan suffix " - Pokja XXX"
        nama_paket = _re.sub(r'^\d+\.\s*', '', nama_folder).strip()
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

    # Auto-generate PDF tabel BoQ (tanpa header ringkasan)
    try:
        from _hps_to_pdf import md_to_pdf
        md_to_pdf(md_path)
    except Exception:
        pass  # best-effort, jangan block HPS flow

    # Auto re-parse personil dari HPS yang baru ditulis → update Supabase langsung
    # Ini memastikan sertifikat selalu up-to-date tanpa perlu klik Refresh manual
    try:
        from parse_kak_pl import ekstrak_personil_3layer
        from pl_engine import simpan_paket_pl
        personil = ekstrak_personil_3layer(folder, require_hps=True)
        if personil:
            simpan_paket_pl({"kode_paket": kode_paket, "personil_json": personil})
    except Exception:
        pass  # best-effort, jangan block HPS flow

    return md_path


# ============================================================
# PL Mode — HPS Non-Tender
# Endpoint: /dokumennontender/{DOKID}/hps (DOKID resolve dari kode_paket)
# Tabel Supabase: hps_items_pl (PK: kode_paket, urutan)
# ============================================================

def _resolve_dokid_hps_pl(kode_paket: str, cookie_str: str) -> str:
    """Resolve DOKID dokumen HPS dari kode_paket via link /surveyhargappk di halaman nontender.
    Return DOKID string, atau '' jika tidak ketemu."""
    import requests
    url = f"{SPSE_BASE_URL}nontender/{kode_paket}"
    r = requests.get(url, headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"}, timeout=15)
    if r.status_code != 200:
        return ""
    m = re.search(r'dokumennontender/(\d+)/surveyhargappk', r.text)
    return m.group(1) if m else ""


def _fetch_data_var_pl(kode_paket: str) -> list:
    """Ambil var JS `data` dari halaman HPS non-tender via requests + cookie PP.
    Resolve DOKID HPS dari kode_paket (link /surveyhargappk), GET /hps dgn Referer wajib."""
    import requests
    import json as _json
    import spse_browser

    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return []

    # Resolve DOKID dulu — id_nontender di DB adalah ID peserta, bukan DOKID HPS
    dokid = _resolve_dokid_hps_pl(kode_paket, cookie_str)
    if not dokid:
        return []

    url = f"{SPSE_BASE_URL}dokumennontender/{dokid}/hps"
    r = requests.get(
        url,
        headers={
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0",
            # Referer wajib — tanpa ini server return 500
            "Referer": f"{SPSE_BASE_URL}nontender/{kode_paket}",
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


def scrape_hps_pl(kode_paket: str) -> dict:
    """Scrape HPS PL via kode_paket (resolve DOKID live). Struktur sama dengan tender."""
    raw = _fetch_data_var_pl(kode_paket)
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
    """Scrape HPS PL → upsert. Resolve DOKID langsung dari kode_paket (tanpa lookup DB)."""
    try:
        hasil = scrape_hps_pl(kode_paket)
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
