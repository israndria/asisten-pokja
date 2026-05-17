import sys
import os
import re
import csv
import time
import pdfplumber

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

# 43 SBU Lama missing names lookup
MISSING_OLD_NAMES = {
    "AR103": "Jasa Penilai Perawatan dan Kelayakan Bangunan Gedung",
    "AR104": "Jasa Desain Interior",
    "AR201": "Jasa Pengawas Administrasi Kontrak",
    "BG002": "Jasa Pelaksana Konstruksi Bangunan Multi atau Banyak Hunian",
    "BG009": "Jasa Pelaksana Konstruksi Bangunan Gedung Lainnya",
    "EL001": "Jasa Pelaksana Konstruksi Instalasi Pembangkit Tenaga Listrik Semua Daya",
    "EL002": "Jasa Pelaksana Konstruksi Instalasi Transmisi Tenaga Listrik Tegangan Tinggi/Ekstra Tinggi",
    "EL003": "Jasa Pelaksana Konstruksi Instalasi Transmisi Tenaga Listrik Tegangan Menengah dan Rendah",
    "EL004": "Jasa Pelaksana Konstruksi Instalasi Jaringan Distribusi Tenaga Listrik Tegangan Menengah",
    "EL007": "Jasa Pelaksana Konstruksi Instalasi Jaringan Distribusi Tenaga Listrik Tegangan Rendah",
    "EL008": "Jasa Pelaksana Konstruksi Instalasi Jaringan Distribusi Telekomunikasi",
    "EL009": "Jasa Pelaksana Konstruksi Instalasi Sistem Kontrol dan Instrumentasi",
    "EL010": "Jasa Pelaksana Konstruksi Instalasi Listrik Gedung dan Pabrik",
    "KL401": "Jasa Konsultansi Lingkungan",
    "KL403": "Jasa Manajemen Proyek Terkait Konstruksi Bangunan",
    "KL404": "Jasa Manajemen Proyek Terkait Konstruksi Pekerjaan Teknik Sipil Transportasi",
    "KL405": "Jasa Manajemen Proyek Terkait Konstruksi Pekerjaan Teknik Sipil Keairan",
    "KL407": "Jasa Manajemen Proyek Terkait Konstruksi Pekerjaan Teknik Sipil Lainnya",
    "KL409": "Jasa Konsultansi Rekayasa Lainnya",
    "KT004": "Pekerjaan Pengerjaan PB003",
    "KT008": "Pekerjaan Pemasangan PB005",
    "KT009": "Pekerjaan Pengerjaan PB003",
    "KT010": "Pekerjaan Pengerjaan PB003",
    "MK003": "Jasa Pelaksana Konstruksi Pemasangan Pipa Air (Plumbing) Dalam Gedung dan Salurannya",
    "MK008": "Jasa Pelaksana Konstruksi Pemasangan Lift dan Eskalator",
    "MK009": "Jasa Pelaksana Konstruksi Pemasangan Pipa Gas Dalam Gedung",
    "MK010": "Jasa Pelaksana Konstruksi Instalasi Fasilitas Produksi Minyak dan Gas",
    "PL004": "Jasa Pelaksana Pekerjaan Khusus",
    "PR201": "Jasa Pengawas dan Pengendali Penataan Ruang",
    "RE102": "Jasa Desain Rekayasa untuk Konstruksi Pondasi serta Struktur Bangunan",
    "RE103": "Jasa Desain Rekayasa untuk Pekerjaan Teknik Sipil Air",
    "RE105": "Jasa Desain Rekayasa untuk Pekerjaan Mekanikal dan Elektrikal dalam Bangunan",
    "RE107": "Jasa Desain Rekayasa untuk Proses Industrial dan Produksi",
    "RE108": "Jasa Desain Rekayasa Lainnya",
    "RE201": "Jasa Pengawas Pekerjaan Konstruksi Bangunan Gedung",
    "RE202": "Jasa Pengawas Pekerjaan Konstruksi Sipil Sumber Daya Air",
    "RE204": "Jasa Pengawas Pekerjaan Konstruksi Sipil Transportasi",
    "SI008": "Jasa Pelaksana Konstruksi Perpipaan Air Minum Lokal",
    "SI009": "Jasa Pelaksana Konstruksi Perpipaan Air Limbah Lokal",
    "SI012": "Jasa Pelaksana Konstruksi Bangunan Fasilitas Olah Raga Indoor dan Fasilitas Rekreasi",
    "SP005": "Jasa Pelaksanaan Pekerjaan Khusus",
    "SP013": "Jasa Pelaksanaan Pekerjaan Penyelidikan Tanah dan Struktur",
    "SP304": "Jasa Pembuatan Peta",
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

def extract_mappings_from_pdf(pdf_path):
    print(f"\n[PARSING] Membaca PDF: {pdf_path}...")
    mappings = []
    
    old_pattern = re.compile(r'\b(\d{5})\s+([A-Z]{2}\d{3})\b')
    new_pattern = re.compile(r'\b([A-Z]{2}\d{3})\s+(\d{5})\b')
    
    current_kode_lama = None
    current_kbli_2017 = None
    
    with pdfplumber.open(pdf_path) as pdf:
        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            
            for line_idx, line in enumerate(text.split("\n")):
                # Check for SBU Lama definition: KBLI 2017 + SBU Lama
                olds = old_pattern.findall(line)
                if olds:
                    kbli_2017, code_lama = olds[-1]
                    current_kode_lama = code_lama
                    current_kbli_2017 = kbli_2017
                
                # Check for SBU Baru mapping: SBU Baru + KBLI 2020
                news = new_pattern.findall(line)
                for code_baru, kbli_2020 in news:
                    # Validasi prefix baru
                    try:
                        infer_klasifikasi(code_baru)
                    except ValueError as ve:
                        print(f"  [ERROR] Baris abnormal di Halaman {p_idx+1} Baris {line_idx+1}: {line}")
                        raise ve
                    
                    if current_kode_lama:
                        mappings.append({
                            "kode_baru": code_baru,
                            "kode_lama": current_kode_lama,
                            "kbli_2020": kbli_2020,
                            "kbli_2017": current_kbli_2017
                        })
                        
            if (p_idx + 1) % 10 == 0:
                print(f"  Telah membaca {p_idx + 1} halaman...")
                
    return mappings

def main():
    pdf_path = r"D:\Dokumen\@ POKJA 2026\Lampiran Permenpupr 8 2022 SBU.pdf"
    
    apply_db = "--apply" in sys.argv
    force_apply = "--force" in sys.argv
    
    # 1. Parse PDF
    mappings = extract_mappings_from_pdf(pdf_path)
    
    # Deduplicate mappings
    unique_mappings = {}
    for m in mappings:
        key = (m["kode_baru"], m["kode_lama"])
        if key not in unique_mappings:
            unique_mappings[key] = m
    deduped_list = list(unique_mappings.values())
    
    print(f"\n[SUMMARY] Total baris mentah diekstrak: {len(mappings)}")
    print(f"[SUMMARY] Total pasangan unik (kode_baru, kode_lama): {len(deduped_list)}")
    
    # Check client
    client = sb()
    
    # Fetch existing master tables to preserve manual fields
    print("\n[DB FETCH] Memuat data existing untuk preservasi field...")
    existing_baru_rows = client.table("master_sbu_baru").select("*").execute().data
    existing_baru = {r["kode"]: r for r in existing_baru_rows}
    
    existing_lama_rows = client.table("master_sbu_lama").select("*").execute().data
    existing_lama = {r["kode"]: r for r in existing_lama_rows}
    
    # Diff vs existing mappings (Test 4 / Hard Gate)
    existing_mapping_rows = client.table("sbu_mapping").select("kode_baru, kode_lama").execute().data
    old_pairs = set((r["kode_baru"], r["kode_lama"]) for r in existing_mapping_rows)
    new_pairs = set((m["kode_baru"], m["kode_lama"]) for m in deduped_list)
    
    added = new_pairs - old_pairs
    removed = old_pairs - new_pairs
    common = new_pairs & old_pairs
    
    print("\n=== HASIL DIFFERENSI MAPPING ===")
    print(f"  Pasangan Baru di PDF (Extracted):  {len(new_pairs)}")
    print(f"  Pasangan Existing di DB:           {len(old_pairs)}")
    print(f"  Added (Ditambahkan):               {len(added)}")
    print(f"  Removed (Dihilangkan):             {len(removed)}")
    print(f"  Common (Sama):                     {len(common)}")
    
    # Hard Gate Validation
    if len(removed) > 10 or len(new_pairs) < 90:
        print(f"\n[CRITICAL WARNING] Hasil diff melanggar batas aman!")
        print(f"  Removed: {len(removed)} (Batas aman <= 10)")
        print(f"  Total Extracted: {len(new_pairs)} (Batas aman >= 90)")
        if not force_apply:
            print("[FATAL ERROR] Hard Gate gagal! Eksekusi dihentikan.")
            print("  Gunakan bendera '--force' untuk memaksa apply jika Anda yakin.")
            sys.exit(1)
        else:
            print("[WARNING] Hard Gate dilanggar, memaksa lanjut karena bendera --force aktif.")
            
    if not apply_db:
        print("\n[DRY RUN] Ekstraksi sukses. Gunakan bendera '--apply' untuk menulis ke Supabase.")
        return
        
    # 2. RUN BACKUP
    backup_pre_apply(client)
    
    # 3. UPSERT master_sbu_baru (Preserve manual fields)
    unique_new_codes = sorted(list(set(m["kode_baru"] for m in deduped_list)))
    baru_upserts = []
    for kb in unique_new_codes:
        # Find KBLI 2020
        kbli_2020 = next(m["kbli_2020"] for m in deduped_list if m["kode_baru"] == kb)
        existing_row = existing_baru.get(kb, {})
        
        nama_singkat = existing_row.get("nama_singkat") or f"Subklasifikasi {kb}"
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
    
    # 4. UPSERT master_sbu_lama (Preserve manual fields)
    unique_old_codes = sorted(list(set(m["kode_lama"] for m in deduped_list)))
    lama_upserts = []
    for kl in unique_old_codes:
        kbli_2017 = next(m["kbli_2017"] for m in deduped_list if m["kode_lama"] == kl)
        existing_row = existing_lama.get(kl, {})
        
        nama_singkat = MISSING_OLD_NAMES.get(kl) or existing_row.get("nama_singkat") or f"Subklasifikasi {kl}"
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
    
    # 5. OPSI A: DELETE all sbu_mapping and INSERT fresh
    print("[DELETE] Menghapus seluruh pemetaan sbu_mapping existing (PDF Authoritative)...")
    client.table("sbu_mapping").delete().neq("kode_baru", "DUMMY_PLACEHOLDER").execute()
    print("  [SUCCESS] sbu_mapping dibersihkan.")
    
    # Batch INSERT fresh
    map_list = [{"kode_baru": m["kode_baru"], "kode_lama": m["kode_lama"]} for m in deduped_list]
    print(f"[INSERT] Memasukkan {len(map_list)} pemetaan baru ke sbu_mapping...")
    for i in range(0, len(map_list), 50):
        batch = map_list[i:i+50]
        client.table("sbu_mapping").insert(batch).execute()
    print("  [SUCCESS] sbu_mapping selesai di-isi ulang.")
    
    # 6. Post-apply verification queries
    print("\n=== VERIFIKASI AKHIR DATABASE ===")
    total_maps = client.table("sbu_mapping").select("id", count="exact").execute().count
    print(f"  Total row count of sbu_mapping: {total_maps} (Expected: > 90)")
    
    rk003_maps = client.table("sbu_mapping").select("kode_lama").eq("kode_baru", "RK003").execute().data
    rk003_kodes = [r["kode_lama"] for r in rk003_maps]
    print(f"  RK003 padanan SBU Lama ({len(rk003_kodes)}): {rk003_kodes} (Expected: multiple codes)")
    
    all_baru_keys = set(r["kode"] for r in client.table("master_sbu_baru").select("kode").execute().data)
    all_lama_keys = set(r["kode"] for r in client.table("master_sbu_lama").select("kode").execute().data)
    
    orphans_baru = [r for r in deduped_list if r["kode_baru"] not in all_baru_keys]
    orphans_lama = [r for r in deduped_list if r["kode_lama"] not in all_lama_keys]
    print(f"  Orphan kode_baru: {len(orphans_baru)}")
    print(f"  Orphan kode_lama: {len(orphans_lama)}")
    
    # 7. GENERATE CSV MASTER
    csv_dir = r"d:\Dokumen\@ POKJA 2026\Asisten_Pokja\data"
    os.makedirs(csv_dir, exist_ok=True)
    csv_file = os.path.join(csv_dir, "sbu_mapping_complete.csv")
    print(f"\n[CSV] Menulis CSV master ke: {csv_file}...")
    
    final_baru = {r["kode"]: r for r in client.table("master_sbu_baru").select("kode, nama_singkat").execute().data}
    final_lama = {r["kode"]: r for r in client.table("master_sbu_lama").select("kode, nama_singkat").execute().data}
    
    csv_rows = []
    for m in deduped_list:
        kb = m["kode_baru"]
        kl = m["kode_lama"]
        klasifikasi = infer_klasifikasi(kb)
        nama_baru = final_baru.get(kb, {}).get("nama_singkat") or f"Subklasifikasi {kb}"
        nama_lama = final_lama.get(kl, {}).get("nama_singkat") or f"Subklasifikasi {kl}"
        
        csv_rows.append({
            "kode_baru": kb,
            "klasifikasi": klasifikasi,
            "kode_lama": kl,
            "nama_baru_singkat": nama_baru,
            "nama_lama_singkat": nama_lama,
            "kbli_2020": m["kbli_2020"],
            "kbli_2017": m["kbli_2017"]
        })
        
    csv_rows.sort(key=lambda x: (x["klasifikasi"], x["kode_baru"], x["kode_lama"]))
    
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["kode_baru", "klasifikasi", "kode_lama", "nama_baru_singkat", "nama_lama_singkat", "kbli_2020", "kbli_2017"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(csv_rows)
        
    print(f"  [SUCCESS] Berhasil menulis {len(csv_rows)} baris ke CSV master.")
    print("\nDONE. Tunggu user verify hasil di Streamlit + Supabase, baru push.")

if __name__ == "__main__":
    main()
