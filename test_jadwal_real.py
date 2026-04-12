"""Test opsi A dengan tanggal REAL: Senin 13 April 2026 08:00."""
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import json, re

PAKET_ID = "4618177"
TGL_MULAI = datetime(2026, 4, 13, 8, 0)  # Senin 13 April 2026
JAM_KERJA = (8, 17)
BASE = "https://spse.inaproc.id/tapinkab"

print("=" * 70)
print(f"TEST OPSI A — Jadwal REAL (Senin 13 April 2026)")
print(f"Paket: {PAKET_ID}")
print("=" * 70)

# ── Helper ──
_libur = {}
def fetch_libur(th):
    if th in _libur: return _libur[th]
    liburs = []
    for bl in range(1, 13):
        try:
            import urllib.request
            url = f"https://dayoffapi.vercel.app/api?month={bl}&year={th}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                for item in json.loads(r.read()):
                    if isinstance(item, dict) and "tanggal" in item:
                        liburs.append(datetime.strptime(item["tanggal"], "%Y-%m-%d"))
        except: pass
    _libur[th] = liburs
    return liburs

def is_libur(dt):
    return any(l.year==dt.year and l.month==dt.month and l.day==dt.day for l in fetch_libur(dt.year))
def is_weekend(dt): return dt.weekday() >= 5

def geser_hari_kerja(dt):
    a = 0
    while (is_weekend(dt) or is_libur(dt)) and a < 30:
        dt += timedelta(days=1); a += 1
    if dt.hour < JAM_KERJA[0] or dt.hour >= JAM_KERJA[1]:
        dt = dt.replace(hour=JAM_KERJA[0], minute=0)
    return dt
def geser_jam_kerja(dt):
    if dt.hour < JAM_KERJA[0] or dt.hour >= JAM_KERJA[1]:
        dt = dt.replace(hour=JAM_KERJA[0], minute=0)
        return geser_hari_kerja(dt)
    return dt

def fmt(dt): return dt.strftime("%d/%m/%Y %H:%M")

# ── Hitung jadwal ──
t1 = TGL_MULAI; t1s = t1 + timedelta(days=5)
t2 = TGL_MULAI; t2s = t2 + timedelta(days=6)
t3k = t1 + timedelta(days=3); t3 = geser_hari_kerja(t3k); t3s = t3 + timedelta(hours=2)
t4k = t3s + timedelta(hours=2); t4 = geser_hari_kerja(t4k); t4s = geser_hari_kerja(t4 + timedelta(days=3))
t5 = t4s + timedelta(minutes=1); t5s = t5 + timedelta(hours=24)
t6 = t5 + timedelta(minutes=1); t6s = geser_hari_kerja(t6 + timedelta(days=4))
t7 = t6s.replace(hour=9); t7s = t6s.replace(hour=15, minute=30)
if t7.hour >= 15 or (t7.hour==15 and t7.minute>=30):
    t7 = geser_hari_kerja(t6s+timedelta(days=1)).replace(hour=9); t7s = t7.replace(hour=15,minute=30)
t8 = t7s; t8s = t8 + timedelta(hours=2)
t9 = t8s; t9s = t9 + timedelta(hours=4)
t10k = t9s + timedelta(days=5); t10 = geser_jam_kerja(t10k); t10s = geser_hari_kerja(t10 + timedelta(days=5))
t11k = t10s + timedelta(hours=1); t11 = geser_hari_kerja(t11k); t11s = geser_hari_kerja(t11 + timedelta(days=5))
t12k = t11 + timedelta(days=1); t12 = geser_hari_kerja(t12k); t12s = geser_hari_kerja(t12 + timedelta(days=5))

jadwal = [
    ("Pengumuman Pascakualifikasi", t1, t1s),
    ("Download Dokumen Pemilihan", t2, t2s),
    ("Pemberian Penjelasan", t3, t3s),
    ("Upload Dokumen Penawaran", t4, t4s),
    ("Pembukaan Dokumen Penawaran", t5, t5s),
    ("Evaluasi Administrasi/Kualifikasi", t6, t6s),
    ("Pembuktian Kualifikasi", t7, t7s),
    ("Penetapan Pemenang", t8, t8s),
    ("Pengumuman Pemenang", t9, t9s),
    ("Masa Sanggah", t10, t10s),
    ("SPPBJ", t11, t11s),
    ("Penandatanganan Kontrak", t12, t12s),
]

print(f"\n[1/5] Hitung jadwal dari {fmt(TGL_MULAI)}:")
for nama, m, s in jadwal:
    print(f"   {nama:<45} {fmt(m)} → {fmt(s)}")

# ── Connect & scrap via background tab ──
print(f"\n[2/5] Connect Chrome CDP & scrap via background tab...")
p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
ctx = browser.contexts[0]

# Cek halaman user SEBELUM scrap
user_page = ctx.pages[-1] if ctx.pages else ctx.new_page()
user_url_before = user_page.evaluate("() => window.location.href")
user_title_before = user_page.evaluate("() => document.title")
print(f"   Halaman user SEBELUM: {user_title_before[:60]}")

# Buat background tab
bg = ctx.new_page()
bg.goto(f"{BASE}/jadwal/{PAKET_ID}/list", wait_until="domcontentloaded", timeout=30000)
bg.wait_for_timeout(3000)

