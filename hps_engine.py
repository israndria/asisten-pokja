"""Scrape + upsert data HPS dari SPSE ke Supabase tabel hps_items."""

import re
from decimal import Decimal, ROUND_HALF_UP
from bs4 import BeautifulSoup
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


def scrape_hps(kode_tender: str, session) -> dict:
    """
    Scrape halaman /dokumen/{kode_tender}/hps via session cloudscraper.
    Return dict: {"items": [...], "total_nilai": float, "total_nilai_bulat": float}
    Setiap item: {urutan, jenis_bj, satuan, vol, harga, pajak_pct, total_spse,
                  kbki, is_divisi, selisih, selisih_ok}
    """
    url = f"{SPSE_BASE_URL}dokumen/{kode_tender}/hps"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")

    if len(tables) < 2:
        return {"items": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}

    # Tabel 1: item HPS (header di baris 0)
    rows = tables[1].find_all("tr")
    items = []
    for row in rows[1:]:  # skip header
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 7:
            continue

        # Kolom: [urutan, jenis_bj, satuan, vol, harga, pajak, total, ket, kunci, kbki]
        urutan_raw = cells[0]
        jenis_bj   = cells[1]
        satuan     = cells[2]
        vol_raw    = cells[3]
        harga_raw  = cells[4]
        pajak_raw  = cells[5]
        total_raw  = cells[6]
        kbki       = cells[9] if len(cells) > 9 else ""

        is_divisi = (satuan == "" and vol_raw == "" and harga_raw == "")

        vol        = _parse_rp(vol_raw)
        harga      = _parse_rp(harga_raw)
        pajak_pct  = _parse_rp(pajak_raw)
        total_spse = _parse_rp(total_raw)

        # Hitung manual: vol × harga × (1 + pajak/100), bulatkan 2 desimal
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

        try:
            urutan = int(float(urutan_raw)) if urutan_raw else 0
        except ValueError:
            urutan = 0

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

    # Cari total nilai dari tabel "TOTAL NILAI"
    total_nilai       = 0.0
    total_nilai_bulat = 0.0
    for tbl in tables:
        if "TOTAL NILAI" in tbl.get_text():
            for r in tbl.find_all("tr"):
                cells = [c.get_text(strip=True) for c in r.find_all(["td", "th"])]
                if len(cells) >= 2:
                    if "setelah pembulatan" in cells[0].lower():
                        total_nilai_bulat = _parse_rp(cells[1])
                    elif "TOTAL NILAI" in cells[0]:
                        total_nilai = _parse_rp(cells[1])

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

    if records:
        sb.table("hps_items").upsert(records).execute()

    return {
        "count":   len(records),
        "warning": [it for it in hasil["items"] if not it["selisih_ok"]],
    }


def scrape_dan_upsert_hps(kode_tender: str, session) -> dict:
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
