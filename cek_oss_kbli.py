"""Cek autocomplete/classification untuk Izin Usaha."""
from playwright.sync_api import sync_playwright
import json

p = sync_playwright().start()
b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = b.contexts[0]
pg = ctx.pages[-1]

pg.goto("https://spse.inaproc.id/tapinkab/dokumen/4618177/ldk", wait_until="domcontentloaded", timeout=30000)
pg.wait_for_timeout(2000)

# ── Cek struktur tblIjinUsaha ──
print("=" * 70)
print("STRUKTUR tblIjinUsaha:")
print("=" * 70)

tbl_html = pg.evaluate("""() => {
    const tbl = document.getElementById('tblIjinUsaha');
    return tbl ? tbl.outerHTML : 'TIDAK DITEMUKAN';
}""")
print(tbl_html[:2000])

# ── Cek JS events pada input ──
print(f"\n{'='*70}")
print("EVENT HANDLER pada input ijin:")
print(f"{'='*70}")

events = pg.evaluate("""() => {
    const inp = document.querySelector('input[name="ijin[0].chk_nama"]');
    if (!inp) return 'TIDAK DITEMUKAN';
    
    // Cek attributes
    const attrs = {};
    for (const a of inp.attributes) {
        attrs[a.name] = a.value;
    }
    
    // Cek data-* attributes (biasanya autocomplete URL)
    return JSON.stringify({
        attributes: attrs,
        dataset: inp.dataset || {},
        autocomplete: inp.autocomplete,
        maxLength: inp.maxLength,
    });
}""")
print(events)

# ── Cek JS global variables terkait OSS/KBLI ──
print(f"\n{'='*70}")
print("JS GLOBAL terkait OSS/KBLI:")
print(f"{'='*70}")

globals = pg.evaluate("""() => {
    const keys = ['oss', 'kbli', 'izin', 'IzinUsaha', 'ossUrl', 'baseUrl', 'base_url'];
    const found = {};
    keys.forEach(k => {
        if (typeof window[k] !== 'undefined') {
            found[k] = JSON.stringify(window[k]).substring(0, 200);
        }
    });
    return found;
}""")
for k, v in globals.items():
    print(f"  window.{k} = {v[:200]}")

# ── Cek file JS yang di-load ──
print(f"\n{'='*70}")
print("SCRIPT SRC yang di-load:")
print(f"{'='*70}")

scripts = pg.evaluate("""() => {
    return Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
}""")
for s in scripts:
    if 'form' in s.lower() or 'util' in s.lower() or 'common' in s.lower():
        print(f"  {s}")

b.close()
p.stop()
print("\n✅ Selesai.")
