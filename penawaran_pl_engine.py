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
    """Parse 'Rp. 8.000.000,00' → 8000000.0"""
    if not s:
        return 0.0
    cleaned = re.sub(r"[Rp\.\s]", "", s).replace(".", "").replace(",", ".")
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
