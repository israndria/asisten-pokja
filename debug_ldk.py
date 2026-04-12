"""
Debug Tab 3 LDK Auto-fill — scan form, klasifikasi, build payload.
Test langsung ke halaman LDK SPSE.
"""
from playwright.sync_api import sync_playwright
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import spse_browser
import ldk_engine
import ldk_config

print("=" * 70)
print("DEBUG: Tab 3 LDK Auto-fill — Persyaratan Kualifikasi")
print("=" * 70)

# ── 1. Connect Chrome ──
print("\n[1/5] Connect Chrome CDP...")
p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]

# Set untuk spse_browser
spse_browser._context = ctx
spse_browser._page = ctx.pages[-1] if ctx.pages else None

page = spse_browser.halaman_aktif()
if not page:
    print("❌ Browser tidak terhubung!")
    exit(1)

current_url = page.evaluate("() => window.location.href")
current_title = page.evaluate("() => document.title")
print(f"   Tab aktif: {current_title[:60]}")
print(f"   URL: {current_url[:100]}")

# ── 2. Deteksi paket ID ──
print("\n[2/5] Deteksi paket ID dari URL...")
import re
match = re.search(r'/dokumen/(\d+)/', current_url)
if not match:
    # Coba dari URL lain
    match = re.search(r'/(\d{7,})', current_url)

if match:
    paket_id = match.group(1)
    print(f"   ✅ Paket ID: {paket_id}")
    ldk_url = f"https://spse.inaproc.id/tapinkab/dokumen/{paket_id}/ldk"
    print(f"   URL LDK: {ldk_url}")
else:
    print("   ❌ Tidak bisa deteksi paket ID dari URL")
    print("   Buka halaman dokumen paket di browser dulu!")
    browser.close()
    p.stop()
    exit(1)

# ── 3. Navigasi ke LDK ──
print(f"\n[3/5] Navigasi ke halaman LDK...")
page.goto(ldk_url, wait_until="domcontentloaded", timeout=30000)
page.wait_for_timeout(3000)

ldk_url_aktif = page.evaluate("() => window.location.href")
ldk_title = page.evaluate("() => document.title")
print(f"   ✅ Halaman: {ldk_title[:60]}")
print(f"   URL: {ldk_url_aktif[:100]}")

# ── 4. Scan form ──
print(f"\n[4/5] Scan form LDK...")
try:
    form_info = ldk_engine.scan_ldk_form()
except Exception as e:
    print(f"   ❌ Error scan: {e}")
    browser.close()
    p.stop()
    exit(1)

print(f"   ✅ Scan berhasil!")
print(f"   Form action: {form_info.get('action', '?')}")
print(f"   Form method: {form_info.get('method', '?')}")
print(f"   CSRF: {'✅ ada' if form_info.get('csrf') else '❌ tidak ditemukan'}")
print(f"   Total checkbox: {len(form_info.get('checkboxes', []))}")

# Klasifikasi
classified = ldk_engine.classify_checkboxes(form_info)

print(f"\n   Klasifikasi:")
print(f"   🔒 Locked:         {len(classified['locked'])}")
print(f"   ✅ Auto-check:     {len(classified['auto_check'])}")
print(f"   ✅ Check + Fill:   {len(classified['check_and_fill'])}")
print(f"   ⬜ Skip:           {len(classified['skip'])}")
print(f"   ❓ Unknown:        {len(classified['unknown'])}")

# Detail
if classified["auto_check"]:
    print(f"\n   ✅ AUTO-CHECK items:")
    for cb in classified["auto_check"]:
        print(f"      • {cb['label'][:120]}")

if classified["check_and_fill"]:
    print(f"\n   ✅ CHECK + FILL items:")
    for cb, cfg in classified["check_and_fill"]:
        print(f"      • {cb['label'][:120]}")
        print(f"        → Teks: {cfg['text'][:100]}...")

if classified["skip"]:
    print(f"\n   ⬜ SKIP items:")
    for cb in classified["skip"]:
        print(f"      • {cb['label'][:120]}")

if classified["unknown"]:
    print(f"\n   ❓ UNKNOWN items:")
    for cb in classified["unknown"]:
        fallback = f"name={cb['name']} value={cb['value']}"
        print(f"      • {cb['label'][:120] or fallback}")

if classified["locked"]:
    print(f"\n   🔒 LOCKED items:")
    for cb in classified["locked"]:
        print(f"      • {cb['label'][:120] or '(tanpa label)'}")

# ── 5. Build payload preview ──
print(f"\n[5/5] Build payload preview...")
payload = ldk_engine.build_payload(form_info, classified)
print(f"   Payload fields: {len(payload)}")
print(f"\n   Payload JSON:")
import json
print(json.dumps(payload, indent=2, ensure_ascii=False))

# ── Tanya user ──
print(f"\n{'='*70}")
print("DEBUG SELESAI")
print(f"{'='*70}")
print("\nIngin submit ke SPSE? (y/n): ", end="")
try:
    jawaban = input().strip().lower()
    if jawaban == 'y':
        print("\nSubmit ke SPSE...")
        result = ldk_engine.submit_ldk(form_info, payload)
        print(f"   Status: {result.get('status', '?')}")
        print(f"   OK: {result.get('ok', False)}")
        if result.get('ok'):
            print("   ✅ Submit berhasil!")
        else:
            print(f"   ❌ Submit gagal: {result}")
    else:
        print("   Submit dibatalkan.")
except:
    print("   Submit dibatalkan.")

browser.close()
p.stop()
print("\n✅ Selesai.")
