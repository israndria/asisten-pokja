"""Test LDK langsung — klik checkbox di browser + lihat hasilnya."""
from playwright.sync_api import sync_playwright
import json

PAKET_ID = "4618177"
BASE = "https://spse.inaproc.id/tapinkab"

p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]
page = ctx.pages[-1]

print(f"Navigasi ke LDK...")
page.goto(f"{BASE}/dokumen/{PAKET_ID}/ldk", wait_until="domcontentloaded", timeout=30000)
page.wait_for_timeout(2000)

# ── Extract semua checkbox + label ──
checkboxes = page.evaluate("""() => {
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
            label: label,
            className: cb.className || '',
        });
    });
    return result;
}""")

# ── Klasifikasi manual ──
AUTO_KW = [
    "Memiliki pengalaman paling kurang 1 Pekerjaan Konstruksi",
    "Memperhitungkan Sisa Kemampuan Paket",
    "Untuk kualifikasi Usaha Kecil yang baru berdiri kurang dari 3",
]
SKIP_KW = ["konsorsium", "kerja sama operasi", "Kemampuan Dasar", "Sertifikat Manajemen Mutu", "Usaha Menengah atau Usaha Besar", "Leadfirm", "SBU"]

to_check = []
for cb in checkboxes:
    label_lower = cb["label"].lower()
    
    # Skip KSO
    if cb["className"] == "kso":
        print(f"  🔒 LOCKED (KSO): {cb['label'][:60]}...")
        continue
    
    # Disabled
    if cb["disabled"]:
        print(f"  🔒 LOCKED (disabled): {cb['label'][:60]}...")
        continue
    
    # Skip keywords
    if any(kw.lower() in label_lower for kw in SKIP_KW):
        print(f"  ⬜ SKIP: {cb['label'][:60]}...")
        continue
    
    # Auto check
    matched = False
    for kw in AUTO_KW:
        if kw.lower() in label_lower:
            print(f"  ✅ AUTO-CHECK: {cb['label'][:60]}...")
            to_check.append({"name": cb["name"], "value": cb["value"]})
            matched = True
            break
    
    if not matched:
        print(f"  ❓ UNKNOWN: {cb['label'][:60]}...")

print(f"\nCheckbox yang akan dicentang: {len(to_check)}")
for item in to_check:
    print(f"  → {item['name']} = {item['value']}")

# ── Klik checkbox ──
if to_check:
    print(f"\nKlik checkbox di browser...")
    clicked = page.evaluate("""(items) => {
        const result = [];
        items.forEach(item => {
            document.querySelectorAll(`input[type="checkbox"][name="${item.name}"][value="${item.value}"]`).forEach(cb => {
                if (!cb.checked && !cb.disabled) {
                    cb.checked = true;
                    cb.dispatchEvent(new Event('change', { bubbles: true }));
                    result.push(item.name);
                }
            });
        });
        return result;
    }""", to_check)
    print(f"  ✅ Checkbox tercentang: {clicked}")
    
    # Cek status setelah klik
    status_after = page.evaluate("""(items) => {
        return items.map(item => {
            const cb = document.querySelector(`input[type="checkbox"][name="${item.name}"][value="${item.value}"]`);
            return { name: item.name, checked: cb ? cb.checked : false };
        });
    }""", to_check)
    print(f"  Status setelah klik:")
    for s in status_after:
        print(f"    → {s['name']}: checked={s['checked']}")

    # ── Submit form ──
    print(f"\nSubmit form...")
    page.evaluate("""() => {
        const form = document.querySelector('form');
        if (form) form.submit();
    }""")
    
    page.wait_for_timeout(3000)
    print(f"  Halaman setelah submit: {page.evaluate('() => window.location.href')[:100]}")
    print(f"  Title: {page.evaluate('() => document.title')[:60]}")

browser.close()
p.stop()
print("\n✅ Selesai.")
