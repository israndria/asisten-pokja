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
CHROME_PROFILE = r"C:\Users\MSI\AppData\Local\Google\Chrome\User Data"
CDP_PORT = 9222


async def _connect_cdp_async(url: str):
    """Connect ke Chrome yang sudah jalan via CDP, buka tab baru."""
    global _pw, _context, _page
    if _pw is None:
        _pw = await async_playwright().start()
    browser = await _pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
    # Pakai context pertama (window Chrome yang sudah terbuka)
    if browser.contexts:
        _context = browser.contexts[0]
    else:
        _context = await browser.new_context()
    _page = await _context.new_page()
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


def buka_browser(url: str = SPSE_BASE_URL):
    """Connect ke Chrome SPSE via CDP dan buka tab baru.
    Chrome harus sudah dibuka via 'Buka Chrome SPSE.bat' terlebih dahulu.
    """
    if not _cek_cdp_aktif():
        raise RuntimeError(
            "Chrome SPSE belum terbuka. "
            "Jalankan dulu file 'Buka Chrome SPSE.bat' di folder Asisten_Pokja."
        )
    return _run(_connect_cdp_async(url))


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


def halaman_aktif() -> Page | None:
    global _page
    if _page and not _page.is_closed():
        return _page
    if _context and _context.pages:
        _page = _context.pages[-1]
        return _page
    return None


def daftar_tab() -> list[dict]:
    """Return semua tab yang terbuka: [{'index': int, 'title': str, 'url': str}]"""
    if not _context:
        return []
    result = []
    for i, p in enumerate(_context.pages):
        try:
            url = _run(p.evaluate("() => window.location.href"))
            title = _run(p.evaluate("() => document.title"))
        except Exception:
            url, title = "", ""
        result.append({"index": i, "title": title, "url": url})
    return result


def pilih_tab(index: int):
    """Set halaman aktif ke tab berdasarkan index."""
    global _page
    if _context and 0 <= index < len(_context.pages):
        _page = _context.pages[index]


def get_url() -> str:
    page = halaman_aktif()
    if page:
        return _run(page.evaluate("() => window.location.href"))
    return ""


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


def isi(selector: str, nilai: str):
    page = halaman_aktif()
    _run(page.fill(selector, nilai))


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


# ============================================================
# Form inspection
# ============================================================

async def _scan_fields_async(page: Page) -> list[dict]:
    return await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('input, textarea, select'))
            .filter(el => el.type !== 'hidden' && el.type !== 'submit' && el.type !== 'button')
            .map(el => ({
                tag: el.tagName,
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                value: el.value || ''
            }));
    }""")


def scan_form_fields() -> list[dict]:
    page = halaman_aktif()
    if not page:
        return []
    return _run(_scan_fields_async(page))


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
