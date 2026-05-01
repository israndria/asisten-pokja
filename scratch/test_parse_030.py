import subprocess
import os
import json

python_exe = r"D:/Dokumen/@ POKJA 2026/V19_Scheduler/WPy64-313110/python/python.exe"
script_path = r"d:\Dokumen\@ POKJA 2026\V19_Scheduler\WPy64-313110\parse_reviu.py"
folder_input = r"d:\Dokumen\@ POKJA 2026\9. Pokja 030 - Normalisasi Sungai Lingkar Periuk Desa Masta Kec. Bakarangan"
output_folder = folder_input

cmd = [python_exe, script_path, folder_input, output_folder, "SDA"]
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
        print(f"Alat 1: {data['reviu']['E9']['nilai']} ({data['reviu']['E15']['nilai']}, {data['reviu']['E21']['nilai']})")
        print(f"Alat 2: {data['reviu']['E10']['nilai']} ({data['reviu']['E16']['nilai']}, {data['reviu']['E22']['nilai']})")
        print(f"Personil Teknis: {data['reviu']['E27']['nilai']} ({data['reviu']['E28']['nilai']} th, {data['reviu']['E29']['nilai']})")
        print(f"Personil K3: {data['reviu']['E30']['nilai']} ({data['reviu']['E31']['nilai']} th, {data['reviu']['E32']['nilai']})")
        print(f"E33 (RK3K): {data['reviu']['E33']['nilai']}")
        print(f"E34 (Risiko): {data['reviu']['E34']['nilai']}")
        print(f"Dokpil E6: {data['dokpil']['E6']['nilai']}")
        print(f"Dokpil E7: {data['dokpil']['E7']['nilai']}")
