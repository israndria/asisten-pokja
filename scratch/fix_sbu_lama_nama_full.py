"""Fix pola nama_full master_sbu_lama agar konsisten dgn master_sbu_baru.

Pattern lama (salah): 'Subklasifikasi {nama_singkat} (KBLI 2017) {KODE}'
Pattern baru (benar): 'Subklasifikasi {KODE} (KBLI 2017) {nama_singkat}'

Juga regenerate draft_paket_pl.sbu_lama untuk semua paket existing yang
nilainya match pola lama.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from config import sb


def build_nama_full(kode: str, nama_singkat: str, tahun: str = "2017") -> str:
    return f"Subklasifikasi {kode} (KBLI {tahun}) {nama_singkat}".strip()


def fix_master_sbu_lama(apply: bool) -> dict:
    client = sb()
    rows = client.table("master_sbu_lama").select("kode,nama_singkat,nama_full").execute().data
    update_list = []
    for r in rows:
        kode = r["kode"]
        ns = (r.get("nama_singkat") or "").strip()
        if not ns:
            continue
        target = build_nama_full(kode, ns, "2017")
        if (r.get("nama_full") or "").strip() != target:
            update_list.append({"kode": kode, "old": r.get("nama_full"), "new": target})

    print(f"[master_sbu_lama] perlu update: {len(update_list)}/{len(rows)}")
    for u in update_list[:5]:
        print(f"  {u['kode']}:")
        print(f"    OLD: {u['old']}")
        print(f"    NEW: {u['new']}")

    if apply and update_list:
        for u in update_list:
            client.table("master_sbu_lama").update({"nama_full": u["new"]}).eq("kode", u["kode"]).execute()
        print(f"  -> APPLIED {len(update_list)} row")
    return {"checked": len(rows), "updated": len(update_list)}


def fix_draft_paket_pl(apply: bool) -> dict:
    """Regenerate sbu_lama di draft_paket_pl pakai pola baru.

    Build target dari nama_singkat (bukan lookup master, agar tidak ketergantungan
    urutan apply step 1 dulu).
    """
    client = sb()
    master = client.table("master_sbu_lama").select("kode,nama_singkat").execute().data
    by_kode = {r["kode"]: build_nama_full(r["kode"], (r.get("nama_singkat") or "").strip(), "2017") for r in master}

    drafts = client.table("draft_paket_pl").select("kode_paket,sbu_lama").execute().data
    update_list = []
    for d in drafts:
        old = (d.get("sbu_lama") or "").strip()
        if not old:
            continue
        # Detect kode SBU di string (mis 'RE104')
        import re
        m = re.search(r"\b([A-Z]{2}\d{3})\b", old)
        if not m:
            continue
        kode = m.group(1)
        target = by_kode.get(kode)
        if target and target != old:
            update_list.append({"kode_paket": d["kode_paket"], "kode_sbu": kode, "old": old, "new": target})

    print(f"\n[draft_paket_pl] perlu update sbu_lama: {len(update_list)}/{len(drafts)}")
    for u in update_list[:5]:
        print(f"  paket {u['kode_paket']} ({u['kode_sbu']}):")
        print(f"    OLD: {u['old']}")
        print(f"    NEW: {u['new']}")

    if apply and update_list:
        for u in update_list:
            client.table("draft_paket_pl").update({"sbu_lama": u["new"]}).eq("kode_paket", u["kode_paket"]).execute()
        print(f"  -> APPLIED {len(update_list)} row")
    return {"checked": len(drafts), "updated": len(update_list)}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    s1 = fix_master_sbu_lama(args.apply)
    s2 = fix_draft_paket_pl(args.apply)

    print("\n=== Summary ===")
    print(f"master_sbu_lama  : checked={s1['checked']} updated={s1['updated']}")
    print(f"draft_paket_pl   : checked={s2['checked']} updated={s2['updated']}")
    if not args.apply:
        print("\n(dry-run) Tambah --apply utk eksekusi.")
