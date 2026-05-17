"""
migrate_sbu_v2.py — Migrate master_sbu (172 row) ke 3 tabel:
- master_sbu_baru (unique by kode SBU 2020)
- master_sbu_lama (unique by kode SBU 2017)
- sbu_mapping    (many-to-many junction)

Parse sbu_baru: 'Subklasifikasi RK003 (KBLI 2020) Jasa Rekayasa...' -> kode='RK003', nama_singkat='Jasa Rekayasa...'
Parse sbu_lama: 'Subklasifikasi Jasa Desain Rekayasa... (KBLI 2017) RE104' -> kode='RE104', nama_singkat='Jasa Desain Rekayasa...'

Dry-run default. Apply: --apply
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import sb


def parse_sbu_baru(text: str) -> dict:
    """
    'Subklasifikasi RK003 (KBLI 2020) Jasa Rekayasa Pekerjaan Teknik Sipil Transportasi'
    -> {kode: 'RK003', nama_singkat: 'Jasa Rekayasa Pekerjaan Teknik Sipil Transportasi'}
    """
    if not text:
        return {}
    text = text.strip()
    # Pattern: Subklasifikasi <KODE> (KBLI 2020) <NAMA>
    m = re.match(r"^Subklasifikasi\s+([A-Z]{2}\d{3})\s+\(KBLI\s+2020\)\s+(.+)$", text, re.I)
    if m:
        return {"kode": m.group(1).upper(), "nama_singkat": m.group(2).strip(), "nama_full": text}
    # Fallback: cari kode di mana saja
    m2 = re.search(r"\b([A-Z]{2}\d{3})\b", text)
    if m2:
        return {"kode": m2.group(1).upper(), "nama_singkat": "", "nama_full": text}
    return {}


def parse_sbu_lama(text: str) -> dict:
    """
    'Subklasifikasi Jasa Desain Rekayasa... (KBLI 2017) RE104'
    -> {kode: 'RE104', nama_singkat: 'Jasa Desain Rekayasa...'}
    """
    if not text:
        return {}
    text = text.strip()
    # Pattern: Subklasifikasi <NAMA> (KBLI 2017) <KODE>
    m = re.match(r"^Subklasifikasi\s+(.+?)\s*\(KBLI\s+201[57]\)\s+([A-Z]{2}\d{3})$", text, re.I)
    if m:
        return {"kode": m.group(2).upper(), "nama_singkat": m.group(1).strip(), "nama_full": text}
    # Fallback: kode di akhir
    m2 = re.search(r"\b([A-Z]{2}\d{3})\b", text)
    if m2:
        return {"kode": m2.group(1).upper(), "nama_singkat": "", "nama_full": text}
    return {}


def main(apply_fix: bool = False):
    client = sb()
    rows = client.table("master_sbu").select("*").execute().data
    print(f"Total source rows: {len(rows)}\n")

    sbu_baru_map = {}   # kode -> dict (full data)
    sbu_lama_map = {}   # kode -> dict
    mappings = set()    # (kode_baru, kode_lama)

    skip_no_baru = 0
    for row in rows:
        baru_p = parse_sbu_baru(row.get("sbu_baru") or "")
        lama_p = parse_sbu_lama(row.get("sbu_lama") or "")

        if not baru_p.get("kode"):
            skip_no_baru += 1
            continue

        kb = baru_p["kode"]
        # Aggregate sbu_baru data (prefer richer row)
        existing = sbu_baru_map.get(kb, {})
        sbu_baru_map[kb] = {
            "kode":               kb,
            "klasifikasi":        row.get("klasifikasi") or existing.get("klasifikasi") or "",
            "nama_full":          baru_p["nama_full"],
            "nama_singkat":       baru_p.get("nama_singkat") or existing.get("nama_singkat") or "",
            "jabatan_ahli":       row.get("jabatan_ahli") or existing.get("jabatan_ahli") or None,
            "skk_kode":           row.get("skk_kode") or existing.get("skk_kode") or None,
            "lingkup_pekerjaan":  row.get("lingkup_pekerjaan") or existing.get("lingkup_pekerjaan") or None,
        }

        if lama_p.get("kode"):
            kl = lama_p["kode"]
            sbu_lama_map[kl] = {
                "kode":         kl,
                "nama_full":    lama_p["nama_full"],
                "nama_singkat": lama_p.get("nama_singkat") or "",
            }
            mappings.add((kb, kl))

    print(f"=== PARSED ===")
    print(f"  unique sbu_baru: {len(sbu_baru_map)}")
    print(f"  unique sbu_lama: {len(sbu_lama_map)}")
    print(f"  mappings (M:N): {len(mappings)}")
    print(f"  skip_no_baru:   {skip_no_baru}")

    # Sample
    print(f"\n=== SAMPLE sbu_baru (3) ===")
    for k in list(sbu_baru_map.keys())[:3]:
        r = sbu_baru_map[k]
        print(f"  {k} | {r['klasifikasi']} | {r['nama_singkat'][:60]}")
        lamas = [kl for (kb, kl) in mappings if kb == k]
        print(f"    padanan lama: {lamas}")

    if not apply_fix:
        print(f"\n(Dry run. Run dgn --apply.)")
        return

    # APPLY
    print(f"\n=== APPLYING ===")

    # 1. Insert master_sbu_baru (upsert)
    print(f"  Upsert {len(sbu_baru_map)} sbu_baru...")
    baru_list = list(sbu_baru_map.values())
    # Batch 50
    for i in range(0, len(baru_list), 50):
        batch = baru_list[i:i+50]
        try:
            client.table("master_sbu_baru").upsert(batch, on_conflict="kode").execute()
        except Exception as e:
            print(f"    FAIL batch {i}: {e}")
    print(f"  OK sbu_baru.")

    # 2. Insert master_sbu_lama (upsert)
    print(f"  Upsert {len(sbu_lama_map)} sbu_lama...")
    lama_list = list(sbu_lama_map.values())
    for i in range(0, len(lama_list), 50):
        batch = lama_list[i:i+50]
        try:
            client.table("master_sbu_lama").upsert(batch, on_conflict="kode").execute()
        except Exception as e:
            print(f"    FAIL batch {i}: {e}")
    print(f"  OK sbu_lama.")

    # 3. Insert sbu_mapping (upsert by unique constraint)
    print(f"  Upsert {len(mappings)} mappings...")
    map_list = [{"kode_baru": kb, "kode_lama": kl} for (kb, kl) in mappings]
    for i in range(0, len(map_list), 50):
        batch = map_list[i:i+50]
        try:
            client.table("sbu_mapping").upsert(batch, on_conflict="kode_baru,kode_lama").execute()
        except Exception as e:
            print(f"    FAIL batch {i}: {e}")
    print(f"  OK mappings.")

    # Verify
    nb = client.table("master_sbu_baru").select("kode", count="exact").execute().count
    nl = client.table("master_sbu_lama").select("kode", count="exact").execute().count
    nm = client.table("sbu_mapping").select("id", count="exact").execute().count
    print(f"\n=== VERIFY ===")
    print(f"  master_sbu_baru: {nb}")
    print(f"  master_sbu_lama: {nl}")
    print(f"  sbu_mapping:     {nm}")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    main(apply_fix=apply)
