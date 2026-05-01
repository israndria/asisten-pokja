import os
import httpx

# Baca secret
env_path = r"d:\Dokumen\@ POKJA 2026\V19_Scheduler\WPy64-313110\secret_supabase.env"
secrets = {}
with open(env_path, "r") as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            secrets[k] = v

url = secrets.get("SUPABASE_URL", "").strip('"')
key = secrets.get("SUPABASE_KEY", "").strip('"')

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}"
}

# Coba fetch list table (via postgrest openapi)
try:
    r = httpx.get(f"{url}/rest/v1/", headers=headers)
    if r.status_code == 200:
        print("Daftar Tabel di Supabase:")
        print(r.text)
    else:
        print(f"Gagal: {r.status_code}")
        print(r.text)
except Exception as e:
    print(f"Error: {e}")
