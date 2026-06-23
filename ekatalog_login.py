"""E-Katalog Login Helper — auto-isi email+password Inaproc via CDP."""
import os
import asyncio
import json
import time
from playwright.async_api import async_playwright

_LOGIN_URL = (
    "https://daftar-akun.inaproc.id/id/login"
    "?callbackUrl=https%3A%2F%2Fkatalog.inaproc.id%2Fauth%2Fsignin%2F"
)
_SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_inaproc_session.json")
_SESSION_TTL = 3600 * 8  # 8 jam


def _baca_credentials() -> tuple[str, str]:
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret_spse.env")
    env = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env.get("INAPROC_EMAIL", ""), env.get("INAPROC_PASSWORD", "")


def load_session() -> dict | None:
    """Load cookies dari file jika belum expired."""
    if not os.path.exists(_SESSION_FILE):
        return None
    try:
        with open(_SESSION_FILE) as f:
            data = json.load(f)
        if data.get("saved_at", 0) + _SESSION_TTL < time.time():
            return None
        return data.get("cookies")
    except Exception:
        return None


def save_session(cookies: dict):
    with open(_SESSION_FILE, "w") as f:
        json.dump({"cookies": cookies, "saved_at": time.time()}, f)


def clear_session():
    if os.path.exists(_SESSION_FILE):
        os.remove(_SESSION_FILE)


def ambil_cookies_cdp() -> dict:
    """Ambil cookies inaproc dari semua domain terkait via CDP."""
    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
            ctx = browser.contexts[0] if browser.contexts else None
            if ctx is None:
                return {}
            cookies = {}
            for domain in ["https://katalog.inaproc.id", "https://daftar-akun.inaproc.id", "https://login-akun.inaproc.id"]:
                for c in await ctx.cookies(domain):
                    cookies[c["name"]] = c["value"]
            return cookies
    return asyncio.run(_run())


def buka_dan_isi_login() -> str:
    """
    Buka tab login Inaproc di Brave CDP, auto-isi email+password.
    Return: pesan status untuk ditampilkan ke user.
    Jika reCAPTCHA muncul, user harus centang manual lalu klik Masuk.
    """
    email, password = _baca_credentials()
    if not email or not password:
        return "INAPROC_EMAIL atau INAPROC_PASSWORD belum diisi di secret_spse.env"

    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
            ctx = browser.contexts[0]

            # Tutup tab inaproc lama yang mungkin stuck
            for p in ctx.pages:
                if any(d in p.url for d in ["daftar-akun.inaproc.id", "login-akun.inaproc.id"]):
                    await p.close()

            page = await ctx.new_page()
            await page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)

            # Step 1: isi email + submit
            email_inp = await page.query_selector("input[type='text']")
            if not email_inp:
                return "Form email tidak ditemukan di halaman login"
            await email_inp.fill(email)
            await asyncio.sleep(0.5)
            btn = await page.query_selector("button[type='submit']")
            if btn:
                await btn.click()
                await asyncio.sleep(4)

            # Step 2: isi password jika sudah redirect
            if "login-akun.inaproc.id" in page.url:
                pass_inp = await page.query_selector("input[type='password']")
                if pass_inp:
                    await pass_inp.fill(password)
                    await asyncio.sleep(0.5)
                    # Cek reCAPTCHA
                    recaptcha = await page.query_selector("iframe[src*='recaptcha']")
                    if recaptcha:
                        return "captcha"  # sinyal ke caller bahwa perlu aksi manual
                    # Tidak ada reCAPTCHA — langsung submit
                    btn2 = await page.query_selector("button[type='submit']")
                    if btn2:
                        await btn2.click()
                        await asyncio.sleep(5)
                        if "katalog.inaproc.id" in page.url:
                            return "ok"
                        return f"Login gagal, URL: {page.url}"
            return f"Redirect tidak sesuai: {page.url}"

    return asyncio.run(_run())
