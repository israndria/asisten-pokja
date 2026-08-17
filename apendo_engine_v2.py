"""Apendo Engine v2 — Download dokumen penawaran via HTTP requests murni (tanpa GUI Apendo).

Flow:
1. Aktifkan mitmproxy (port 8892) — capture Apendo-Signature + Cookie + id dokumen
2. User buka Apendo sekali, klik Unduh manual 1x → mitmproxy capture semua headers
3. Engine Python replay headers tersebut untuk download semua peserta secara background

Keunggulan vs apendo_engine.py (v1):
- Tidak merebut mouse/keyboard sama sekali
- Background 100% — bisa paralel dengan pekerjaan lain
- Tidak butuh Apendo berjalan selama proses download
"""

import os
import re
import json
import time
import subprocess
import ctypes
import requests
import urllib3
from config import SPSE_CDP_PORT

urllib3.disable_warnings()

PYTHON_SYS  = r"C:\Users\MSI\AppData\Local\Programs\Python\Python312\python.exe"
MITM_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_inject_cookie.py")
MITM_OUT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_out.txt")
MITM_PORT   = 8892

APENDO_EXE    = r"D:\Dokumen\3 @ POKJA 2025\@ POKJA 2025\2. Pokja 009\Apendo v5.1.5u20220905(x64)\release\Apendo.exe"
APENDO_CONFIG = r"D:\Dokumen\3 @ POKJA 2025\@ POKJA 2025\2. Pokja 009\Apendo v5.1.5u20220905(x64)\config\config.json"

SW_MINIMIZE = 6
SW_HIDE     = 0

APENDO_UA   = "Apendo/5.1.5 (18 november 2021) LT17/1.1 (18 november 2021) Qt/5.14.0 LKPPRI-SPSE/4.4"
BASE_HEADERS = {
    "User-Agent": APENDO_UA,
    "Accept-Encoding": "identity",
    "Accept-Language": "en-ID,*",
    "Connection": "Keep-Alive",
}

_mitm_proc = None


# ── Apendo config proxy ───────────────────────────────────────────────────────

