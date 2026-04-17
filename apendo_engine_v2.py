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
import threading
import requests
import urllib3
import tempfile

urllib3.disable_warnings()

PYTHON_SYS  = r"C:\Users\MSI\AppData\Local\Programs\Python\Python312\python.exe"
MITM_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_log_response.py")
MITM_OUT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_out.txt")
MITM_PORT   = 8892

APENDO_UA   = "Apendo/5.1.5 (18 november 2021) LT17/1.1 (18 november 2021) Qt/5.14.0 LKPPRI-SPSE/4.4"
BASE_HEADERS = {
    "User-Agent": APENDO_UA,
    "Accept-Encoding": "identity",
    "Accept-Language": "en-ID,*",
    "Connection": "Keep-Alive",
}

_mitm_proc = None


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


def mulai_mitmproxy(progress_cb=None):
    """Mulai mitmproxy di background. Return True jika berhasil listen."""
    global _mitm_proc

    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _kill_port(MITM_PORT)
    time.sleep(1)

    # Aktifkan Windows system proxy
    subprocess.run([
        "powershell", "-Command",
        f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
        f"-Name ProxyEnable -Value 1; "
        f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
        f"-Name ProxyServer -Value '127.0.0.1:{MITM_PORT}'"
    ], capture_output=True)

    # Bersihkan file output lama
    for f in [MITM_OUT, MITM_SCRIPT.replace("mitm_log_response.py", "mitm_headers_log.json")]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    mitmdump = r"C:\Users\MSI\AppData\Local\Programs\Python\Python312\Scripts\mitmdump.exe"
    _mitm_proc = subprocess.Popen(
        [mitmdump, "--mode", f"regular@127.0.0.1:{MITM_PORT}", "-s", MITM_SCRIPT],
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
    """Hentikan mitmproxy dan matikan Windows proxy."""
    global _mitm_proc
    if _mitm_proc:
        _mitm_proc.terminate()
        _mitm_proc = None

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
    Tunggu sampai mitmproxy capture request download dari Apendo.
    Return dict berisi: signature, cookie, id_dok, token, lpse_kode
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _log(" Menunggu klik Unduh di Apendo...")
    deadline = time.time() + timeout

    while time.time() < deadline:
        entries = _baca_headers_log()
        for e in entries:
            url = e.get("url", "")
            if "/lt17/download" not in url:
                continue
            req_h = e.get("req_headers", {})
            sig = req_h.get("Apendo-Signature", "")
            cookie = req_h.get("Cookie", "")
            if not sig or not cookie:
                continue

            # Parse URL
            m_token = re.search(r"access_token=([^&]+)", url)
            m_id    = re.search(r"id=([^&]+)", url)
            m_lpse  = re.search(r"inaproc\.id/([^/]+)/lt17", url)

            if not (m_token and m_id and m_lpse):
                continue

            _log(f"OK Capture berhasil! id={m_id.group(1)}")
            return {
                "signature": sig,
                "cookie": cookie,
                "id_dok": m_id.group(1),
                "access_token": m_token.group(1),
                "lpse_kode": m_lpse.group(1),
                "base_url": f"https://spse.inaproc.id/{m_lpse.group(1)}",
            }

        time.sleep(2)

    _log("GAGAL Timeout — tidak ada capture dari Apendo")
    return None


# ── Download engine ───────────────────────────────────────────────────────────

def _buat_session(capture: dict) -> requests.Session:
    sess = requests.Session()
    sess.proxies = {"http": None, "https": None}
    sess.headers.update(BASE_HEADERS)
    sess.headers["Apendo-Signature"] = capture["signature"]
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

    # Step 1 — start mitmproxy
    if not mulai_mitmproxy(progress_cb=_log):
        return {"ok": False, "files": [], "pesan": "mitmproxy gagal start"}

    _log("mitmproxy aktif (hanya localhost). Sekarang:")
    _log("  1. Buka Apendo → login → buka paket")
    _log("  2. Klik tombol Unduh satu kali")
    _log("  Engine akan otomatis lanjutkan setelah itu.")

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
        # Step 4 — selalu stop mitmproxy, bahkan jika crash
        hentikan_mitmproxy()
        _log("mitmproxy dihentikan, proxy Windows dimatikan.")

    return {
        "ok": len(files_downloaded) > 0,
        "files": files_downloaded,
        "capture": capture,
        "pesan": f"{len(files_downloaded)}/{len(id_dok_list)} file berhasil diunduh",
    }
