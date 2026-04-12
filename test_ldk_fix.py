"""Test LDK Auto-fill — fix checkbox + submit native."""
from playwright.sync_api import sync_playwright
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import spse_browser
import ldk_engine
import ldk_config

PAKET_ID = "4618177"
BASE = "https://spse.inaproc.id/tapinkab"

print("=" * 70)
print("TEST LDK Auto-fill — Fix Checkbox + Submit Native")
print("=" * 70)

# ── Connect ──
p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]

spse_browser._context = ctx
spse_browser._page = ctx.pages[-1] if ctx.pages else None

page = spse_browser.halaman_aktif()
if not page:
    print("❌ Browser tidak terhubung!")
    exit(1)

# ── Navigasi ke LDK ──
print(f"\n[1/4] Navigasi ke LDK...")
page.goto(f"{BASE}/dokumen/{PAKET_ID}/ldk", wait_until="domcontentloaded", timeout=30000)
page.wait_for_timeout(2000)
print(f"   ✅ Halaman: {page.evaluate('() => document.title')[:60]}")

# ── Scan ──
print(f"\n[2/4] Scan form...")

# Pakai evaluate langsung (sync) karena playwright sync_api tidak butuh _run
SCAN_JS = """() => {
    const form = document.querySelector('form');
    const csrfInput = document.querySelector('input[name="_token"]') ||
                      document.querySelector('input[name="authenticityToken"]');
    const csrf = csrfInput ? csrfInput.value : '';

    const checkboxes = [];
    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        let label = '';
        if (cb.id) {
            const lbl = document.querySelector('label[for="' + cb.id + '"]');
            if (lbl) label = lbl.innerText.trim();
        }
        if (!label) {
            const tr = cb.closest('tr');
            if (tr) {
                const tds = tr.querySelectorAll('td');
                for (const td of tds) {
                    if (!td.contains(cb)) { label = td.innerText.trim(); break; }
                }
            }
        }
        if (!label) {
            const pl = cb.closest('label');
            if (pl) label = pl.innerText.replace(/\\s+/g, ' ').trim();
        }

        let textInputName = null;
        const container = cb.closest('tr') || cb.closest('div') || cb.parentElement;
        if (container) {
            const txt = container.querySelector('input[type="text"], textarea');
            if (txt) textInputName = txt.name || txt.id || null;
        }

        const hiddenFields = {};
        if (container) {
            container.querySelectorAll('input[type="hidden"]').forEach(h => {
                hiddenFields[h.name] = h.value;
            });
        }

        checkboxes.push({
            name: cb.name || '',
            value: cb.value || '',
            checked: cb.checked,
            disabled: cb.disabled,
            label: label,
            textInputName: textInputName,
            hiddenFields: hiddenFields,
            className: cb.className || '',
        });
    });

    return {
        action: form ? form.action : window.location.href,
        method: form ? form.method.toUpperCase() : 'POST',
        csrf: csrf,
        checkboxes: checkboxes,
    };
}"""

form_info = page.evaluate(SCAN_JS)
print(f"   Action: {form_info['action']}")
print(f"   CSRF: {'✅' if form_info.get('csrf') else '❌'} (len={len(form_info.get('csrf',''))})")
print(f"   Checkbox: {len(form_info['checkboxes'])}")

# ── Klasifikasi ──
print(f"\n[3/4] Klasifikasi...")
classified = ldk_engine.classify_checkboxes(form_info)
print(f"   🔒 Locked:    {len(classified['locked'])}")
print(f"   ✅ Auto:      {len(classified['auto_check'])}")
print(f"   ✅ Fill:      {len(classified['check_and_fill'])}")
print(f"   ⬜ Skip:      {len(classified['skip'])}")
print(f"   ❓ Unknown:   {len(classified['unknown'])}")

# Detail auto_check
for cb in classified['auto_check']:
    print(f"      → {cb['label'][:80]}...")
for cb, cfg in classified['check_and_fill']:
    print(f"      → {cb['label'][:80]}... (text: {cfg['text'][:50]}...)")

# Payload
payload = ldk_engine.build_payload(form_info, classified)
print(f"\n   Payload: {len(payload)} fields")
print(f"   {json.dumps(list(payload.keys()), indent=2, ensure_ascii=False)[:500]}")

# ── Submit ──
print(f"\n[4/4] Submit ke SPSE...")
try:
    result = ldk_engine.submit_ldk(form_info, payload)
    print(f"   Status: {result}")
except Exception as e:
    print(f"   ❌ Error: {e}")

browser.close()
p.stop()
print("\n✅ Test selesai.")
