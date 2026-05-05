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


def _parse_rows_via_playwright(kode_tender: str) -> dict:
    """
    Scrape tabel HPS via Playwright CDP — halaman di-render JS, requests biasa tidak cukup.
    Return dict {"rows": [[...], ...], "rekap": [[...], ...]}
    """
    import spse_browser

    url = f"{SPSE_BASE_URL}dokumen/{kode_tender}/hps"
    spse_browser.buka_browser(navigate=False)

    # Cari tab yang sudah buka URL ini, atau navigate tab pertama
    page = next((p for p in spse_browser._context.pages if f"/{kode_tender}/hps" in p.url), None)
    if page is None:
        # Buka di tab yang sudah ada (jangan buat tab baru)
        page = spse_browser._context.pages[0]
        spse_browser._run(page.goto(url, wait_until="networkidle", timeout=30000))
    else:
        # Pastikan halaman sudah selesai load
        spse_browser._run(page.wait_for_load_state("networkidle", timeout=15000))

    # Virtual scroll: akumulasi baris sambil scroll — DOM recycle baris di luar viewport
    # Key pakai nomor urut (kolom pertama) agar baris divisi identik tidak tabrakan
    JS_SCRAPE_ALL = """async () => {
        const tbl = document.querySelectorAll('table')[1];
        if (!tbl) return {rows: [], rekap: []};

        // key = kolom-0 (nomor urut) + '|' + kolom-1 (nama pekerjaan awal 40 char)
        // Fallback ke auto-increment jika kolom-0 kosong (baris header/divisi tanpa nomor)
        let autoIdx = 0;
        const seen = new Map();

        const capture = () => {
            Array.from(tbl.querySelectorAll('tr')).forEach(tr => {
                const cells = Array.from(tr.querySelectorAll('th,td')).map(c => c.innerText.trim());
                if (!cells.length) return;
                const num = cells[0].trim();
                const nama = (cells[1] || '').slice(0, 40);
                // Baris dengan nomor urut → key = num|nama (unik per baris item)
                // Baris tanpa nomor (divisi/header) → key = _auto_N|nama
                const key = num ? (num + '|' + nama) : ('_auto_' + (++autoIdx) + '|' + nama);
                if (!seen.has(key)) seen.set(key, cells);
            });
        };

        // Scroll perlahan dari atas ke bawah, capture tiap langkah
        const step = Math.max(window.innerHeight * 0.5, 150);
        capture();
        for (let y = step; y <= document.body.scrollHeight + step; y += step) {
            window.scrollTo(0, y);
            await new Promise(r => setTimeout(r, 400));
            capture();
            if (y > document.body.scrollHeight) break;
        }
        window.scrollTo(0, 0);
        await new Promise(r => setTimeout(r, 300));

        const rekapTbl = Array.from(document.querySelectorAll('table')).find(t => t.id === 'rekap');
        const rekapRows = rekapTbl
            ? Array.from(rekapTbl.querySelectorAll('tr')).map(r =>
                Array.from(r.querySelectorAll('th,td')).map(c => c.innerText.trim()))
            : [];

        return {
            rows: Array.from(seen.values()),
            rekap: rekapRows,
        };
    }"""
    return spse_browser._run(page.evaluate(JS_SCRAPE_ALL))


def scrape_hps(kode_tender: str, session=None) -> dict:
    """
    Scrape halaman /dokumen/{kode_tender}/hps via Playwright (JS-rendered).
    session diabaikan — dipertahankan untuk backward compat.
    Return dict: {"items": [...], "total_nilai": float, "total_nilai_bulat": float}
    """
    data = _parse_rows_via_playwright(kode_tender)
    rows = data.get("rows", [])
    rekap = data.get("rekap", [])

    if not rows:
        return {"items": [], "total_nilai": 0.0, "total_nilai_bulat": 0.0}

    items = []
    for row in rows[1:]:  # skip header
        if len(row) < 7:
            continue

        # Kolom: [urutan, jenis_bj, satuan, vol, harga, pajak, total, ket, kunci, kbki]
        urutan_raw = row[0]
        jenis_bj   = row[1]
        satuan     = row[2]
        vol_raw    = row[3]
        harga_raw  = row[4]
        pajak_raw  = row[5]
        total_raw  = row[6]
        kbki       = row[9] if len(row) > 9 else ""

        is_divisi = (satuan == "" and vol_raw == "" and harga_raw == "")

        vol        = _parse_rp(vol_raw)
        harga      = _parse_rp(harga_raw)
        pajak_pct  = _parse_rp(pajak_raw)
        total_spse = _parse_rp(total_raw)

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

    total_nilai       = 0.0
    total_nilai_bulat = 0.0
    for r in rekap:
        if len(r) >= 2:
            if "setelah pembulatan" in r[0].lower():
                total_nilai_bulat = _parse_rp(r[1])
            elif "TOTAL NILAI" in r[0]:
                total_nilai = _parse_rp(r[1])

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
