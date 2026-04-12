"""Test scrap background tab — user tidak lihat navigasi."""
from playwright.sync_api import sync_playwright
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import spse_browser
import jadwal_engine

PAKET_ID = "4618177"

print("=" * 60)
print("TEST: Scrap Hidden Fields via Tab Background")
print("=" * 60)

# Connect manual (tanpa Streamlit)
p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]

# Set global context untuk spse_browser
spse_browser._context = ctx
spse_browser._page = ctx.pages[-1] if ctx.pages else None

# Cek halaman aktif SEBELUM scrap
page_awal = spse_browser.halaman_aktif()
url_awal = ""
title_awal = ""
if page_awal:
    url_awal = page_awal.evaluate("() => window.location.href")
    title_awal = page_awal.evaluate("() => document.title")

print(f"\nHalaman SEBELUM scrap:")
print(f"  Title: {title_awal[:60]}")
print(f"  URL: {url_awal[:80]}")
print(f"  Total tabs: {len(ctx.pages)}")

# Scrap via background tab
print(f"\nScrap hidden fields paket {PAKET_ID}...")
try:
    scraped = jadwal_engine.scrap_hidden_fields(PAKET_ID)
    if scraped:
        print(f"✅ Scrap berhasil!")
        print(f"   CSRF: {scraped['csrf'][:30]}...")
        print(f"   Paket ID: {scraped['id']}")
        print(f"   Rows: {len(scraped['rows'])}")
    else:
        print("❌ Scrap gagal: form tidak ditemukan")
except Exception as e:
    print(f"❌ Error: {e}")

# Cek halaman SESUDAH scrap
page_akhir = spse_browser.halaman_aktif()
url_akhir = ""
title_akhir = ""
if page_akhir:
    url_akhir = page_akhir.evaluate("() => window.location.href")
    title_akhir = page_akhir.evaluate("() => document.title")

print(f"\nHalaman SESUDAH scrap:")
print(f"  Title: {title_akhir[:60]}")
print(f"  URL: {url_akhir[:80]}")
print(f"  Total tabs: {len(ctx.pages)}")

# Verifikasi: halaman tidak berubah
if url_awal == url_akhir and title_awal == title_akhir:
    print(f"\n✅ VERIFIKASI: Halaman user TIDAK BERUBAH — background tab berhasil!")
else:
    print(f"\n❌ MASALAH: Halaman user berubah!")
    print(f"   Dari: {url_awal[:60]}")
    print(f"   Ke: {url_akhir[:60]}")

browser.close()
p.stop()
print("\n✅ Test selesai.")
