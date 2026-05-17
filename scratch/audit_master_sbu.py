"""
audit_master_sbu.py — Audit + cleanup master_sbu Supabase.

Tujuan:
1. Ekstrak subklasifikasi_kode dari sbu_baru (regex [A-Z]{2}\\d{3})
2. Re-infer klasifikasi dari prefix subklasifikasi_kode (drop garbage angka KBLI)
3. Print laporan: row OK, row salah klasifikasi, row tanpa subklasifikasi_kode
4. (Opsional) Apply fix ke Supabase via --apply

Mapping prefix → klasifikasi (Permen PUPR 8/2022):
- AR : Arsitektur
- AL : Arsitektur Lanskap (sub Arsitektur)
- AT : Arsitektur Interior (sub Arsitektur)
- RE : Rekayasa (KBLI 2017 lama)
- RK : Rekayasa (KBLI 2020 baru)
- BG : Bangunan Gedung (Sipil)
- BS : Bangunan Sipil
- SI : Sipil
- GT : Geoteknik (Sipil)
- MK : Mekanikal
- EL : Elektrikal
- TL : Tata Lingkungan
- TI : Tata Lingkungan / Sipil
- KT : Konstruksi Keterampilan
- PR : Pengelolaan Proyek (Manajemen)
- SP : Spesialis
- IN : Instalasi
- PL : Plumbing/Pipa
- KK : Konsultansi Konstruksi (umum)
- MR : Manajemen Rekayasa
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import sb

# Klasifikasi resmi Permen PUPR 8/2022 (8 klasifikasi):
# 1. Arsitektur
# 2. Rekayasa
# 3. Rekayasa Terpadu (RT)
# 4. Konsultansi Ilmiah dan Teknis (IT)
# 5. Sipil
# 6. Mekanikal-Elektrikal (gabungan)
# 7. Spesialis
# 8. Terintegrasi
# Plus: Konsultansi Konstruksi (KK), Tata Lingkungan (TL)
PREFIX_KLASIFIKASI = {
    "AR": "Arsitektur",
    "AL": "Arsitektur",          # Lanskap (sub arsitektur)
    "AT": "Arsitektur",          # Interior (sub arsitektur)
    "RE": "Rekayasa",            # KBLI 2017
    "RK": "Rekayasa",            # KBLI 2020
    "RT": "Rekayasa Terpadu",    # Pelayanan Studi Investasi, Konstruksi Pembangkit
    "IT": "Konsultansi Ilmiah dan Teknis",  # Geologi, Bawah Tanah
    "BG": "Sipil",               # Bangunan Gedung
    "BS": "Sipil",               # Bangunan Sipil
    "SI": "Sipil",               # Sipil umum
    "GT": "Sipil",               # Geoteknik (sub Sipil)
    "KP": "Sipil",               # Konstruksi Prapabrikasi
    "MK": "Mekanikal",
    "EL": "Elektrikal",
    "TL": "Tata Lingkungan",
    "TI": "Tata Lingkungan",
    "KT": "Konstruksi Keterampilan",
    "PR": "Manajemen Rekayasa",
    "MR": "Manajemen Rekayasa",
    "SP": "Spesialis",
    "IN": "Spesialis",           # Instalasi (sub Spesialis)
    "PL": "Spesialis",           # Plumbing (sub Spesialis)
    "KK": "Konsultansi Konstruksi",
    "PB": "Spesialis",           # Pengerjaan Bangunan finishing (sub Spesialis)
    "PA": "Spesialis",           # Penyewaan Alat (sub Spesialis)
    "ST": "Terintegrasi",        # Sub-Terintegrasi
}


def extract_kode(sbu_baru: str) -> str:
    """Ekstrak kode XXNNN pertama dari sbu_baru."""
    if not sbu_baru:
        return ""
    m = re.search(r"\b([A-Z]{2}\d{3})\b", sbu_baru)
    return m.group(1) if m else ""


def infer_klasifikasi(kode: str) -> str:
    """Infer klasifikasi dari prefix 2 huruf."""
    if not kode or len(kode) < 2:
        return ""
    prefix = kode[:2]
    return PREFIX_KLASIFIKASI.get(prefix, "")


def main(apply_fix: bool = False):
    client = sb()
    rows = client.table("master_sbu").select("*").execute().data
    print(f"Total rows: {len(rows)}\n")

    stats = {
        "ok": 0,
        "klasifikasi_fixable": 0,
        "no_kode": 0,
        "prefix_unknown": 0,
    }
    fixes = []
    unknown_prefixes = {}

    for row in rows:
        rid = row["id"]
        old_klas = (row.get("klasifikasi") or "").strip()
        sbu_baru = row.get("sbu_baru") or ""
        kode = extract_kode(sbu_baru)

        if not kode:
            stats["no_kode"] += 1
            print(f"  [NO KODE] id={rid} sbu_baru={sbu_baru[:60]}")
            continue

        new_klas = infer_klasifikasi(kode)
        if not new_klas:
            stats["prefix_unknown"] += 1
            unknown_prefixes[kode[:2]] = unknown_prefixes.get(kode[:2], 0) + 1
            continue

        # Detect klasifikasi rusak: jika ≠ new_klas DAN old_klas TIDAK valid string huruf
        old_is_valid = old_klas and not old_klas.isdigit() and any(c.isalpha() for c in old_klas)

        if not old_is_valid or old_klas != new_klas:
            fixes.append({
                "id": rid,
                "kode": kode,
                "old_klasifikasi": old_klas,
                "new_klasifikasi": new_klas,
                "subklasifikasi_kode": kode,
            })
            stats["klasifikasi_fixable"] += 1
        else:
            stats["ok"] += 1

    print(f"\n=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nPrefix unknown: {unknown_prefixes}")
    print(f"\nFix samples (first 20 of {len(fixes)}):")
    for fix in fixes[:20]:
        print(f"  id={fix['id']:3d} {fix['kode']} | OLD='{fix['old_klasifikasi'][:30]}' -> NEW='{fix['new_klasifikasi']}'")

    if apply_fix and fixes:
        print(f"\nAPPLYING {len(fixes)} fixes...")
        for fix in fixes:
            try:
                client.table("master_sbu").update({
                    "klasifikasi": fix["new_klasifikasi"],
                }).eq("id", fix["id"]).execute()
            except Exception as e:
                print(f"  FAIL id={fix['id']}: {e}")
        print("  Done.")
    elif fixes:
        print(f"\n(Dry run. Run dgn --apply untuk eksekusi {len(fixes)} fix.)")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    main(apply_fix=apply)