def _set_apendo_proxy(address: str):
    """Set proxy address di config.json Apendo. address='' untuk disable."""
    try:
        with open(APENDO_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("proxy", {})["address"] = address
        with open(APENDO_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception:
        pass


# ── mitmproxy lifecycle ───────────────────────────────────────────────────────

def _kill_port(port: int):
    """Kill proses yang listen di port tertentu."""
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"],
            capture_output=True, text=True
        )
        pid = result.stdout.strip()
        if pid and pid.isdigit():
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            time.sleep(1)
    except Exception:
        pass


# ── Apendo lifecycle ─────────────────────────────────────────────────────────

def _cari_hwnd_apendo() -> int:
    """Cari window handle Apendo yang sedang berjalan."""
    hasil = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def callback(hwnd, _):
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        if "Apendo" in buf.value or "Aplikasi Pengaman Dokumen" in buf.value:
            hasil.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(EnumWindowsProc(callback), 0)
    return hasil[0] if hasil else 0


def _cdp_via_playwright(progress_cb=None):
    """
    Return (browser, pages) via Playwright connect_over_cdp.
    Caller bertanggung jawab menutup browser.
    """
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://localhost:{SPSE_CDP_PORT}")
    pages = browser.contexts[0].pages if browser.contexts else []
    return pw, browser, pages


def ambil_token_dari_browser(progress_cb=None) -> str:
    """
    Ambil token URL lt17 dari tab Brave yang sedang aktif via Playwright CDP
    pada port instance.
    Return URL lengkap mis. 'https://spse.inaproc.id/tapinkab/lt17/<TOKEN>...' atau ''.
    """
    def _log(msg):
        if progress_cb: progress_cb(msg)

    try:
        pw, browser, pages = _cdp_via_playwright(progress_cb)
        try:
            for page in pages:
                if "spse.inaproc.id" not in page.url:
                    continue
                token_url = page.evaluate("""() => {
                    var links = document.querySelectorAll('a[href*="lt17"]');
                    for (var i = 0; i < links.length; i++) {
                        if (links[i].href && links[i].href.includes('/lt17/')) return links[i].href;
                    }
                    if (window.location.href.includes('/lt17/')) return window.location.href;
                    return '';
                }""")
                if token_url and "/lt17/" in token_url:
                    _log(f"OK Token URL ditemukan: {token_url[:60]}...")
                    return token_url
        finally:
            # connect_over_cdp memakai browser milik user. Jangan panggil
            # browser.close() karena dapat menutup seluruh Brave beserta tab
            # SPSE; cukup putuskan client Playwright-nya.
            pw.stop()

        _log("INFO Token URL lt17 tidak ditemukan di tab Chrome")
        return ""
    except Exception as ex:
        _log(f"INFO Tidak bisa ambil token dari browser: {ex}")
        return ""


def simpan_session_dari_browser(progress_cb=None) -> str:
    """
    Ambil SPSE_SESSION dari Chrome via Playwright CDP dan simpan ke spse_session.json.
    Return nilai SPSE_SESSION atau ''.
    """
    def _log(msg):
        if progress_cb: progress_cb(msg)

    session_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spse_session.json")
    try:
        pw, browser, pages = _cdp_via_playwright(progress_cb)
        try:
            ctx = browser.contexts[0] if browser.contexts else None
            if ctx:
                cookies = ctx.cookies(["https://spse.inaproc.id"])
                for c in cookies:
                    if c.get("name") == "SPSE_SESSION":
                        spse = c["value"]
                        with open(session_file, "w") as f:
                            json.dump({"SPSE_SESSION": spse}, f)
                        _log(f"OK SPSE_SESSION disimpan ({spse[:16]}...)")
                        return spse
        finally:
            # Brave adalah browser milik user, bukan resource engine Apendo.
            # Hentikan koneksi Playwright saja agar CDP tetap hidup.
            pw.stop()

        _log("INFO SPSE_SESSION tidak ditemukan di browser")
        return ""
    except Exception as ex:
        _log(f"INFO Tidak bisa ambil session dari browser: {ex}")
        return ""


def launch_apendo(token_url: str = "", progress_cb=None) -> int:
    """
    Launch Apendo jika belum berjalan, minimize window-nya.
    Jika token_url diberikan, launch dengan URL itu sebagai CLI arg (auto-load /lt17).
    Return PID Apendo, atau 0 jika gagal.
    """
    def _log(msg):
        if progress_cb: progress_cb(msg)

    # Cek apakah sudah berjalan
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Apendo.exe"],
                       capture_output=True, text=True)
    sudah_jalan = "Apendo.exe" in r.stdout

    if sudah_jalan:
        _log("INFO Apendo sudah berjalan — tutup dulu untuk kirim token baru.")
        tutup_apendo()
        time.sleep(2)

    if not os.path.exists(APENDO_EXE):
        _log(f"GAGAL Apendo.exe tidak ditemukan: {APENDO_EXE}")
        return 0

    cmd = [APENDO_EXE]
    if token_url:
        cmd.append(token_url)
        _log(f"Meluncurkan Apendo dengan token URL: {token_url[:60]}...")
    else:
        _log("Meluncurkan Apendo (tanpa token — perlu paste manual)...")
    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    time.sleep(5)  # tunggu window muncul

    # Minimize window Apendo
    for _ in range(10):
        hwnd = _cari_hwnd_apendo()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            _log("Apendo diminimize ke background.")
            break
        time.sleep(1)

    # Ambil PID
    r2 = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Apendo.exe", "/FO", "CSV"],
                        capture_output=True, text=True)
    for line in r2.stdout.splitlines():
        if "Apendo.exe" in line:
            pid = int(line.split(",")[1].strip().strip('"'))
            return pid
    return 0


def tutup_apendo(pid: int = 0, progress_cb=None):
    """Tutup Apendo secara graceful (WM_CLOSE), fallback ke taskkill."""
    def _log(msg):
        if progress_cb: progress_cb(msg)

    hwnd = _cari_hwnd_apendo()
    if hwnd:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(2)

    # Verifikasi sudah tutup
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Apendo.exe"],
                       capture_output=True, text=True)
    if "Apendo.exe" in r.stdout:
        subprocess.run(["taskkill", "/F", "/IM", "Apendo.exe"], capture_output=True)
        _log("Apendo ditutup paksa.")
    else:
        _log("Apendo ditutup.")


