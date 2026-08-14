"""SPSE Browser Automation — Playwright di thread terpisah (Streamlit-safe)."""
from __future__ import annotations

import os
import asyncio
import json
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from playwright.async_api import Page, BrowserContext

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
# Event loop + CDP state — semua di builtins agar survive Streamlit hot-reload
# ============================================================

import builtins as _builtins_sb
if not hasattr(_builtins_sb, "_spse_cdp_state"):
    _builtins_sb._spse_cdp_state = {"pw": None, "context": None, "page": None}
if not hasattr(_builtins_sb, "_spse_loop_state"):
    _builtins_sb._spse_loop_state = {"loop": None, "thread": None}
if not hasattr(_builtins_sb, "_spse_restore_state"):
    _builtins_sb._spse_restore_state = {"signature": None}

def _get_pw():      return _builtins_sb._spse_cdp_state["pw"]
def _set_pw(v):     _builtins_sb._spse_cdp_state["pw"] = v
def _get_ctx():     return _builtins_sb._spse_cdp_state["context"]
def _set_ctx(v):    _builtins_sb._spse_cdp_state["context"] = v
def _get_page():    return _builtins_sb._spse_cdp_state["page"]
def _set_page(v):   _builtins_sb._spse_cdp_state["page"] = v

def _get_loop():    return _builtins_sb._spse_loop_state["loop"]
def _set_loop(v):   _builtins_sb._spse_loop_state["loop"] = v
def _get_loop_thread(): return _builtins_sb._spse_loop_state["thread"]
def _set_loop_thread(v): _builtins_sb._spse_loop_state["thread"] = v

# Module-level aliases (stale setelah hot-reload, tapi dibutuhkan agar tidak NameError di kode lama)
_loop = None
_loop_thread = None


def _start_loop():
    lp = asyncio.ProactorEventLoop()  # Windows: wajib ProactorEventLoop untuk subprocess
    asyncio.set_event_loop(lp)
    _set_loop(lp)
    lp.run_forever()


def _ensure_loop():
    lp = _get_loop()
    if lp is None or not lp.is_running():
        # Loop mati → pw terikat loop lama, harus reset semua state CDP
        _set_pw(None)
        _set_ctx(None)
        _set_page(None)
        t = threading.Thread(target=_start_loop, daemon=True)
        _set_loop_thread(t)
        t.start()
        import time; time.sleep(0.3)


def _run(coro, timeout=60):
    """Jalankan coroutine di background loop, tunggu hasilnya."""
    _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result(timeout=timeout)




# ============================================================
# Auto-Refresh Daemon
# Simpan state di dict global proses (bukan module-level) agar survive hot-reload Streamlit.
# ============================================================
import builtins as _builtins
if not hasattr(_builtins, "_spse_refresh_state"):
    _builtins._spse_refresh_state = {
        "event": threading.Event(), "thread": None,
        "last_refresh": None, "last_error": None, "stopped_reason": None,
    }

