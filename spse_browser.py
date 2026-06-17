"""SPSE Browser Automation — Playwright di thread terpisah (Streamlit-safe)."""

import os
import asyncio
import threading
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext

from config import SPSE_BASE_URL, BROWSER_SESSION_DIR, DOWNLOAD_DIR

# Patch subprocess.Popen agar Playwright tidak spawn console hitam di Windows
import subprocess as _subprocess
_OrigPopen = _subprocess.Popen
class _NoCmdWindowPopen(_OrigPopen):
    def __init__(self, *args, **kwargs):
        if os.name == "nt":
            si = kwargs.pop("startupinfo", None) or _subprocess.STARTUPINFO()
            si.dwFlags |= _subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = _subprocess.SW_HIDE
            kwargs["startupinfo"] = si
            kwargs.setdefault("creationflags", 0)
            kwargs["creationflags"] |= _subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)
_subprocess.Popen = _NoCmdWindowPopen

# ============================================================
# Event loop di thread terpisah (agar tidak konflik dengan Streamlit)
# ============================================================

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_pw = None
_context: BrowserContext | None = None
_page: Page | None = None


def _start_loop():
    global _loop
    _loop = asyncio.ProactorEventLoop()  # Windows: wajib ProactorEventLoop untuk subprocess
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _ensure_loop():
    global _loop, _loop_thread
    if _loop is None or not _loop.is_running():
        _loop_thread = threading.Thread(target=_start_loop, daemon=True)
        _loop_thread.start()
        import time; time.sleep(0.3)


def _run(coro, timeout=60):
    """Jalankan coroutine di background loop, tunggu hasilnya."""
    _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)




# ============================================================
# Auto-Refresh Daemon
# ============================================================
_refresh_event = threading.Event()
_refresh_thread: threading.Thread | None = None

