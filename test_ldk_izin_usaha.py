"""Test LDK + Isi Izin Usaha + Submit."""
from playwright.sync_api import sync_playwright
import time

p = sync_playwright().start()
b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = b.contexts[0]
pg = ctx.pages[-1]

print("Navigasi ke LDK...")
pg.goto("https://spse.inaproc.id/tapinkab/dokumen/4618177/ldk", wait_until="domcontentloaded", timeout=30000)
pg.wait_for_timeout(2000)

# ── 1. Centang 3 checkbox ──
print("\n[1/3] Centang checkbox...")
checkboxes_to_check = [
    {"name": "syaratTeknis[0].ckm_id", "value": "437"},
    {"name": "syaratTeknis[1].ckm_id", "value": "438"},
    {"name": "syaratTeknis[2].ckm_id", "value": "439"},
]
pg.evaluate("""(items) => {
    items.forEach(item => {
        document.querySelectorAll(`input[type="checkbox"][name="${item.name}"][value="${item.value}"]`).forEach(cb => {
            if (!cb.checked && !cb.disabled) {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
    });
}""", checkboxes_to_check)

# Verify
status = pg.evaluate("""(items) => {
    return items.map(item => {
        const cb = document.querySelector(`input[type="checkbox"][name="${item.name}"][value="${item.value}"]`);
        return { name: item.name, checked: cb ? cb.checked : false };
    });
}""", checkboxes_to_check)
for s in status:
    print(f"  {s['name']}: checked={s['checked']}")

# ── 2. Isi Izin Usaha ──
print("\n[2/3] Isi Izin Usaha...")

# Isi field Jenis Izin
ijin_nama = pg.query_selector('input[name="ijin[0].chk_nama"]')
if ijin_nama:
    ijin_nama.fill("Izin Usaha")
    print(f"  ✅ ijin[0].chk_nama = '{ijin_nama.input_value()}'")

# Isi field Klasifikasi — pakai KBLI konstruksi umum
ijin_klas = pg.query_selector('input[name="ijin[0].chk_klasifikasi"]')
if ijin_klas:
    ijin_klas.fill("41001 - Konstruksi Umum")
    print(f"  ✅ ijin[0].chk_klasifikasi = '{ijin_klas.input_value()}'")

# ── 3. Submit ──
print("\n[3/3] Submit form...")
pg.evaluate("""() => {
    const form = document.querySelector('form');
    if (form) form.submit();
}""")

pg.wait_for_timeout(4000)

url_after = pg.evaluate("() => window.location.href")
title_after = pg.evaluate("() => document.title")
print(f"  URL: {url_after[:100]}")
print(f"  Title: {title_after[:80]}")

# Cek alert/error
alerts = pg.evaluate("""() => {
    const a = document.querySelectorAll('.alert-danger,.alert-warning,.alert-success,.bs-callout-danger');
    return Array.from(a).map(x => x.innerText.trim().substring(0, 300));
}""")
if alerts:
    print(f"\n  Alert dari SPSE:")
    for a in alerts:
        print(f"    → {a[:200]}")
else:
    print("\n  Tidak ada alert — cek apakah data tersimpan...")

# Cek apakah checkbox masih tercentang
checked_count = pg.evaluate("""() => {
    return document.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)').length;
}""")
print(f"\n  Checkbox tercentang (non-disabled): {checked_count}")

# Cek field izin usaha
ijin_val = pg.evaluate("""() => {
    const n = document.querySelector('input[name="ijin[0].chk_nama"]');
    const k = document.querySelector('input[name="ijin[0].chk_klasifikasi"]');
    return { nama: n?.value || '', klas: k?.value || '' };
}""")
print(f"  Izin Usaha: nama='{ijin_val['nama']}', klas='{ijin_val['klas']}'")

b.close()
p.stop()
print("\n✅ Test selesai.")
