"""Cari field 'Izin Usaha' di halaman LDK."""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = b.contexts[0]
pg = ctx.pages[-1]

pg.goto("https://spse.inaproc.id/tapinkab/dokumen/4618177/ldk", wait_until="domcontentloaded", timeout=30000)
pg.wait_for_timeout(2000)

# ── Cari semua input type=text, select, textarea ──
print("=" * 70)
print("SEMUA INPUT FIELD DI HALAMAN LDK:")
print("=" * 70)

inputs = pg.evaluate("""() => {
    const result = [];
    
    // text inputs
    document.querySelectorAll('input[type="text"]').forEach((el, i) => {
        let label = '';
        const tr = el.closest('tr');
        if (tr) {
            const tds = tr.querySelectorAll('td');
            for (const td of tds) {
                if (!td.contains(el)) { label = td.innerText.trim(); break; }
            }
        }
        if (!label) {
            const lbl = el.previousElementSibling;
            if (lbl) label = lbl.innerText?.trim() || '';
        }
        result.push({
            type: 'text',
            name: el.name || '',
            id: el.id || '',
            placeholder: el.placeholder || '',
            value: el.value || '',
            label: label || '(tidak ada label)',
            required: el.required || false,
        });
    });
    
    // selects
    document.querySelectorAll('select').forEach((el, i) => {
        let label = '';
        const tr = el.closest('tr');
        if (tr) {
            const tds = tr.querySelectorAll('td');
            for (const td of tds) {
                if (!td.contains(el)) { label = td.innerText.trim(); break; }
            }
        }
        result.push({
            type: 'select',
            name: el.name || '',
            id: el.id || '',
            value: el.value || '',
            label: label || '(tidak ada label)',
            options: Array.from(el.options).map(o => ({text: o.text.substring(0,60), value: o.value})),
        });
    });
    
    // textareas
    document.querySelectorAll('textarea').forEach((el, i) => {
        let label = '';
        const tr = el.closest('tr');
        if (tr) {
            const tds = tr.querySelectorAll('td');
            for (const td of tds) {
                if (!td.contains(el)) { label = td.innerText.trim(); break; }
            }
        }
        result.push({
            type: 'textarea',
            name: el.name || '',
            id: el.id || '',
            label: label || '(tidak ada label)',
        });
    });
    
    return result;
}""")

for inp in inputs:
    req = "🔴" if inp.get("required") else "  "
    print(f"\n  {req} [{inp['type'].upper()}] {inp.get('label', '')[:100]}")
    print(f"      name={inp['name']}, id={inp['id']}")
    if inp.get('placeholder'): print(f"      placeholder={inp['placeholder']}")
    if inp.get('value'): print(f"      value={inp['value'][:50]}")
    if inp.get('options'):
        print(f"      options: {[o['text'] for o in inp['options'][:5]]}")

# ── Cari spesifik 'izin usaha' ──
print(f"\n{'='*70}")
print("CARI FIELD 'IZIN USAHA':")
print(f"{'='*70}")

izin_search = pg.evaluate("""() => {
    // Cari label yang mengandung 'izin' atau 'usaha'
    const allText = document.body.innerText;
    const lines = allText.split('\\n').filter(l => 
        l.toLowerCase().includes('izin') || l.toLowerCase().includes('usaha')
    );
    return lines.map(l => l.trim()).filter(l => l.length > 0);
}""")

for line in izin_search:
    print(f"  → {line[:120]}")

b.close()
p.stop()
print("\n✅ Selesai.")