def _refresh_worker(interval_menit: int):
    import time
    while not _refresh_event.is_set():
        # Sleep per 5 detik supaya interupsi cepat
        for _ in range(interval_menit * 60 // 5):
            if _refresh_event.is_set():
                return
            time.sleep(5)
            
        if _refresh_event.is_set():
            return
            
        if not _cek_cdp_aktif():
            break
            
        try:
            refresh_browser()
        except Exception:
            pass

def mulai_auto_refresh(interval_menit: int = 10):
    global _refresh_thread
    if _refresh_thread and _refresh_thread.is_alive():
        return
        
    _refresh_event.clear()
    _refresh_thread = threading.Thread(target=_refresh_worker, args=(interval_menit,), daemon=True)
    _refresh_thread.start()

def stop_auto_refresh():
    _refresh_event.set()
    if _refresh_thread and _refresh_thread.is_alive():
        _refresh_thread.join(timeout=1.0)

# ============================================================
# Session management
# ============================================================

CHROME_EXE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
CHROME_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\MSI\AppData\Local"), "BraveSoftware", "Brave-Browser", "User Data")
CDP_PORT = 9222


async def _connect_cdp_async(url: str = "", navigate: bool = True):
    """Connect ke Chrome yang sudah jalan via CDP.
    Jika navigate=False, hanya connect tanpa membuka tab baru (cepat, untuk auto-reconnect).
    """
    global _pw, _context, _page
    if _pw is None:
        _pw = await async_playwright().start()
    import os as _os
    _downloads_dir = _os.path.join(_os.path.expanduser("~"), "Downloads")
    browser = await _pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
    # Pakai context pertama (window Chrome yang sudah terbuka)
    if browser.contexts:
        _context = browser.contexts[0]
    else:
        _context = await browser.new_context()
    # Set download behavior ke folder Downloads user via CDP session langsung
    # (accept_downloads tidak bisa di-set ke existing context via Playwright API)
    try:
        pages = _context.pages
        if pages:
            cdp_session = await _context.new_cdp_session(pages[0])
            await cdp_session.send("Browser.setDownloadBehavior", {
                "behavior": "allowAndName",
                "downloadPath": _downloads_dir,
                "eventsEnabled": True,
            })
            await cdp_session.detach()
    except Exception:
        pass
    # Pakai tab yang sudah ada (tab pertama/aktif), jangan buka tab baru saat reconnect
    if _context.pages:
        _page = _context.pages[0]
    else:
        _page = await _context.new_page()
    if navigate and url:
        await _page.goto(url, wait_until="domcontentloaded", timeout=30000)
    return _page


def _cek_cdp_aktif() -> bool:
    """Cek apakah Chrome sudah listen di CDP port."""
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", CDP_PORT), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def buka_browser(url: str = SPSE_BASE_URL, navigate: bool = True):
    """Connect ke Chrome SPSE via CDP.
    navigate=True  : buka tab baru dan navigasi ke url (untuk koneksi manual)
    navigate=False : hanya connect, pakai tab yang sudah ada (untuk auto-reconnect cepat)
    Chrome harus sudah dibuka via 'Buka Chrome SPSE.bat' terlebih dahulu.
    """
    if not _cek_cdp_aktif():
        raise RuntimeError(
            "Brave SPSE belum terbuka. "
            "Brave harus sudah dibuka via 'Buka Brave POKJA.bat' terlebih dahulu."
        )
    return _run(_connect_cdp_async(url, navigate=navigate))


def launch_chrome_dengan_cdp():
    """Launch Brave baru dengan remote-debugging-port + buka SPSE langsung (1 tab)."""
    import subprocess, shutil
    # Hapus session lama agar tidak restore tab
    session_dir = BROWSER_SESSION_DIR
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)
    os.makedirs(session_dir, exist_ok=True)
    subprocess.Popen([
        CHROME_EXE,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={session_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        SPSE_BASE_URL,
    ])


async def _tutup_async():
    global _pw, _context, _page
    if _context:
        await _context.close()
    if _pw:
        await _pw.stop()
    _pw = _context = _page = None


def tutup_browser():
    """Tutup Chrome: via Playwright jika connect, fallback CDP Browser.close, lalu diskonek."""
    stop_auto_refresh()
    global _pw, _context, _page, _cdp_tabs_cache, _cdp_tabs_cache_ts
    if _context:
        _run(_tutup_async())
    else:
        # Fallback: kirim CDP command Browser.close langsung via HTTP
        import requests as _req
        try:
            tabs = _req.get(f"http://localhost:{CDP_PORT}/json", timeout=2).json()
            if tabs:
                ws_url = tabs[0].get("webSocketDebuggerUrl", "")
                # Pakai /json/close/{id} per tab, lalu Browser.close via CDP WebSocket tidak mudah lewat requests
                # Alternatif: POST ke /json/close semua tab
                for t in tabs:
                    try:
                        _req.get(f"http://localhost:{CDP_PORT}/json/close/{t['id']}", timeout=2)
                    except Exception:
                        pass
        except Exception:
            pass
    # Selalu reset state
    _pw = _context = _page = None
    _cdp_tabs_cache = []
    _cdp_tabs_cache_ts = 0.0
    # Hapus last_role saat browser ditutup
    try:
        from pathlib import Path as _Path
        _rf = _Path(__file__).parent / ".browser_session" / "last_role.txt"
        if _rf.exists():
            _rf.unlink()
    except Exception:
        pass


def refresh_browser():
    """Reload tab aktif Chrome via CDP HTTP (tidak butuh Playwright _page)."""
    import requests as _req
    global _cdp_tabs_cache, _cdp_tabs_cache_ts
    try:
        tabs = _req.get(f"http://localhost:{CDP_PORT}/json", timeout=2).json()
        page_tabs = [t for t in tabs if t.get("type") == "page"]
        if not page_tabs:
            return False
        # Reload background — jangan activate (foreground takeover)
        tab = page_tabs[0]
        current_url = tab.get("url", "")
        # Jika Playwright tersedia, pakai reload
        page = halaman_aktif()
        if page and not page.is_closed():
            try:
                page.reload(timeout=15000)
                _cdp_tabs_cache = []
                _cdp_tabs_cache_ts = 0.0
                return True
            except Exception:
                pass
        # Fallback: navigate ulang ke URL yang sama via Playwright connect
        if current_url and current_url.startswith("http"):
            try:
                buka_browser(current_url, navigate=True)
                _cdp_tabs_cache = []
                _cdp_tabs_cache_ts = 0.0
                return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def diskonek():
    """Reset koneksi Playwright tanpa menutup browser. Berguna jika CDP sudah ditutup manual."""
    global _pw, _context, _page, _cdp_tabs_cache, _cdp_tabs_cache_ts
    _pw = _context = _page = None
    _cdp_tabs_cache = []
    _cdp_tabs_cache_ts = 0.0


def _kill_browser():
    """Kill hanya proses Brave CDP (listen port 9222) + reset state."""
    stop_auto_refresh()
    import subprocess
    diskonek()
    try:
        # Cari PID yang listen di port 9222
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, shell=True, timeout=5
        )
        pids = set()
        for line in result.stdout.splitlines():
            if ":9222" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pids.add(parts[-1])

        # Kill hanya PID tersebut (bukan semua brave.exe)
        for pid in pids:
            if pid.isdigit():
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True, shell=True
                )
    except Exception:
        pass


