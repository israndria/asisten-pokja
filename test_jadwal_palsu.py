"""
Test submit jadwal palsu (Januari 2025) — standalone, tidak butuh Streamlit.
Connect langsung ke Chrome CDP via Playwright sync API.
"""

from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import json
import sys
import urllib.request

CDP_PORT = 9222
PAKET_ID = "4618177"
TGL_MULAI = datetime(2025, 1, 15, 8, 0)
JAM_KERJA = (8, 17)

print("=" * 60)
print(f"TEST JADWAL PALSU — Paket {PAKET_ID}")
print(f"Tanggal mulai: {TGL_MULAI.strftime('%d/%m/%Y %H:%M')}")
print("=" * 60)

# ── Libur nasional cache ──
_libur_cache = {}

def fetch_libur(tahun):
    if tahun in _libur_cache:
        return _libur_cache[tahun]
    liburs = []
    for bulan in range(1, 13):
        try:
            url = f"https://dayoffapi.vercel.app/api?month={bulan}&year={tahun}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "tanggal" in item:
                            try:
                                tgl = datetime.strptime(item["tanggal"], "%Y-%m-%d")
                                if tgl not in liburs:
                                    liburs.append(tgl)
                            except:
                                pass
        except:
            pass
    _libur_cache[tahun] = liburs
    return liburs

def is_libur(dt):
    for l in fetch_libur(dt.year):
        if l.year == dt.year and l.month == dt.month and l.day == dt.day:
            return True
    return False

def is_weekend(dt):
    return dt.weekday() >= 5

def geser_hari_kerja(dt):
    attempts = 0
    while (is_weekend(dt) or is_libur(dt)) and attempts < 30:
        dt += timedelta(days=1)
        attempts += 1
    if dt.hour < JAM_KERJA[0] or dt.hour >= JAM_KERJA[1]:
        dt = dt.replace(hour=JAM_KERJA[0], minute=0, second=0, microsecond=0)
    return dt

def geser_jam_kerja(dt):
    if dt.hour < JAM_KERJA[0] or dt.hour >= JAM_KERJA[1]:
        dt = dt.replace(hour=JAM_KERJA[0], minute=0, second=0, microsecond=0)
        return geser_hari_kerja(dt)
    return dt

# ── Hitung jadwal ──
def hitung_jadwal(tgl):
    hasil = []
    t1 = tgl; t1s = t1 + timedelta(days=5)
    hasil.append({"nama": "Pengumuman Pascakualifikasi", "mulai": t1, "selesai": t1s})
    t2 = tgl; t2s = t2 + timedelta(days=6)
    hasil.append({"nama": "Download Dokumen Pemilihan", "mulai": t2, "selesai": t2s})
    t3k = t1 + timedelta(days=3); t3 = geser_hari_kerja(t3k); t3s = t3 + timedelta(hours=2)
    hasil.append({"nama": "Pemberian Penjelasan", "mulai": t3, "selesai": t3s})
    t4k = t3s + timedelta(hours=2); t4 = geser_hari_kerja(t4k); t4sk = t4 + timedelta(days=3); t4s = geser_hari_kerja(t4sk)
    hasil.append({"nama": "Upload Dokumen Penawaran", "mulai": t4, "selesai": t4s})
    t5 = t4s + timedelta(minutes=1); t5s = t5 + timedelta(hours=24)
    hasil.append({"nama": "Pembukaan Dokumen Penawaran", "mulai": t5, "selesai": t5s})
    t6 = t5 + timedelta(minutes=1); t6sk = t6 + timedelta(days=4); t6s = geser_hari_kerja(t6sk)
    hasil.append({"nama": "Evaluasi", "mulai": t6, "selesai": t6s})
    t7 = t6s.replace(hour=9, minute=0); t7s = t6s.replace(hour=15, minute=30)
    if t7.hour >= 15 or (t7.hour == 15 and t7.minute >= 30):
        t7 = geser_hari_kerja(t6s + timedelta(days=1)); t7 = t7.replace(hour=9); t7s = t7.replace(hour=15, minute=30)
    hasil.append({"nama": "Pembuktian Kualifikasi", "mulai": t7, "selesai": t7s})
    t8 = t7s; t8s = t8 + timedelta(hours=2)
    hasil.append({"nama": "Penetapan Pemenang", "mulai": t8, "selesai": t8s})
    t9 = t8s; t9s = t9 + timedelta(hours=4)
    hasil.append({"nama": "Pengumuman Pemenang", "mulai": t9, "selesai": t9s})
    t10k = t9s + timedelta(days=5); t10 = geser_jam_kerja(t10k); t10s = geser_hari_kerja(t10 + timedelta(days=5))
    hasil.append({"nama": "Masa Sanggah", "mulai": t10, "selesai": t10s})
    t11k = t10s + timedelta(hours=1); t11 = geser_hari_kerja(t11k); t11s = geser_hari_kerja(t11 + timedelta(days=5))
    hasil.append({"nama": "SPPBJ", "mulai": t11, "selesai": t11s})
    t12k = t11 + timedelta(days=1); t12 = geser_hari_kerja(t12k); t12s = geser_hari_kerja(t12 + timedelta(days=5))
    hasil.append({"nama": "Kontrak", "mulai": t12, "selesai": t12s})
    return hasil

jadwal_list = hitung_jadwal(TGL_MULAI)

