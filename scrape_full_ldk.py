"""Scrape full LDK page structure."""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = b.contexts[0]
pg = ctx.pages[-1]

print("Navigasi ke LDK...")
pg.goto("https://spse.inaproc.id/tapinkab/dokumen/4618177/ldk", wait_until="domcontentloaded", timeout=30000)
pg.wait_for_timeout(3000)

title = pg.evaluate("() => document.title")
print(f"Title: {title}")

# ── Full page text ──
page_text = pg.evaluate("() => document.body.innerText")
print(f"\n{'='*60}")
print(f"FULL PAGE TEXT:")
print(f"{'='*60}")
print(page_text[:5000])

# ── All checkboxes ──
print(f"\n{'='*60}")
print(f"CHECKBOXES:")
print(f"{'='*60}")
checkboxes = pg.evaluate("""() => {
    const result = [];
    document.querySelectorAll('input[type="checkbox"]').forEach((cb, i) => {
        let label = '';
        const tr = cb.closest('tr');
        if (tr) {
            const tds = tr.querySelectorAll('td');
            for (const td of tds) {
                if (!td.contains(cb)) { label = td.innerText.trim(); break; }
            }
        }
        result.push({
            i, name: cb.name, value: cb.value,
            checked: cb.checked, disabled: cb.disabled,
            label: label || '(no label)',
            className: cb.className || '',
        });
    });
    return result;
}""")

for cb in checkboxes:
    status = "✅" if cb["checked"] else "⬜"
    if cb["disabled"]: status = "🔒"
    print(f"  {status} [{cb['i']}] {cb['label'][:100]}")
    print(f"      name={cb['name']}, value={cb['value']}, class={cb['className']}")

# ── All text inputs ──
print(f"\n{'='*60}")
print(f"TEXT INPUTS:")
print(f"{'='*60}")
text_inputs = pg.evaluate("""() => {
    const result = [];
    document.querySelectorAll('input[type="text"]').forEach((el, i) => {
        let label = '';
        const tr = el.closest('tr');
        if (tr) {
            const tds = tr.querySelectorAll('td');
            for (const td of tds) {
                if (!td.contains(el)) { label = td.innerText.trim(); break; }
            }
        }
        result.push({
            i, name: el.name, value: el.value,
            placeholder: el.placeholder, className: el.className,
            label: label || '(no label)',
        });
    });
    return result;
}""")

for inp in text_inputs:
    print(f"  [{inp['i']}] {inp['label'][:80]}")
    print(f"      name={inp['name']}, value='{inp['value']}', class={inp['className']}")

# ── Buttons ──
print(f"\n{'='*60}")
print(f"BUTTONS:")
print(f"{'='*60}")
buttons = pg.evaluate("""() => {
    return Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]')).map((el, i) => ({
        i, tag: el.tagName, type: el.type, text: el.innerText?.trim() || el.value || '',
        className: el.className || '',
    }));
}""")

for btn in buttons:
    print(f"  [{btn['i']}] <{btn['tag']}> {btn['text'][:60]} (class={btn['className']})")

# ── Full HTML of tblIjinUsaha ──
print(f"\n{'='*60}")
print(f"HTML tblIjinUsaha:")
print(f"{'='*60}")
ijin_html = pg.evaluate("""() => {
    const tbl = document.getElementById('tblIjinUsaha');
    return tbl ? tbl.outerHTML : 'NOT FOUND';
}""")
print(ijin_html[:2000])

# ── Full HTML of tblSyaratAdmin ──
print(f"\n{'='*60}")
print(f"HTML tblSyaratAdmin (first 3000):")
print(f"{'='*60}")
admin_html = pg.evaluate("""() => {
    const tbl = document.getElementById('tblSyaratAdmin');
    return tbl ? tbl.outerHTML : 'NOT FOUND';
}""")
print(admin_html[:3000])

b.close()
p.stop()
print("\n✅ Selesai.")