async def _ubah_metode_async(kode_paket: str, kategori_id: int, pilih: int, base_url: str) -> str:
    """
    Navigasi ke /metode via Playwright, pilih kategori + radio, accept confirm dialog, klik Simpan.
    Return: "OK" jika sukses, pesan error jika gagal.
    """
    global _context
    if _context is None:
        buka_browser(navigate=False)
    if _context is None:
        return "CDP tidak tersambung"

    page = await _context.new_page()
    try:
        # Auto-accept dialog (confirm/alert) — asyncio.ensure_future agar tidak deadlock
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        url_metode = f"{base_url}nontender/{kode_paket}/metode"
        await page.goto(url_metode, wait_until="domcontentloaded", timeout=20000)

        # Pilih kategori dari dropdown + dispatch change event
        await page.select_option("select[name='kategoriId']", str(kategori_id))
        await page.dispatch_event("select[name='kategoriId']", "change")
        await page.wait_for_timeout(1000)  # tunggu JS update radio list

        # Klik radio pilih + dispatch change event
        radio_selector = f"input[name='pilih'][value='{pilih}']"
        await page.check(radio_selector)
        await page.dispatch_event(radio_selector, "change")
        await page.wait_for_timeout(500)

        # Klik Simpan → trigger confirm() → auto-accept → form submit
        await page.click("button[name='simpan']")
        await page.wait_for_timeout(4000)

        # Verifikasi redirect ke /edit (sukses)
        if "/edit" in page.url:
            return "OK"
        return f"Gagal redirect, posisi URL: {page.url}"
    except Exception as e:
        return f"Error: {e}"
    finally:
        await page.close()


def ubah_metode_via_playwright(kode_paket: str, kategori_id: int, pilih: int, base_url: str) -> str:
    """
    Ubah metode pengadaan via Playwright CDP (handle JS confirm dialog).
    Return "OK" jika sukses, pesan error jika gagal.
    """
    return _run(_ubah_metode_async(kode_paket, kategori_id, pilih, base_url), timeout=45)


async def _update_ijin_sbu_async(kode_paket: str, ijin_idx: int, klas_baru: str, base_url: str) -> str:
    """
    Update isi field ijin[N].chk_klasifikasi di form LDK via Playwright CDP, lalu submit.
    Dipakai karena server SPSE block update ijin existing via requests POST (nilai di-revert).
    Return "OK" jika sukses, pesan error jika gagal.
    """
    global _context
    if _context is None:
        buka_browser(navigate=False)
    if _context is None:
        return "CDP tidak tersambung"

    page = await _context.new_page()
    try:
        url_ldk = f"{base_url}dokumennontender/{kode_paket}/ldk"
        await page.goto(url_ldk, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1000)

        # Set nilai baru pada field ijin klasifikasi
        field_selector = f"input[name='ijin[{ijin_idx}].chk_klasifikasi']"
        await page.eval_on_selector(
            field_selector,
            f"(el) => {{ el.value = {repr(klas_baru)}; }}"
        )

        # Submit form
        await page.click("button[type='submit'], input[type='submit']")
        await page.wait_for_timeout(3000)

        if "/ldk" in page.url:
            return "OK"
        return f"Gagal redirect, URL: {page.url}"
    except Exception as e:
        return f"Error: {e}"
    finally:
        await page.close()


def update_ijin_sbu_via_playwright(kode_paket: str, ijin_idx: int, klas_baru: str, base_url: str) -> str:
    """
    Update teks klasifikasi SBU pada baris ijin[N] di form LDK nontender via Playwright CDP.
    Server SPSE tidak bisa update ijin existing via requests POST, harus via browser real.
    Return "OK" jika sukses, pesan error jika gagal.
    """
    return _run(_update_ijin_sbu_async(kode_paket, ijin_idx, klas_baru, base_url), timeout=45)


def _format_npwp_15(npwp_raw: str) -> str:
    """
    Konversi NPWP ke format XX.XXX.XXX.X-XXX.XXX (15 digit SPSE).
    Handle:
      - 15 digit → langsung format
      - 16 digit (NPWP baru) → strip prefix 1 digit terdepan (biasanya '1')
      - 14 digit → pad trailing '0' jadi 15
      - Sudah ada titik/strip → kembalikan as-is
    """
    if "." in npwp_raw and "-" in npwp_raw:
        return npwp_raw  # sudah terformat
    digits = "".join(c for c in npwp_raw if c.isdigit())
    if len(digits) == 16:
        digits = digits[1:]   # strip prefix NPWP 16 digit
    elif len(digits) == 14:
        digits = digits + "0" # pad trailing 0
    if len(digits) != 15:
        return npwp_raw  # fallback
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}.{digits[8]}-{digits[9:12]}.{digits[12:15]}"


