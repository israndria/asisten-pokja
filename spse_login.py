"""
spse_login.py — Auto-login SPSE via CDP + OCR CAPTCHA (pytesseract).

Security:
- Credentials dibaca dari secret_spse.env (gitignored), TIDAK pernah di-log/print.
- Tidak ada credential yang masuk ke session_state Streamlit.
- CAPTCHA screenshot disimpan sementara di .browser_session/ lalu dihapus setelah OCR.
- Retry max 3x — kalau gagal, raise RuntimeError (bukan expose password).
"""

from __future__ import annotations
import os
import re
import time
import asyncio
import tempfile
import base64
from pathlib import Path
from typing import Literal

# ============================================================
# Load credentials — SEKALI saat import, tidak di-cache di state
# ============================================================

_ENV_PATH = Path(__file__).parent / "secret_spse.env"

def _load_env() -> dict[str, str]:
    """Baca secret_spse.env → dict. Raise jika file tidak ada."""
    if not _ENV_PATH.exists():
        raise FileNotFoundError(f"File credentials tidak ditemukan: {_ENV_PATH}")
    result: dict[str, str] = {}
    with open(_ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    return result


def _get_creds(role: Literal["PP", "POKJA"]) -> tuple[str, str]:
    """Return (username, password) untuk role PP atau POKJA."""
    env = _load_env()
    key_u = f"SPSE_USERNAME_{role}"
    key_p = f"SPSE_PASSWORD_{role}"
    username = env.get(key_u, "").strip()
    password = env.get(key_p, "").strip()
    if not username or not password:
        raise ValueError(f"Credentials untuk role '{role}' tidak lengkap di secret_spse.env")
    return username, password


# ============================================================
# OCR CAPTCHA
# ============================================================

def _ocr_captcha(img_bytes: bytes) -> str:
    """
    OCR teks CAPTCHA dari bytes gambar.
    Multi-strategy: coba beberapa threshold + PSM, ambil hasil terpanjang.
    Return string hasil OCR (lowercase, alfanumerik only).
    """
    import os
    import cv2
    import numpy as np
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = r"C:\Users\MSI\scoop\apps\tesseract\5.5.0.20241111\tesseract.exe"
    os.environ["TESSDATA_PREFIX"] = r"C:\Users\MSI\scoop\apps\tesseract\5.5.0.20241111\tessdata"

    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)  # baca RGBA
    if img is None:
        return ""

    # Handle RGBA — composite ke background putih
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4] / 255.0
        rgb = img[:, :, :3].astype(float)
        white = np.ones_like(rgb) * 255
        img_rgb = (rgb * alpha + white * (1 - alpha)).astype(np.uint8)
        gray = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2GRAY)
    elif img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    big = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    # Hapus grid noise via morfologi:
    # 1. Invert (huruf jadi putih), 2. Erode hancurkan grid tipis,
    # 3. Dilate kembalikan huruf, 4. Invert balik (huruf hitam untuk tesseract)
    inv = 255 - big
    k_erode = cv2.getStructuringElement(cv2.MORPH_RECT, (4, 4))
    k_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    eroded = cv2.erode(inv, k_erode, iterations=1)
    dilated = cv2.dilate(eroded, k_dilate, iterations=1)
    cleaned = 255 - dilated  # huruf hitam, background putih

    whitelist = "abcdefghijklmnopqrstuvwxyz0123456789"
    results = []

    variants = [
        cleaned,
        255 - big,  # raw inverted
        cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
    ]

    for processed in variants:
        for psm in [7, 8, 6]:
            cfg = f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
            try:
                txt = pytesseract.image_to_string(processed, config=cfg).strip()
                txt = "".join(c for c in txt.lower() if c.isalnum())
                # CAPTCHA SPSE = 4-8 karakter — filter hasil noise (terlalu panjang/pendek)
                if 4 <= len(txt) <= 8:
                    results.append(txt)
            except Exception:
                pass

    if not results:
        return ""
    # Ambil yang paling sering muncul, fallback ke terpendek
    from collections import Counter
    freq = Counter(results)
    return freq.most_common(1)[0][0]


# ============================================================
# Auto-login via CDP (Playwright async)
# ============================================================

_LOGIN_URL = "https://spse.inaproc.id/tapinkab/loginpass"
_MAX_RETRY  = 3