def _refresh_worker(interval_menit: int):
    import time
    state = _builtins._spse_refresh_state
    while not state["event"].is_set():
        for _ in range(interval_menit * 60 // 5):
            if state["event"].wait(timeout=5):
                return
        if state["event"].is_set():
            return
        if not _cek_cdp_aktif():
            state["stopped_reason"] = "CDP tidak aktif; menunggu Brave tersambung kembali"
            if state["event"].wait(timeout=15):
                return
            continue
        for _attempt in range(2):
            try:
                if refresh_browser() or keepalive_browser():
                    state["last_refresh"] = time.time()
                    state["last_error"] = None
                    state["stopped_reason"] = None
                    break
                state["last_error"] = "Tidak ada tab SPSE pada rute aman"
            except Exception as exc:
                state["last_error"] = str(exc)[:200]
                if _attempt == 0:
                    time.sleep(1)

def mulai_auto_refresh(interval_menit: int = 5):
    state = _builtins._spse_refresh_state
    t = state.get("thread")
    if t and t.is_alive():
        return
    state["event"].clear()
    t = threading.Thread(target=_refresh_worker, args=(interval_menit,), daemon=True)
    t.start()
    state["thread"] = t

def stop_auto_refresh():
    state = _builtins._spse_refresh_state
    state["event"].set()
    t = state.get("thread")
    if t and t.is_alive():
        t.join(timeout=1.0)

# ============================================================
# Session management
# ============================================================

CHROME_EXE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
CHROME_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\MSI\AppData\Local"), "BraveSoftware", "Brave-Browser", "User Data")
CHROME_PROFILE_DIR = "Profile 1"  # direktori profil israndria di dalam CHROME_PROFILE
CDP_PORT = 9222

# Auto-refresh hanya halaman navigasi aman. Jangan reload halaman form/detail
# karena dapat menghilangkan input manual yang sedang dikerjakan user.
_AUTO_REFRESH_PATHS = {
    "/",                # home publik/authenticated SPSE
    "/home",
    "/paket",           # halaman paket Pokja yang dipakai Brave saat ini
    "/paketnontender",    # PP/PPK
    "/paketlelang",       # Pokja (jika UI memakai route ini)
    "/paketpanitia",      # fallback route tender lama
}


def _boleh_auto_refresh(url: str) -> bool:
    from urllib.parse import urlsplit
    base = urlsplit(SPSE_BASE_URL)
    current = urlsplit(url or "")
    allowed_paths = {
        f"{base.path.rstrip('/')}{path}".rstrip("/")
        for path in _AUTO_REFRESH_PATHS
    }
    return (
        current.scheme == base.scheme
        and current.netloc == base.netloc
        and current.path.rstrip("/") in allowed_paths
    )


_SPSE_ACCESS_ERROR_MARKERS = (
    "akses ditolak",
    "belum login",
    "session telah habis",
    "sesi telah habis",
    "terjadi kesalahan",
)


def _is_spse_login_page_text(text: str) -> bool:
    """Deteksi halaman publik/login yang bukan sesi authenticated."""
    import re

    normalized = " ".join((text or "").casefold().split())
    return bool(
        re.search(r"\blogin\b", normalized)
        or "nama pengguna" in normalized
        or "kata sandi" in normalized
    )


def _is_spse_access_error_text(text: str) -> bool:
    """Deteksi halaman SPSE stale/error dari title atau body yang terlihat."""
    normalized = " ".join((text or "").casefold().split())
    return any(marker in normalized for marker in _SPSE_ACCESS_ERROR_MARKERS)


def _url_spse_score(url: str, title: str = "") -> int:
    """Beri skor tab SPSE agar tab loginpass/root tidak mengalahkan sesi aktif.

    CDP ``/json`` tidak memberi penanda tab foreground. Urutan list juga tidak
    sama dengan tab yang sedang dilihat user, sehingga pemilihan berdasarkan
    ``tabs[0]`` bisa salah dan UI terlihat logout padahal sesi masih aktif.
    """
    from urllib.parse import urlsplit

    base = urlsplit(SPSE_BASE_URL)
    current = urlsplit(url or "")
    if current.scheme not in {"http", "https"} or current.netloc != base.netloc:
        return -1
    if _is_spse_access_error_text(title):
        return -100
    base_path = base.path.rstrip("/")
    path = current.path.rstrip("/")
    if path == base_path or any(path.endswith(suffix) for suffix in ("/login", "/loginpass", "/logout")):
        return 1  # tetap dipakai jika memang hanya halaman login yang ada

    score = 50
    if path.endswith("/home"):
        score += 20
    if any(part in path for part in ("/paket", "/nontender", "/lelang", "/dokumen", "/jadwal")):
        score += 20
    title_lower = (title or "").lower()
    if any(marker in title_lower for marker in ("pejabat pengadaan", "pokja", "ppk")):
        score += 10
    return score


def _pilih_tab_spse(tabs: list[dict]) -> dict | None:
    """Pilih tab SPSE paling mungkin sudah login, tanpa bergantung urutan CDP."""
    candidates = [
        tab for tab in tabs
        if _url_spse_score(tab.get("url", ""), tab.get("title", "")) >= 0
    ]
    if not candidates:
        return None
    return max(
        enumerate(candidates),
        key=lambda pair: (_url_spse_score(pair[1].get("url", ""), pair[1].get("title", "")), -pair[0]),
    )[1]


async def _deskripsikan_page_spse(page, *, inspect_body: bool = False) -> dict:
    """Ambil metadata page tanpa navigasi untuk pemilihan tab yang aman."""
    url = page.url
    title = ""
    try:
        title = (await page.title()).strip()
    except Exception:
        pass

    is_error = _is_spse_access_error_text(title)
    score = _url_spse_score(url, title)
    if inspect_body and score >= 0:
        try:
            body = await page.locator("body").inner_text(timeout=1500)
            if _is_spse_access_error_text(body) or _is_spse_login_page_text(body):
                is_error = True
                score = -100
        except Exception:
            # Body tidak terbaca bukan bukti logout; pertahankan skor URL/title.
            pass
    return {
        "page": page,
        "url": url,
        "title": title,
        "score": score,
        "error": is_error,
    }


async def _deskripsikan_page_pemilihan(page) -> dict:
    """Metadata ringan; inspeksi body hanya untuk URL login/root."""
    info = await _deskripsikan_page_spse(page, inspect_body=False)
    if 0 <= info["score"] <= 1:
        info = await _deskripsikan_page_spse(page, inspect_body=True)
    return info


async def _find_page_for_tab_async(tab: dict):
    """Cocokkan tab CDP ke Playwright memakai URL + title, bukan URL saja."""
    context = _get_ctx()
    if context is None:
        return None
    target_url = tab.get("url", "")
    pages = [page for page in context.pages if not page.is_closed()]
    same_url = [page for page in pages if page.url == target_url]
    if not same_url:
        return None

    target_title = (tab.get("title", "") or "").strip()
    if target_title:
        for page in same_url:
            try:
                if (await page.title()).strip() == target_title:
                    return page
            except Exception:
                continue

    descriptions = []
    for page in same_url:
        try:
            descriptions.append(await _deskripsikan_page_spse(page, inspect_body=True))
        except Exception:
            continue
    if not descriptions:
        return same_url[0]
    return max(descriptions, key=lambda item: item["score"])["page"]


async def _fokuskan_tab_spse_async():
    """Bawa tab SPSE terbaik ke foreground untuk flow auto-login saja."""
    context = _get_ctx()
    if context is None:
        return None

    from urllib.parse import urlsplit as _urlsplit
    base_netloc = _urlsplit(SPSE_BASE_URL).netloc
    candidates = []
    for page in context.pages:
        if page.is_closed():
            continue
        try:
            info = await _deskripsikan_page_pemilihan(page)
        except Exception:
            continue
        if _urlsplit(info["url"]).netloc == base_netloc:
            candidates.append(info)
    if not candidates:
        return None

    best = max(candidates, key=lambda item: item["score"])
    page = best["page"]
    _set_page(page)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return page


def _cdp_listener_pids() -> set[int]:
    """Ambil PID Brave yang sedang listen pada port CDP aktif."""
    import subprocess as _sp

    try:
        result = _sp.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            shell=True,
            timeout=5,
        )
    except Exception:
        return set()

    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 5 and parts[1].endswith(f":{CDP_PORT}") and parts[3] == "LISTENING":
            if parts[-1].isdigit():
                pids.add(int(parts[-1]))
    return pids


