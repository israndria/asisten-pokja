"""
penawaran_pl_engine.py — Scrape harga penawaran PL dari SPSE.

Flow:
  1. GET evaluasinontender/{kode_paket} → parse link pesertanontender/{peserta_id}/rincian_penawaran
  2. GET pesertanontender/{peserta_id}/rincian_penawaran → parse tabel harga
  3. Return list item + total penawaran

Perbedaan dengan penawaran_engine.py (tender):
  - Endpoint list: pakai evaluasinontender/{kode} (bukan pesertanontender/{kode}/penawaran yg 403)
  - Tabel rincian: 8 kolom (bukan 13) — tidak ada kolom PPK
  - Kolom: Jenis BJ, Satuan, Vol, Harga Satuan, Total sbl Pajak, Pajak%, Total stlh Pajak, Keterangan
"""

import re
import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser


def _headers(cookie_override: str = "") -> dict:
    cookie = cookie_override or spse_browser.get_spse_cookies()
    return {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
    }


def _parse_rp(s: str) -> float:
    """Parse 'Rp. 8.000.000,00' → 8000000.0  |  '1.0' atau '3.0' → float langsung"""
    if not s:
        return 0.0
    # Volume SPSE: '1.0', '3.0' — titik = desimal, tidak ada prefix Rp
    # Harga SPSE:  'Rp. 8.000.000,00' — titik = ribuan, koma = desimal
    # Deteksi: ada 'Rp' atau koma → format Rp; sisanya → float langsung
    if "Rp" in s or "," in s:
        cleaned = re.sub(r"[Rp\s]", "", s).replace(".", "").replace(",", ".")
    else:
        cleaned = s.strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def fetch_peserta_ids_pl(kode_paket: str, cookie_str: str = "") -> list[dict]:
    """
    GET evaluasinontender/{kode_paket} → parse semua link rincian_penawaran.
    Return: [{"peserta_id": str, "nama_peserta": str}, ...]
    """
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/evaluasinontender/{kode_paket}"
    resp = requests.get(url, headers=_headers(cookie_str), timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    hasil = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # href: /prefix/pesertanontender/{peserta_id}/rincian_penawaran
        if "/pesertanontender/" not in href or "/rincian_penawaran" not in href:
            continue
        parts = href.rstrip("/").split("/")
        try:
            idx = parts.index("pesertanontender")
            peserta_id = parts[idx + 1]
        except (ValueError, IndexError):
            continue
        if peserta_id in seen:
            continue
        seen.add(peserta_id)

        # Coba ambil nama peserta dari td terdekat
        nama = ""
        td = a.find_parent("td")
        if td:
            tr = td.find_parent("tr")
            if tr:
                cells = tr.find_all("td")
                for c in cells:
                    txt = c.get_text(strip=True)
                    if txt and txt != a.get_text(strip=True):
                        nama = txt
                        break

        hasil.append({"peserta_id": peserta_id, "nama_peserta": nama})

    return hasil


def scrape_rincian_penawaran_pl(peserta_id: str, cookie_str: str = "") -> dict:
    """
    GET pesertanontender/{peserta_id}/rincian_penawaran → parse tabel harga PL.

    Kolom tabel (8 kolom):
      0=Jenis BJ, 1=Satuan, 2=Vol, 3=Harga Satuan,
      4=Total sbl Pajak, 5=Pajak%, 6=Total stlh Pajak, 7=Keterangan

    Return:
      {
        "items": [{"urutan","jenis_bj","satuan","vol","harga_satuan",
                   "total_sbl_pajak","pajak_pct","total_stlh_pajak"}],
        "total_penawaran": float,  # Total termasuk PPN
        "nama_peserta": str,
        "kode_paket": str,
        "nama_paket": str,
      }
    """
    base = SPSE_BASE_URL.rstrip("/")
    url = f"{base}/pesertanontender/{peserta_id}/rincian_penawaran"
    resp = requests.get(url, headers=_headers(cookie_str), timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Info paket dari tblTeknis
    nama_peserta = ""
    kode_paket = ""
    nama_paket = ""
    tbl_teknis = soup.find("table", id="tblTeknis")
    if tbl_teknis:
        for row in tbl_teknis.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            val   = cells[1].get_text(strip=True)
            if "Kode Paket" in label:
                # Kode paket sering ada teks tombol "Cetak"/"Download" di td yg sama
                # Ambil hanya angka pertama
                m = re.search(r"\d{10,}", val)
                kode_paket = m.group(0) if m else val.split()[0]
            elif "Nama Paket" in label:
                nama_paket = val
            elif "Nama Peserta" in label:
                nama_peserta = val

    # Parse tabel harga (table.table-bordered, bukan id=tblTeknis)
    tabel_harga = None
    for tbl in soup.find_all("table", class_="table-bordered"):
        # Cek header baris pertama
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if any("Jenis" in h or "Satuan" in h for h in headers):
            tabel_harga = tbl
            break

    items = []
    total_penawaran = 0.0

    if tabel_harga:
        rows = tabel_harga.find_all("tr")
        urutan = 0
        for row in rows[1:]:  # skip header
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue

            # Baris Total Penawaran / PDN (colspan, sedikit cell)
            full_text = " ".join(cells)
            if "Total Penawaran" in full_text:
                # Nilai ada di cell terakhir atau cell setelah label
                for c in reversed(cells):
                    v = _parse_rp(c)
                    if v > 0:
                        total_penawaran = v
                        break
                continue
            if "Produk Dalam Negeri" in full_text or "PDN" in full_text:
                continue

            # Baris data item
            if len(cells) >= 7:
                jenis_bj        = cells[0]
                satuan          = cells[1]
                vol_raw         = cells[2]
                harga_satuan    = cells[3]
                total_sbl_pajak = cells[4]
                pajak_pct       = cells[5]
                total_stlh_pajak = cells[6]

                urutan += 1
                items.append({
                    "urutan":           urutan,
                    "jenis_bj":         jenis_bj,
                    "satuan":           satuan or None,
                    "vol":              _parse_rp(vol_raw),
                    "harga_satuan":     _parse_rp(harga_satuan),
                    "total_sbl_pajak":  _parse_rp(total_sbl_pajak),
                    "pajak_pct":        _parse_rp(pajak_pct),
                    "total_stlh_pajak": _parse_rp(total_stlh_pajak),
                })

    return {
        "items":            items,
        "total_penawaran":  total_penawaran,
        "nama_peserta":     nama_peserta,
        "kode_paket":       kode_paket,
        "nama_paket":       nama_paket,
    }


def fetch_semua_penawaran_pl(kode_paket: str, cookie_str: str = "") -> dict:
    """
    Entry point: fetch semua peserta + rincian penawaran untuk 1 paket PL.

    Return:
      {
        "ok": bool,
        "peserta": [
          {
            "peserta_id": str,
            "nama_peserta": str,
            "items": [...],
            "total_penawaran": float,
          }
        ],
        "error": str,
      }
    """
    try:
        cookie = cookie_str or spse_browser.get_spse_cookies()
        peserta_list = fetch_peserta_ids_pl(kode_paket, cookie)
        if not peserta_list:
            return {"ok": False, "peserta": [], "error": "Tidak ada peserta yang sudah kirim penawaran."}

        hasil_peserta = []
        for p in peserta_list:
            try:
                detail = scrape_rincian_penawaran_pl(p["peserta_id"], cookie)
                hasil_peserta.append({
                    "peserta_id":    p["peserta_id"],
                    "nama_peserta":  detail["nama_peserta"] or p["nama_peserta"],
                    "items":         detail["items"],
                    "total_penawaran": detail["total_penawaran"],
                })
            except Exception as e:
                hasil_peserta.append({
                    "peserta_id":    p["peserta_id"],
                    "nama_peserta":  p["nama_peserta"],
                    "items":         [],
                    "total_penawaran": 0.0,
                    "error":         str(e),
                })

        return {"ok": True, "peserta": hasil_peserta, "error": ""}

    except Exception as e:
        return {"ok": False, "peserta": [], "error": str(e)}


def tulis_penawaran_ke_excel(folder_paket: str, id_nontender: str, progress_cb=None) -> dict:
    """
    Scrape rincian_penawaran untuk 1 peserta (via id_nontender = peserta_id),
    lalu tulis ke sheet '6. Penawaran' di file .xlsm dalam folder_paket.

    Args:
        folder_paket : folder root paket PL (berisi .xlsm)
        id_nontender : ID peserta (dipakai langsung sebagai peserta_id di URL)
        progress_cb  : callback(str)

    Return: {"ok": bool, "pesan": str, "total_penawaran": float}
    """
    import os, glob, pythoncom, win32com.client

    def _log(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    # 1. Scrape data penawaran
    _log(f"  Scrape rincian_penawaran id={id_nontender}...")
    try:
        data = scrape_rincian_penawaran_pl(id_nontender)
    except Exception as e:
        return {"ok": False, "pesan": f"Gagal scrape: {e}", "total_penawaran": 0.0}

    items = data.get("items", [])
    total = data.get("total_penawaran", 0.0)
    _log(f"  {len(items)} item, total Rp {total:,.0f}")

    if not items:
        return {"ok": False, "pesan": "Tidak ada item penawaran", "total_penawaran": 0.0}

    # 2. Cari file .xlsm di folder_paket (1 level, bukan rekursif)
    xlsm_files = [
        f for f in glob.glob(os.path.join(folder_paket, "*.xlsm"))
        if not os.path.basename(f).startswith("~$")
        and ".backup" not in os.path.basename(f)
    ]
    if not xlsm_files:
        return {"ok": False, "pesan": "File .xlsm tidak ditemukan di folder paket", "total_penawaran": total}

    xlsm_path = xlsm_files[0]
    _log(f"  Tulis ke {os.path.basename(xlsm_path)} → sheet '6. Penawaran'...")

    # 3. Tulis via COM
    try:
        pythoncom.CoInitialize()
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        # Jangan pernah Save workbook PL dengan UDF VBA dalam keadaan macro
        # disabled: dependent cached values dapat berubah menjadi #NAME?.
        try:
            xl.AutomationSecurity = 1  # msoAutomationSecurityLow
        except Exception as exc:
            raise RuntimeError(
                "Excel AutomationSecurity gagal diatur ke macro-enabled; "
                "writer dibatalkan agar cache UDF tidak rusak."
            ) from exc
        xl.EnableEvents = False
        try:
            wb = xl.Workbooks.Open(os.path.abspath(xlsm_path), ReadOnly=False)
            ws = None
            for i in range(1, wb.Sheets.Count + 1):
                if wb.Sheets(i).Name == "6. Penawaran":
                    ws = wb.Sheets(i)
                    break
            if ws is None:
                wb.Close(False)
                return {"ok": False, "pesan": "Sheet '6. Penawaran' tidak ditemukan", "total_penawaran": total}

            # Hapus data lama (baris 2 dst)
            last_row = ws.UsedRange.Rows.Count
            if last_row > 1:
                ws.Rows(f"2:{last_row}").Delete()

            # Tulis header-compatible: No | Jenis | Satuan | Volume | Harga Satuan |
            #   Total sbl Pajak | Pajak% | Total stlh Pajak | Keterangan
            # Replicate format sheet 5. HPS persis
            FMT_RP  = '#.##0,00'   # harga/total: 21.000.000,00
            FMT_VOL = '#.##0,00'   # volume: 1,00 / 3,00
            FMT_PCT = '0,00'       # pajak: 11,00

            def _fmt_rp(v: float) -> float:
                return round(v, 2)

            def _fmt_vol(v: float) -> float:
                return round(v, 2)

            no_counter = 0
            for row_idx, item in enumerate(items, start=2):
                jenis     = item.get("jenis_bj", "")
                satuan    = item.get("satuan") or ""
                vol       = item.get("vol", 0.0)
                harga_sat = item.get("harga_satuan", 0.0)
                total_sbl = item.get("total_sbl_pajak", 0.0)
                pajak     = item.get("pajak_pct", 0.0)
                total_stlh = item.get("total_stlh_pajak", 0.0)
                is_kategori = not satuan and harga_sat == 0.0 and total_sbl == 0.0

                no_counter += 1
                ws.Cells(row_idx, 1).Value = no_counter
                ws.Cells(row_idx, 2).Value = jenis
                ws.Cells(row_idx, 3).Value = satuan

                if is_kategori:
                    for col in (4, 5, 6, 7, 8):
                        ws.Cells(row_idx, col).Value = ""
                else:
                    ws.Cells(row_idx, 4).Value = _fmt_vol(vol)
                    ws.Cells(row_idx, 4).NumberFormat = FMT_VOL
                    ws.Cells(row_idx, 5).Value = _fmt_rp(harga_sat)
                    ws.Cells(row_idx, 5).NumberFormat = FMT_RP
                    ws.Cells(row_idx, 6).Value = _fmt_rp(total_sbl)
                    ws.Cells(row_idx, 6).NumberFormat = FMT_RP
                    ws.Cells(row_idx, 7).Value = int(round(pajak))
                    ws.Cells(row_idx, 7).NumberFormat = FMT_PCT
                    ws.Cells(row_idx, 8).Value = _fmt_rp(total_stlh)
                    ws.Cells(row_idx, 8).NumberFormat = FMT_RP

            # Baris Total Penawaran
            total_row = len(items) + 2
            ws.Cells(total_row, 2).Value = "Total Penawaran"
            ws.Cells(total_row, 8).Value = _fmt_rp(total)
            ws.Cells(total_row, 8).NumberFormat = FMT_RP

            # Sheet 7.2 berisi formula turunan dari sheet 6. Penawaran.
            # Hitung ulang dulu, lalu rapikan row setelah semua nilai masuk.
            try:
                wb.Calculate()
                xl.Run(f"'{wb.Name}'!FixSheetByName", "7.2 Dengan Nego")
                _log("  Autofit otomatis: sheet '7.2 Dengan Nego' dirapikan.")
            except Exception as e:
                _log(f"  ⚠️ Autofit 7.2 dilewati: {e}")

            wb.Save()
            wb.Close(False)
            _log(f"  Berhasil tulis {no_counter} item + Total → {os.path.basename(xlsm_path)}")
            return {"ok": True, "pesan": f"{no_counter} item ditulis", "total_penawaran": total}
        finally:
            try:
                xl.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()
    except Exception as e:
        return {"ok": False, "pesan": f"COM error: {e}", "total_penawaran": total}


def download_penawaran_batch(
    paket_peserta_list: list,
    progress_cb=None,
) -> dict:
    """
    Batch tulis penawaran ke Excel untuk banyak paket.

    paket_peserta_list: [
        {
            "kode_paket": str,
            "folder_paket": str,
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
    n_ok = n_total = 0

    for item in paket_peserta_list:
        kode = item["kode_paket"]
        folder_paket = item["folder_paket"]
        peserta_list = item.get("peserta", [])
        _log(f"=== Paket {kode} ({len(peserta_list)} peserta) ===")

        for p in peserta_list:
            n_total += 1
            _log(f"Peserta: {p['nama']}")
            res = tulis_penawaran_ke_excel(
                folder_paket=folder_paket,
                id_nontender=p["id_nontender"],
                progress_cb=progress_cb,
            )
            if res["ok"]:
                n_ok += 1
            detail.append({
                "kode_paket": kode,
                "nama": p["nama"],
                **res,
            })

    ringkasan = f"{n_ok}/{n_total} peserta berhasil ditulis ke Excel"
    return {"ok": n_ok == n_total, "ringkasan": ringkasan, "detail": detail}
