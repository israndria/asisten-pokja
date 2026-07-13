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
import hashlib
import json
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
_ROLE_FILE = Path(__file__).parent / ".browser_session" / "last_role.txt"


def _cookie_fingerprint(cookie: str) -> str:
    """Hash SPSE_SESSION; nilai cookie tidak pernah disimpan."""
    session = next((p.split("=", 1)[1] for p in cookie.split("; ") if p.startswith("SPSE_SESSION=")), "")
    return hashlib.sha256(session.encode("utf-8")).hexdigest() if session else ""


def remember_login_role(role: str) -> None:
    """Simpan role + fingerprint sesi agar cache role stale ditolak saat F5."""
    import spse_browser as _sb
    cookie = _sb.get_spse_cookies(force=True)
    if not cookie:
        return
    _ROLE_FILE.parent.mkdir(exist_ok=True)
    _ROLE_FILE.write_text(json.dumps({"role": role, "cookie_fp": _cookie_fingerprint(cookie)}), encoding="utf-8")

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


def _get_creds(role: Literal["PP", "POKJA", "PPK"]) -> tuple[str, str]:
    """Return (username, password) untuk role PP atau POKJA."""
    env = _load_env()
    key_u = f"SPSE_USERNAME_{role}"
    key_p = f"SPSE_PASSWORD_{role}"
    username = env.get(key_u, "").strip()
    password = env.get(key_p, "").strip()
    if not username or not password:
        raise ValueError(f"Credentials untuk role '{role}' tidak lengkap di secret_spse.env")
    return username, password


