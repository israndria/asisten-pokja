"""Scrape + upsert data HPS dari SPSE ke Supabase tabel hps_items."""

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

    page = next((p for p in spse_browser._context.pages if f"/{kode_tender}/hps" in p.url), None)
    if page is None:
        page = spse_browser._context.pages[0]
        spse_browser._run(page.goto(url, wait_until="networkidle", timeout=30000))
    else:
        spse_browser._run(page.reload(wait_until="networkidle", timeout=30000))

    return spse_browser._run(page.evaluate("() => typeof data !== 'undefined' ? data : []"))


def scrape_hps(kode_tender: str, session=None) -> dict:
    """
    Scrape HPS dari variabel JS `data` di halaman /dokumen/{kode_tender}/hps.
    Return dict: {"items": [...], "total_nilai": float, "total_nilai_bulat": float}
    """
    raw = _fetch_data_var(kode_tender)

    if not raw:
        return {"items": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}

    items = []
    auto_urutan = 0
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

        # Urutan: gunakan index+1, baris divisi pakai counter negatif agar tidak tabrakan
        if not is_divisi:
            urutan = i + 1
        else:
            auto_urutan -= 1
            urutan = auto_urutan

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
