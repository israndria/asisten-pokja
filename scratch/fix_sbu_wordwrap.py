import sys
import os
import re
import csv
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import sb

# Set kata-kata valid yang dikompilasi dari kosa kata SBU resmi
VALID_WORDS = {
    "jasa", "perencanaan", "perancangan", "perkotaan", "lingkungan", "bangunan", "lansekap", "lanskap",
    "pengembangan", "pemanfaatan", "ruang", "telekomunikasi", "transmisi", "instalasi", "pemasangan",
    "atap", "rangka", "roofcovering", "pekerjaan", "konstruksi", "hiburan", "publik", "kesehatan",
    "pendidikan", "hotel", "restoran", "pengawas", "manajemen", "proyek", "sipil", "transportasi",
    "keairan", "sumber", "daya", "air", "nasihat", "nasehat", "desain", "arsitektural", "interior", "penilai",
    "perawatan", "kelayakan", "administrasi", "kontrak", "pembangkit", "tenaga", "listrik", "sistem",
    "kontrol", "instrumentasi", "plumbing", "pipa", "gas", "lift", "eskalator", "minyak", "bumi",
    "kanal", "irigasi", "bendungan", "pengerukan", "reklamasi", "pelabuhan", "bandara", "jalan",
    "rel", "jembatan", "terowongan", "pengeboran", "geotermal", "pondasi", "struktur", "pancang",
    "mekanikal", "elektrikal", "tata", "spesialis", "keterampilan", "terintegrasi", "umum", "maupun",
    "atau", "dan", "dengan", "oleh", "pada", "yang", "di", "ke", "dari", "untuk", "non", "sub",
    "antar", "multi", "anti", "pra", "pro", "pasca", "serta", "dalam", "luar", "semua", "tinggi",
    "rendah", "menengah", "gardu", "sentral", "pabrik", "gedung", "evaluasi", "insulasi", "prafabrikasi",
    "prapabrikasi", "penyiapan", "pematangan", "pembongkaran", "pengecatan", "pengelasan", "perancah",
    "baja", "beton", "kayu", "batu", "lantai", "dinding", "kaca", "jendela", "dekorasi", "curtain",
    "wall", "ac", "conditioner", "pemanas", "ventilasi", "pendingin", "is", "es", "gas", "minyak",
    "panas", "uap", "geofisika", "geologi", "survei", "pembuatan", "peta", "taman", "pertamanan",
    "tanah", "pengujian", "analisis", "analisa", "komposisi", "kemurnian", "parameter", "fisikal",
    "commissioning", "proses", "industrial", "produksi", "kendali", "lintas", "jalan raya", "layang",
    "underpass", "subways", "terowongan", "studi", "kelayakan", "investasi", "hutan", "pertanian",
    "perkebunan", "petrokimia", "farmasi", "pertambangan", "pengolahan", "limbah", "padat", "cair",
    "sampah", "sanitasi", "drainase", "irigasi", "sungai", "rawa", "pantai", "pelindung", "pemeliharaan",
    "peningkatan", "rehabilitasi", "rehab", "pengerukan", "reklamasi", "pelabuhan", "bandar", "udara",
    "heliport", "landas", "pacu", "jalan kereta api", "jembatan layang", "jalan layang", "subway",
    "terowongan jalan", "pengeboran sumur", "penyelidikan", "struktur tanah", "peleburan", "tanur",
    "flare", "incenerator", "peringkat", "pencampuran", "penyulingan", "perpipaan", "distribusi",
    "penyaluran", "tangki", "depot", "penyimpanan", "terminal", "stasiun", "pengisian", "pengelasan",
    "underwater", "welding", "drydocking", "galangan", "kapal", "dok", "terapung", "perakitan",
    "pemasangan rangka", "atap/roofcovering", "kedap air", "waterproofing", "waterproffing",
    "pemancangan", "piling", "foundation", "sheet", "pile", "dinding penahan", "pengeboran air",
    "sumur bor", "eksplorasi", "produksi minyak", "produksi gas", "panas bumi", "konstruksi khusus",
    "scaffolding", "perancah/steiger", "formwork", "bekisting", "pembetonan", "pembesian", "pemasangan batu",
    "pemasangan bata", "plesteran", "acian", "finishing", "pemasangan lantai", "pemasangan dinding",
    "pemasangan keramik", "marmer", "granit", "parquet", "vinyl", "karpet", "pemasangan kaca",
    "pemasangan jendela", "pemasangan pintu", "pemasangan railing", "pencucian", "pencampuran aspal",
    "hotmix", "penghamparan aspal", "pemberantasan", "hama", "rayap", "fogging", "penghijauan",
    "penanaman pohon", "lansekap/pertamanan", "taman kota", "taman lingkungan", "taman rumah",
    "pemancangan/piling", "baja konstruksi", "rangka baja", "jembatan baja", "gedung baja",
    "pekerjaan logam", "ornamen logam", "pagar logam", "tralis", "kanopi", "interior gedung",
    "arsitektur interior", "furnitur", "fitting", "wallpaper", "partisi", "ceiling", "gypsum",
    "plafond", "curtain wall", "fasad", "dinding kaca", "alokasi", "frekuensi", "radio",
    "spektrum", "satelit", "stasiun bumi", "radar", "navigasi udara", "navigasi laut",
    "menara", "telekomunikasi", "bts", "base", "transceiver", "station", "fiber", "optic",
    "optik", "kabel laut", "kabel tanah", "kabel udara", "jaringan lokal", "jaringan backbone",
    "seluler", "broadband", "microwave", "link", "wi-fi", "internet", "wireless", "jasa pertambangan",
    "jasa energi", "jasa industri", "jasa transportasi", "jasa lingkungan", "jasa pariwisata",
    "jasa kesehatan", "jasa pendidikan", "jasa hukum", "jasa bisnis", "jasa keuangan",
    "jasa asuransi", "jasa rekreasi", "jasa olahraga", "jasa kesenian", "jasa keagamaan",
    "jasa sosial", "jasa kemasyarakatan", "jasa pribadi", "jasa rumah tangga", "jasa lainnya",
    "pemancangannya", "pemasangannya", "pertamanan"
}