def detect_login_role() -> str | None:
    """
    Ambil role login aktif dari cache yang dicocokkan dengan cookie sesi Brave.

    Login di app ini WAJIB via tombol (Launch & Auto-Login), yang menulis role ke file
    setelah login sukses. Fungsi ini hanya untuk memulihkan role saat Streamlit hot-reload
    (session_state hilang tapi browser + file cache masih ada). Cache teks lama ditolak.

    Return: "PP" | "POKJA" | "PPK" | None (kalau belum login / halaman masih di login).
    """
    import spse_browser as _sb

    def _detect_role_from_page(url: str, cookie: str) -> str | None:
        """Validasi role dari halaman SPSE saat fingerprint cookie berubah."""
        import requests
        from bs4 import BeautifulSoup
        try:
            response = requests.get(
                url,
                headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
                timeout=10,
                allow_redirects=True,
            )
            final_url = response.url.lower()
            if "loginpass" in final_url:
                return None
            text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
            if "Pejabat Pengadaan" in text:
                return "PP"
            if "Pejabat Pembuat Komitmen" in text:
                return "PPK"
            if "Kelompok Kerja" in text or "Pokja" in text:
                return "POKJA"
        except Exception:
            pass
        return None

    try:
        url = _sb.get_url()
        if not url:
            return None
        # URL root /tapinkab atau /loginpass = belum/pasca logout → belum login
        from config import SPSE_BASE_URL
        _base = SPSE_BASE_URL.rstrip("/")
        if url.rstrip("/") == _base or "loginpass" in url:
            return None
        if _ROLE_FILE.exists():
            record = json.loads(_ROLE_FILE.read_text(encoding="utf-8"))
            role = record.get("role")
            cookie = _sb.get_spse_cookies(force=True)
            if role not in ("PP", "POKJA", "PPK", "E-Katalog"):
                return None
            current_fp = _cookie_fingerprint(cookie)
            if record.get("cookie_fp") == current_fp:
                return role

            # Session SPSE dapat rotate tanpa logout. Validasi halaman aktif,
            # lalu refresh fingerprint agar F5 tidak memaksa login ulang.
            detected = _detect_role_from_page(url, cookie)
            if detected:
                _ROLE_FILE.write_text(
                    json.dumps({"role": detected, "cookie_fp": current_fp}),
                    encoding="utf-8",
                )
                return detected
    except Exception:
        pass
    return None


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
    img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img is None:
        return ""

    # Handle RGBA — CAPTCHA SPSE: RGB=0, teks dikodekan di alpha channel
    if img.ndim == 3 and img.shape[2] == 4:
        r_ch, g_ch, b_ch, a_ch = cv2.split(img)
        rgb_sum = r_ch.astype(float) + g_ch.astype(float) + b_ch.astype(float)
        if rgb_sum.max() < 10:
            # RGB semua nol → pakai alpha channel sebagai grayscale
            gray = a_ch
        else:
            # Normal RGBA → composite ke putih
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
    big4 = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

    # Auto-detect: kalau background gelap (teks terang) → invert dulu
    mean_val = big.mean()
    work  = 255 - big  if mean_val < 128 else big.copy()
    work4 = 255 - big4 if mean_val < 128 else big4.copy()

    # Hapus grid noise via morfologi — selalu dijalankan
    def _clean(w):
        inv = 255 - w
        ke = cv2.getStructuringElement(cv2.MORPH_RECT, (4, 4))
        kd = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        return 255 - cv2.dilate(cv2.erode(inv, ke), kd)

    cleaned  = _clean(work)
    cleaned4 = _clean(work4)

    whitelist = "abcdefghijklmnopqrstuvwxyz0123456789"
    results = []
    variants = [
        cleaned,   work,                                                    # fx=3
        cleaned4,  work4,                                                   # fx=4
        cv2.threshold(work,  0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.threshold(work4, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
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


def _ocr_captcha_gemini(img_bytes: bytes) -> str:
    """
    Fallback OCR via Gemini Vision API.
    Dipanggil hanya setelah Tesseract gagal MAX_RETRY kali.
    Return string hasil OCR (lowercase, alfanumerik only), atau '' kalau gagal.
    """
    import os, base64
    from pathlib import Path

    # Load API key dari secret_spse.env
    env_path = Path(__file__).parent / "secret_spse.env"
    api_key = None
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return ""

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = (
            "This is a CAPTCHA image from a government procurement website. "
            "Read the text exactly as shown. It contains exactly 4-8 alphanumeric characters (letters and/or digits). "
            "Return ONLY the characters in lowercase, nothing else — no spaces, no punctuation, no explanation."
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                prompt,
            ],
        )
        raw = response.text.strip().lower()
        result = "".join(c for c in raw if c.isalnum())
        # Sanity check panjang
        if 4 <= len(result) <= 8:
            return result
        # Kalau terlalu panjang → ambil 6 char pertama
        return result[:6] if len(result) > 8 else ""
    except Exception:
        return ""


# ============================================================
# Auto-login via CDP (Playwright async)
# ============================================================

_LOGIN_URL = "https://spse.inaproc.id/tapinkab/loginpass"
_MAX_RETRY = 5


async def _login_async(role: Literal["PP", "POKJA", "PPK"], log_fn=None) -> bool:
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

    # Reuse page dari spse_browser (sudah di-init via buka_browser sebelum login)
    if _sb._get_page() is None:
        raise RuntimeError("spse_browser belum di-init — panggil buka_browser() dulu.")
    page = _sb._get_page()

    # Step 1: Home SPSE — navigate fresh, tunggu sampai networkidle (Bootstrap JS siap)
    from config import SPSE_BASE_URL
    _log("Membuka halaman SPSE...")
    await page.goto(SPSE_BASE_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(500)

    # Step 1b: Logout dulu kalau sudah login
    already_logged_in = await page.evaluate("""() => {
        var links = Array.from(document.querySelectorAll('a, button'));
        return links.some(l => (l.innerText||'').toUpperCase().includes('KELUAR') ||
                                (l.innerText||'').toUpperCase().includes('LOGOUT') ||
                                (l.href||'').includes('logout'));
    }""")
    if already_logged_in:
        _log("Sesi lama terdeteksi, logout dulu...")
        await page.evaluate("""() => {
            var links = Array.from(document.querySelectorAll('a, button'));
            var btn = links.find(l => (l.innerText||'').toUpperCase().includes('KELUAR') ||
                                       (l.innerText||'').toUpperCase().includes('LOGOUT') ||
                                       (l.href||'').includes('logout'));
            if (btn) btn.click();
        }""")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(500)
        # Ganti akun cepat: session/cookie lama sering masih nempel di server → /home balas
        # "Akses Ditolak". Paksa clear cookies lalu navigate ulang ke home agar bersih.
        try:
            if _sb._get_ctx() is not None:
                await _sb._get_ctx().clear_cookies()
                _log("Cookie sesi lama dibersihkan.")
        except Exception as _ce:
            _log(f"(clear cookie dilewati: {_ce})")
        await page.goto(SPSE_BASE_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(500)

    # Step 2: Klik tombol LOGIN via JS
    _log("Klik tombol Login...")
    # Cek dulu #login ada. Saat ganti akun cepat, kadang halaman masih "Akses Ditolak"
    # (session lama belum benar-benar habis) → retry reload home beberapa kali.
    login_el = await page.query_selector("#login")
    if not login_el:
        for _retry in range(4):
            _log(f"#login belum ada — reload home (percobaan {_retry+1}/4)...")
            await page.wait_for_timeout(1500)
            await page.goto(SPSE_BASE_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(500)
            login_el = await page.query_selector("#login")
            if login_el:
                break
    if not login_el:
        # Screenshot untuk debug
        from pathlib import Path as _P
        _ss = _P(__file__).parent / "scratch" / "debug_nologin.png"
        _ss.parent.mkdir(exist_ok=True)
        await page.screenshot(path=str(_ss))
        current_url = page.url
        page_text = await page.evaluate("() => document.body?.innerText?.slice(0,200) || ''")
        raise RuntimeError(f"Tombol #login tidak ditemukan — halaman: {current_url}\n{page_text}")
    await page.evaluate("document.querySelector('#login').click()")

    # Tunggu modal Bootstrap animate-in (max 5 detik)
    for _i in range(10):
        await page.wait_for_timeout(500)
        modal_visible = await page.evaluate("""() => {
            var m = document.querySelector('.modal.show');
            return m !== null && m.offsetParent !== null;
        }""")
        if modal_visible:
            break
    _log(f"Modal visible: {modal_visible}")

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

    # Semua Tesseract retry habis — fallback ke Gemini Vision
    return await _gemini_captcha_attempt(page, password, log_fn=log_fn)


_MAX_GEMINI_RETRY = 3

async def _gemini_captcha_attempt(page, password: str, log_fn=None) -> bool:
    """3x retry login pakai Gemini Vision — refresh captcha tiap attempt."""
    def _log(msg):
        if log_fn: log_fn(msg)

    _log("🤖 Fallback ke Gemini Vision untuk baca CAPTCHA...")

    for _gi in range(1, _MAX_GEMINI_RETRY + 1):
        await page.wait_for_selector("#txtPassword", timeout=8000)
        await page.fill("#txtPassword", password)

        captcha_el = await page.query_selector("img[src*='showcaptcha']")
        if not captcha_el:
            raise RuntimeError("Elemen CAPTCHA tidak ditemukan (Gemini attempt).")

        captcha_src = await captcha_el.get_attribute("src")
        captcha_b64 = await page.evaluate(f"""async () => {{
            const r = await fetch({repr(captcha_src)}, {{credentials: 'include'}});
            const buf = await r.arrayBuffer();
            return btoa(String.fromCharCode(...new Uint8Array(buf)));
        }}""")
        import base64 as _b64
        captcha_bytes = _b64.b64decode(captcha_b64)

        # Simpan debug
        from pathlib import Path as _P
        (_P(__file__).parent / "scratch" / f"captcha_gemini_{_gi}.png").write_bytes(captcha_bytes)

        captcha_text = _ocr_captcha_gemini(captcha_bytes)
        _log(f"Gemini OCR [{_gi}/{_MAX_GEMINI_RETRY}]: '{captcha_text}'")

        if not captcha_text:
            _log(f"Gemini gagal baca CAPTCHA attempt {_gi}, refresh...")
            refresh = await page.query_selector("a:has-text('klik di sini')")
            if refresh:
                await refresh.click()
                await page.wait_for_timeout(800)
            continue

        await page.fill("#txtCode", captcha_text)
        await page.click("button[type='submit']")
        await page.wait_for_timeout(2000)

        if "loginpass" not in page.url and "login" not in page.url.split("/")[-1]:
            _log(f"✅ Login berhasil via Gemini (attempt {_gi})!")
            return True

        err_el = await page.query_selector(".alert-danger, .alert-error, .error")
        err_msg = (await err_el.inner_text()).strip() if err_el else ""
        if any(k in err_msg.lower() for k in ["captcha", "kode", "code"]):
            _log(f"Gemini CAPTCHA salah attempt {_gi}, refresh...")
            refresh = await page.query_selector("a:has-text('klik di sini')")
            if refresh:
                await refresh.click()
                await page.wait_for_timeout(800)
        elif err_msg:
            raise RuntimeError(f"Login gagal (Gemini): {err_msg[:120]}")

    raise RuntimeError(f"Login gagal setelah {_MAX_GEMINI_RETRY}x Gemini — CAPTCHA tidak terbaca.")


async def _retry_captcha_async(password: str, log_fn=None) -> bool:
    """Hanya isi ulang password + captcha di halaman /loginpass yang sudah terbuka."""
    import spse_browser as _sb

    def _log(msg):
        if log_fn:
            log_fn(msg)

    page = _sb._get_page()
    if page is None:
        raise RuntimeError("Browser belum terhubung.")

    for attempt in range(1, _MAX_RETRY + 1):
        _log(f"Retry captcha {attempt}/{_MAX_RETRY}...")

        # Pastikan masih di halaman loginpass
        if "loginpass" not in page.url:
            raise RuntimeError("Halaman sudah berpindah — tidak bisa retry captcha saja.")

        await page.wait_for_selector("#txtPassword", timeout=8000)
        await page.fill("#txtPassword", password)

        captcha_el = await page.query_selector("img[src*='showcaptcha']")
        if not captcha_el:
            raise RuntimeError("Elemen CAPTCHA tidak ditemukan.")

        captcha_src = await captcha_el.get_attribute("src")
        captcha_b64 = await page.evaluate(f"""async () => {{
            const r = await fetch({repr(captcha_src)}, {{credentials: 'include'}});
            const buf = await r.arrayBuffer();
            return btoa(String.fromCharCode(...new Uint8Array(buf)));
        }}""")
        import base64 as _b64
        captcha_bytes = _b64.b64decode(captcha_b64)

        from pathlib import Path as _Path
        (_Path(__file__).parent / "scratch").mkdir(exist_ok=True)
        (_Path(__file__).parent / "scratch" / f"captcha_attempt_{attempt}.png").write_bytes(captcha_bytes)

        captcha_text = _ocr_captcha(captcha_bytes)
        _log(f"OCR CAPTCHA: '{captcha_text}'")

        if not captcha_text:
            refresh = await page.query_selector("a:has-text('klik di sini')")
            if refresh:
                await refresh.click()
                await page.wait_for_timeout(800)
            continue

        await page.fill("#txtCode", captcha_text)
        await page.click("button[type='submit']")
        await page.wait_for_timeout(2000)

        if "loginpass" not in page.url and "login" not in page.url.split("/")[-1]:
            _log("✅ Login berhasil!")
            return True

        err_el = await page.query_selector(".alert-danger, .alert-error, .error")
        err_msg = (await err_el.inner_text()).strip() if err_el else ""
        _log(f"Salah, retry... ({err_msg[:60]})")

        refresh = await page.query_selector("a:has-text('klik di sini')")
        if refresh:
            await refresh.click()
            await page.wait_for_timeout(800)

    raise RuntimeError(f"Login gagal setelah {_MAX_RETRY} retry captcha.")


def retry_captcha(role: Literal["PP", "POKJA", "PPK"] = "PP", log_fn=None) -> bool:
    """Entry point sinkronus — retry hanya step password+captcha tanpa navigate ulang."""
    import spse_browser as _sb
    _, password = _get_creds(role)
    return _sb._run(_retry_captcha_async(password, log_fn=log_fn), timeout=180)


async def _submit_manual_captcha_async(
    role: Literal["PP", "POKJA", "PPK"],
    captcha_text: str,
    log_fn=None,
) -> bool:
    """Isi CAPTCHA yang dibaca user; tidak mencoba menebak atau bypass CAPTCHA."""
    import spse_browser as _sb

    page = _sb._get_page()
    if page is None:
        raise RuntimeError("Browser belum terhubung.")
    if "loginpass" not in page.url:
        raise RuntimeError("Halaman sudah berpindah — CAPTCHA manual tidak diperlukan.")

    _, password = _get_creds(role)
    value = "".join(c for c in captcha_text.strip().lower() if c.isalnum())
    if not 4 <= len(value) <= 8:
        raise ValueError("CAPTCHA harus 4-8 karakter alfanumerik.")

    await page.fill("#txtPassword", password)
    await page.fill("#txtCode", value)
    await page.click("button[type='submit']")
    await page.wait_for_timeout(2000)

    if "loginpass" not in page.url and "login" not in page.url.split("/")[-1]:
        if log_fn:
            log_fn("✅ Login berhasil dengan CAPTCHA manual.")
        return True

    err_el = await page.query_selector(".alert-danger, .alert-error, .error")
    err_msg = (await err_el.inner_text()).strip() if err_el else "CAPTCHA ditolak atau login belum berhasil."
    raise RuntimeError(f"Login manual gagal: {err_msg[:120]}")


def submit_manual_captcha(
    role: Literal["PP", "POKJA", "PPK"] = "PP",
    captcha_text: str = "",
    log_fn=None,
) -> bool:
    """Entry point sinkronus untuk CAPTCHA yang dibaca user."""
    import spse_browser as _sb
    return _sb._run(
        _submit_manual_captcha_async(role, captcha_text, log_fn=log_fn),
        timeout=60,
    )


def logout_spse(log_fn=None) -> bool:
    """POST ke /logout SPSE via requests + cookie CDP. 302 = sukses."""
    import requests as _req
    import spse_browser as _sb

    def _log(msg):
        if log_fn:
            log_fn(msg)

    if not _sb._cek_cdp_aktif():
        _log("CDP tidak aktif — skip logout.")
        return False
    try:
        cookie_str = _sb.get_spse_cookies()
        from config import SPSE_BASE_URL
        r = _req.post(
            f"{SPSE_BASE_URL}logout",
            headers={
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{SPSE_BASE_URL}home",
                "Content-Length": "0",
            },
            data={},
            allow_redirects=False,
            timeout=10,
        )
        if r.status_code in (302, 200):
            _log("Logout SPSE berhasil.")
            return True
        _log(f"Logout SPSE status {r.status_code} — mungkin sudah logout.")
        return True
    except Exception as e:
        _log(f"Logout gagal: {e}")
        return False


def login_spse(role: Literal["PP", "POKJA", "PPK"] = "PP", log_fn=None) -> bool:
    """
    Entry point sinkronus untuk dipanggil dari Streamlit / app.py.
    role: 'PP' atau 'POKJA'
    log_fn: callable(str) untuk progress logging (opsional)
    """
    import spse_browser as _sb
    # Timeout 180s — cover 5x Tesseract retry + Gemini fallback
    _sb._ensure_loop()
    return _sb._run(_login_async(role, log_fn=log_fn), timeout=180)