def _brave_cdp_window_handles() -> list[int]:
    """Cari HWND window Brave milik PID CDP, termasuk window tersembunyi."""
    if os.name != "nt":
        return []

    import ctypes
    from ctypes import wintypes

    pids = _cdp_listener_pids()
    if not pids:
        return []

    user32 = ctypes.windll.user32
    handles: list[int] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc_type
    def _enum_window(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True

        class_name = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if class_name.value.startswith("Chrome_WidgetWin_"):
            handles.append(int(hwnd))
        return True

    user32.EnumWindows(_enum_window, 0)
    return handles


def _fokuskan_jendela_brave() -> bool:
    """Restore + foreground-kan window Brave yang memiliki port CDP."""
    if os.name != "nt":
        return False

    handles = _brave_cdp_window_handles()
    if not handles:
        return False

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = wintypes.HWND(handles[0])
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    else:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.BringWindowToTop(hwnd)
    user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
    focused = bool(user32.SetForegroundWindow(hwnd))

    # Windows bisa menolak SetForegroundWindow lintas thread. Attach sementara
    # ke foreground thread hanya sebagai fallback setelah user menekan tombol.
    if not focused:
        foreground = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
        if target_thread and foreground_thread and target_thread != foreground_thread:
            current_thread = user32.GetCurrentThreadId()
            user32.AttachThreadInput(current_thread, foreground_thread, True)
            try:
                user32.BringWindowToTop(hwnd)
                focused = bool(user32.SetForegroundWindow(hwnd))
            finally:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
    return focused or int(user32.GetForegroundWindow() or 0) == int(hwnd.value or 0)


def _visible_brave_command(*, with_cdp: bool = False) -> list[str]:
    """Susun command profile sesi tanpa startup flag yang menyembunyikan GUI."""
    command = [
        CHROME_EXE,
        f"--user-data-dir={BROWSER_SESSION_DIR}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        SPSE_BASE_URL,
    ]
    if with_cdp:
        command.insert(1, f"--remote-debugging-port={CDP_PORT}")
    return command


def _buka_jendela_brave_visible() -> bool:
    """Minta profile CDP yang sudah hidup membuat window GUI terlihat."""
    try:
        # Wajib Popen asli. Popen module-level sudah dipatch SW_HIDE untuk
        # proses Playwright sehingga tidak boleh dipakai untuk Brave GUI.
        _OrigPopen(
            _visible_brave_command(),
            stdin=_subprocess.DEVNULL,
            stdout=_subprocess.DEVNULL,
            stderr=_subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception:
        return False

    import time as _time
    for _ in range(20):
        if _fokuskan_jendela_brave():
            return True
        _time.sleep(0.25)
    return False


def pastikan_jendela_brave() -> bool:
    """Pastikan browser CDP punya window GUI yang terlihat dan terfokus."""
    if _fokuskan_jendela_brave():
        return True
    if not _cek_cdp_aktif():
        return False
    return _buka_jendela_brave_visible()


async def _pastikan_tab_spse_async():
    """Fokuskan tab SPSE; jika semua tab tertutup, gunakan/buka satu tab."""
    page = await _fokuskan_tab_spse_async()
    if page is not None:
        return page

    context = _get_ctx()
    if context is None:
        return None
    pages = [p for p in context.pages if not p.is_closed()]
    # Jangan menimpa tab eksternal user. Reuse hanya blank/new-tab; selain itu
    # buka satu tab baru agar tab YouTube/Inaproc tetap aman.
    page = next(
        (p for p in pages if p.url in ("", "about:blank", "chrome://newtab/")),
        None,
    ) or await context.new_page()
    await page.goto(SPSE_BASE_URL, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return page


def pastikan_tab_spse():
    """Pastikan window Brave terlihat dan minimal satu tab SPSE tersedia."""
    if _get_ctx() is None:
        return None
    pastikan_jendela_brave()
    page = _run(_pastikan_tab_spse_async(), timeout=40)
    # Window bisa baru muncul setelah page dibuat; ulangi focus sekali.
    pastikan_jendela_brave()
    return page


def fokuskan_tab_spse():
    """Bawa tab SPSE authenticated terbaik ke foreground tanpa navigasi."""
    if _get_ctx() is None:
        return None
    page = _run(_fokuskan_tab_spse_async(), timeout=15)
    if page is not None:
        pastikan_jendela_brave()
    return page


async def _rapikan_tab_spse_async():
    """Tutup hanya tab SPSE stale/error hasil restore, lalu fokuskan tab terbaik."""
    context = _get_ctx()
    if context is None:
        return None

    from urllib.parse import urlsplit as _urlsplit
    base_netloc = _urlsplit(SPSE_BASE_URL).netloc
    candidates = []
    for page in context.pages:
        if page.is_closed():
            continue
        try:
            info = await _deskripsikan_page_spse(page, inspect_body=True)
        except Exception:
            continue
        if _urlsplit(info["url"]).netloc == base_netloc:
            candidates.append(info)
    if not candidates:
        return None

    best = max(candidates, key=lambda item: item["score"])
    for item in candidates:
        if item is best or not item["error"]:
            continue
        try:
            await item["page"].close()
        except Exception:
            pass

    page = best["page"]
    _set_page(page)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return page


def rapikan_tab_spse():
    """Hapus tab error restore dan fokuskan tab SPSE terbaik tanpa navigasi."""
    if _get_ctx() is None:
        return None
    return _run(_rapikan_tab_spse_async(), timeout=20)


def _spse_tabs_signature(tabs: list[dict]) -> tuple[tuple[str, str], ...]:
    """Fingerprint ringan URL+title tab untuk mencegah cleanup berulang."""
    return tuple(sorted(
        (str(tab.get("url") or ""), str(tab.get("title") or ""))
        for tab in tabs or []
    ))


def ensure_spse_restore_cleaned() -> dict:
    """Bersihkan tab error hasil restore Brave satu kali per snapshot.

    Brave dapat memulihkan tab lama sebelum user menekan tombol login. Fungsi
    ini sengaja tidak menutup tab jika hanya tab error yang tersedia; pipeline
    login tetap membutuhkan tab tersebut sebagai konteks awal. Jika snapshot
    tab berubah, cleanup dicoba ulang (termasuk setelah Brave direstart).
    """
    if not _cek_cdp_aktif():
        return {"ok": False, "skipped": True, "reason": "cdp_inactive"}

    tabs_before = _cdp_tabs(force=True)
    if not tabs_before:
        return {"ok": False, "skipped": True, "reason": "no_tabs"}

    state = _builtins_sb._spse_restore_state
    signature_before = _spse_tabs_signature(tabs_before)
    if state.get("signature") == signature_before:
        return {"ok": True, "skipped": True, "reason": "same_snapshot"}

    try:
        # Reconnect tanpa navigasi agar cleanup juga bekerja setelah Brave
        # direstart sementara proses Streamlit masih hidup.
        buka_browser(navigate=False)
        selected = rapikan_tab_spse()
        tabs_after = _cdp_tabs(force=True)
        state["signature"] = _spse_tabs_signature(tabs_after)
        return {
            "ok": True,
            "skipped": False,
            "url": getattr(selected, "url", "") if selected else "",
        }
    except Exception as exc:
        # Jangan menyimpan signature saat gagal; rerun berikutnya harus retry.
        return {"ok": False, "skipped": False, "reason": str(exc)[:240]}


# File/folder yang di-clone dari profil asli (tanpa cache)
_CLONE_FILES = [
    "Bookmarks", "Bookmarks.bak", "Preferences", "Secure Preferences",
    "Favicons", "History", "Web Data", "Login Data", "Login Data-journal",
    "Shortcuts", "Top Sites", "Visited Links",
]
_CLONE_DIRS = ["Extensions", "Local Extension Settings"]
_CLONE_FLAG = ".profile_cloned"  # flag file di session_dir — ada = sudah pernah clone


def clone_profil_ke_session(force: bool = False) -> tuple[bool, str]:
    """Clone file penting dari profil Brave asli (israndria/Profile 1) ke BROWSER_SESSION_DIR.

    Hanya clone sekali (cek flag). Pakai force=True untuk clone ulang (update bookmark dll).
    Return: (ok, pesan)
    """
    import shutil
    src_profile = os.path.join(CHROME_PROFILE, CHROME_PROFILE_DIR)
    dst_session = BROWSER_SESSION_DIR
    flag_path = os.path.join(dst_session, _CLONE_FLAG)

    if not force and os.path.exists(flag_path):
        return True, "Profil sudah di-clone sebelumnya."

    if not os.path.isdir(src_profile):
        return False, f"Profil sumber tidak ditemukan: {src_profile}"

    # Brave harus tidak sedang pakai profile ini (cek lockfile)
    lockfile = os.path.join(src_profile, "lockfile")
    if os.path.exists(lockfile):
        return False, (
            "Profil Brave asli sedang dipakai (lockfile ada). "
            "Tutup semua jendela Brave normal terlebih dahulu, lalu sinkronkan ulang."
        )

    os.makedirs(dst_session, exist_ok=True)

    # Buat subfolder Default di dalam session_dir (Chromium butuh subfolder profil)
    dst_profile = os.path.join(dst_session, "Default")
    os.makedirs(dst_profile, exist_ok=True)

    copied, skipped = 0, 0
    for fname in _CLONE_FILES:
        src = os.path.join(src_profile, fname)
        dst = os.path.join(dst_profile, fname)
        if os.path.exists(src):
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception:
                skipped += 1

    for dname in _CLONE_DIRS:
        src = os.path.join(src_profile, dname)
        dst = os.path.join(dst_profile, dname)
        if os.path.isdir(src):
            try:
                if os.path.exists(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                    "Cache", "cache", "Code Cache", "GPUCache", "ScriptCache",
                    "*.log", "*.tmp",
                ))
                copied += 1
            except Exception:
                skipped += 1

    # Tulis flag
    try:
        with open(flag_path, "w", encoding="utf-8") as _f:
            import datetime
            _f.write(datetime.datetime.now().isoformat())
    except Exception:
        pass

    label = "diperbarui" if force else "di-clone"
    return True, f"Profil berhasil {label}: {copied} item disalin, {skipped} dilewati."


async def _connect_cdp_async(url: str = "", navigate: bool = True):
    """Connect ke Chrome yang sudah jalan via CDP.
    Jika navigate=False, hanya connect tanpa membuka tab baru (cepat, untuk auto-reconnect).
    """
    from playwright.async_api import async_playwright
    if _get_pw() is None:
        _set_pw(await async_playwright().start())
    import os as _os
    _downloads_dir = _os.path.join(_os.path.expanduser("~"), "Downloads")
    try:
        browser = await _get_pw().chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
    except Exception:
        # _pw stale (context lama dari sesi sebelumnya) — reset dan coba ulang
        try:
            await _get_pw().stop()
        except Exception:
            pass
        _set_pw(await async_playwright().start())
        _set_ctx(None)
        _set_page(None)
        browser = await _get_pw().chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
    # Pakai context pertama (window Chrome yang sudah terbuka)
    if browser.contexts:
        _set_ctx(browser.contexts[0])
    else:
        _set_ctx(await browser.new_context())
    # Set download behavior ke folder Downloads user via CDP session langsung
    # (accept_downloads tidak bisa di-set ke existing context via Playwright API)
    try:
        pages = _get_ctx().pages
        if pages:
            cdp_session = await _get_ctx().new_cdp_session(pages[0])
            await cdp_session.send("Browser.setDownloadBehavior", {
                "behavior": "allowAndName",
                "downloadPath": _downloads_dir,
                "eventsEnabled": True,
            })
            await cdp_session.detach()
    except Exception:
        pass
    # Pakai tab SPSE paling relevan. Urutan ``context.pages`` bukan urutan tab
    # foreground dan bisa menempatkan loginpass/root di posisi pertama.
    if _get_ctx().pages:
        _page_candidates = []
        for page in _get_ctx().pages:
            if page.is_closed():
                continue
            try:
                _page_candidates.append(await _deskripsikan_page_pemilihan(page))
            except Exception:
                continue
        # Jika ada page SPSE, jangan biarkan tab eksternal mengalahkannya.
        from urllib.parse import urlsplit as _urlsplit
        _base_netloc = _urlsplit(SPSE_BASE_URL).netloc
        _spse_candidates = [
            item for item in _page_candidates
            if _urlsplit(item["url"]).netloc == _base_netloc
        ]
        _choice_pool = _spse_candidates or _page_candidates
        _best = max(_choice_pool, key=lambda item: item["score"]) if _choice_pool else None
        _set_page(_best["page"] if _best else _get_ctx().pages[0])
    else:
        _set_page(await _get_ctx().new_page())
    if navigate and url:
        await _get_page().goto(url, wait_until="domcontentloaded", timeout=30000)
    return _get_page()


def _cek_cdp_aktif() -> bool:
    """Cek apakah endpoint DevTools Brave benar-benar sehat.

    Cek TCP saja bisa false-positive: port masih LISTENING walau endpoint
    CDP sudah stale/tidak merespons. Validasi `/json/version` agar UI tidak
    menganggap sesi browser masih aktif hanya karena ada proses di port 9222.
    """
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", CDP_PORT), timeout=1)
        s.close()
    except OSError:
        return False

    try:
        import json as _json
        import urllib.request as _urlreq

        request = _urlreq.Request(f"http://127.0.0.1:{CDP_PORT}/json/version")
        with _urlreq.urlopen(request, timeout=1.5) as response:
            if getattr(response, "status", 200) != 200:
                raise RuntimeError(f"HTTP {getattr(response, 'status', '?')}")
            payload = _json.loads(response.read().decode("utf-8", errors="replace"))
        healthy = bool(payload.get("Browser") or payload.get("webSocketDebuggerUrl"))
        if healthy:
            return True
    except Exception:
        pass

    # Jangan biarkan cache tab/cookie lama membuat Streamlit terlihat login.
    global _cdp_tabs_cache, _cdp_tabs_cache_ts
    _cdp_tabs_cache = []
    _cdp_tabs_cache_ts = 0.0
    return False


def buka_browser(url: str = SPSE_BASE_URL, navigate: bool = True):
    """Connect ke Brave SPSE via CDP.
    navigate=True  : buka tab baru dan navigasi ke url (untuk koneksi manual)
    navigate=False : hanya connect, pakai tab yang sudah ada (untuk auto-reconnect cepat)
    Brave harus sudah dibuka via launcher Brave CDP terlebih dahulu.
    """
    if not _cek_cdp_aktif():
        raise RuntimeError(
            "Brave SPSE belum terbuka. "
            "Buka Brave dengan remote debugging port 9222 terlebih dahulu."
        )
    last_error = None
    # Setelah boot/restart, port CDP dapat sudah listen sementara websocket
    # browser belum siap dipakai Playwright. Satu reconnect bersih mencegah
    # error intermiten yang sebelumnya langsung dilempar ke UI.
    for attempt in range(2):
        if not _cek_cdp_aktif():
            raise RuntimeError(
                "Brave SPSE belum terbuka. "
                "Buka Brave dengan remote debugging port 9222 terlebih dahulu."
            )
        try:
            return _run(_connect_cdp_async(url, navigate=navigate), timeout=45)
        except Exception as exc:
            last_error = exc
            diskonek()
            if attempt == 0:
                time.sleep(0.75)
                continue
            raise RuntimeError(
                "Koneksi Brave/CDP gagal setelah reconnect: "
                f"{type(exc).__name__}: {str(exc)[:180]}"
            ) from exc
    raise RuntimeError(f"Koneksi Brave/CDP gagal: {last_error}")


def tunggu_cdp_ready(timeout_seconds: float = 20.0, interval_seconds: float = 0.5) -> bool:
    """Tunggu endpoint CDP benar-benar sehat setelah Brave baru diluncurkan."""
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while time.monotonic() <= deadline:
        if _cek_cdp_aktif():
            return True
        time.sleep(max(0.05, float(interval_seconds)))
    return False


def tunggu_tab_spse_ready(
    timeout_seconds: float = 15.0,
    interval_seconds: float = 0.25,
):
    """Tunggu tab SPSE hasil cold-start tersedia tanpa inspeksi/cleanup DOM.

    Setelah Brave baru diluncurkan, endpoint CDP dapat sehat beberapa saat
    sebelum tab dengan URL SPSE masuk ke context Playwright. Boundary login
    hanya perlu menunggu tabnya muncul; inspeksi body dan cleanup tab publik
    dilakukan setelah login agar race cold-start tidak menggagalkan pipeline.
    """
    from urllib.parse import urlsplit

    base_netloc = urlsplit(SPSE_BASE_URL).netloc
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while time.monotonic() <= deadline:
        context = _get_ctx()
        if context is not None:
            pages = [page for page in context.pages if not page.is_closed()]
            current = _get_page()
            candidates = ([current] if current in pages else []) + [
                page for page in pages if page is not current
            ]
            for page in candidates:
                try:
                    if urlsplit(page.url).netloc == base_netloc:
                        _set_page(page)
                        return page
                except Exception:
                    continue
        time.sleep(max(0.05, float(interval_seconds)))
    return None


async def _buka_tab_baru_async(url: str):
    """Buka tab baru di Brave CDP (tidak overwrite tab aktif)."""
    if _get_ctx() is None:
        await _connect_cdp_async(navigate=False)
    page = await _get_ctx().new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)  # tunggu JS/Cloudflare hydrate
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return page


def buka_tab_baru(url: str):
    """Buka tab baru di Brave CDP untuk URL eksternal (misal inaproc).
    Tidak overwrite tab SPSE yang sudah aktif.
    """
    if not _cek_cdp_aktif():
        raise RuntimeError("Brave belum terbuka via CDP.")
    return _run(_buka_tab_baru_async(url))


def launch_chrome_dengan_cdp():
    """Launch Brave baru dengan remote-debugging-port + buka SPSE langsung (1 tab).
    Pakai profil clone dari israndria (Profile 1) — bookmark & setting terbawa.
    Clone hanya dilakukan sekali; gunakan clone_profil_ke_session(force=True) untuk update.
    """
    import subprocess
    session_dir = BROWSER_SESSION_DIR
    os.makedirs(session_dir, exist_ok=True)
    # Clone profil jika belum pernah (idempoten)
    clone_profil_ke_session(force=False)
    # Jangan pakai subprocess.Popen module-level: di atas sudah di-patch
    # SW_HIDE untuk proses Playwright dan itu membuat window Brave invisible.
    _OrigPopen(
        _visible_brave_command(with_cdp=True),
        stdin=_subprocess.DEVNULL,
        stdout=_subprocess.DEVNULL,
        stderr=_subprocess.DEVNULL,
        close_fds=True,
    )


async def _tutup_async():
    if _get_ctx():
        await _get_ctx().close()
    if _get_pw():
        await _get_pw().stop()
    _set_pw(None)
    _set_ctx(None)
    _set_page(None)


def tutup_browser():
    """Tutup browser SPSE secara deterministik: kill proses Brave CDP (port 9222) + reset state.

    Sebelumnya fallback hanya menutup TAB via /json/close (proses Brave tetap listen 9222),
    sehingga tombol Tutup terlihat no-op saat Playwright ctx belum connect. Sekarang selalu
    kill proses agar port benar-benar bebas dan sidebar kembali ke form login.
    """
    global _cdp_tabs_cache, _cdp_tabs_cache_ts
    # Coba tutup rapi via Playwright kalau ctx ada (menyimpan profil dengan bersih)
    if _get_ctx():
        try:
            _run(_tutup_async(), timeout=8)
        except Exception:
            pass
    # Kill proses Brave apa pun kondisinya — ini yang bikin deterministik
    _kill_browser()
    _cdp_tabs_cache = []
    _cdp_tabs_cache_ts = 0.0
    _clear_cookie_cache()
    # Hapus last_role saat browser ditutup
    try:
        from pathlib import Path as _Path
        _rf = _Path(__file__).parent / ".browser_session" / "last_role.txt"
        if _rf.exists():
            _rf.unlink()
    except Exception:
        pass


def refresh_browser():
    """Reload tab SPSE yang sedang berada di halaman navigasi aman."""
    import requests as _req
    global _cdp_tabs_cache, _cdp_tabs_cache_ts
    for attempt in range(2):
        try:
            tabs = _req.get(f"http://localhost:{CDP_PORT}/json", timeout=2).json()
            page_tabs = [t for t in tabs if t.get("type") == "page"]
            target_tabs = [t for t in page_tabs if _boleh_auto_refresh(t.get("url", ""))]
            if not target_tabs:
                return False
            # Reload background — jangan activate (foreground takeover).
            tab = _pilih_tab_spse(target_tabs)
            if tab is None:
                return False
            if _get_ctx() is None:
                # Daemon harus tetap bisa refresh walau context Playwright
                # belum pernah tersambung atau sudah stale. connect_over_cdp
                # dapat menggantung saat Brave memulihkan banyak tab; CDP
                # WebSocket langsung cukup untuk Page.reload + validasi DOM.
                return _reload_tab_via_cdp(tab)
            page = _run(_find_page_for_tab_async(tab), timeout=8)
            if page is None or page.is_closed():
                raise RuntimeError("Context Playwright tidak punya tab CDP yang cocok")
            _run(page.reload(timeout=15000), timeout=20)
            # Reload HTTP sukses belum berarti sesi SPSE valid. Validasi body
            # setelah reload agar daemon tidak mencatat 403/login sebagai
            # refresh berhasil.
            title = _run(page.title(), timeout=5)
            body = _run(page.locator("body").inner_text(timeout=3000), timeout=5)
            if _is_spse_access_error_text(title) or _is_spse_access_error_text(body):
                return False
            if _is_spse_login_page_text(title) or _is_spse_login_page_text(body):
                return False
            _set_page(page)
            _cdp_tabs_cache = []
            _cdp_tabs_cache_ts = 0.0
            return True
        except Exception:
            if attempt == 0 and _cek_cdp_aktif():
                # Context lama dapat tetap non-None walau websocket CDP sudah
                # mati. Reset lalu fallback ke CDP langsung; jangan membuat
                # daemon memanggil buka_browser() yang bisa blocking.
                diskonek()
                return _reload_tab_via_cdp(tab)
            return False
    return False


def _cdp_page_command(tab: dict, method: str, params: dict | None = None, timeout: float = 8.0) -> dict:
    """Kirim satu command CDP ke tab tanpa Playwright/context global."""
    ws_url = str(tab.get("webSocketDebuggerUrl") or "").strip()
    if not ws_url:
        raise RuntimeError("Tab CDP tidak memiliki websocketDebuggerUrl")

    result: list[dict | None] = [None]
    error: list[BaseException | None] = [None]

    def _worker() -> None:
        async def _send() -> dict:
            import websockets as _ws

            async with _ws.connect(
                ws_url,
                open_timeout=min(3.0, timeout),
                close_timeout=1.0,
            ) as ws:
                await ws.send(json.dumps({
                    "id": 1,
                    "method": method,
                    "params": params or {},
                }))
                deadline = asyncio.get_running_loop().time() + timeout
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError(f"Timeout CDP {method}")
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                    if message.get("id") != 1:
                        continue
                    if message.get("error"):
                        raise RuntimeError(str(message["error"]))
                    return message.get("result") or {}

        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            result[0] = loop.run_until_complete(_send())
        except BaseException as exc:  # diteruskan ke caller dengan timeout terbatas
            error[0] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=max(1.0, float(timeout)) + 2.0)
    if thread.is_alive():
        raise TimeoutError(f"Timeout thread CDP {method}")
    if error[0] is not None:
        raise error[0]
    return result[0] or {}