def clean_word(w: str) -> str:
    return w.lower().strip(".,()/-")

def fix_text(text: str) -> str:
    if not text:
        return text
        
    # Suku kata atau fragmen yang sering terpisah
    fragments = {"n", "an", "ngan", "ering", "asi", "si", "kasi", "a", "ya", "am", "anan"}
    
    # 1. Hardcoded replacements for known multi-split or complex patterns
    hard_rules = {
        "Pert am anan": "Pertamanan",
        "Lansekap/Pert am anan": "Lansekap/Pertamanan",
        "Telekomunika si": "Telekomunikasi",
        "Telekomunik asi": "Telekomunikasi",
        "Telekomuni kasi": "Telekomunikasi",
        "Roofcov ering": "Roofcovering",
        "Atap/Roofcov ering": "Atap/Roofcovering",
        "Pemancangann ya": "Pemancangannya",
        "Pemasanganny a": "Pemasangannya",
    }
    
    for k, v in hard_rules.items():
        if k in text:
            text = text.replace(k, v)
        # Case insensitive check
        k_lower = k.lower()
        if k_lower in text.lower():
            idx = text.lower().find(k_lower)
            if idx != -1:
                orig = text[idx:idx+len(k)]
                text = text.replace(orig, v if orig.islower() else v.capitalize())

    words = text.split()
    fixed_words = []
    i = 0
    while i < len(words):
        w1 = words[i]
        
        # Check if there is a next word to potentially merge
        if i + 1 < len(words):
            w2 = words[i+1]
            
            # Clean variants for lookup
            cw1 = clean_word(w1)
            cw2 = clean_word(w2)
            merged_clean = cw1 + cw2
            
            # Condition: w2 is a known fragment, OR merged_clean is a valid Indonesian word
            if cw2 in fragments or merged_clean in VALID_WORDS:
                if merged_clean in VALID_WORDS or (cw2 in fragments and merged_clean.replace("waterproffing", "waterproofing") in VALID_WORDS):
                    # Merge them!
                    punctuation = ""
                    if w2[-1] in ".,)":
                        punctuation = w2[-1]
                    
                    # Capitalization preservation
                    raw_merged = w1 + w2.strip(".,)") + punctuation
                    
                    fixed_words.append(raw_merged)
                    i += 2
                    continue
                    
        fixed_words.append(w1)
        i += 1
        
    return " ".join(fixed_words)

