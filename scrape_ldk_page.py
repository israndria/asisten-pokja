"""Scrape LDK page — lihat semua checkbox + label + struktur HTML."""
from playwright.sync_api import sync_playwright
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import spse_browser

p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]

page = ctx.pages[-1] if ctx.pages else None
if not page:
    print("❌ Browser tidak terhubung!")
    exit(1)

current_url = page.evaluate("() => window.location.href")
current_title = page.evaluate("() => document.title")
print(f"Tab aktif: {current_title}")
print(f"URL: {current_url}")

# Deteksi paket ID
import re
match = re.search(r'/dokumen/(\d+)/', current_url)
if not match:
    match = re.search(r'/(46\d{5})', current_url)
if match:
    paket_id = match.group(1)
    ldk_url = f"https://spse.inaproc.id/tapinkab/dokumen/{paket_id}/ldk"
    print(f"\nNavigasi ke: {ldk_url}")
    page.goto(ldk_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
else:
    print("❌ Tidak bisa deteksi paket ID")
    exit(1)

# ── Extract semua checkbox + konteks HTML ──
print(f"\n{'='*80}")
print(f"SEMUA CHECKBOX DI HALAMAN LDK:")
print(f"{'='*80}")

checkboxes = page.evaluate("""() => {
    const result = [];
    document.querySelectorAll('input[type="checkbox"]').forEach((cb, i) => {
        let label = '';

        // 1. label[for=id]
        if (cb.id) {
            const lbl = document.querySelector('label[for="' + cb.id + '"]');
            if (lbl) label = lbl.innerText.trim();
        }
        // 2. label ancestor
        if (!label) {
            const pl = cb.closest('label');
            if (pl) label = pl.innerText.replace(/\\s+/g, ' ').trim();
        }
        // 3. td siblings in same tr
        if (!label) {
            const tr = cb.closest('tr');
            if (tr) {
                const tds = tr.querySelectorAll('td');
                for (const td of tds) {
                    if (!td.contains(cb)) { label = td.innerText.trim(); break; }
                }
            }
        }
        // 4. parent td text
        if (!label) {
            const td = cb.closest('td');
            if (td) label = td.innerText.trim();
        }

        // Text input/textarea in same row
        let textField = null;
        const container = cb.closest('tr') || cb.closest('div') || cb.parentElement;
        if (container) {
            const txt = container.querySelector('input[type="text"], textarea');
            if (txt) textField = { name: txt.name, id: txt.id, type: txt.type };
        }

        result.push({
            index: i,
            name: cb.name || '',
            value: cb.value || '',
            id: cb.id || '',
            checked: cb.checked,
            disabled: cb.disabled,
            label: label || '(tidak ada label)',
            textField: textField,
            className: cb.className || '',
        });
    });
    return result;
}""")

for cb in checkboxes:
    status = "✅" if cb["checked"] else "⬜"
    if cb["disabled"]: status = "🔒"
    print(f"\n  {status} [{cb['index']}] {cb['label'][:150]}")
    print(f"      name={cb['name']}, value={cb['value']}, id={cb['id']}")
    print(f"      class={cb['className']}")
    if cb['textField']:
        print(f"      text_field: name={cb['textField']['name']}, type={cb['textField']['type']}")

print(f"\n\nTotal checkbox: {len(checkboxes)}")

# ── Cek form ──
form_info = page.evaluate("""() => {
    const form = document.querySelector('form');
    if (!form) return { found: false };
    return {
        found: true,
        action: form.action,
        method: form.method,
        id: form.id,
        csrf_meta: document.querySelector('meta[name="csrf-token"]')?.content || null,
        csrf_input: document.querySelector('input[name="_token"]')?.value ||
                    document.querySelector('input[name="authenticityToken"]')?.value || null,
    };
}""")

import json
print(f"\n{'='*80}")
print(f"FORM INFO:")
print(f"{'='*80}")
print(json.dumps(form_info, indent=2) if form_info['found'] else "❌ Form tidak ditemukan")

# ── Ambil HTML sekitar 3 checkbox pertama untuk lihat struktur ──
print(f"\n{'='*80}")
print(f"CONTOH STRUKTUR HTML (3 checkbox pertama):")
print(f"{'='*80}")

html_samples = page.evaluate("""() => {
    const samples = [];
    document.querySelectorAll('input[type="checkbox"]').forEach((cb, i) => {
        if (i < 3) {
            const tr = cb.closest('tr');
            samples.push({
                index: i,
                tr_html: tr ? tr.outerHTML.substring(0, 500) : cb.parentElement?.outerHTML.substring(0, 500) || '',
            });
        }
    });
    return samples;
}""")

for s in html_samples:
    print(f"\n--- Checkbox [{s['index']}] ---")
    print(s['tr_html'][:500])

import json
browser.close()
p.stop()
print(f"\n\n✅ Scrap selesai.")