def _cdp_runtime_value(payload: dict):
    """Ambil value Runtime.evaluate dari response CDP langsung maupun wrapper test."""
    result = payload.get("result") or {}
    if isinstance(result, dict) and "value" in result:
        return result.get("value")
    nested = result.get("result") if isinstance(result, dict) else None
    return nested.get("value") if isinstance(nested, dict) else None


def _reload_tab_via_cdp(tab: dict) -> bool:
    """Reload + validasi tab aman melalui CDP langsung.

    Jalur ini khusus refresh background/user; tidak mengambil alih foreground
    dan tidak menyentuh form/detail. False berarti sesi sudah login/error atau
    tab tidak dapat divalidasi.
    """
    _cdp_page_command(tab, "Page.reload", {"ignoreCache": False}, timeout=6.0)
    expression = (
        "JSON.stringify({title: document.title || '', "
        "body: document.body ? document.body.innerText : ''})"
    )
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        try:
            payload = _cdp_page_command(
                tab,
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
                timeout=3.0,
            )
            value = _cdp_runtime_value(payload)
            data = json.loads(value) if isinstance(value, str) else {}
            title = str(data.get("title") or "")
            body = str(data.get("body") or "")
            if _is_spse_access_error_text(title) or _is_spse_access_error_text(body):
                return False
            if _is_spse_login_page_text(title) or _is_spse_login_page_text(body):
                return False
            if body.strip():
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _keepalive_tab_via_cdp(tab: dict) -> bool:
    """Pertahankan cookie sesi tanpa reload atau mengubah DOM tab user.

    Dipakai saat user sedang berada di form/detail PL. GET dilakukan melalui
    ``fetch`` di origin SPSE yang sama, sehingga cookie browser ikut, tetapi
    halaman/form yang sedang diedit tidak dinavigasi ulang.
    """
    expression = """(async () => {
        try {
            const response = await fetch(window.location.href, {
                method: "GET",
                credentials: "include",
                cache: "no-store",
                headers: {
                    "Accept": "text/html,application/xhtml+xml",
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const html = await response.text();
            const parsed = new DOMParser().parseFromString(html, "text/html");
            parsed.querySelectorAll("script,style,noscript").forEach((node) => node.remove());
            const body = parsed.body ? parsed.body.innerText : html;
            return JSON.stringify({
                status: response.status,
                url: response.url,
                body: body.slice(0, 5000),
            });
        } catch (error) {
            return JSON.stringify({error: String(error)});
        }
    })()"""
    try:
        payload = _cdp_page_command(
            tab,
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
            timeout=10.0,
        )
        value = _cdp_runtime_value(payload)
        data = json.loads(value) if isinstance(value, str) else {}
        status = int(data.get("status") or 0)
        final_url = str(data.get("url") or "")
        body = str(data.get("body") or "")
        if status < 200 or status >= 400:
            return False
        if "loginpass" in final_url.casefold() or _is_spse_login_page_text(body):
            return False
        if _is_spse_access_error_text(body):
            return False
        return bool(body.strip())
    except Exception:
        return False


