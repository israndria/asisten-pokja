import subprocess
import os
import json

python_exe = r"D:/Dokumen/@ POKJA 2026/V19_Scheduler/WPy64-313110/python/python.exe"
script_path = r"d:\Dokumen\@ POKJA 2026\V19_Scheduler\WPy64-313110\parse_reviu.py"
folder_input = r"D:\Dokumen\@ POKJA 2026\1. Pokja 086 - Perbaikan - Peningkatan Jalan Desa Hatungun Rt.06, Kab. Tapin"
output_folder = folder_input

cmd = [python_exe, script_path, folder_input, output_folder, "Bina Marga"]
print(f"Running: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)

json_path = os.path.join(output_folder, "_parse_reviu.json")
if os.path.exists(json_path):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
        print("\n--- RESULTS ---")
        print(f"E2 (Fungsi): {data['reviu']['E2']['nilai']}")
        print(f"E16 (Kegiatan): {data['input_data']['E16']['nilai']}")
        print(f"E32 (Lokasi): {data['input_data']['E32']['nilai']}")
        print(f"E33 (Sumber Dana): {data['input_data']['E33']['nilai']}")
        print(f"Alat 1: {data['reviu']['E9']['nilai']} ({data['reviu']['E15']['nilai']}, {data['reviu']['E21']['nilai']})")
        print(f"Alat 2: {data['reviu']['E10']['nilai']} ({data['reviu']['E16']['nilai']}, {data['reviu']['E22']['nilai']})")
        print(f"E33 (RK3K): {data['reviu']['E33']['nilai']}")
        print(f"E34 (Risiko): {data['reviu']['E34']['nilai']}")
        print(f"Dokpil E6: {data['dokpil']['E6']['nilai']}")
        print(f"Dokpil E7: {data['dokpil']['E7']['nilai']}")
