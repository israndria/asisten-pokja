"""Scrape detail form Izin Usaha."""
from playwright.sync_api import sync_playwright
import json

p = sync_playwright().start()
b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = b.contexts[0]
pg = ctx.pages[-1]

pg.goto("https://spse.inaproc.id/tapinkab/dokumen/4618177/ldk", wait_until="domcontentloaded", timeout=30000)
pg.wait_for_timeout(2000)

# ── Extract section Izin Usaha ──
result = pg.evaluate("""() => {
    // Cari elemen yang mengandung teks 'Izin Usaha' atau 'Jenis Izin'
    const allEls = document.querySelectorAll('*');
    const izinSections = [];
    
    allEls.forEach(el => {
        if (el.innerText && el.innerText.includes('Jenis Izin') && el.children.length < 20) {
            izinSections.push({
                tag: el.tagName,
                text: el.innerText.substring(0, 200),
                html: el.outerHTML.substring(0, 1000),
            });
        }
    });
    
    // Cari semua input di sekitar 'ijin'
    const ijinInputs = [];
    document.querySelectorAll('input[name*="ijin"]').forEach(el => {
        ijinInputs.push({
            name: el.name,
            type: el.type,
            value: el.value,
            placeholder: el.placeholder,
            id: el.id,
            className: el.className,
        });
    });
    
    // Cari select[name*="ijin"]
    const ijinSelects = [];
    document.querySelectorAll('select[name*="ijin"]').forEach(el => {
        ijinSelects.push({
            name: el.name,
            value: el.value,
            options: Array.from(el.options).map(o => ({text: o.text.substring(0,80), value: o.value})),
        });
    });
    
    return {
        sections: izinSections,
        inputs: ijinInputs,
        selects: ijinSelects,
    };
}""")

print("=" * 70)
print("SECTION IZIN USAHA:")
print("=" * 70)
for s in result["sections"]:
    print(f"\nTag: <{s['tag']}>")
    print(f"Text: {s['text'][:200]}")
    print(f"HTML: {s['html'][:500]}")

print(f"\n{'='*70}")
print("INPUTS name*='ijin':")
print(f"{'='*70}")
for inp in result["inputs"]:
    print(f"\n  name={inp['name']}")
    print(f"  type={inp['type']}")
    print(f"  value={inp['value'][:50] if inp['value'] else '(kosong)'}")
    print(f"  placeholder={inp['placeholder']}")
    print(f"  class={inp['className']}")

print(f"\n{'='*70}")
print("SELECTS name*='ijin':")
print(f"{'='*70}")
for sel in result["selects"]:
    print(f"\n  name={sel['name']}")
    print(f"  value={sel['value']}")
    print(f"  options ({len(sel['options'])}):")
    for o in sel['options'][:5]:
        print(f"    → '{o['text']}' (value={o['value']})")
    if len(sel['options']) > 5:
        print(f"    ... dan {len(sel['options'])-5} lainnya")

b.close()
p.stop()
print("\n✅ Selesai.")