def keepalive_browser() -> bool:
    """Keep SPSE session alive when no safe page may be reloaded.

    Manual ``refresh_browser()`` remains restricted to safe navigation routes;
    this helper is background-only and uses non-navigating GET for authenticated
    form/detail tabs.
    """
    try:
        tabs = _cdp_tabs(force=True)
        target_tabs = [
            tab for tab in tabs
            if tab.get("type") == "page"
            and _url_spse_score(tab.get("url", ""), tab.get("title", "")) > 1
        ]
        if not target_tabs:
            return False
        tab = _pilih_tab_spse(target_tabs)
        return bool(tab and _keepalive_tab_via_cdp(tab))
    except Exception:
        return False


def diskonek():
    """Reset koneksi Playwright tanpa menutup browser. Berguna jika CDP sudah ditutup manual."""
    global _cdp_tabs_cache, _cdp_tabs_cache_ts
    _set_pw(None)
    _set_ctx(None)
    _set_page(None)
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
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True, shell=True
                )
    except Exception:
        pass


def ubah_metode_via_playwright(kode_paket: str, kategori_id: int, pilih: int, base_url: str) -> str:
    """
    Ubah metode pengadaan via cdp_eval fetch POST (bypass Playwright new_page + confirm dialog).
    GET /metode → ambil authenticityToken → POST /metodesubmit → verifikasi opaqueredirect.
    Return "OK" jika sukses, pesan error jika gagal.
    """
    import json as _json
    from ppk_upload_engine import _cdp_eval

    lpse = base_url.rstrip("/").rsplit("/", 1)[-1]
    js = f"""
(async () => {{
  const lpse = {_json.dumps(lpse)};
  const kode = {_json.dumps(kode_paket)};
  const kategoriId = {_json.dumps(str(kategori_id))};
  const pilih = {_json.dumps(str(pilih))};

  // GET /metode untuk ambil authenticityToken
  const rGet = await fetch('/' + lpse + '/nontender/' + kode + '/metode', {{credentials: 'include'}});
  if (!rGet.ok) return {{ok: false, msg: 'GET status ' + rGet.status + ' type ' + rGet.type}};
  const html = await rGet.text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const token = doc.querySelector('input[name=authenticityToken]')?.value || '';
  if (!token) return {{ok: false, msg: 'authenticityToken tidak ditemukan'}};

  // POST /metodesubmit — redirect: manual agar tidak throw
  const body = new FormData();
  body.append('authenticityToken', token);
  body.append('kategoriId', kategoriId);
  body.append('pilih', pilih);
  body.append('simpan', 'simpan');

  const rPost = await fetch('/' + lpse + '/nontender/' + kode + '/metodesubmit', {{
    method: 'POST',
    credentials: 'include',
    body,
    redirect: 'manual'
  }});

  // opaqueredirect (type=opaqueredirect, status=0) = 302 → sukses
  if (rPost.type === 'opaqueredirect' || rPost.status === 0 || rPost.status === 302 || rPost.status === 200) {{
    return {{ok: true, msg: 'OK'}};
  }}
  const responseText = await rPost.text().catch(() => '');
  const detail = responseText.replace(/\\s+/g, ' ').slice(0, 160);
  return {{ok: false, msg: 'POST status ' + rPost.status + ' type ' + rPost.type + (detail ? ' body ' + detail : '')}};
}})()
"""
    for _attempt in range(3):
        ok, val, err = _cdp_eval(js, timeout=20)
        if not ok:
            return f"CDP error: {err}"
        if isinstance(val, dict) and val.get("ok"):
            return "OK"
        msg = val.get("msg", "unknown") if isinstance(val, dict) else str(val)
        transient = any(
            f"{method} status {status}" in msg
            for method in ("GET", "POST")
            for status in (502, 503, 504)
        )
        if transient and _attempt < 2:
            time.sleep(0.8 * (2 ** _attempt))
            continue
        return f"Gagal: {msg}"
    return "Gagal: SPSE tidak merespons setelah 3 percobaan"


