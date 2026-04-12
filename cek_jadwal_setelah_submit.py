"""Cek nilai tanggal di form setelah submit jadwal palsu."""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]
page = ctx.pages[0] if ctx.pages else ctx.new_page()

page.goto("https://spse.inaproc.id/tapinkab/jadwal/4618177/list",
          wait_until="domcontentloaded", timeout=30000)
page.wait_for_timeout(2000)

result = page.evaluate("""() => {
    const rows = document.querySelectorAll("#tblJadwal tbody tr");
    return Array.from(rows).map((tr, i) => {
        const mulai = tr.querySelector("input[name$='dtj_tglawal']");
        const selesai = tr.querySelector("input[name$='dtj_tglakhir']");
        const namaCell = tr.querySelector("td:nth-child(2)");
        let nama = "Tahap " + (i+1);
        if (namaCell) {
            const parts = namaCell.innerText.trim().split('\\n');
            nama = parts[0].trim();
        }
        return {
            tahap: i + 1,
            nama: nama.substring(0, 40),
            mulai: mulai ? mulai.value : "(tidak ada)",
            selesai: selesai ? selesai.value : "(tidak ada)"
        };
    });
}""")

print("=" * 90)
print("NILAI TANGGAL DI FORM SETELAH SUBMIT JADWAL PALSU:")
print("=" * 90)
for r in result:
    status = "✅ TERISI" if r["mulai"] != "(tidak ada)" and r["mulai"] else "❌ KOSONG"
    print(f"  {r['tahap']:2}. {r['nama']:<40} | Mulai: {r['mulai']:<18} | Selesai: {r['selesai']:<18} | {status}")

print("\n" + "=" * 90)
# Cek apakah ada alert/pesan error
alert = page.evaluate("""() => {
    const alerts = document.querySelectorAll('.alert-danger, .alert-warning, .alert-success, .alert-info');
    return Array.from(alerts).map(a => a.innerText.trim());
}""")
if alert:
    print("ALERT DI HALAMAN:")
    for a in alert:
        print(f"  ⚠️  {a[:200]}")
else:
    print("Tidak ada alert/pesan di halaman.")

page.close()
p.stop()
