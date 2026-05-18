"""SPSE Browser Automation — Playwright di thread terpisah (Streamlit-safe)."""

import os
import asyncio
import threading
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext

from config import SPSE_BASE_URL, BROWSER_SESSION_DIR, DOWNLOAD_DIR

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
# Session management
# ============================================================

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\MSI\AppData\Local"), "Google", "Chrome", "User Data")
CDP_PORT = 9222


async def _connect_cdp_async(url: str = "", navigate: bool = True):
    """Connect ke Chrome yang sudah jalan via CDP.
    Jika navigate=False, hanya connect tanpa membuka tab baru (cepat, untuk auto-reconnect).
    """
    global _pw, _context, _page
    if _pw is None:
        _pw = await async_playwright().start()
    browser = await _pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
    # Pakai context pertama (window Chrome yang sudah terbuka)
    if browser.contexts:
        _context = browser.contexts[0]
    else:
        _context = await browser.new_context()
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
            "Chrome SPSE belum terbuka. "
            "Jalankan dulu file 'Buka Chrome SPSE.bat' di folder Asisten_Pokja."
        )
    return _run(_connect_cdp_async(url, navigate=navigate))


def launch_chrome_dengan_cdp():
    """Launch Chrome baru (instance terpisah) dengan remote-debugging-port.
    Tidak mematikan Chrome yang sudah jalan (agar Streamlit tidak terganggu).
    """
    import subprocess
    # Pakai BROWSER_SESSION_DIR sebagai profile terpisah khusus SPSE
    subprocess.Popen([
        CHROME_EXE,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={BROWSER_SESSION_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
    ])


async def _tutup_async():
    global _pw, _context, _page
    if _context:
        await _context.close()
    if _pw:
        await _pw.stop()
    _pw = _context = _page = None


def tutup_browser():
    if _context:
        _run(_tutup_async())


def diskonek():
    """Reset koneksi Playwright tanpa menutup browser. Berguna jika CDP sudah ditutup manual."""
    global _pw, _context, _page, _cdp_tabs_cache, _cdp_tabs_cache_ts
    _pw = _context = _page = None
    _cdp_tabs_cache = []
    _cdp_tabs_cache_ts = 0.0


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
_CDP_CACHE_TTL = 5.0  # detik — cache tab list selama 5 detik antar rerun


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
        return _cdp_tabs_cache  # kembalikan cache lama jika gagal


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