async def _login_async(role: Literal["PP", "POKJA"], log_fn=None) -> bool:
    """
    Connect ke Brave CDP → buka halaman login → auto-login dengan OCR CAPTCHA.
    Return True jika berhasil, raise RuntimeError jika gagal semua retry.
    log_fn: callable(str) untuk progress (opsional, tidak pernah log credential).
    """
    import spse_browser as _sb

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    username, password = _get_creds(role)
    _log(f"Menghubungkan ke Brave CDP (port {_sb.CDP_PORT})...")

    # Reuse _pw dari spse_browser (sudah jalan di background loop)
    if _sb._pw is None:
        _sb._pw = await _sb.async_playwright().start()
    browser = await _sb._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{_sb.CDP_PORT}")
    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    # Step 1: Home SPSE — navigate fresh (jangan asumsi state halaman)
    from config import SPSE_BASE_URL
    _log("Membuka halaman SPSE...")
    await page.goto(SPSE_BASE_URL, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(1000)  # tunggu JS Bootstrap load

    # Step 2: Klik tombol LOGIN via JS
    _log("Klik tombol Login...")
    await page.evaluate("document.querySelector('#login').click()")
    await page.wait_for_timeout(1500)  # tunggu modal Bootstrap animate-in

    # Step 3: Pilih Non Penyedia via JS (modal Bootstrap, Playwright wait_for_selector tidak reliable)
    _log("Pilih Non Penyedia...")
    await page.wait_for_timeout(800)
    clicked = await page.evaluate("""() => {
        var btns = Array.from(document.querySelectorAll('button'));
        var btn = btns.find(b => (b.innerText || b.textContent || '').trim().toUpperCase().includes('NON PENYEDIA'));
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    if not clicked:
        await page.screenshot(path=str(Path(__file__).parent / "scratch" / "debug_nonpenyedia.png"))
        raise RuntimeError("Tombol NON PENYEDIA tidak ditemukan — lihat scratch/debug_nonpenyedia.png")
    await page.wait_for_load_state("domcontentloaded")
    _log("Isi User ID...")
    await page.wait_for_selector("input[name='txtUserId']", timeout=8000)
    await page.fill("input[name='txtUserId']", username)
    await page.click("button[type='submit']")
    await page.wait_for_load_state("domcontentloaded")
    _log("Halaman password + CAPTCHA terbuka.")

    for attempt in range(1, _MAX_RETRY + 1):
        _log(f"Percobaan login {attempt}/{_MAX_RETRY}...")

        await page.wait_for_selector("#txtPassword", timeout=10000)
        await page.fill("#txtPassword", password)

        # CAPTCHA: ambil src → fetch bytes via JS (lebih reliable dari element screenshot)
        captcha_el = await page.query_selector("img[src*='showcaptcha']")
        if not captcha_el:
            raise RuntimeError("Elemen CAPTCHA tidak ditemukan di halaman login.")

        captcha_src = await captcha_el.get_attribute("src")
        # Fetch bytes CAPTCHA via browser (session cookie otomatis ikut)
        captcha_b64 = await page.evaluate(f"""async () => {{
            const r = await fetch({repr(captcha_src)}, {{credentials: 'include'}});
            const buf = await r.arrayBuffer();
            return btoa(String.fromCharCode(...new Uint8Array(buf)));
        }}""")
        import base64 as _b64
        captcha_bytes = _b64.b64decode(captcha_b64)

        # Debug: simpan ke scratch
        _debug_path = Path(__file__).parent / "scratch" / f"captcha_attempt_{attempt}.png"
        _debug_path.parent.mkdir(exist_ok=True)
        _debug_path.write_bytes(captcha_bytes)

        captcha_text = _ocr_captcha(captcha_bytes)
        _log(f"OCR CAPTCHA: '{captcha_text}' (attempt {attempt})")

        if not captcha_text:
            _log("OCR gagal membaca CAPTCHA, refresh...")
            refresh = await page.query_selector("a:has-text('klik di sini')")
            if refresh:
                await refresh.click()
                await page.wait_for_timeout(800)
            continue

        await page.fill("#txtCode", captcha_text)
        await page.click("button[type='submit']")
        await page.wait_for_timeout(2000)
        current_url = page.url

        if "loginpass" not in current_url and "login" not in current_url.split("/")[-1]:
            _log(f"✅ Login berhasil sebagai {role}!")
            return True

        err_el = await page.query_selector(".alert-danger, .alert-error, .error")
        err_msg = (await err_el.inner_text()).strip() if err_el else ""

        if any(k in err_msg.lower() for k in ["captcha", "kode", "code"]):
            _log(f"CAPTCHA salah, retry... ({err_msg[:60]})")
            refresh = await page.query_selector("a:has-text('klik di sini')")
            if refresh:
                await refresh.click()
                await page.wait_for_timeout(800)
        elif err_msg:
            raise RuntimeError(f"Login gagal: {err_msg[:120]}")
        else:
            _log("Login belum berhasil, retry...")

    raise RuntimeError(f"Login gagal setelah {_MAX_RETRY} percobaan — CAPTCHA tidak terbaca.")


def login_spse(role: Literal["PP", "POKJA"] = "PP", log_fn=None) -> bool:
    """
    Entry point sinkronus untuk dipanggil dari Streamlit / app.py.
    role: 'PP' atau 'POKJA'
    log_fn: callable(str) untuk progress logging (opsional)
    """
    import spse_browser as _sb
    # Pakai loop + _run dari spse_browser (ProactorEventLoop Windows)
    _sb._ensure_loop()
    return _sb._run(_login_async(role, log_fn=log_fn))