async def _update_ijin_sbu_async(kode_paket: str, ijin_idx: int, klas_baru: str, base_url: str) -> str:
    """
    Update isi field ijin[N].chk_klasifikasi di form LDK via Playwright CDP, lalu submit.
    Dipakai karena server SPSE block update ijin existing via requests POST (nilai di-revert).
    Return "OK" jika sukses, pesan error jika gagal.
    """
    if _get_ctx() is None:
        await _connect_cdp_async(navigate=False)
    if _get_ctx() is None:
        return "CDP tidak tersambung"

    page = await _get_ctx().new_page()
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
    if _get_ctx() is None:
        await _connect_cdp_async(navigate=False)
    if _get_ctx() is None:
        return {"ok": False, "pesan": "CDP tidak tersambung"}

    page = await _get_ctx().new_page()
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

    def _nama_key(s: str) -> str:
        return _re.sub(r"\s+", " ", (s or "").upper().replace(".", " ")).strip()

    def _nama_tanpa_prefix(s: str) -> str:
        stop = {"CV", "PT", "UD", "TB", "FA", "FIRMA", "KOPERASI"}
        return " ".join(w for w in _nama_key(s).split() if w and w not in stop)

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
            return {
                "ok": True,
                "nama": nama_hasil,
                "nama_penyedia": nama_hasil,
                "npwp": npwp16,
                "npwp_penyedia": npwp16,
                "rkn_npwp_16": npwp16,
                "mode": "sudah_terpilih",
                "pesan": "Penyedia sudah terpilih sebelumnya",
            }

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

    # Fallback: search by nama. Penting untuk NPWP 16 placeholder/NIK-like yang
    # tidak terdaftar persis di DB rekanan SPSE, tapi nama penyedia tersedia.
    if target_idx is None and nama_penyedia:
        nama_cari = _nama_tanpa_prefix(nama_penyedia)
        if nama_cari:
            url_search_nama = f"{url_form}?search=true&nama={_up.quote(nama_cari)}&npwp=&jenisIjin="
            r2 = sess.get(url_search_nama, timeout=45)
            if r2.status_code == 200:
                soup2 = _BS(r2.text, "html.parser")
                csrf = csrf or _get_csrf(soup2)
                rekanan_data = _parse_rekanan(soup2)
                target_nama = _nama_key(nama_penyedia)
                target_nama_strip = _nama_tanpa_prefix(nama_penyedia)
                for idx, d in rekanan_data.items():
                    nama_db = _nama_key(d.get("rkn_nama", ""))
                    nama_db_strip = _nama_tanpa_prefix(d.get("rkn_nama", ""))
                    if nama_db == target_nama or nama_db_strip == target_nama_strip:
                        target_idx = idx
                        search_mode = "nama_exact"
                        break
                if target_idx is None and len(rekanan_data) == 1:
                    target_idx = list(rekanan_data.keys())[0]
                    search_mode = "nama_single"

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
        "nama_penyedia": nama_hasil,
        "npwp": d.get("rkn_npwp_16") or d.get("rkn_npwp") or npwp,
        "npwp_penyedia": d.get("rkn_npwp_16") or d.get("rkn_npwp") or npwp,
        "rkn_id": d.get("rkn_id", ""),
        "rkn_npwp": d.get("rkn_npwp", ""),
        "rkn_npwp_16": d.get("rkn_npwp_16", ""),
        "kabupaten_id": d.get("kabupaten_id", ""),
        "mode": search_mode,
        "status": rp.status_code,
        "pesan": rp.headers.get("Location", "") if ok else f"HTTP {rp.status_code}: {rp.text[:200]}",
    }