def build_nama_full_baru(kode: str, nama_singkat: str, kbli_2020: str) -> str:
    return f"Subklasifikasi {kode} (KBLI 2020) {nama_singkat}".strip()

def backup_pre_apply(client):
    print("\n[BACKUP] Memulai pencadangan database sebelum menerapkan perbaikan...")
    timestamp = int(time.time())
    for tbl in ["master_sbu_baru", "master_sbu_lama"]:
        try:
            rows = client.table(tbl).select("*").execute().data
            if not rows:
                continue
            out_dir = r"d:\Dokumen\@ POKJA 2026\Asisten_Pokja\scratch"
            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, f"_backup_pre_wordwrap_{tbl}_{timestamp}.csv")
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            print(f"  [BACKUP SUCCESS] Tabel {tbl}: {len(rows)} baris -> {out_file}")
        except Exception as e:
            print(f"  [BACKUP FAILED] Gagal mencadangkan {tbl}: {e}")
            raise e

def main():
    apply_db = "--apply" in sys.argv
    
    client = sb()
    
    # 1. Fetch data
    print("[DB FETCH] Memuat master_sbu_baru dan master_sbu_lama dari Supabase...")
    baru_rows = client.table("master_sbu_baru").select("*").execute().data
    lama_rows = client.table("master_sbu_lama").select("*").execute().data
    
    # 2. Process master_sbu_baru
    baru_updates = []
    for r in baru_rows:
        ns = r.get("nama_singkat") or ""
        fixed = fix_text(ns)
        if fixed != ns:
            baru_updates.append({
                "kode": r["kode"],
                "old_ns": ns,
                "new_ns": fixed,
                "old_nf": r.get("nama_full"),
                "new_nf": build_nama_full_baru(r["kode"], fixed, r.get("kbli_2020") or "")
            })
            
    print("\n=== PERUBAHAN DETEKSI WORD-WRAP master_sbu_baru ===")
    for u in baru_updates:
        print(f"  {u['kode']}:")
        print(f"    OLD NAMA_SINGKAT: {u['old_ns']}")
        print(f"    NEW NAMA_SINGKAT: {u['new_ns']}")
        print(f"    NEW NAMA_FULL   : {u['new_nf']}")
        
    print(f"Total baris terdeteksi di master_sbu_baru: {len(baru_updates)}/{len(baru_rows)}")
    
    # 3. Process master_sbu_lama
    lama_updates = []
    for r in lama_rows:
        ns = r.get("nama_singkat") or ""
        fixed = fix_text(ns)
        if fixed != ns:
            lama_updates.append({
                "kode": r["kode"],
                "old_ns": ns,
                "new_ns": fixed
            })
            
    print("\n=== PERUBAHAN DETEKSI WORD-WRAP master_sbu_lama ===")
    for u in lama_updates:
        print(f"  {u['kode']}:")
        print(f"    OLD NAMA_SINGKAT: {u['old_ns']}")
        print(f"    NEW NAMA_SINGKAT: {u['new_ns']}")
        
    print(f"Total baris terdeteksi di master_sbu_lama: {len(lama_updates)}/{len(lama_rows)}")
    
    # 4. Hard Gate Validation Check
    gate_baru_limit = len(baru_rows) * 0.5
    gate_lama_limit = len(lama_rows) * 0.5
    
    if len(baru_updates) > gate_baru_limit or len(lama_updates) > gate_lama_limit:
        print(f"\n[CRITICAL ERROR] Perubahan melebihi batas aman 50%!")
        print(f"  SBU Baru: {len(baru_updates)} > {gate_baru_limit}")
        print(f"  SBU Lama: {len(lama_updates)} > {gate_lama_limit}")
        print("  Eksekusi dibatalkan secara aman.")
        sys.exit(1)
        
    if not apply_db:
        print("\n[DRY RUN] Deteksi selesai. Gunakan bendera '--apply' untuk memperbarui ke Supabase.")
        return
        
    # 5. RUN BACKUP & APPLY
    backup_pre_apply(client)
    
    # Apply master_sbu_baru updates
    if baru_updates:
        print(f"\n[APPLY] Memperbarui {len(baru_updates)} baris di master_sbu_baru...")
        for u in baru_updates:
            client.table("master_sbu_baru").update({
                "nama_singkat": u["new_ns"],
                "nama_full": u["new_nf"]
            }).eq("kode", u["kode"]).execute()
        print("  [SUCCESS] master_sbu_baru diperbarui.")
        
    # Apply master_sbu_lama updates
    if lama_updates:
        print(f"\n[APPLY] Memperbarui {len(lama_updates)} baris di master_sbu_lama...")
        for u in lama_updates:
            client.table("master_sbu_lama").update({
                "nama_singkat": u["new_ns"]
            }).eq("kode", u["kode"]).execute()
        print("  [SUCCESS] master_sbu_lama diperbarui.")
        
    # 6. RUN fix_sbu_lama_nama_full.py to regenerate lama.nama_full and draft_paket_pl
    print("\n[RUN REGENERATION] Menjalankan skrip regenerasi nama_full lama dan draft_paket_pl...")
    py_exe = r"D:\Dokumen\@ POKJA 2026\V19_Scheduler\WPy64-313110\python\python.exe"
    script_path = r"d:\Dokumen\@ POKJA 2026\Asisten_Pokja\scratch\fix_sbu_lama_nama_full.py"
    
    res = subprocess.run([py_exe, script_path, "--apply"], capture_output=True, text=True)
    print("  === LOG REGENERATOR ===")
    print(res.stdout)
    if res.returncode != 0:
        print(f"  [ERROR] Regenerator gagal dengan exit code: {res.returncode}")
        print(res.stderr)
        sys.exit(res.returncode)
    print("  [SUCCESS] Regenerasi nama_full & draft_paket_pl selesai.")
    
    # 7. REGENERATE CSV MASTER
    print("\n[REGENERATE CSV] Menyusun ulang berkas CSV Master sbu_mapping_complete.csv...")
    
    # Fetch clean newly updated records
    fresh_baru = {r["kode"]: r for r in client.table("master_sbu_baru").select("*").execute().data}
    fresh_lama = {r["kode"]: r for r in client.table("master_sbu_lama").select("*").execute().data}
    fresh_maps = client.table("sbu_mapping").select("kode_baru, kode_lama").execute().data
    
    csv_rows = []
    for m in fresh_maps:
        kb = m["kode_baru"]
        kl = m["kode_lama"]
        
        row_baru = fresh_baru.get(kb, {})
        row_lama = fresh_lama.get(kl, {})
        
        # Helper classification infer prefix
        prefix = kb[:2].upper()
        # Lookup prefix in local PREFIX_KLASIFIKASI
        from extract_sbu_pdf import PREFIX_KLASIFIKASI
        klasifikasi = PREFIX_KLASIFIKASI.get(prefix, "N/A")
        
        csv_rows.append({
            "kode_baru": kb,
            "klasifikasi": klasifikasi,
            "kode_lama": kl,
            "nama_baru_singkat": row_baru.get("nama_singkat") or f"Subklasifikasi {kb}",
            "nama_lama_singkat": row_lama.get("nama_singkat") or f"Subklasifikasi {kl}",
            "kbli_2020": row_baru.get("kbli_2020") or "",
            "kbli_2017": row_lama.get("kbli_2017") or ""
        })
        
    csv_rows.sort(key=lambda x: (x["klasifikasi"], x["kode_baru"], x["kode_lama"]))
    
    csv_file = r"d:\Dokumen\@ POKJA 2026\Asisten_Pokja\data\sbu_mapping_complete.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["kode_baru", "klasifikasi", "kode_lama", "nama_baru_singkat", "nama_lama_singkat", "kbli_2020", "kbli_2017"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(csv_rows)
        
    print(f"  [SUCCESS] Berhasil menulis {len(csv_rows)} baris ter-normalisasi ke: {csv_file}")
    print("\nPROSES SELESAI. Semua data SBU sudah 100% dinormalisasi dan sinkron.")

if __name__ == "__main__":
    main()
