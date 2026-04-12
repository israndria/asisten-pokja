"""Debug script: ambil HTML + teks dari halaman jadwal SPSE."""
from playwright.sync_api import sync_playwright
import json

p = sync_playwright().start()
print("Connecting to CDP...")
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]

# Cek tab yang sudah terbuka
pages = ctx.pages
print(f"Existing tabs: {len(pages)}")
for i, pg in enumerate(pages):
    try:
        print(f"  [{i}] {pg.title()[:60]} | {pg.url[:80]}")
    except:
        print(f"  [{i}] (closed/error)")

# Navigasi ke halaman jadwal
print("\nNavigasi ke jadwal...")
page = ctx.pages[-1] if ctx.pages else ctx.new_page()
page.goto(
    "https://spse.inaproc.id/tapinkab/jadwal/4618177/list",
    timeout=60000,
    wait_until="domcontentloaded",
)
print(f"Loaded: {page.title()}")

# Tunggu konten render
print("Tunggu konten render...")
page.wait_for_timeout(5000)

# Ambil HTML lengkap
html = page.content()
with open("jadwal_debug.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"\nHTML saved: jadwal_debug.html ({len(html):,} bytes)")

# Ambil teks tubuh halaman (potong ke 8000 karakter)
body_text = page.inner_text("body")
with open("jadwal_debug_text.txt", "w", encoding="utf-8") as f:
    f.write(body_text)
print(f"Text saved: jadwal_debug_text.txt ({len(body_text):,} chars)")
print("\n--- BODY TEXT (first 4000 chars) ---")
print(body_text[:4000])

# Ambil tabel jadwal
tables = page.query_selector_all("table")
print(f"\n--- Found {len(tables)} table(s) ---")
for i, tbl in enumerate(tables):
    rows = tbl.query_selector_all("tr")
    print(f"\nTable {i}: {len(rows)} rows")
    for j, row in enumerate(rows[:30]):  # max 30 baris
        cells = row.query_selector_all("th, td")
        vals = [c.inner_text().strip() for c in cells]
        print(f"  Row {j}: {vals}")

# Screenshot
page.screenshot("jadwal_screenshot.png", full_page=True)
print("\nScreenshot saved: jadwal_screenshot.png")

p.stop()
print("Done.")