scraped = bg.evaluate("""() => {
    const form = document.getElementById('jadwalEdit');
    if (!form) return null;
    const r = {
        csrf: form.querySelector('input[name="authenticityToken"]')?.value || null,
        id: form.querySelector('input[name="id"]')?.value || null,
        jamAwal: document.getElementById('jamAwal')?.value || '00:00',
        jamAkhir: document.getElementById('jamAkhir')?.value || '23:59',
        rows: []
    };
    document.querySelectorAll('#tblJadwal tbody tr').forEach((tr, idx) => {
        const h = {};
        tr.querySelectorAll('input[type="hidden"]').forEach(i => { h[i.name] = i.value; });
        const m = tr.querySelector('input[name$="dtj_tglawal"]');
        const s = tr.querySelector('input[name$="dtj_tglakhir"]');
        r.rows.push({ index: idx, hidden: h, name_mulai: m?.name||null, name_selesai: s?.name||null });
    });
    return r;
}""")

bg.close()

# Buat tab baru untuk submit (karena bg sudah ditutup)
submit_page = ctx.new_page()

# Cek halaman user SETELAH scrap
user_url_after = user_page.evaluate("() => window.location.href")
user_title_after = user_page.evaluate("() => document.title")
print(f"   Halaman user SETELAH: {user_title_after[:60]}")

if not scraped:
    print("   ❌ Scrap gagal!")
    browser.close(); p.stop(); exit(1)

print(f"   ✅ Scrap berhasil: CSRF ada={bool(scraped['csrf'])}, {len(scraped['rows'])} rows")
if user_url_before == user_url_after:
    print(f"   ✅ Halaman user TIDAK BERUBAH (background tab works!)")
else:
    print(f"   ⚠️  Halaman user berubah!")

# ── Build payload ──
payload = {"id": scraped["id"], "jamAwal": scraped["jamAwal"], "jamAkhir": scraped["jamAkhir"]}
if scraped["csrf"]: payload["authenticityToken"] = scraped["csrf"]
for i, (nama, m, s) in enumerate(jadwal):
    if i < len(scraped["rows"]):
        row = scraped["rows"][i]
        for hn, hv in row["hidden"].items(): payload[hn] = hv
        if row.get("name_mulai"): payload[row["name_mulai"]] = fmt(m)
        if row.get("name_selesai"): payload[row["name_selesai"]] = fmt(s)
payload["simpan"] = "simpan"

print(f"\n[3/5] Payload built: {len(payload)} fields")

# ── Submit ──
print(f"\n[4/5] Submit ke SPSE...")
# Navigasi dulu ke domain SPSE (halaman kosong cepat)
submit_page.goto(f"{BASE}/home", wait_until="domcontentloaded", timeout=15000)

result = submit_page.evaluate("""([url, payload]) => {
    const p = new URLSearchParams();
    for (const [k,v] of Object.entries(payload)) p.append(k, String(v));
    return fetch(url, {method:'POST',credentials:'include',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:p.toString()})
        .then(r => r.text().then(b => ({status:r.status,ok:r.ok,redirected:r.redirected,url:r.url,bodyLen:b.length,
            hasErr:b.includes('alert-danger')||b.includes('alert-warning'),
            hasOk:b.includes('alert-success')})));
}""", [f"/tapinkab/jadwal/{PAKET_ID}/simpan", payload])

print(f"   Status: {result['status']}, OK: {result['ok']}, Redirected: {result['redirected']}")
print(f"   Body: {result['bodyLen']} chars, hasError: {result['hasErr']}, hasSuccess: {result['hasOk']}")

# ── Cek apakah data tersimpan ──
print(f"\n[5/5] Cek apakah data tersimpan di form...")
submit_page.goto(f"{BASE}/jadwal/{PAKET_ID}/list", wait_until="domcontentloaded", timeout=30000)
submit_page.wait_for_timeout(2000)

filled = submit_page.evaluate("""() => {
    const rows = document.querySelectorAll('#tblJadwal tbody tr');
    const result = [];
    rows.forEach((tr, i) => {
        const m = tr.querySelector('input[name$="dtj_tglawal"]');
        const s = tr.querySelector('input[name$="dtj_tglakhir"]');
        const namaCell = tr.querySelector('td:nth-child(2)');
        let nama = "Tahap " + (i+1);
        if (namaCell) nama = namaCell.innerText.trim().split('\\n')[0].trim().substring(0,40);
        result.push({
            nama,
            mulai: m ? m.value : '',
            selesai: s ? s.value : ''
        });
    });
    return result;
}""")

filled_count = sum(1 for f in filled if f["mulai"])
print(f"   Field terisi: {filled_count}/12")

if filled_count == 12:
    print(f"\n{'='*70}")
    print("✅✅✅ SUKSES! Jadwal TERSIMPAN di SPSE! ✅✅✅")
    print(f"{'='*70}")
    for f in filled:
        print(f"   {f['nama']:<45} {f['mulai']:<18} → {f['selesai']}")
elif filled_count > 0:
    print(f"\n⚠️  SEBAGIAN tersimpan ({filled_count}/12):")
    for f in filled:
        status = "✅" if f["mulai"] else "❌"
        print(f"   {status} {f['nama']:<45} {f['mulai'] or '(kosong)':<18}")
else:
    print(f"\n❌ Data TIDAK tersimpan — SPSE menolak (mungkin validasi server-side)")
    # Cek alert
    alerts = submit_page.evaluate("""() => {
        const a = document.querySelectorAll('.alert-danger,.alert-warning,.alert-success');
        return Array.from(a).map(x => x.innerText.trim().substring(0,200));
    }""")
    if alerts:
        print(f"   Alert: {alerts}")

submit_page.close()
browser.close()
p.stop()
print(f"\n{'='*70}")
print("TEST SELESAI")
print(f"{'='*70}")