def halaman_aktif() -> Page | None:
    if _get_page() and not _get_page().is_closed():
        return _get_page()
    if _get_ctx() and _get_ctx().pages:
        _set_page(_get_ctx().pages[-1])
        return _get_page()
    return None


_cdp_tabs_cache: list[dict] = []
_cdp_tabs_cache_ts: float = 0.0
_CDP_CACHE_TTL = 10.0  # detik — cache tab list 10 detik; cukup responsif tapi hemat rerun


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
    if not _get_ctx():
        return
    tabs = _cdp_tabs()
    if 0 <= index < len(tabs):
        target_url = tabs[index].get("url", "")
        if target_url:
            matched = next((p for p in _get_ctx().pages if p.url == target_url), None)
            if matched:
                _set_page(matched)
                return
    # fallback ke index Playwright
    if 0 <= index < len(_get_ctx().pages):
        _set_page(_get_ctx().pages[index])


def get_url() -> str:
    """Ambil URL tab aktif via CDP HTTP API — instant."""
    tabs = _cdp_tabs()
    if not tabs:
        return ""
    # Cari tab yang sedang aktif (focused) atau pakai tab pertama
    # Prioritaskan tab SPSE yang sudah authenticated; urutan CDP bukan urutan
    # tab foreground sehingga tab loginpass/root bisa muncul lebih dahulu.
    active = _pilih_tab_spse(tabs)
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


