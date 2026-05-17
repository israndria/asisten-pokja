"""Backfill personil_json slot idx>=2 sertifikat → '(Tidak Dipersyaratkan)'.

Jalankan sekali dari folder Asisten_Pokja:
    python scratch/backfill_personil_sertifikat.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import sb as _sb

client = _sb()
rows = client.table("draft_paket_pl").select("kode_paket,personil_json").execute().data

updated = 0
for row in rows:
    pj = row.get("personil_json")
    if not pj or not isinstance(pj, list):
        continue
    changed = False
    for i, p in enumerate(pj):
        if i >= 2 and p.get("sertifikat", "") not in ("(Tidak Dipersyaratkan)", ""):
            p["sertifikat"] = "(Tidak Dipersyaratkan)"
            changed = True
    if changed:
        client.table("draft_paket_pl").update({"personil_json": pj}).eq("kode_paket", row["kode_paket"]).execute()
        print(f"Updated {row['kode_paket']}")
        updated += 1

print(f"Done. {updated} baris diupdate.")
