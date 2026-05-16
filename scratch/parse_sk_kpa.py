"""
parse_sk_kpa.py — Parse PDF SK KPA Bupati → upsert ke Supabase master_kpa.

Format PDF: Lampiran tabel 4 kolom: No | Nama+Pangkat+NIP | Jabatan | Wewenang
Nomor SK + tanggal di halaman 1.

Usage:
    python parse_sk_kpa.py "D:/Download/(5) SK KPA 2026 PERUBAHAN KESATU - Salin.pdf"
"""
import sys
import re
import os
import pdfplumber
from datetime import datetime


def _to_date(s: str) -> str | None:
    """'09 Februari 2026' → '2026-02-09'."""
    BULAN = {
        "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
        "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    }
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", s, re.IGNORECASE)
    if not m:
        return None
    d, b, t = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    if b not in BULAN:
        return None
    return f"{t}-{BULAN[b]:02d}-{d:02d}"


def parse_sk_pdf(pdf_path: str) -> dict:
    """Parse PDF SK KPA, return: {nomor_sk, tanggal_sk, rows: [...]}."""
    teks_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for pg in pdf.pages:
            teks_pages.append(pg.extract_text() or "")

    full = "\n".join(teks_pages)

    # Nomor SK
    m_nosk = re.search(r"NOMOR\s+(\d+\.\d+\.\d+\.\d+/\d+/[A-Z]+/\d+)", full)
    nomor_sk = m_nosk.group(1) if m_nosk else ""

    # Tanggal
    m_tgl = re.search(r"pada tanggal\s+(\d{1,2}\s+\w+\s+\d{4})", full, re.IGNORECASE)
    tanggal_sk = _to_date(m_tgl.group(1)) if m_tgl else None

    # Parse tabel via pdfplumber extract_tables
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for pg in pdf.pages:
            for table in (pg.extract_tables() or []):
                for r in table:
                    # Filter header / kosong
                    if not r or len(r) < 4:
                        continue
                    no_raw = (r[0] or "").strip().rstrip(".")
                    if not no_raw.isdigit():
                        continue
                    cell_nama = (r[1] or "").strip()
                    jabatan = (r[2] or "").strip().replace("\n", " ")
                    wewenang = (r[3] or "").strip().replace("\n", " ")
                    # Skip header indikasi row 1|2|3|4
                    if cell_nama in {"2", ""} and jabatan in {"3", ""}:
                        continue

                    # Split nama / pangkat / NIP — biasanya 3 baris di 1 cell
                    parts = [p.strip() for p in cell_nama.split("\n") if p.strip()]
                    nama = parts[0] if parts else ""
                    pangkat = parts[1] if len(parts) > 1 else ""
                    nip = ""
                    for p in parts[2:]:
                        m_nip = re.search(r"NIP\.?\s*([\d\s]+)", p)
                        if m_nip:
                            nip = m_nip.group(1).strip()
                            break

                    # Deteksi nama_dinas dari wewenang
                    nama_dinas = ""
                    if "Sekretariat Daerah" in wewenang:
                        nama_dinas = "Sekretariat Daerah Kabupaten Tapin"
                    elif "Pekerjaan Umum" in wewenang or "DPUPR" in wewenang:
                        nama_dinas = "Dinas Pekerjaan Umum dan Penataan Ruang"
                    elif "Kesehatan" in wewenang or "Puskesmas" in wewenang:
                        nama_dinas = "Dinas Kesehatan Kabupaten Tapin"
                    elif "Keuangan dan Aset" in wewenang:
                        nama_dinas = "Badan Keuangan dan Aset Daerah Kabupaten Tapin"
                    elif "Kelurahan" in wewenang or "Lurah" in jabatan:
                        nama_dinas = "Kelurahan"

                    rows.append({
                        "no_urut":    int(no_raw),
                        "nama":       nama,
                        "pangkat":    pangkat,
                        "nip":        nip,
                        "jabatan":    jabatan,
                        "wewenang":   wewenang,
                        "nama_dinas": nama_dinas,
                    })

    return {"nomor_sk": nomor_sk, "tanggal_sk": tanggal_sk, "rows": rows}


def upsert_supabase(parsed: dict, tahun: int = 2026) -> int:
    """Hapus + upsert ulang seluruh row SK ini ke master_kpa."""
    import sys as _sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import sb as _sb

    nomor_sk = parsed["nomor_sk"]
    tanggal_sk = parsed["tanggal_sk"]

    # Hapus row lama dengan nomor_sk + tahun yang sama
    _sb().table("master_kpa").delete().eq("nomor_sk", nomor_sk).eq("tahun", tahun).execute()

    records = []
    for r in parsed["rows"]:
        records.append({
            **r,
            "nomor_sk":   nomor_sk,
            "tanggal_sk": tanggal_sk,
            "tahun":      tahun,
        })

    if records:
        _sb().table("master_kpa").insert(records).execute()

    return len(records)


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else r"D:\Download\(5) SK KPA 2026 PERUBAHAN KESATU - Salin.pdf"
    parsed = parse_sk_pdf(pdf)
    print(f"Nomor SK : {parsed['nomor_sk']}")
    print(f"Tanggal  : {parsed['tanggal_sk']}")
    print(f"Total rows: {len(parsed['rows'])}")
    for r in parsed["rows"][:3]:
        print(f"  [{r['no_urut']}] {r['nama']} | {r['nip']} | {r['jabatan'][:40]}")

    if "--upsert" in sys.argv:
        n = upsert_supabase(parsed)
        print(f"Upserted: {n} rows to master_kpa")