def _clear_cookie_cache() -> None:
    """Hapus cookie cache lokal agar sesi browser mati tidak dipakai ulang."""
    global _cookie_cache, _cookie_cache_ts
    _cookie_cache = ""
    _cookie_cache_ts = 0.0


def get_spse_cookies(force: bool = False) -> str:
    """
    Ambil cookies SPSE via Playwright context yang sudah ada.
    Di-cache 5 menit + thread-safe lock agar concurrent caller (bulk paralel)
    tidak race init Playwright.
    """
    import time as _time
    global _cookie_cache, _cookie_cache_ts

    # Jangan mengembalikan cookie lama bila CDP sudah mati/stale.
    if not _cek_cdp_aktif():
        _clear_cookie_cache()
        return ""

    if force:
        _cookie_cache = ""
        _cookie_cache_ts = 0.0

    # Fast-path: cache hit tanpa lock
    now = _time.time()
    if _cookie_cache and (now - _cookie_cache_ts) < _COOKIE_CACHE_TTL:
        return _cookie_cache

    # Slow-path: pegang lock, double-check (worker lain mungkin sudah refresh)
    with _cookie_lock:
        now = _time.time()
        if _cookie_cache and (now - _cookie_cache_ts) < _COOKIE_CACHE_TTL:
            return _cookie_cache

        # Coba via Playwright context dulu
        if _get_ctx() is not None:
            try:
                cookies = _run(_get_ctx().cookies(), timeout=10)
                spse = [c for c in cookies if "inaproc" in c.get("domain", "")]
                result = "; ".join(f'{c["name"]}={c["value"]}' for c in spse)
                if result:
                    _cookie_cache = result
                    _cookie_cache_ts = now
                    return result
            except Exception:
                pass

        # Fallback: ambil cookie via CDP WebSocket per-tab di thread terpisah
        try:
            import asyncio as _aio, json as _json2, urllib.request as _ur2, threading as _thr
            tabs = _json2.loads(_ur2.urlopen(f"http://localhost:{CDP_PORT}/json", timeout=3).read())
            tab = next(
                (t for t in tabs if "spse.inaproc.id" in t.get("url", "") and t.get("type") == "page"),
                None
            )
            if tab and tab.get("webSocketDebuggerUrl"):
                _ws_url = tab["webSocketDebuggerUrl"]
                _cookie_result = [None]

                def _fetch_cookies_thread():
                    async def _inner():
                        import websockets as _ws
                        async with _ws.connect(_ws_url, open_timeout=5) as ws:
                            await ws.send(_json2.dumps({"id": 1, "method": "Network.getAllCookies", "params": {}}))
                            while True:
                                msg = _json2.loads(await _aio.wait_for(ws.recv(), timeout=10))
                                if msg.get("id") == 1:
                                    return msg.get("result", {}).get("cookies", [])
                    lp = _aio.ProactorEventLoop()  # Windows: wajib Proactor untuk WS
                    _aio.set_event_loop(lp)
                    try:
                        _cookie_result[0] = lp.run_until_complete(_inner())
                    finally:
                        lp.close()

                t = _thr.Thread(target=_fetch_cookies_thread, daemon=True)
                t.start()
                t.join(timeout=15)
                if _cookie_result[0] is not None:
                    spse = [c for c in _cookie_result[0] if "inaproc" in c.get("domain", "")]
                    result = "; ".join(f'{c["name"]}={c["value"]}' for c in spse)
                    if result:
                        _cookie_cache = result
                        _cookie_cache_ts = now
                        return result
        except Exception:
            pass

        # Semua jalur gagal: sesi harus dianggap tidak tersedia, bukan
        # mengembalikan cookie stale yang dapat membuat auto-login palsu.
        _clear_cookie_cache()
        return ""