async def _pilih_penyedia_async(kode_paket: str, npwp: str, base_url: str, nama_penyedia: str = "") -> dict:
    """
    Buka /pilihpenyedia/{kode} via browser CDP.
    Strategi 1: goto URL dengan ?search=true&npwp=XX.XXX.XXX.X-XXX.XXX (SPSE auto-trigger search).
    Strategi 2: search manual by nama (kata signifikan pertama), lalu filter NPWP 16-digit di hasil.
    """
    global _context
    if _context is None:
        await _connect_cdp_async(navigate=False)
    if _context is None:
        return {"ok": False, "pesan": "CDP tidak tersambung"}

    page = await _context.new_page()
    try:
        npwp_fmt = _format_npwp_15(npwp)
        # Digits NPWP 16: strip non-digit dari raw input, pad ke 16
        npwp_digits = "".join(c for c in npwp if c.isdigit())
        npwp16 = npwp_digits.zfill(16) if len(npwp_digits) <= 16 else npwp_digits[:16]

        found = False
        search_mode = ""
        chk_idx = 0  # index checkbox yang cocok

        # Strategi 1: URL dengan query string NPWP → SPSE langsung trigger search
        url_npwp = f"{base_url}nontender/{kode_paket}/pilihpenyedia?search=true&nama=&npwp={npwp_fmt}"
        await page.goto(url_npwp, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2000)

        chk_count = await page.locator("input.chk").count()
        if chk_count > 0:
            found = True
            search_mode = "npwp_url"
            # Cari checkbox yang NPWP 16-nya cocok
            for _ci in range(chk_count):
                _chk = page.locator("input.chk").nth(_ci)
                _idx = (await _chk.get_attribute("name") or "").split("[")[-1].split("]")[0]
                _npwp16_field = await page.locator(f"#rekananNpwp16_{_idx}").get_attribute("value") if _idx.isdigit() else ""
                if npwp16 and _npwp16_field and _npwp16_field.strip() == npwp16:
                    chk_idx = _ci
                    break

        # Strategi 2: search by nama jika NPWP tidak ketemu
        if not found and nama_penyedia:
            kata = [w for w in nama_penyedia.upper().split()
                    if w not in ("CV.", "PT.", "CV", "PT", "UD.", "UD", "TB.", "TB",
                                 "FIRMA", "FA.", "FA", "KOPERASI")]
            if kata:
                url_base = f"{base_url}nontender/{kode_paket}/pilihpenyedia"
                await page.goto(url_base, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(1500)
                await page.locator("input[name='nama']").fill(kata[0])
                await page.locator("button:has-text('Cari Penyedia')").click()
                await page.wait_for_timeout(3000)

                chk_count = await page.locator("input.chk").count()
                if chk_count > 0:
                    # Filter: cari yang NPWP 16 atau nama cocok
                    for _ci in range(chk_count):
                        _chk = page.locator("input.chk").nth(_ci)
                        _idx = (await _chk.get_attribute("name") or "").split("[")[-1].split("]")[0]
                        if not _idx.isdigit():
                            continue
                        _np16 = (await page.locator(f"#rekananNpwp16_{_idx}").get_attribute("value") or "").strip()
                        _nm = (await page.locator(f"#rekananNama_{_idx}").get_attribute("value") or "").strip().upper()
                        if (npwp16 and _np16 == npwp16) or _nm == nama_penyedia.upper():
                            chk_idx = _ci
                            found = True
                            search_mode = "nama_exact"
                            break
                    if not found and chk_count == 1:
                        # Hanya 1 hasil → ambil saja
                        chk_idx = 0
                        found = True
                        search_mode = "nama_single"

        if not found:
            return {"ok": False, "pesan": f"Penyedia tidak ditemukan (NPWP: {npwp_fmt}, nama: {nama_penyedia})"}

        # Ambil nama penyedia dari hidden field
        nama_hasil = ""
        try:
            chk_el = page.locator("input.chk").nth(chk_idx)
            _idx = (await chk_el.get_attribute("name") or "").split("[")[-1].split("]")[0]
            if _idx.isdigit():
                nama_hasil = (await page.locator(f"#rekananNama_{_idx}").get_attribute("value") or "").strip()
        except Exception:
            pass
        if not nama_hasil:
            try:
                row = page.locator("table tbody tr").nth(chk_idx)
                nama_hasil = (await row.locator("td").nth(1).text_content() or "").strip()
            except Exception:
                pass

        # Centang checkbox — click() agar trigger event JS
        chk_target = page.locator("input.chk").nth(chk_idx)
        try:
            if await chk_target.is_checked():
                await chk_target.click()
                await page.wait_for_timeout(200)
            await chk_target.click()
        except Exception:
            await chk_target.evaluate("el => el.click()")
        await page.wait_for_timeout(500)

        # Klik tombol Simpan (class btn-simpan di SPSE)
        simpan_clicked = False
        try:
            simpan_btn = page.locator("button.btn-simpan")
            if await simpan_btn.count() > 0:
                await simpan_btn.first.click()
                simpan_clicked = True
        except Exception:
            pass

        if not simpan_clicked:
            try:
                simpan_btn = page.locator("button:has-text('Simpan')")
                if await simpan_btn.count() > 0:
                    await simpan_btn.first.click()
                    simpan_clicked = True
            except Exception:
                pass

        if not simpan_clicked:
            await page.locator("form").first.evaluate("f => f.submit()")

        # Tunggu respons SPSE — redirect atau alert muncul
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            await page.wait_for_timeout(3000)

        # Debug: screenshot + state checkbox + URL
        _dbg_dir = Path(__file__).parent / "_debug_pilih_penyedia"
        _dbg_dir.mkdir(exist_ok=True)
        try:
            await page.screenshot(path=str(_dbg_dir / f"{kode_paket}_after.png"), full_page=True)
            _chk_state = await page.locator("input.chk").first.is_checked() if await page.locator("input.chk").count() > 0 else "no_chk"
            (_dbg_dir / f"{kode_paket}_state.txt").write_text(
                f"url={page.url}\nchk_checked={_chk_state}\nfound_mode={search_mode}\n",
                encoding="utf-8"
            )
        except Exception as _de:
            pass

        # Cek sukses: URL redirect ATAU alert sukses (SPSE kadang tidak redirect)
        if "pilihpenyedia" not in page.url:
            return {"ok": True, "nama": nama_hasil, "mode": search_mode}

        # Cek alert — bisa sukses atau error
        alert_txt = ""
        try:
            alert_loc = page.locator(".alert")
            if await alert_loc.count() > 0:
                alert_txt = (await alert_loc.first.text_content() or "").strip()
        except Exception:
            pass

        # SPSE alert sukses: "Berhasil simpan draft Penyedia"
        if "berhasil" in alert_txt.lower():
            return {"ok": True, "nama": nama_hasil, "mode": search_mode, "pesan": alert_txt}

        return {"ok": False, "pesan": f"Submit gagal. {alert_txt}"}

    except Exception as e:
        return {"ok": False, "pesan": f"Error: {e}"}
    finally:
        await page.close()


def pilih_penyedia_via_playwright(kode_paket: str, npwp: str, base_url: str, nama_penyedia: str = "") -> dict:
    """
    Pilih penyedia PL ke SPSE via Playwright browser CDP.
    Lebih reliable dari requests karena data penyedia di-render via JS.
    """
    return _run(_pilih_penyedia_async(kode_paket, npwp, base_url, nama_penyedia=nama_penyedia), timeout=180)


def pilih_penyedia_via_api(kode_paket: str, npwp: str, base_url: str, nama_penyedia: str = "", cookie_str: str = "") -> dict:
    """
    Pilih penyedia PL ke SPSE via direct HTTP API (tanpa Playwright).

    Flow:
      1. GET /pilihpenyedia/{kode} — ambil CSRF
      2. GET /pilihpenyedia/{kode}?search=true&nama={kata_kunci}&npwp= — cari rekanan
      3. POST /action/nonlelang.pengadaanlctr/simpanpilihpenyedia?lelangId={kode} — submit

    Strategi pencarian:
      - Prioritas 1: search by NPWP (format 15-digit)
      - Prioritas 2: search by nama (kata signifikan pertama)
      - Match: rkn_npwp_16 == npwp16 (16-digit) ATAU nama exact, atau satu-satunya hasil

    Return: {"ok": bool, "nama": str, "mode": str, "pesan": str}
    """
    import re as _re
    import requests as _req
    from bs4 import BeautifulSoup as _BS

    import urllib.parse as _up

    _base = (base_url or "").rstrip("/")
    cookie = cookie_str or get_spse_cookies()
    if not cookie:
        return {"ok": False, "pesan": "Cookie SPSE kosong"}

    url_form = f"{_base}/pilihpenyedia/{kode_paket}"
    url_edit = f"{_base}/nontender/{kode_paket}/edit"
    sess = _req.Session()
    sess.headers.update({
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0",
        "Referer": url_edit,
    })

    # Helper: parse semua rekanan dari soup
    def _parse_rekanan(soup) -> dict:
        result = {}
        for inp in soup.find_all("input"):
            name = inp.get("name", "")
            val = inp.get("value", "") or ""
            m = _re.match(r"rekananList\[(\d+)\]\.(\w+)", name)
            if m:
                idx, field = int(m.group(1)), m.group(2)
                result.setdefault(idx, {})[field] = val
        return result

    def _get_csrf(soup) -> str:
        inp = soup.find("input", {"name": "authenticityToken"})
        return inp["value"] if inp else ""

    # Siapkan NPWP dalam 2 format
    npwp_fmt = _format_npwp_15(npwp)
    npwp_digits = "".join(c for c in npwp if c.isdigit())
    # NPWP 16-digit: pad kiri jika kurang, ambil 16 digit TERAKHIR jika lebih
    # (NPWP baru Indonesia selalu 16 digit, digit ke-1 adalah prefix tambahan)
    npwp16 = npwp_digits.zfill(16) if len(npwp_digits) <= 16 else npwp_digits[-16:]

    rekanan_data = {}
    target_idx = None
    search_mode = ""
    csrf = ""

    # Step 0: Cek halaman edit — apakah penyedia sudah terpilih (NPWP16 match)
    r_edit = sess.get(url_edit, timeout=45)
    if r_edit.status_code == 200:
        soup_edit = _BS(r_edit.text, "html.parser")
        # Tabel rekanan terpilih berisi NPWP16 sebagai teks di kolom NPWP
        edit_txt = soup_edit.get_text(separator=" ")
        if npwp16 in edit_txt or npwp16.lstrip("0") in edit_txt:
            # NPWP16 sudah ada di tabel rekanan terpilih
            # Cari nama penyedia dari teks tabel
            nama_hasil = nama_penyedia
            for tbl in soup_edit.find_all("table"):
                ttxt = tbl.get_text(separator=" ", strip=True)
                if npwp16 in ttxt or npwp16.lstrip("0") in ttxt:
                    # Ambil nama dari baris tabel: biasanya "1 {nama} {npwp16} ..."
                    rows = tbl.find_all("tr")
                    for row in rows:
                        cells = [td.get_text(strip=True) for td in row.find_all("td")]
                        if any(npwp16 in c or npwp16.lstrip("0") in c for c in cells):
                            # Nama biasanya cell ke-1 (setelah No)
                            if len(cells) >= 2:
                                nama_hasil = cells[1]
                    break
            return {"ok": True, "nama": nama_hasil, "mode": "sudah_terpilih", "pesan": "Penyedia sudah terpilih sebelumnya"}

    # Step 1+2a gabung: Search by NPWP16 (format 16-digit leading-zero) + ambil CSRF
    # SPSE hanya match NPWP jika format 16-digit dengan leading zero persis
    sess.headers.update({"Referer": url_form})
    url_search_npwp = f"{url_form}?search=true&nama=&npwp={_up.quote(npwp16)}&jenisIjin="
    r1 = sess.get(url_search_npwp, timeout=45)
    if r1.status_code == 200:
        soup1 = _BS(r1.text, "html.parser")
        csrf = _get_csrf(soup1)
        rekanan_data = _parse_rekanan(soup1)
        for idx, d in rekanan_data.items():
            np16 = d.get("rkn_npwp_16", "").strip()
            if npwp16 and (np16 == npwp16 or np16.lstrip("0") == npwp16.lstrip("0")):
                target_idx = idx
                search_mode = "npwp_exact"
                break
        if target_idx is None and len(rekanan_data) == 1:
            target_idx = list(rekanan_data.keys())[0]
            search_mode = "npwp_single"

    # Fallback: GET form saja untuk CSRF jika search NPWP tidak menghasilkan rekanan
    if not csrf:
        r0 = sess.get(url_form, timeout=45)
        if r0.status_code == 200:
            csrf = _get_csrf(_BS(r0.text, "html.parser"))
    if not csrf:
        return {"ok": False, "pesan": "CSRF tidak ditemukan di form pilih penyedia"}

    if target_idx is None:
        return {"ok": False, "pesan": f"Penyedia tidak ditemukan di DB rekanan SPSE (NPWP: {npwp_fmt}). Pastikan penyedia sudah terdaftar di SPSE sebelum dipilih."}

    d = rekanan_data[target_idx]
    nama_hasil = d.get("rkn_nama", nama_penyedia)

    # Step 3: Submit
    url_submit = f"{_base}/action/nonlelang.pengadaanlctr/simpanpilihpenyedia?lelangId={kode_paket}"
    payload = {
        "authenticityToken": csrf,
        "rekananList[0].rkn_id": d.get("rkn_id", ""),
        "rekananList[0].rkn_nama": d.get("rkn_nama", ""),
        "rekananList[0].rkn_npwp": d.get("rkn_npwp", ""),
        "rekananList[0].rkn_npwp_16": d.get("rkn_npwp_16", ""),
        "rekananList[0].rkn_email": d.get("rkn_email", ""),
        "rekananList[0].rkn_telepon": d.get("rkn_telepon", ""),
        "rekananList[0].rkn_alamat": d.get("rkn_alamat", ""),
    }
    sess.headers.update({"Content-Type": "application/x-www-form-urlencoded"})
    rp = sess.post(url_submit, data=payload, allow_redirects=False, timeout=45)
    ok = rp.status_code in (200, 302)
    return {
        "ok": ok,
        "nama": nama_hasil,
        "mode": search_mode,
        "status": rp.status_code,
        "pesan": rp.headers.get("Location", "") if ok else f"HTTP {rp.status_code}: {rp.text[:200]}",
    }


def halaman_aktif() -> Page | None:
    global _page
    if _page and not _page.is_closed():
        return _page
    if _context and _context.pages:
        _page = _context.pages[-1]
        return _page
    return None


_cdp_tabs_cache: list[dict] = []
_cdp_tabs_cache_ts: float = 0.0
_CDP_CACHE_TTL = 2.0  # detik — cache tab list 2 detik; lebih pendek supaya status sidebar cepat merah saat CDP tutup


def _cdp_tabs(force: bool = False) -> list[dict]:
    """Ambil daftar tab via CDP HTTP API dengan cache 5 detik.
    force=True untuk paksa refresh (misal setelah user klik Refresh).
    """
    import requests as _req
    import time as _time
    global _cdp_tabs_cache, _cdp_tabs_cache_ts
    now = _time.time()
    if not force and _cdp_tabs_cache and (now - _cdp_tabs_cache_ts) < _CDP_CACHE_TTL:
        return _cdp_tabs_cache
    try:
        tabs = _req.get(f"http://localhost:{CDP_PORT}/json", timeout=2).json()
        _cdp_tabs_cache = [t for t in tabs if t.get("type") == "page"]
        _cdp_tabs_cache_ts = now
        return _cdp_tabs_cache
    except Exception:
        _cdp_tabs_cache = []
        _cdp_tabs_cache_ts = 0.0
        return []


def daftar_tab() -> list[dict]:
    """Return semua tab yang terbuka: [{'index': int, 'title': str, 'url': str}]"""
    tabs = _cdp_tabs()
    return [
        {"index": i, "title": t.get("title", ""), "url": t.get("url", "")}
        for i, t in enumerate(tabs)
    ]


def pilih_tab(index: int):
    """Set halaman aktif ke tab berdasarkan index (berdasarkan CDP tab list)."""
    global _page
    if not _context:
        return
    tabs = _cdp_tabs()
    if 0 <= index < len(tabs):
        target_url = tabs[index].get("url", "")
        if target_url:
            matched = next((p for p in _context.pages if p.url == target_url), None)
            if matched:
                _page = matched
                return
    # fallback ke index Playwright
    if 0 <= index < len(_context.pages):
        _page = _context.pages[index]


def get_url() -> str:
    """Ambil URL tab aktif via CDP HTTP API — instant."""
    tabs = _cdp_tabs()
    if not tabs:
        return ""
    # Cari tab yang sedang aktif (focused) atau pakai tab pertama
    active = next((t for t in tabs if t.get("url", "").startswith("http")), None)
    return active.get("url", "") if active else ""


# ============================================================
# Navigation & helpers
# ============================================================

def navigasi(url: str):
    page = halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")
    _run(page.goto(url, wait_until="domcontentloaded", timeout=30000))


def klik(selector: str):
    page = halaman_aktif()
    _run(page.click(selector, timeout=10000))


def screenshot(path: str | None = None) -> bytes:
    page = halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")
    return _run(page.screenshot(path=path, full_page=True))


def get_html() -> str:
    page = halaman_aktif()
    if not page:
        return ""
    return _run(page.content())


def fetch_json_via_cdp(url: str, params: dict | None = None) -> dict:
    """Fetch JSON endpoint via browser CDP — session cookie otomatis ikut (sudah login)."""
    import urllib.parse
    page = halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    result = _run(page.evaluate(f"""async () => {{
        const r = await fetch({repr(url)}, {{
            headers: {{
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            }},
            credentials: "include",
        }});
        if (!r.ok) throw new Error("HTTP " + r.status);
        return await r.json();
    }}"""))
    return result


# ============================================================
# Scan & Download
# ============================================================

async def _scan_links_async(page: Page) -> list[dict]:
    return await page.evaluate("""() => {
        const ext = ['.pdf', '.doc', '.docx', '.zip', '.xls', '.xlsx', '.rar'];
        return Array.from(document.querySelectorAll('a[href]'))
            .filter(a => {
                const h = a.href.toLowerCase();
                return ext.some(e => h.includes(e))
                    || h.includes('/dl/')
                    || h.includes('/download')
                    || h.includes('/unduh');
            })
            .map(a => ({ text: a.innerText.trim() || a.href.split('/').pop(), href: a.href }));
    }""")


def scan_link_file() -> list[dict]:
    page = halaman_aktif()
    if not page:
        return []
    return _run(_scan_links_async(page))


async def _download_file_async(page: Page, url: str, nama_file: str | None) -> str:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    async with page.expect_download() as dl_info:
        await page.goto(url)
    download = await dl_info.value
    save_path = os.path.join(DOWNLOAD_DIR, nama_file or download.suggested_filename)
    await download.save_as(save_path)
    return save_path


def download_file(url: str, nama_file: str | None = None) -> str:
    page = halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")
    return _run(_download_file_async(page, url, nama_file), timeout=120)


def download_semua_dari_halaman(progress_callback=None) -> list[dict]:
    links = scan_link_file()
    hasil = []
    for i, link in enumerate(links):
        if progress_callback:
            progress_callback(i / max(len(links), 1), f"Downloading: {link['text'] or link['href']}")
        try:
            path = download_file(link["href"])
            hasil.append({"nama": link["text"] or os.path.basename(path), "path": path, "status": "OK"})
        except Exception as e:
            hasil.append({"nama": link["text"] or link["href"], "path": "", "status": f"Gagal: {e}"})
    if progress_callback:
        progress_callback(1.0, "Selesai")
    return hasil


async def _scan_file_inputs_async(page: Page) -> list[dict]:
    return await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('input[type=file]'))
            .map(el => ({
                name: el.name || '',
                id: el.id || '',
                accept: el.accept || '',
                multiple: el.multiple
            }));
    }""")


def scan_file_inputs() -> list[dict]:
    page = halaman_aktif()
    if not page:
        return []
    return _run(_scan_file_inputs_async(page))


async def _set_input_files_async(page: Page, selector: str, paths: list[str]):
    await page.set_input_files(selector, paths)


def set_input_files(selector: str, paths: list[str]):
    page = halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")
    _run(_set_input_files_async(page, selector, paths))


# ============================================================
# LDK Auto-fill
# ============================================================

def navigasi_ldk(ldk_url: str):
    """Navigate ke halaman LDK dan tunggu sampai fully loaded."""
    page = halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")
    _run(page.goto(ldk_url, wait_until="networkidle", timeout=30000))


def get_paket_id() -> str | None:
    """
    Extract ID paket dari URL aktif di browser.
    Pattern: /dokumen/[ID]/ atau /lelang/[ID]/
    """
    import re
    url = get_url()
    if not url:
        return None
    match = re.search(r'/(?:dokumen|lelang)/(\d+)', url)
    return match.group(1) if match else None


def get_nama_paket(paket_id: str | None = None) -> str | None:
    """
    Ambil nama paket dari SPSE via pure requests ke /lelang/[ID]/view.
    Scrape <h3> pertama di dalam .panel-body (judul paket).
    Jika paket_id tidak diberikan, otomatis ambil dari URL aktif.
    """
    import requests
    from bs4 import BeautifulSoup

    pid = paket_id or get_paket_id()
    if not pid:
        return None
    cookie_str = get_spse_cookies()
    if not cookie_str:
        return None
    try:
        url = f"{SPSE_BASE_URL}lelang/{pid}/view"
        resp = requests.get(
            url,
            headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
            timeout=10,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # Nama paket ada di <title>: "LPSE ... - Informasi Tender Nama Paket"
        if soup.title:
            import re
            title_text = soup.title.string or ""
            # Strip prefix hingga "- Informasi Tender " atau "- Edit Tender "
            match = re.search(r'-\s*(?:Informasi|Edit)\s+Tender\s+(.+)', title_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
            # Fallback: ambil bagian setelah " - " terakhir
            parts = title_text.split(" - ")
            if len(parts) > 1:
                kandidat = parts[-1].strip()
                if len(kandidat) > 10:
                    return kandidat
        return None
    except Exception:
        return None


_FETCH_JS = """
async ([url, method, payload, contentType, formEncoded]) => {
    const body = formEncoded
        ? new URLSearchParams(payload).toString()
        : JSON.stringify(payload);
    const resp = await fetch(url, {
        method:      method,
        credentials: 'include',
        headers: {
            'Content-Type':     contentType,
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: body,
    });
    return { status: resp.status, ok: resp.ok, body: await resp.text() };
}
"""


def submit_via_fetch(endpoint_url: str, payload: dict, method: str = "POST") -> dict:
    """
    Submit ke API dari dalam browser context — cookie/session otomatis ikut.
    Coba JSON dulu; jika response 400/415/422 fallback ke form-encoded.
    """
    page = halaman_aktif()
    if not page:
        raise RuntimeError("Browser belum terbuka.")

    async def _fetch(content_type: str, form_encoded: bool) -> dict:
        return await page.evaluate(
            _FETCH_JS,
            [endpoint_url, method, payload, content_type, form_encoded],
        )

    result = _run(_fetch("application/json", False))
    if not result["ok"] and result["status"] in (400, 415, 422):
        result = _run(_fetch("application/x-www-form-urlencoded", True))
    return result


# ============================================================
# Cookie extraction — untuk direct HTTP requests tanpa browser
# ============================================================

_cookie_cache: str = ""
_cookie_cache_ts: float = 0.0
_COOKIE_CACHE_TTL = 300.0  # cookie valid 5 menit (cukup utk bulk paralel)
_cookie_lock = threading.Lock()


def get_spse_cookies() -> str:
    """
    Ambil cookies SPSE via Playwright context yang sudah ada.
    Di-cache 5 menit + thread-safe lock agar concurrent caller (bulk paralel)
    tidak race init Playwright.
    """
    import time as _time
    global _cookie_cache, _cookie_cache_ts

    # Fast-path: cache hit tanpa lock
    now = _time.time()
    if _cookie_cache and (now - _cookie_cache_ts) < _COOKIE_CACHE_TTL:
        return _cookie_cache

    # Slow-path: pegang lock, double-check (worker lain mungkin sudah refresh)
    with _cookie_lock:
        now = _time.time()
        if _cookie_cache and (now - _cookie_cache_ts) < _COOKIE_CACHE_TTL:
            return _cookie_cache

        if _context is None:
            try:
                buka_browser(navigate=False)
            except Exception:
                return ""

        if _context is None:
            return ""

        try:
            cookies = _run(_context.cookies(), timeout=10)
            spse = [c for c in cookies if "inaproc" in c.get("domain", "")]
            result = "; ".join(f'{c["name"]}={c["value"]}' for c in spse)
            if result:
                _cookie_cache = result
                _cookie_cache_ts = now
            return result
        except Exception:
            return _cookie_cache  # kembalikan cache lama jika gagal
