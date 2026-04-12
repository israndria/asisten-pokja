"""Test lebih detail: intercept response submit."""
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import json

p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]

# Buat page baru
page = ctx.new_page()

# Intercept response untuk lihat status code asli
responses = []
page.on("response", lambda r: responses.append({
    "url": r.url,
    "status": r.status,
    "ok": r.ok
}))

PAKET_ID = "4618177"
url_jadwal = f"https://spse.inaproc.id/tapinkab/jadwal/{PAKET_ID}/list"

print(f"Navigasi ke {url_jadwal}...")
page.goto(url_jadwal, wait_until="domcontentloaded", timeout=30000)
page.wait_for_timeout(3000)
print(f"Title: {page.title()}")

# Scrap
scraped = page.evaluate("""() => {
    const form = document.getElementById('jadwalEdit');
    if (!form) return null;
    const result = {
        csrf: form.querySelector('input[name="authenticityToken"]')?.value || null,
        id: form.querySelector('input[name="id"]')?.value || null,
        jamAwal: document.getElementById('jamAwal')?.value || '00:00',
        jamAkhir: document.getElementById('jamAkhir')?.value || '23:59',
        rows: []
    };
    document.querySelectorAll('#tblJadwal tbody tr').forEach((tr, idx) => {
        const hidden = {};
        tr.querySelectorAll('input[type="hidden"]').forEach(h => { hidden[h.name] = h.value; });
        const m = tr.querySelector('input[name$="dtj_tglawal"]');
        const s = tr.querySelector('input[name$="dtj_tglakhir"]');
        result.rows.push({ index: idx, hidden, name_mulai: m?.name || null, name_selesai: s?.name || null });
    });
    return result;
}""")

if not scraped:
    print("Gagal scrap!")
    page.close()
    p.stop()
    exit(1)

print(f"CSRF: {scraped['csrf'][:20]}...")
print(f"Rows: {len(scraped['rows'])}")

# Build payload dengan tanggal 2025
payload = {}
payload["id"] = scraped["id"]
payload["jamAwal"] = scraped["jamAwal"]
payload["jamAkhir"] = scraped["jamAkhir"]
payload["authenticityToken"] = scraped["csrf"]
for i in range(len(scraped["rows"])):
    row = scraped["rows"][i]
    for h, v in row["hidden"].items():
        payload[h] = v
    # Tanggal palsu: 15/01/2025 08:00 - 20/01/2025 08:00
    if row["name_mulai"]:
        payload[row["name_mulai"]] = "15/01/2025 08:00"
    if row["name_selesai"]:
        payload[row["name_selesai"]] = "20/01/2025 08:00"
payload["simpan"] = "simpan"

# Clear response log
responses.clear()

print(f"\nSubmit ke /tapinkab/jadwal/{PAKET_ID}/simpan ...")

# Submit via fetch
result = page.evaluate("""([url, payload]) => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(payload)) {
        params.append(k, String(v));
    }
    return fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
    }).then(async r => {
        const text = await r.text();
        return {
            status: r.status,
            ok: r.ok,
            url: r.url,
            redirected: r.redirected,
            bodyLen: text.length,
            bodyPreview: text.substring(0, 500),
            // Cek apakah ada alert error di body
            hasError: text.includes('alert-danger') || text.includes('alert-warning'),
            hasSuccess: text.includes('alert-success'),
            hasInfo: text.includes('alert-info'),
        };
    });
}""", [f"/tapinkab/jadwal/{PAKET_ID}/simpan", payload])

print(f"\n{'='*70}")
print(f"RESPONSE DETAIL:")
print(f"{'='*70}")
for k, v in result.items():
    print(f"  {k}: {v}")

# Cek responses
print(f"\n{'='*70}")
print(f"INTERCEPTED RESPONSES ({len(responses)}):")
print(f"{'='*70}")
for r in responses:
    if "jadwal" in r["url"].lower() and r["status"] != 200:
        print(f"  [{r['status']}] {r['url']}")

# Refresh halaman dan cek apakah data berubah
print(f"\nRefresh halaman untuk cek apakah data tersimpan...")
page.reload(wait_until="domcontentloaded", timeout=30000)
page.wait_for_timeout(2000)

filled = page.evaluate("""() => {
    const rows = document.querySelectorAll('#tblJadwal tbody tr');
    let filledCount = 0;
    rows.forEach((tr, i) => {
        const m = tr.querySelector('input[name$="dtj_tglawal"]');
        const s = tr.querySelector('input[name$="dtj_tglakhir"]');
        if (m && m.value) filledCount++;
    });
    return { filledCount };
}""")

print(f"  Field terisi setelah refresh: {filled['filledCount']}/24")

# Cek alert
alerts = page.evaluate("""() => {
    const a = document.querySelectorAll('.alert-danger, .alert-warning, .alert-success, .alert-info');
    return Array.from(a).map(x => ({type: x.className.split(' ')[1] || 'alert', text: x.innerText.trim().substring(0,200)}));
}""")
if alerts:
    print(f"\n  Alert ditemukan:")
    for a in alerts:
        print(f"    [{a['type']}] {a['text'][:150]}")
else:
    print(f"\n  Tidak ada alert ditemukan.")

page.close()
p.stop()
print(f"\n{'='*70}")
print("TEST SELESAI")
print(f"{'='*70}")
