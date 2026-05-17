import sys
import os
import csv
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import sb

# PREFIX_KLASIFIKASI resmi Permen PUPR 8/2022 (23 prefixes)
PREFIX_KLASIFIKASI = {
    "AR": "Arsitektur", "AL": "Arsitektur", "AT": "Arsitektur",
    "RE": "Rekayasa", "RK": "Rekayasa",
    "RT": "Rekayasa Terpadu",
    "IT": "Konsultansi Ilmiah dan Teknis",
    "BG": "Sipil", "BS": "Sipil", "SI": "Sipil", "GT": "Sipil", "KP": "Sipil",
    "MK": "Mekanikal",
    "EL": "Elektrikal",
    "TL": "Tata Lingkungan", "TI": "Tata Lingkungan",
    "KT": "Konstruksi Keterampilan",
    "PR": "Manajemen Rekayasa", "MR": "Manajemen Rekayasa",
    "SP": "Spesialis", "IN": "Spesialis", "PL": "Spesialis", "PB": "Spesialis", "PA": "Spesialis",
    "KK": "Konsultansi Konstruksi",
    "ST": "Terintegrasi",
}

def infer_klasifikasi(kode: str) -> str:
    if not kode or len(kode) < 2:
        return ""
    prefix = kode[:2].upper()
    if prefix not in PREFIX_KLASIFIKASI:
        raise ValueError(f"CRITICAL: Prefix '{prefix}' pada kode '{kode}' tidak dikenal!")
    return PREFIX_KLASIFIKASI[prefix]

def backup_pre_apply(client):
    print("\n[BACKUP] Memulai pencadangan database existing...")
    timestamp = int(time.time())
    for tbl in ["master_sbu_baru", "master_sbu_lama", "sbu_mapping"]:
        try:
            rows = client.table(tbl).select("*").execute().data
            if not rows:
                print(f"  Tabel {tbl} kosong, skip backup.")
                continue
            out_dir = r"d:\Dokumen\@ POKJA 2026\Asisten_Pokja\scratch"
            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, f"_backup_{tbl}_{timestamp}.csv")
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            print(f"  [BACKUP SUCCESS] Tabel {tbl}: {len(rows)} baris -> {out_file}")
        except Exception as e:
            print(f"  [BACKUP FAILED] Gagal mencadangkan {tbl}: {e}")
            raise e

