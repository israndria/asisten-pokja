"""Scrape harga penawaran peserta dari SPSE → upsert ke Supabase tabel harga_penawaran."""

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