def mulai_mitmproxy(progress_cb=None):
    """Mulai mitmproxy di background. Return True jika berhasil listen."""
    global _mitm_proc

    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _kill_port(MITM_PORT)
    # Juga kill semua proses mitmdump yang mungkin masih jalan
    subprocess.run(["taskkill", "/F", "/IM", "mitmdump.exe"], capture_output=True)
    time.sleep(1)

    # Set proxy di config Apendo (Qt5Network pakai ini, bukan Windows proxy)
    _set_apendo_proxy(f"127.0.0.1:{MITM_PORT}")

    # Aktifkan Windows system proxy (untuk Chrome/browser jika perlu)
    subprocess.run([
        "powershell", "-Command",
        f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
        f"-Name ProxyEnable -Value 1; "
        f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
        f"-Name ProxyServer -Value '127.0.0.1:{MITM_PORT}'"
    ], capture_output=True)

    # Bersihkan file output lama
    LOG_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_headers_log.json")
    for f in [MITM_OUT, LOG_JSON]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    mitmdump = r"C:\Users\MSI\AppData\Local\Programs\Python\Python312\Scripts\mitmdump.exe"
    _mitm_proc = subprocess.Popen(
        [mitmdump, "-p", str(MITM_PORT), "-s", MITM_SCRIPT],
        stdout=open(MITM_OUT, "w"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # Tunggu listen
    for _ in range(10):
        time.sleep(1)
        result = subprocess.run(
            ["powershell", "-Command", f"netstat -aon | Select-String '{MITM_PORT}'"],
            capture_output=True, text=True
        )
        if str(MITM_PORT) in result.stdout:
            _log(f"OK mitmproxy aktif di port {MITM_PORT}")
            return True

    _log("GAGAL mitmproxy gagal start")
    return False


def hentikan_mitmproxy():
    """Hentikan mitmproxy, matikan Windows proxy, dan reset proxy Apendo."""
    global _mitm_proc
    if _mitm_proc:
        _mitm_proc.terminate()
        _mitm_proc = None

    subprocess.run(["taskkill", "/F", "/IM", "mitmdump.exe"], capture_output=True)

    # Reset proxy Apendo
    _set_apendo_proxy("")

    subprocess.run([
        "powershell", "-Command",
        "Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
        "-Name ProxyEnable -Value 0"
    ], capture_output=True)


# ── Capture dari mitmproxy log ────────────────────────────────────────────────

def _baca_headers_log() -> list[dict]:
    """Baca mitm_headers_log.json, return list entry."""
    log_path = os.path.join(os.path.dirname(MITM_SCRIPT), "mitm_headers_log.json")
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def tunggu_capture(timeout=120, progress_cb=None) -> dict | None:
    """
    Tunggu sampai mitmproxy capture request GET /lt17 dari Apendo (saat paste token).
    id_dok di-parse dari HTML response /lt17 — tidak perlu klik Unduh.
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _log("Menunggu Apendo load halaman lt17 (paste token ke Apendo)...")
    deadline = time.time() + timeout

    while time.time() < deadline:
        entries = _baca_headers_log()
        for e in entries:
            url = e.get("url", "")
            # Cukup dari GET /lt17? (load halaman), bukan dari /download
            if "/lt17?" not in url and "/lt17/download" not in url:
                continue
            req_h = e.get("req_headers", {})
            sig   = req_h.get("Apendo-Signature", "") or req_h.get("apendo-signature", "")
            cookie = req_h.get("Cookie", "") or req_h.get("cookie", "")
            if not sig or not cookie:
                continue

            m_token = re.search(r"access_token=([^&\s]+)", url)
            m_lpse  = re.search(r"inaproc\.id/([^/]+)/lt17", url)
            if not (m_token and m_lpse):
                continue

            token    = m_token.group(1)
            lpse     = m_lpse.group(1)
            base_url = f"https://spse.inaproc.id/{lpse}"

            # Parse id_dok dari HTML /lt17
            id_list = _ambil_id_dari_halaman(base_url, token, sig, cookie)

            _log(f"OK Capture! token={token[:8]}... | {len(id_list)} id ditemukan: {id_list}")
            return {
                "signature":    sig,
                "cookie":       cookie,
                "id_dok":       id_list[0] if id_list else "",
                "id_dok_list":  id_list,
                "access_token": token,
                "lpse_kode":    lpse,
                "base_url":     base_url,
            }

        time.sleep(2)

    _log("GAGAL Timeout — Apendo tidak load halaman lt17")
    return None


def _ambil_id_dari_halaman(base_url: str, token: str, sig: str, cookie: str) -> list[str]:
    """Parse semua id_dok dari HTML response /lt17."""
    sess = requests.Session()
    sess.proxies = {"http": None, "https": None}
    headers = {
        "User-Agent": APENDO_UA,
        "apendo-signature": sig,
        "Cookie": cookie,
    }
    try:
        r = sess.get(f"{base_url}/lt17?access_token={token}",
                     headers=headers, timeout=30, verify=False)
        ids = re.findall(r'\bid\s*:\s*["\']?(10000\d+)["\']?', r.text)
        return list(dict.fromkeys(ids))  # unik, urut
    except Exception:
        return []


# ── Download engine ───────────────────────────────────────────────────────────

def _buat_session(capture: dict) -> requests.Session:
    sess = requests.Session()
    sess.proxies = {"http": None, "https": None}
    sess.headers.update(BASE_HEADERS)
    sess.headers["apendo-signature"] = capture["signature"]
    sess.headers["Cookie"] = capture["cookie"]
    return sess


def download_dokumen(capture: dict, id_dok: str, path_simpan: str,
                     progress_cb=None) -> bool:
    """Download 1 file .rhs ke path_simpan. Return True jika berhasil."""
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    sess = _buat_session(capture)
    url = f"{capture['base_url']}/lt17/download?id={id_dok}&access_token={capture['access_token']}"

    _log(f"  Download id={id_dok}...")
    try:
        r = sess.get(url, timeout=120, verify=False)
        if r.status_code != 200:
            _log(f"GAGAL HTTP {r.status_code} untuk id={id_dok}")
            return False
        os.makedirs(os.path.dirname(path_simpan), exist_ok=True)
        with open(path_simpan, "wb") as f:
            f.write(r.content)
        _log(f"OK Tersimpan: {path_simpan} ({len(r.content):,} bytes)")
        return True
    except Exception as ex:
        _log(f"GAGAL Error download: {ex}")
        return False


def submit_info_teknis(capture: dict, id_submit: str, files_info: list,
                       progress_cb=None) -> bool:
    """
    POST /lt17/submit_info_teknis — lapor path file ke server.
    files_info = [{"category": "1  Teknis - ...", "files": ["D:/path/to/file.rhs"]}]
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    import uuid
    boundary = f"boundary_.oOo._{uuid.uuid4().hex[:20]}"
    payload_json = json.dumps(files_info, ensure_ascii=False)

    body  = f"--{boundary}\r\n"
    body += f'Content-Disposition: form-data; name="id"\r\n\r\n{id_submit}\r\n'
    body += f"--{boundary}\r\n"
    body += f'Content-Disposition: form-data; name="info"\r\n\r\n{payload_json}\r\n'
    body += f"--{boundary}--\r\n"

    sess = _buat_session(capture)
    sess.headers["Content-Type"] = f"multipart/form-data; boundary=\"{boundary}\""
    sess.headers["MIME-Version"] = "1.0"

    url = f"{capture['base_url']}/lt17/submit_info_teknis?access_token={capture['access_token']}"
    try:
        r = sess.post(url, data=body.encode("utf-8"), timeout=30, verify=False)
        if r.status_code == 200:
            _log("OK submit_info_teknis OK")
            return True
        _log(f"GAGAL submit_info_teknis HTTP {r.status_code}")
        return False
    except Exception as ex:
        _log(f"GAGAL submit_info_teknis error: {ex}")
        return False


# ── Flow utama ────────────────────────────────────────────────────────────────

def buka_penawaran(
    kode_tender: str,
    id_dok_list: list[str],
    dir_output: str,
    progress_cb=None,
    timeout_capture: int = 120,
    auto_apendo: bool = True,
) -> dict:
    """
    Flow lengkap buka penawaran tanpa GUI Apendo:

    1. Start mitmproxy
    2. User buka Apendo + klik Unduh manual 1x
    3. Engine capture headers lalu download semua id_dok_list
    4. Stop mitmproxy

    Args:
        kode_tender: mis. "10092474000"
        id_dok_list: list id dokumen peserta mis. ["1000011812001", "1000011812002"]
        dir_output:  folder simpan file .rhs
        progress_cb: callback(str) untuk update UI
        timeout_capture: detik tunggu klik Unduh pertama

    Returns:
        {"ok": bool, "files": [...], "pesan": "..."}
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    # Step 0 — simpan SPSE_SESSION dari browser (untuk inject ke Apendo via mitmproxy)
    simpan_session_dari_browser(progress_cb=_log)

    # Step 1 — start mitmproxy
    if not mulai_mitmproxy(progress_cb=_log):
        return {"ok": False, "files": [], "pesan": "mitmproxy gagal start"}

    # Step 1b — launch Apendo otomatis jika diminta
    apendo_pid = 0
    if auto_apendo:
        # Coba ambil token URL dari browser
        token_url = ambil_token_dari_browser(progress_cb=_log)
        apendo_pid = launch_apendo(token_url=token_url, progress_cb=_log)
        if not apendo_pid:
            hentikan_mitmproxy()
            return {"ok": False, "files": [], "pesan": "Apendo gagal diluncurkan"}
        if token_url:
            _log("Apendo berjalan di background — auto-load halaman tender.")
        else:
            _log("Apendo berjalan di background — paste token di Apendo, lalu tunggu.")
    else:
        _log("mitmproxy aktif. Buka Apendo → paste token. Tidak perlu klik Unduh.")

    try:
        # Step 2 — tunggu capture
        capture = tunggu_capture(timeout=timeout_capture, progress_cb=_log)
        if not capture:
            return {"ok": False, "files": [], "pesan": "Timeout — tidak ada capture dari Apendo"}

        # Step 3 — download semua id
        if not id_dok_list:
            id_dok_list = [capture["id_dok"]]
            _log(f"INFO id_dok_list kosong, pakai dari capture: {id_dok_list}")

        files_downloaded = []
        for id_dok in id_dok_list:
            fname = f"{kode_tender}-{id_dok}.rhs"
            fpath = os.path.join(dir_output, fname)
            ok = download_dokumen(capture, id_dok, fpath, progress_cb=_log)
            if ok:
                files_downloaded.append(fpath)

    finally:
        # Step 4 — selalu stop mitmproxy + tutup Apendo
        hentikan_mitmproxy()
        _log("mitmproxy dihentikan, proxy Windows dimatikan.")
        if auto_apendo and apendo_pid:
            tutup_apendo(apendo_pid, progress_cb=_log)

    return {
        "ok": len(files_downloaded) > 0,
        "files": files_downloaded,
        "capture": capture,
        "pesan": f"{len(files_downloaded)}/{len(id_dok_list)} file berhasil diunduh",
    }


# ── Flow v3: tanpa Apendo, tanpa mitmproxy ───────────────────────────────────

def _generate_signature() -> str:
    """Generate Apendo-Signature dummy — server hanya cek format, tidak validasi isi."""
    import secrets, base64
    ts = str(int(time.time() * 1000))
    nonce = secrets.token_urlsafe(9)[:12]
    mac = base64.b64encode(secrets.token_bytes(20)).decode()
    return f"{ts}|{nonce}|{mac}"


def _ambil_token_dari_tab(kode_tender: str, lpse_kode: str = "tapinkab",
                           progress_cb=None) -> tuple[str, str, str]:
    """
    Ambil access_token + SPSE_SESSION dari Chrome CDP via subprocess terpisah
    (Playwright sync API tidak thread-safe di dalam Streamlit).
    Return (access_token, spse_session, lpse_kode).
    """
    def _log(msg):
        if progress_cb: progress_cb(msg)

    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cdp_get_token.py")
    try:
        r = subprocess.run(
            [PYTHON_SYS, helper, kode_tender, lpse_kode],
            capture_output=True, text=True, timeout=30
        )
        out = r.stdout.strip()
        if not out:
            _log(f"GAGAL CDP subprocess: {r.stderr[:200]}")
            return "", "", lpse_kode
        data = json.loads(out)
        if not data.get("ok"):
            _log(f"GAGAL CDP: {data.get('error', 'tidak ada token/session')}")
            return "", "", lpse_kode
        access_token = data["access_token"]
        spse         = data["spse_session"]
        lpse_kode    = data.get("lpse_kode", lpse_kode)
        _log(f"OK token={access_token[:16]}... lpse={lpse_kode}")
        return access_token, spse, lpse_kode
    except Exception as ex:
        _log(f"GAGAL CDP: {ex}")
        return "", "", lpse_kode


def buka_penawaran_v3(
    kode_tender: str,
    dir_output: str,
    lpse_kode: str = "tapinkab",
    progress_cb=None,
) -> dict:
    """
    Download dokumen penawaran TANPA Apendo dan TANPA mitmproxy.

    Flow:
    1. Ambil access_token + SPSE_SESSION dari Chrome CDP
    2. Generate Apendo-Signature dummy (server tidak validasi isi)
    3. GET /lt17 → parse id_dok semua peserta
    4. Download semua .rhs

    Args:
        kode_tender: mis. "10090469000"
        dir_output:  folder simpan file .rhs
        lpse_kode:   mis. "tapinkab"
        progress_cb: callback(str) untuk update UI

    Returns:
        {"ok": bool, "files": [...], "pesan": "..."}
    """
    def _log(msg):
        if progress_cb: progress_cb(msg)

    _log(f"Ambil token dari browser (kode tender: {kode_tender})...")
    access_token, spse, lpse_kode = _ambil_token_dari_tab(
        kode_tender, lpse_kode, progress_cb=_log
    )
    if not access_token or not spse:
        return {"ok": False, "files": [], "pesan": "Gagal ambil token dari browser CDP"}

    sig = _generate_signature()
    base_url = f"https://spse.inaproc.id/{lpse_kode}/lt17"

    headers = {
        "User-Agent": APENDO_UA,
        "Cookie": f"SPSE_SESSION={spse}",
        "apendo-signature": sig,
        "Accept-Language": "en-ID,*",
        "Accept-Encoding": "identity",
        "Connection": "Keep-Alive",
    }

    sess = requests.Session()
    sess.proxies = {"http": None, "https": None}

    # GET /lt17 → parse id_dok
    _log("GET /lt17 untuk ambil daftar peserta...")
    try:
        r = sess.get(f"{base_url}?access_token={access_token}",
                     headers=headers, timeout=30, verify=False)
    except Exception as ex:
        return {"ok": False, "files": [], "pesan": f"Error GET /lt17: {ex}"}

    if r.status_code != 200:
        return {"ok": False, "files": [], "pesan": f"GET /lt17 HTTP {r.status_code}"}

    id_dok_list = list(dict.fromkeys(
        re.findall(r'\bid\s*:\s*["\']?(10000\d+)["\']?', r.text)
    ))
    _log(f"OK {len(id_dok_list)} peserta ditemukan: {id_dok_list}")

    if not id_dok_list:
        return {"ok": False, "files": [], "pesan": "Tidak ada id_dok ditemukan di halaman lt17"}

    # Download semua .rhs
    os.makedirs(dir_output, exist_ok=True)
    files_downloaded = []
    for id_dok in id_dok_list:
        fname = f"{kode_tender}-{id_dok}.rhs"
        fpath = os.path.join(dir_output, fname)
        dl_url = f"{base_url}/download?id={id_dok}&access_token={access_token}"
        _log(f"  Download {id_dok}...")
        try:
            r2 = sess.get(dl_url, headers=headers, timeout=120, verify=False)
            if r2.status_code == 200:
                with open(fpath, "wb") as f:
                    f.write(r2.content)
                _log(f"  OK {fname} ({len(r2.content):,} bytes)")
                files_downloaded.append(fpath)
            else:
                _log(f"  GAGAL HTTP {r2.status_code} untuk {id_dok}")
        except Exception as ex:
            _log(f"  GAGAL error: {ex}")

    return {
        "ok": len(files_downloaded) > 0,
        "files": files_downloaded,
        "pesan": f"{len(files_downloaded)}/{len(id_dok_list)} file berhasil diunduh",
    }