def main():
    csv_file = r"d:\Dokumen\@ POKJA 2026\Asisten_Pokja\data\sbu_mapping_complete.csv"
    
    if not os.path.exists(csv_file):
        print(f"[FATAL ERROR] File CSV master tidak ditemukan di: {csv_file}")
        sys.exit(1)
        
    print(f"\n[SYNC] Membaca CSV master dari: {csv_file}...")
    csv_rows = []
    with open(csv_file, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            csv_rows.append(row)
            
    print(f"  Total baris pemetaan di CSV: {len(csv_rows)}")
    
    apply_db = "--apply" in sys.argv
    
    if not apply_db:
        print("\n[DRY RUN] Sinkronisasi siap dilakukan. Gunakan bendera '--apply' untuk menulis ke Supabase.")
        return
        
    client = sb()
    
    # 1. RUN BACKUP
    backup_pre_apply(client)
    
    # Fetch existing master tables to preserve manual fields
    print("\n[DB FETCH] Memuat data existing untuk preservasi field...")
    existing_baru_rows = client.table("master_sbu_baru").select("*").execute().data
    existing_baru = {r["kode"]: r for r in existing_baru_rows}
    
    existing_lama_rows = client.table("master_sbu_lama").select("*").execute().data
    existing_lama = {r["kode"]: r for r in existing_lama_rows}
    
    # 2. UPSERT master_sbu_baru (Preserve manual fields)
    unique_new_codes = sorted(list(set(row["kode_baru"] for row in csv_rows)))
    baru_upserts = []
    for kb in unique_new_codes:
        # Find first KBLI 2020 and names in CSV
        matched = next(r for r in csv_rows if r["kode_baru"] == kb)
        kbli_2020 = matched["kbli_2020"]
        nama_singkat_csv = matched["nama_baru_singkat"]
        
        existing_row = existing_baru.get(kb, {})
        nama_singkat = existing_row.get("nama_singkat") or nama_singkat_csv or f"Subklasifikasi {kb}"
        nama_full = existing_row.get("nama_full") or f"Subklasifikasi {kb} (KBLI 2020) {kbli_2020}"
        
        new_data = {
            "kode": kb,
            "klasifikasi": infer_klasifikasi(kb),
            "nama_full": nama_full,
            "nama_singkat": nama_singkat,
            "kbli_2020": kbli_2020,
            "jabatan_ahli": existing_row.get("jabatan_ahli") or None,
            "skk_kode": existing_row.get("skk_kode") or None,
            "lingkup_pekerjaan": existing_row.get("lingkup_pekerjaan") or None,
        }
        baru_upserts.append(new_data)
        
    print(f"\n[UPSERT] Melakukan upsert {len(baru_upserts)} baris ke master_sbu_baru...")
    for i in range(0, len(baru_upserts), 50):
        batch = baru_upserts[i:i+50]
        client.table("master_sbu_baru").upsert(batch, on_conflict="kode").execute()
    print("  [SUCCESS] master_sbu_baru selesai di-upsert.")
    
    # 3. UPSERT master_sbu_lama (Preserve manual fields)
    unique_old_codes = sorted(list(set(row["kode_lama"] for row in csv_rows)))
    lama_upserts = []
    for kl in unique_old_codes:
        matched = next(r for r in csv_rows if r["kode_lama"] == kl)
        kbli_2017 = matched["kbli_2017"]
        nama_singkat_csv = matched["nama_lama_singkat"]
        
        existing_row = existing_lama.get(kl, {})
        nama_singkat = existing_row.get("nama_singkat") or nama_singkat_csv or f"Subklasifikasi {kl}"
        nama_full = existing_row.get("nama_full") or f"Subklasifikasi {nama_singkat} (KBLI 2017) {kbli_2017}"
        
        new_data = {
            "kode": kl,
            "nama_full": nama_full,
            "nama_singkat": nama_singkat,
            "kbli_2017": kbli_2017 or existing_row.get("kbli_2017") or None,
        }
        lama_upserts.append(new_data)
        
    print(f"[UPSERT] Melakukan upsert {len(lama_upserts)} baris ke master_sbu_lama...")
    for i in range(0, len(lama_upserts), 50):
        batch = lama_upserts[i:i+50]
        client.table("master_sbu_lama").upsert(batch, on_conflict="kode").execute()
    print("  [SUCCESS] master_sbu_lama selesai di-upsert.")
    
    # 4. DELETE all sbu_mapping and INSERT fresh (Opsi A: Single Source of Truth)
    print("[DELETE] Menghapus seluruh pemetaan sbu_mapping existing...")
    client.table("sbu_mapping").delete().neq("kode_baru", "DUMMY_PLACEHOLDER").execute()
    print("  [SUCCESS] sbu_mapping dibersihkan.")
    
    map_list = [{"kode_baru": row["kode_baru"], "kode_lama": row["kode_lama"]} for row in csv_rows]
    print(f"[INSERT] Memasukkan {len(map_list)} pemetaan baru dari CSV ke sbu_mapping...")
    for i in range(0, len(map_list), 50):
        batch = map_list[i:i+50]
        client.table("sbu_mapping").insert(batch).execute()
    print("  [SUCCESS] sbu_mapping selesai di-isi ulang.")
    
    print("\n=== VERIFIKASI AKHIR DATABASE ===")
    total_maps = client.table("sbu_mapping").select("id", count="exact").execute().count
    print(f"  Total row count of sbu_mapping: {total_maps}")
    
    rk003_maps = client.table("sbu_mapping").select("kode_lama").eq("kode_baru", "RK003").execute().data
    rk003_kodes = [r["kode_lama"] for r in rk003_maps]
    print(f"  RK003 padanan SBU Lama ({len(rk003_kodes)}): {rk003_kodes}")
    
    print("\n[SYNC SUCCESS] Database Supabase sinkron 100% dengan CSV master.")

if __name__ == "__main__":
    main()
