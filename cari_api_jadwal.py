"""
Opsi C: Reverse engineer API SPSE untuk dapat hidden fields tanpa scrap HTML.
Cari endpoint yang return JSON dengan dtj_id, thp_id, akt_id.
"""
from playwright.sync_api import sync_playwright
import json

PAKET_ID = "4618177"
BASE = "https://spse.inaproc.id/tapinkab"

p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]
page = ctx.new_page()

# Intercept semua response untuk lihat API call
responses = []
page.on("response", lambda r: responses.append({
    "url": r.url,
    "status": r.status,
    "ct": r.headers.get("content-type", ""),
}))

print("Navigasi ke halaman jadwal...")
page.goto(f"{BASE}/jadwal/{PAKET_ID}/list", wait_until="domcontentloaded", timeout=30000)
page.wait_for_timeout(3000)

print(f"\n{'='*80}")
print(f"SEMUA RESPONSE YANG TERINTERCEPT ({len(responses)}):")
print(f"{'='*80}")

for r in responses:
    # Filter: hanya yang json atau api-like
    url = r["url"]
    if "json" in r["ct"].lower() or "api" in url.lower() or "ajax" in url.lower():
        print(f"\n  [{r['status']}] {r['ct'][:40]}")
        print(f"  {url}")

# Coba endpoint yang mungkin ada
print(f"\n{'='*80}")
print("COBA ENDPOINT POTENSIAL:")
print(f"{'='*80}")

endpoints = [
    f"{BASE}/jadwal/{PAKET_ID}/data",
    f"{BASE}/jadwal/{PAKET_ID}/json",
    f"{BASE}/jadwal/{PAKET_ID}/api",
    f"{BASE}/api/jadwal/{PAKET_ID}",
    f"{BASE}/jadwal/{PAKET_ID}/get",
    f"{BASE}/lelang/{PAKET_ID}/jadwal",
    f"{BASE}/lelang/{PAKET_ID}/jadwal/json",
]

for ep in endpoints:
    try:
        resp = page.evaluate(f"""(url) => fetch(url, {{credentials:'include'}}).then(r => ({{status:r.status, ok:r.ok, ct:r.headers.get('content-type')}})).catch(e => ({{error: e.message}}))""", ep)
        ct = resp.get("ct", resp.get("error", "?"))
        status = resp.get("status", "?")
        ok = resp.get("ok", False)
        mark = "✅" if ok else "  "
        print(f"  {mark} [{status}] {ct[:60]} | {ep.split('/tapinkab')[-1]}")
    except:
        print(f"     [err] {ep.split('/tapinkab')[-1]}")

# Coba scraping dari JS global (mungkin ada window.jadwalData atau sejenis)
print(f"\n{'='*80}")
print("CEK GLOBAL JS VARIABLES:")
print(f"{'='*80}")

globals_check = page.evaluate("""() => {
    const keys = ['jadwalData', 'jadwal', 'dataJadwal', 'lelang', 'paketData', 'formJadwal', 'jadwalDetail', 'jadwalList'];
    const found = {};
    keys.forEach(k => {
        if (typeof window[k] !== 'undefined') {
            found[k] = JSON.stringify(window[k]).substring(0, 300);
        }
    });
    return found;
}""")

if globals_check:
    for k, v in globals_check.items():
        print(f"\n  window.{k}:")
        print(f"  {v[:300]}")
else:
    print("  Tidak ada global variable yang ditemukan.")

# Cek apakah ada XHR di halaman
print(f"\n{'='*80}")
print("CEK NETWORK TRAFFIC (semua fetch/XHR):")
print(f"{'='*80}")

xhr_urls = [r for r in responses if r["ct"] and ("json" in r["ct"].lower() or "javascript" not in r["ct"].lower())]
if xhr_urls:
    for r in xhr_urls:
        print(f"  [{r['status']}] {r['url']}")
else:
    print("  Tidak ada XHR/fetch JSON yang terintercept.")

# Coba endpoint /lelang/{id}/edit (halaman edit lelang)
print(f"\n{'='*80}")
print(f"CEK: Apakah /lelang/{PAKET_ID}/edit punya data jadwal embedded?")
print(f"{'='*80}")

try:
    page.goto(f"{BASE}/lelang/{PAKET_ID}/edit", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    edit_html = page.content()
    
    # Cari pattern dtj_id atau thp_id di HTML
    import re
    dtj_matches = re.findall(r'dtj_id["\s=:]+(\d+)', edit_html)
    thp_matches = re.findall(r'thp_id["\s=:]+(\d+)', edit_html)
    
    if dtj_matches:
        print(f"  ✅ dtj_id ditemukan: {list(set(dtj_matches))[:5]}...")
    else:
        print(f"  ❌ dtj_id TIDAK ditemukan di halaman edit")
    
    if thp_matches:
        print(f"  ✅ thp_id ditemukan: {list(set(thp_matches))[:5]}...")
    else:
        print(f"  ❌ thp_id TIDAK ditemukan di halaman edit")
        
except Exception as e:
    print(f"  Error: {e}")

page.close()
p.stop()
print("\n✅ Investigasi selesai.")