print(f"\n[1/4] Hitung 12 tahapan dari {TGL_MULAI.strftime('%d/%m/%Y %H:%M')}...")
for j in jadwal_list:
    print(f"   {j['nama'][:45]:<45} {j['mulai'].strftime('%d/%m/%Y %H:%M')} → {j['selesai'].strftime('%d/%m/%Y %H:%M')}")

# ── Connect ke Chrome ──
print(f"\n[2/4] Connect ke Chrome CDP port {CDP_PORT}...")
p = sync_playwright().start()
try:
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
except Exception as e:
    print(f"❌ Gagal connect ke CDP: {e}")
    sys.exit(1)

ctx = browser.contexts[0] if browser.contexts else browser.new_context()
page = ctx.new_page()
print(f"✅ Connected. Tabs: {len(ctx.pages)}")

# ── Navigate & scrap ──
url_jadwal = f"https://spse.inaproc.id/tapinkab/jadwal/{PAKET_ID}/list"
print(f"\n[3/4] Scrap hidden fields dari {url_jadwal}...")
try:
    page.goto(url_jadwal, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    scraped = page.evaluate("""() => {
        const form = document.getElementById('jadwalEdit');
        if (!form) return null;
        const csrfInput = form.querySelector('input[name="authenticityToken"]');
        const idInput = form.querySelector('input[name="id"]');
        const jamAwal = document.getElementById('jamAwal');
        const jamAkhir = document.getElementById('jamAkhir');
        const result = {
            csrf: csrfInput ? csrfInput.value : null,
            id: idInput ? idInput.value : null,
            jamAwal: jamAwal ? jamAwal.value : '00:00',
            jamAkhir: jamAkhir ? jamAkhir.value : '23:59',
            rows: []
        };
        const rows = form.querySelectorAll('#tblJadwal tbody tr');
        rows.forEach((tr, idx) => {
            const hidden = {};
            tr.querySelectorAll('input[type="hidden"]').forEach(h => {
                hidden[h.name] = h.value;
            });
            const mulaiInput = tr.querySelector('input[name$="dtj_tglawal"]');
            const selesaiInput = tr.querySelector('input[name$="dtj_tglakhir"]');
            result.rows.push({
                index: idx,
                hidden: hidden,
                name_mulai: mulaiInput ? mulaiInput.name : null,
                name_selesai: selesaiInput ? selesaiInput.name : null,
            });
        });
        return result;
    }""")

    if not scraped:
        print("❌ Form tidak ditemukan!")
        print(f"   Title: {page.title()}")
        page.close()
        p.stop()
        sys.exit(1)

    print(f"✅ Scrap berhasil!")
    print(f"   CSRF: {'ada ✅' if scraped.get('csrf') else 'TIDAK ADA ❌'}")
    print(f"   Paket ID: {scraped.get('id')}")
    print(f"   Rows: {len(scraped.get('rows', []))}")

except Exception as e:
    print(f"❌ Error scrap: {e}")
    page.close()
    p.stop()
    sys.exit(1)

# ── Build payload ──
payload = {}
payload["id"] = scraped.get("id", "")
payload["jamAwal"] = scraped.get("jamAwal", "00:00")
payload["jamAkhir"] = scraped.get("jamAkhir", "23:59")
if scraped.get("csrf"):
    payload["authenticityToken"] = scraped["csrf"]

for i, j in enumerate(jadwal_list):
    if i < len(scraped.get("rows", [])):
        row = scraped["rows"][i]
        for hname, hval in row.get("hidden", {}).items():
            payload[hname] = hval
        if row.get("name_mulai"):
            payload[row["name_mulai"]] = j["mulai"].strftime("%d/%m/%Y %H:%M")
        if row.get("name_selesai"):
            payload[row["name_selesai"]] = j["selesai"].strftime("%d/%m/%Y %H:%M")

payload["simpan"] = "simpan"
print(f"\n[4/4] Submit payload ({len(payload)} fields) ke SPSE...")

# Simpan payload untuk referensi
with open("jadwal_test_payload.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, ensure_ascii=False)

# Submit via fetch
result = page.evaluate("""([url, payload]) => {
    const params = new URLSearchParams();
    for (const [key, val] of Object.entries(payload)) {
        params.append(key, String(val));
    }
    return fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: params.toString(),
    }).then(r => r.text().then(body => ({
        status: r.status,
        ok: r.ok,
        body: body.substring(0, 3000)
    })));
}""", [f"/tapinkab/jadwal/{PAKET_ID}/simpan", payload])

print(f"\n{'=' * 60}")
print(f"RESPONSE DARI SPSE:")
print(f"{'=' * 60}")
print(f"  Status Code: {result.get('status')}")
print(f"  OK: {result.get('ok')}")
body = result.get("body", "(kosong)")
print(f"\n  Body ({len(body)} chars):")
print(f"{'-' * 60}")
print(body)
print(f"{'=' * 60}")

if result.get("ok"):
    print("\n⚠️  MENGEJUTKAN — SPSE menerima jadwal Januari 2025!")
else:
    print("\n✅ EXPECTED — SPSE menolak jadwal masa lalu.")
    # Cari pesan error di body
    import re
    error_match = re.search(r'class="alert[^"]*"[^>]*>(.*?)</div>', body, re.DOTALL)
    if error_match:
        print(f"\n   Pesan error dari SPSE:")
        # Bersihkan HTML
        clean = re.sub(r'<[^>]+>', '', error_match.group(1)).strip()
        print(f"   {clean}")

page.close()
p.stop()
print("\n✅ Test selesai.")
