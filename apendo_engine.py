"""Apendo Engine — Otomasi pembukaan dokumen penawaran via Apendo v5.1.5 (GUI automation).

Flow:
1. Ambil token dari halaman SPSE /lelang/{kode_tender} via CDP
2. Launch apendo_bg.py (Python Win32 hybrid automation):
   - Buka Apendo
   - Physical click paste token + Kirim Token
   - PostMessage background untuk step selanjutnya
   - Klik Unduh per peserta via hybrid_click (cursor disimpan & dikembalikan)
3. Tail log file untuk progress reporting

Opsi mode:
  - mode="bg"     → apendo_bg.py (default, Win32 hybrid)
  - mode="frida"  → frida_apendo.py (experimental, inject JS ke Qt5WebKit)
"""

import os
import re
import subprocess
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import APENDO_EXE, PYTHON_SYS
BG_SCRIPT   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apendo_bg.py")

# Legacy AHK (tidak dipakai, dipertahankan sebagai referensi)
AHK_EXE    = r"C:\Program Files\AutoHotkey\AutoHotkey.exe"
AHK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apendo_flow.ahk")


# ── Ambil token dari halaman SPSE ────────────────────────────────────────────

def get_token_dari_spse(kode_tender: str, progress_cb=None) -> dict:
    """
    Ambil token Apendo dari halaman /lelang/{kode_tender} via CDP (Playwright).
    Browser harus sudah terbuka dan login di CDP port 9222.

    Returns:
        {"ok": True, "token_url": "...", "access_token": "...", "nama_tender": "..."}
        {"ok": False, "pesan": "..."}
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    try:
        import spse_browser
        from config import SPSE_BASE_URL

        _log("Menghubungkan ke browser...")
        spse_browser.buka_browser(navigate=False)

        target_url = f"{SPSE_BASE_URL}lelang/{kode_tender}"

        # Cari tab yang sudah terbuka, atau buka baru
        page = next(
            (p for p in spse_browser._context.pages if kode_tender in p.url),
            None,
        )

        if page is None:
            _log(f"Membuka halaman {target_url}...")
            page = spse_browser._context.new_page()
            spse_browser._run(page.goto(target_url, wait_until="domcontentloaded", timeout=30000))
            time.sleep(2)

        _log("Mengambil token dari halaman...")
        result = spse_browser._run(page.evaluate("""() => {
            const btn = document.querySelector("button.btn.btn-secondary");
            if (!btn) return null;
            const onclick = btn.getAttribute("onclick") || "";
            const match = onclick.match(/copyToken\\('([^']+)','([^']+)'\\)/);
            if (!match) return null;

            // Ambil nama tender dari halaman
            const namaTd = document.querySelector("td b");
            const nama = namaTd ? namaTd.innerText.trim() : "";

            return {token_url: match[1], access_token: match[2], nama_tender: nama};
        }"""))

        if not result:
            return {"ok": False, "pesan": "Token tidak ditemukan di halaman. Pastikan paket sudah masuk tahap pembukaan penawaran."}

        _log(f"Token ditemukan: {result['access_token'][:8]}...")
        return {"ok": True, **result}

    except Exception as e:
        return {"ok": False, "pesan": f"Error mengambil token: {e}"}


# ── Launch & Otomasi Apendo via apendo_bg.py ─────────────────────────────────

def buka_dokumen_penawaran(
    token_url: str,
    folder_output: str,
    progress_cb=None,
    jumlah_peserta: int = 3,
    mode: str = "bg",
) -> dict:
    """
    Launch automation script untuk seluruh flow Apendo.

    Args:
        token_url     : URL token dari SPSE
        folder_output : Path folder tujuan (parent folder)
        progress_cb   : Callback(str) untuk progress log
        jumlah_peserta: Jumlah peserta yang akan diunduh
        mode          : "bg" (default) = apendo_bg.py Win32 hybrid
                        "frida"        = frida_apendo.py (experimental)

    Returns:
        {"ok": True, "folder": "...", "files": [...]}
        {"ok": False, "pesan": "..."}
    """
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    if not os.path.exists(APENDO_EXE):
        return {"ok": False, "pesan": f"Apendo.exe tidak ditemukan di: {APENDO_EXE}"}

    if not os.path.isdir(folder_output):
        try:
            os.makedirs(folder_output, exist_ok=True)
        except Exception as e:
            return {"ok": False, "pesan": f"Folder output tidak bisa dibuat: {e}"}

    if mode == "frida":
        return _buka_via_frida(token_url, folder_output, jumlah_peserta, _log)
    else:
        return _buka_via_bg(token_url, folder_output, jumlah_peserta, _log)


def _buka_via_bg(token_url, folder_output, jumlah_peserta, _log):
    """Jalankan apendo_bg.py (Win32 hybrid, default)."""
    if not os.path.exists(BG_SCRIPT):
        return {"ok": False, "pesan": f"apendo_bg.py tidak ditemukan di: {BG_SCRIPT}"}

    if not os.path.exists(PYTHON_SYS):
        return {"ok": False, "pesan": f"Python tidak ditemukan di: {PYTHON_SYS}"}

    # Log file dibuat fresh setiap run
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apendo_bg.log")
    try:
        open(log_file, "w").close()
    except Exception:
        pass

    try:
        _log("Meluncurkan apendo_bg.py (Win32 hybrid)...")
        _log(f"Token : {token_url[:60]}...")
        _log(f"Folder: {folder_output}")
        _log(f"Peserta: {jumlah_peserta}")

        cmd = [
            PYTHON_SYS,
            BG_SCRIPT,
            APENDO_EXE,
            token_url,
            folder_output,
            log_file,
            str(jumlah_peserta),
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _log(f"apendo_bg.py PID={proc.pid}, memantau log...")

        last_pos = 0
        timeout = 360  # 6 menit max (lebih panjang dari AHK karena ada tunggu lebih lama)
        start = time.time()

        while proc.poll() is None and (time.time() - start) < timeout:
            time.sleep(1)
            last_pos = _tail_log(log_file, last_pos, _log)

        last_pos = _tail_log(log_file, last_pos, _log)

        rc = proc.returncode
        if rc == 0:
            _log("apendo_bg.py selesai. Memindai hasil unduhan...")
            files = _scan_folder_output(folder_output)
            _log(f"Ditemukan {len(files)} file di folder output.")
            return {"ok": True, "folder": folder_output, "files": files}
        else:
            pesan = _baca_baris_terakhir_log(log_file)
            return {"ok": False, "pesan": f"apendo_bg.py keluar kode {rc}. {pesan}"}

    except Exception as e:
        import traceback
        return {"ok": False, "pesan": f"Error: {e}\n{traceback.format_exc()}"}


def _buka_via_frida(token_url, folder_output, jumlah_peserta, _log):
    """
    Experimental: Gunakan Frida untuk inject JS ke Qt5WebKit Apendo.
    Apendo harus sudah dibuka oleh caller sebelum memanggil ini
    (frida_apendo.py akan wait_for_apendo() sendiri).
    """
    try:
        frida_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frida_apendo.py")
        if not os.path.exists(frida_script):
            return {"ok": False, "pesan": f"frida_apendo.py tidak ditemukan: {frida_script}"}

        _log("Mode FRIDA — inject ke Qt5WebKit Apendo...")
        _log("Meluncurkan Apendo terlebih dahulu...")

        # Launch Apendo
        apendo_dir = os.path.dirname(APENDO_EXE)
        subprocess.Popen([APENDO_EXE], cwd=apendo_dir)

        # Jalankan frida_apendo.py di proses terpisah
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frida_apendo.log")
        try:
            open(log_file, "w").close()
        except Exception:
            pass

        cmd = [PYTHON_SYS, frida_script, str(jumlah_peserta)]
        proc = subprocess.Popen(
            cmd,
            stdout=open(log_file, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        _log(f"frida_apendo.py PID={proc.pid}")

        last_pos = 0
        timeout = 300
        start = time.time()
        while proc.poll() is None and (time.time() - start) < timeout:
            time.sleep(1)
            last_pos = _tail_log(log_file, last_pos, _log)
        last_pos = _tail_log(log_file, last_pos, _log)

        rc = proc.returncode
        if rc == 0:
            _log("Frida inject selesai. Memindai hasil...")
            files = _scan_folder_output(folder_output)
            return {"ok": True, "folder": folder_output, "files": files, "mode": "frida"}
        else:
            pesan = _baca_baris_terakhir_log(log_file)
            return {"ok": False, "pesan": f"Frida keluar kode {rc}. {pesan}"}

    except Exception as e:
        import traceback
        return {"ok": False, "pesan": f"Frida error: {e}\n{traceback.format_exc()}"}


def _tail_log(log_file: str, last_pos: int, log_cb) -> int:
    """Baca baris baru dari log file sejak last_pos, panggil log_cb per baris."""
    if not os.path.exists(log_file):
        return last_pos
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            f.seek(last_pos)
            for line in f:
                line = line.rstrip()
                if line:
                    log_cb(line)
            return f.tell()
    except Exception:
        return last_pos


def _baca_baris_terakhir_log(log_file: str) -> str:
    """Baca baris terakhir dari log file."""
    if not os.path.exists(log_file):
        return ""
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip()]
            return lines[-1] if lines else ""
    except Exception:
        return ""


def _scan_folder_output(folder_output: str) -> list:
    """Scan folder output Apendo dan return daftar file yang ditemukan."""
    hasil = []
    if not os.path.isdir(folder_output):
        return hasil

    for root, dirs, files in os.walk(folder_output):
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, folder_output)
            size = os.path.getsize(fp)
            hasil.append({"path": fp, "rel": rel, "size": size})

    return sorted(hasil, key=lambda x: x["rel"])


# ── Utilitas ─────────────────────────────────────────────────────────────────

def get_last_apendo_dir() -> str:
    """Baca folder output terakhir yang dipakai."""
    conf = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_apendo_dir")
    if os.path.exists(conf):
        try:
            return open(conf).read().strip()
        except Exception:
            pass
    return r"D:\data"


def save_last_apendo_dir(folder: str):
    """Simpan folder output terakhir."""
    conf = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_apendo_dir")
    try:
        with open(conf, "w") as f:
            f.write(folder)
    except Exception:
        pass
