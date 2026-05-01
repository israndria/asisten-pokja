import subprocess
import os
import json

python_exe = r"D:/Dokumen/@ POKJA 2026/V19_Scheduler/WPy64-313110/python/python.exe"
script_path = r"d:\Dokumen\@ POKJA 2026\V19_Scheduler\WPy64-313110\parse_reviu.py"
folder_input = r"D:\Dokumen\@ POKJA 2026\10. Pokja 034 - Normalisasi Dan Penambahan Alur Sei. Bahari Ds. Sawaja Kec. CLU"
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
        print(f"E33 (Uraian RK3): {data['reviu']['E33']['nilai']}")
        print(f"E34 (Bahaya RT): {data['reviu']['E34']['nilai']}")
