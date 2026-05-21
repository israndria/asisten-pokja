"""
muat_penawaran_pl.py — CLI untuk VBA: scrape harga penawaran PL → tulis ke JSON.

Usage:
    python muat_penawaran_pl.py <kode_paket> <output_json_path>

Output JSON (array of peserta):
[
  {
    "peserta_id": "...",
    "nama_peserta": "...",
    "total_penawaran": 8880000.0,
    "items": [
      {"urutan":1,"jenis_bj":"Pekerjaan","satuan":"Paket","vol":1.0,
       "harga_satuan":8000000.0,"total_sbl_pajak":8000000.0,
       "pajak_pct":11.0,"total_stlh_pajak":8880000.0}
    ]
  }
]

Exit code: 0 = sukses, 1 = error
"""
import sys
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    if len(sys.argv) < 3:
        print("Usage: python muat_penawaran_pl.py <kode_paket> <output_json>")
        sys.exit(1)

    kode_paket  = sys.argv[1].strip()
    output_path = sys.argv[2].strip()

    from penawaran_pl_engine import fetch_semua_penawaran_pl
    result = fetch_semua_penawaran_pl(kode_paket)

    if not result["ok"] or not result["peserta"]:
        # Penawaran belum masuk — tulis JSON kosong, exit 0 (bukan error)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([], f)
        error_msg = result.get("error", "Tidak ada peserta")
        print(f"INFO: {error_msg} — sheet dibiarkan kosong")
        sys.exit(0)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result["peserta"], f, ensure_ascii=False, indent=2)

    print(f"OK: {len(result['peserta'])} peserta, output → {output_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
