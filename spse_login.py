"""
spse_login.py — Auto-login SPSE via CDP + OCR CAPTCHA (pytesseract).

Security:
- Credentials dibaca dari secret_spse.env (gitignored), TIDAK pernah di-log/print.
- Tidak ada credential yang masuk ke session_state Streamlit.
- CAPTCHA hanya disimpan bila SPSE_LOGIN_DEBUG_CAPTCHA=1.
- Telemetry tidak menyimpan credential maupun isi CAPTCHA.
- Retry dibatasi; kalau gagal, raise RuntimeError (bukan expose password).
"""

from __future__ import annotations
import os
import re
import hashlib
import json
import time
import asyncio
import io
import logging
import shutil
import subprocess
import tempfile
import base64
import threading
from pathlib import Path
from typing import Literal
from config import (
    find_secret,
    SPSE_ROLE_FILE,
    SPSE_LOGIN_METRICS_PATH,
    ASISTEN_FIXED_ROLE,
)

# ============================================================
# Load credentials — SEKALI saat import, tidak di-cache di state
# ============================================================

_ENV_PATH = find_secret("secret_spse.env")
_ROLE_FILE = Path(SPSE_ROLE_FILE)
_METRICS_PATH = Path(SPSE_LOGIN_METRICS_PATH)
_TELEMETRY_LOCK = threading.Lock()
_CODEX_MODEL = "gpt-5.6-luna"
_CODEX_REASONING = "medium"
_CODEX_BIN = os.environ.get(
    "POKJA_CODEX_EXE",
    str(Path.home() / "AppData" / "Local" / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"),
)


def _cookie_fingerprint(cookie: str) -> str:
    """Hash SPSE_SESSION; nilai cookie tidak pernah disimpan."""
    session = next((p.split("=", 1)[1] for p in cookie.split("; ") if p.startswith("SPSE_SESSION=")), "")
    return hashlib.sha256(session.encode("utf-8")).hexdigest() if session else ""


def _role_from_text(text: str) -> str | None:
    """Deteksi role dari HTML/teks halaman authenticated."""
    value = (text or "").lower()
    if "pejabat pembuat komitmen" in value:
        return "PPK"
    if "pejabat pengadaan" in value:
        return "PP"
    if "kelompok kerja" in value or "pokja" in value:
        return "POKJA"
    return None


def _record_login_event(
    event: str,
    *,
    role: str = "",
    method: str = "",
    attempt: int = 0,
    status: str = "",
    elapsed_ms: int = 0,
    path: Path | None = None,
) -> None:
    """Append telemetry aman; tidak menerima credential atau isi CAPTCHA."""
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": str(event)[:40],
        "role": role if role in ("PP", "POKJA", "PPK") else "",
        "method": str(method)[:32],
        "attempt": max(0, int(attempt or 0)),
        "status": str(status)[:40],
        "elapsed_ms": max(0, int(elapsed_ms or 0)),
    }
    target = path or _METRICS_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with _TELEMETRY_LOCK, target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        logging.debug("Gagal menulis telemetry login", exc_info=True)


def remember_login_role(role: str) -> None:
    """Simpan role + fingerprint sesi agar cache role stale ditolak saat F5."""
    if ASISTEN_FIXED_ROLE and role != ASISTEN_FIXED_ROLE:
        raise ValueError(
            f"Instance ini dikunci untuk role {ASISTEN_FIXED_ROLE}, bukan {role}."
        )
    import spse_browser as _sb
    cookie = _sb.get_spse_cookies(force=True)
    if not cookie:
        return
    _ROLE_FILE.parent.mkdir(exist_ok=True)
    _ROLE_FILE.write_text(json.dumps({"role": role, "cookie_fp": _cookie_fingerprint(cookie)}), encoding="utf-8")


def get_spse_session_fingerprint(force: bool = False) -> str:
    """Kembalikan hash sesi SPSE aktif tanpa mengekspos nilai cookie."""
    import spse_browser as _sb

    return _cookie_fingerprint(_sb.get_spse_cookies(force=force))


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


def _assert_role_allowed(role: str) -> None:
    """Tolak login silang ketika app dijalankan sebagai instance tetap."""
    if ASISTEN_FIXED_ROLE and role != ASISTEN_FIXED_ROLE:
        raise ValueError(
            f"Instance ini dikunci untuk role {ASISTEN_FIXED_ROLE}, bukan {role}."
        )


def detect_login_role() -> str | None:
    """
    Ambil role login aktif dari cache yang dicocokkan dengan cookie sesi Brave.

    Login di app ini WAJIB via tombol (Launch & Auto-Login), yang menulis role ke file
    setelah login sukses. Fungsi ini hanya untuk memulihkan role saat Streamlit hot-reload
    (session_state hilang tapi browser + file cache masih ada). Cache teks lama ditolak.

    Return: "PP" | "POKJA" | "PPK" | None (kalau belum login / halaman masih di login).
    """
    import spse_browser as _sb

    def _is_login_page(url: str, text: str) -> bool:
        """Bedakan halaman publik/login dari tab authenticated yang belum memuat label role."""
        from urllib.parse import urlsplit

        normalized = " ".join((text or "").casefold().split())
        path = urlsplit(url or "").path.casefold()
        if any(marker in path for marker in ("/login", "/loginpass", "/logout")):
            return True
        # Halaman root publik SPSE memuat tombol LOGIN, sedangkan halaman
        # detail authenticated dapat tidak memuat nama role sama sekali.
        return bool(
            re.search(r"\blogin\b", normalized)
            or "nama pengguna" in normalized
            or "kata sandi" in normalized
        )

    def _is_known_authenticated_path(url: str) -> bool:
        """Route yang hanya berguna setelah user masuk sebagai panitia."""
        from urllib.parse import urlsplit

        path = urlsplit(url or "").path.casefold().rstrip("/")
        return any(
            marker in path
            for marker in (
                "/nontender/",
                "/lelang/",
                "/paketnontender",
                "/paketlelang",
                "/paketpanitia",
                "/dokumen/",
                "/jadwal/",
                "/peserta/",
                "/penjelasan/",
            )
        )

    def _has_authenticated_cdp_tab() -> bool:
        """Deteksi bukti sesi dari metadata CDP tanpa membuka Playwright.

        Recovery dipanggil saat startup Streamlit. ``connect_over_cdp`` dapat
        menggantung bila Brave sedang memulihkan banyak tab SPSE, padahal URL
        tab dan fingerprint cookie sudah cukup untuk memulihkan role cache.
        Validasi body tetap dipakai sebagai fallback bila bukti ringan ini
        tidak tersedia.
        """
        try:
            tabs = _sb._cdp_tabs(force=True)
        except Exception:
            return False
        from urllib.parse import urlsplit

        for tab in tabs or []:
            if str(tab.get("type") or "") != "page":
                continue
            parsed = urlsplit(str(tab.get("url") or ""))
            if parsed.netloc != "spse.inaproc.id":
                continue
            if _is_known_authenticated_path(parsed.path):
                return True
        return False

    def _detect_role_from_session(cookie: str) -> str | None:
        """Validasi role dari /home atau tab detail tanpa navigasi.

        Return tuple ``(role, authenticated_evidence)``. Evidence kedua
        penting: akun PPK sering mendapat 403 dari ``/home`` dan halaman detail
        tidak selalu menampilkan label role. Cache role hanya boleh dipakai
        bila ada evidence halaman authenticated, bukan sekadar cookie tersisa.
        """
        import requests
        from bs4 import BeautifulSoup
        authenticated = False
        try:
            from config import SPSE_BASE_URL
            response = requests.get(
                SPSE_BASE_URL.rstrip("/") + "/home",
                headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
                timeout=10,
                allow_redirects=True,
            )
            final_url = response.url.lower()
            if response.status_code == 200 and "loginpass" not in final_url:
                text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
                if not _sb._is_spse_access_error_text(text) and not _is_login_page(final_url, text):
                    authenticated = True
                    detected = _role_from_text(text)
                    if detected:
                        return detected, True

            # Pada akun PPK, route /home kadang 403 meski tab edit paket tetap
            # authenticated. Pastikan Playwright connect dulu, lalu inspect
            # semua tab berdasarkan URL; _get_page() bisa stale/root setelah
            # Brave restore. Tidak ada goto/navigasi di jalur recovery ini.
            try:
                if _sb._get_ctx() is None and _sb._get_page() is None:
                    _sb.buka_browser(navigate=False)
            except Exception:
                pass
            pages = []
            try:
                context = _sb._get_ctx()
                if context is not None:
                    pages = list(context.pages)
            except Exception:
                pages = []
            if not pages:
                page = _sb._get_page()
                pages = [page] if page is not None else []
            pages.sort(
                key=lambda item: 0 if _is_known_authenticated_path(
                    str(getattr(item, "url", "") or "")
                ) else 1
            )
            for page in pages:
                if page is None or page.is_closed():
                    continue
                page_url = str(getattr(page, "url", "") or "")
                if page_url and not _is_known_authenticated_path(page_url):
                    continue
                try:
                    body = _sb._run(
                        page.locator("body").inner_text(timeout=3000),
                        timeout=5,
                    )
                except Exception:
                    continue
                if (
                    not _sb._is_spse_access_error_text(body)
                    and not _is_login_page(page_url, body)
                    and (not page_url or _is_known_authenticated_path(page_url))
                ):
                    authenticated = True
                    detected = _role_from_text(body)
                    if detected:
                        return detected, True
        except Exception:
            pass
        return None, authenticated

    try:
        # Cache role hanya akselerator recovery, bukan syarat sesi valid.
        # Sesi yang login manual/tertinggal dari profil browser bisa tidak punya
        # last_role.txt, tetapi cookie + halaman authenticated tetap cukup untuk
        # mendeteksi role. Ini juga memperbaiki fresh-start setelah cache lokal
        # dibersihkan atau belum pernah dibuat.
        cookie = _sb.get_spse_cookies(force=True)
        current_fp = _cookie_fingerprint(cookie)
        if not current_fp:
            return None

        record = {}
        if _ROLE_FILE.exists():
            try:
                record = json.loads(_ROLE_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                record = {}

        cached_role = record.get("role")
        if cached_role not in ("PP", "POKJA", "PPK", "E-Katalog"):
            cached_role = None

        cache_matches_session = record.get("cookie_fp") == current_fp
        # Fast path startup: URL authenticated dari endpoint CDP + fingerprint
        # cookie yang sama cukup untuk memakai role cache. Jangan memanggil
        # Playwright di sini; Brave dengan banyak tab restore bisa blocking.
        if (
            cached_role
            and (not ASISTEN_FIXED_ROLE or cached_role == ASISTEN_FIXED_ROLE)
            and cache_matches_session
            and _has_authenticated_cdp_tab()
        ):
            return cached_role
        detected, authenticated = _detect_role_from_session(cookie)
        if detected:
            if ASISTEN_FIXED_ROLE and detected != ASISTEN_FIXED_ROLE:
                return None
            if not cache_matches_session or detected != cached_role:
                _ROLE_FILE.parent.mkdir(parents=True, exist_ok=True)
                _ROLE_FILE.write_text(
                    json.dumps({"role": detected, "cookie_fp": current_fp}),
                    encoding="utf-8",
                )
            return detected
        # Jangan menganggap sesi putus hanya karena label role tidak ada di
        # halaman detail. Gunakan cache hanya jika fingerprint cocok DAN body
        # tab menunjukkan route authenticated; root publik/login tidak lolos.
        if (
            cached_role
            and (not ASISTEN_FIXED_ROLE or cached_role == ASISTEN_FIXED_ROLE)
            and cache_matches_session
            and authenticated
        ):
            return cached_role
    except Exception:
        pass
    return None


# ============================================================
# OCR CAPTCHA
# ============================================================

def _normalize_captcha_png(img_bytes: bytes) -> bytes:
    """Composite PNG transparan ke putih agar vision model tidak melihat gambar hitam."""
    from PIL import Image

    source = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    white = Image.new("RGBA", source.size, (255, 255, 255, 255))
    white.alpha_composite(source)
    output = io.BytesIO()
    white.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def _rank_captcha_candidates(results: list[str]) -> list[str]:
    """Urutkan kandidat berdasarkan voting; panjang 6 menjadi tie-breaker."""
    from collections import Counter

    cleaned = [
        "".join(c for c in str(value).lower() if c.isalnum())
        for value in results
    ]
    freq = Counter(value for value in cleaned if 4 <= len(value) <= 8)
    return sorted(freq, key=lambda value: (-freq[value], abs(len(value) - 6), value))


def _ocr_captcha_candidates(img_bytes: bytes) -> list[str]:
    """
    OCR teks CAPTCHA dari bytes gambar.
    Multi-strategy: beberapa threshold, grid removal, scale, dan PSM.
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

    cleaned = _clean(work)

    whitelist = "abcdefghijklmnopqrstuvwxyz0123456789"
    results: list[str] = []

    # Grid SPSE berada pada baris/kolom penuh tiap 6 px. Hilangkan garis
    # proyeksi dominan lalu close kembali stroke huruf yang terpotong.
    raw_binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)[1]
    if raw_binary.mean() > 127:
        raw_binary = 255 - raw_binary
    gridless = raw_binary.copy()
    rows = np.where((gridless > 0).sum(axis=1) > gridless.shape[1] * 0.75)[0]
    cols = np.where((gridless > 0).sum(axis=0) > gridless.shape[0] * 0.75)[0]
    gridless[rows, :] = 0
    gridless[:, cols] = 0
    gridless = cv2.morphologyEx(
        gridless,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), np.uint8),
    )
    gridless = 255 - cv2.resize(
        gridless,
        None,
        fx=4,
        fy=4,
        interpolation=cv2.INTER_CUBIC,
    )

    variants = [
        cleaned,
        work4,
        gridless,
    ]

    for processed in variants:
        for psm in [7, 8]:
            cfg = f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
            try:
                txt = pytesseract.image_to_string(processed, config=cfg).strip()
                txt = "".join(c for c in txt.lower() if c.isalnum())
                if 4 <= len(txt) <= 8:
                    results.append(txt)
            except Exception:
                pass
    return _rank_captcha_candidates(results)[:5]


def _ocr_captcha(img_bytes: bytes) -> str:
    candidates = _ocr_captcha_candidates(img_bytes)
    return candidates[0] if candidates else ""


def _parse_luna_verdict(output: str, candidates: list[str]) -> str:
    """Terima hanya satu kandidat persis; teks bebas/refusal dianggap gagal."""
    normalized = [value.lower() for value in candidates]
    lines = [line.strip().lower() for line in (output or "").splitlines() if line.strip()]
    if len(normalized) == 1 and lines and lines[-1] == "match":
        return normalized[0]
    return lines[-1] if lines and lines[-1] in normalized else ""


def _classify_luna_failure(returncode: int, stderr: str) -> str:
    """Bedakan NO_MATCH model dari kegagalan proses/config Codex."""
    if returncode == 0:
        return "no_match"
    message = (stderr or "").lower()
    if "config.toml" in message and (
        "duplicate key" in message or "error loading" in message
    ):
        return "config_error"
    return f"cli_exit_{max(1, min(abs(int(returncode)), 999))}"


def _verify_captcha_luna(
    img_bytes: bytes,
    candidates: list[str],
    *,
    timeout: int = 30,
    log_fn=None,
) -> str:
    """Minta GPT-5.6 Luna memilih kandidat OCR; refusal/error selalu fail-open."""
    candidates = _rank_captcha_candidates(candidates)[:5]
    if not candidates:
        return ""

    codex_bin = _CODEX_BIN if Path(_CODEX_BIN).exists() else shutil.which("codex")
    if not codex_bin:
        if log_fn:
            log_fn("Luna verifier tidak tersedia; lanjut Gemini.")
        return ""

    temp_path = ""
    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(_normalize_captcha_png(img_bytes))
            temp_path = handle.name

        prompt = (
            "Verify which OCR candidate exactly matches the CAPTCHA image. "
            f"Candidates: {', '.join(candidates)}. "
            "Return only one candidate exactly as listed, or NO_MATCH. "
            "Do not return any explanation."
        )
        cmd = [
            str(codex_bin),
            "exec",
            "--ephemeral",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-C",
            tempfile.gettempdir(),
            "-m",
            _CODEX_MODEL,
            "-c",
            f"model_reasoning_effort={_CODEX_REASONING}",
            "--image",
            temp_path,
            "--",
            prompt,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        verdict = _parse_luna_verdict(result.stdout, candidates) if result.returncode == 0 else ""
        status = (
            "matched"
            if verdict
            else _classify_luna_failure(result.returncode, result.stderr)
        )
        if log_fn:
            if verdict:
                log_fn("Luna verifier: kandidat cocok.")
            elif status == "no_match":
                log_fn("Luna verifier: tidak cocok; lanjut Gemini.")
            elif status == "config_error":
                log_fn("Luna verifier gagal karena konfigurasi Codex; lanjut Gemini.")
            else:
                log_fn(f"Luna verifier gagal dijalankan ({status}); lanjut Gemini.")
        _record_login_event(
            "captcha_verify",
            method="luna",
            status=status,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return verdict
    except (OSError, subprocess.SubprocessError) as exc:
        if log_fn:
            log_fn(f"Luna verifier dilewati ({type(exc).__name__}); lanjut Gemini.")
        _record_login_event(
            "captcha_verify",
            method="luna",
            status=type(exc).__name__,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return ""
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _ocr_captcha_gemini(img_bytes: bytes, log_fn=None) -> str:
    """
    Fallback OCR via Gemini Vision API.
    Dipanggil setelah kandidat Tesseract tidak disahkan Luna.
    Return string hasil OCR (lowercase, alfanumerik only), atau '' kalau gagal.
    """
    # Load API key dari secret_spse.env
    env_path = _ENV_PATH
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
                types.Part.from_bytes(data=_normalize_captcha_png(img_bytes), mime_type="image/png"),
                prompt,
            ],
        )
        raw = response.text.strip().lower()
        result = "".join(c for c in raw if c.isalnum())
        # Sanity check panjang
        if 4 <= len(result) <= 8:
            return result
        return ""
    except Exception as exc:
        if log_fn:
            log_fn(f"Gemini OCR gagal ({type(exc).__name__}).")
        return ""


# ============================================================
# Auto-login via CDP (Playwright async)
# ============================================================

_LOGIN_URL = "https://spse.inaproc.id/tapinkab/loginpass"
_MAX_RETRY = 5
_LOGIN_TIMEOUT_SECONDS = 420


async def _probe_authenticated_role(page) -> str | None:
    """Validasi sesi lewat /home dan kembalikan role aktual."""
    import spse_browser as _sb
    from config import SPSE_BASE_URL

    try:
        response = await page.context.request.get(
            SPSE_BASE_URL.rstrip("/") + "/home",
            timeout=10000,
            fail_on_status_code=False,
        )
        if response.status == 200:
            text = await response.text()
            if not _sb._is_spse_access_error_text(text) and "loginpass" not in response.url.lower():
                detected = _role_from_text(text)
                if detected:
                    return detected
    except Exception:
        pass

    # Fallback DOM untuk redirect sukses yang belum stabil di endpoint /home.
    try:
        if "loginpass" not in page.url.lower():
            body = await page.locator("body").inner_text(timeout=3000)
            if not _sb._is_spse_access_error_text(body):
                return _role_from_text(body)
    except Exception:
        pass
    return None


async def _wait_for_authenticated_role(
    page,
    *,
    timeout_ms: int = 8000,
    interval_ms: int = 500,
) -> str | None:
    """Poll sesi karena redirect/login SPSE kadang lebih cepat dari propagasi role."""
    attempts = max(1, (max(0, timeout_ms) + max(1, interval_ms) - 1) // max(1, interval_ms))
    for index in range(attempts):
        detected = await _probe_authenticated_role(page)
        if detected:
            return detected
        if index + 1 < attempts:
            await page.wait_for_timeout(interval_ms)
    return None


async def _open_loginpass(page, username: str, log_fn=None) -> None:
    """Buka ulang form password+CAPTCHA dari beranda SPSE."""
    import spse_browser as _sb
    from config import SPSE_BASE_URL

    def _log(message: str) -> None:
        if log_fn:
            log_fn(message)

    _log("Membuka halaman SPSE...")
    await page.goto(SPSE_BASE_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(500)

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
        try:
            if _sb._get_ctx() is not None:
                await _sb._get_ctx().clear_cookies(domain="spse.inaproc.id")
                _log("Cookie sesi lama dibersihkan.")
        except Exception as exc:
            _log(f"(clear cookie dilewati: {type(exc).__name__})")
        await page.goto(SPSE_BASE_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(500)

    _log("Klik tombol Login...")
    login_el = await page.query_selector("#login")
    if not login_el:
        for retry in range(4):
            _log(f"#login belum ada — reload home (percobaan {retry + 1}/4)...")
            await page.wait_for_timeout(1500)
            await page.goto(SPSE_BASE_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(500)
            login_el = await page.query_selector("#login")
            if login_el:
                break
    if not login_el:
        debug_path = Path(__file__).parent / "scratch" / "debug_nologin.png"
        debug_path.parent.mkdir(exist_ok=True)
        await page.screenshot(path=str(debug_path))
        page_text = await page.evaluate("() => document.body?.innerText?.slice(0,200) || ''")
        raise RuntimeError(f"Tombol #login tidak ditemukan — halaman: {page.url}\n{page_text}")
    await page.evaluate("document.querySelector('#login').click()")

    modal_visible = False
    for _ in range(10):
        await page.wait_for_timeout(500)
        modal_visible = await page.evaluate("""() => {
            var m = document.querySelector('.modal.show');
            return m !== null && m.offsetParent !== null;
        }""")
        if modal_visible:
            break
    _log(f"Modal visible: {modal_visible}")

    _log("Pilih Non Penyedia...")
    await page.wait_for_timeout(800)
    clicked = await page.evaluate("""() => {
        var btns = Array.from(document.querySelectorAll('button'));
        var btn = btns.find(b => (b.innerText || b.textContent || '').trim().toUpperCase().includes('NON PENYEDIA'));
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    if not clicked:
        debug_path = Path(__file__).parent / "scratch" / "debug_nonpenyedia.png"
        await page.screenshot(path=str(debug_path))
        raise RuntimeError("Tombol NON PENYEDIA tidak ditemukan — lihat scratch/debug_nonpenyedia.png")
    await page.wait_for_load_state("domcontentloaded")
    _log("Isi User ID...")
    await page.wait_for_selector("input[name='txtUserId']", timeout=8000)
    await page.fill("input[name='txtUserId']", username)
    await page.click("button[type='submit']")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_selector("#txtPassword", timeout=10000)
    _log("Halaman password + CAPTCHA terbuka.")


async def _ensure_loginpass(
    page,
    username: str,
    expected_role: str,
    log_fn=None,
) -> str | None:
    """Pastikan retry berada di form login; pulihkan redirect beranda SPSE."""
    if "loginpass" in page.url.lower():
        try:
            await page.wait_for_selector("#txtPassword", timeout=3000)
            return None
        except Exception:
            pass

    detected = await _probe_authenticated_role(page)
    if detected:
        return detected
    if log_fn:
        log_fn("SPSE kembali ke beranda tanpa sesi; membuka ulang form login.")
    await _open_loginpass(page, username, log_fn=log_fn)
    return None


async def _fetch_captcha_bytes(page) -> bytes:
    captcha_el = await page.query_selector("img[src*='showcaptcha']")
    if not captcha_el:
        raise RuntimeError("Elemen CAPTCHA tidak ditemukan di halaman login.")
    await page.wait_for_function(
        "(el) => el.complete && el.naturalWidth > 0 && el.naturalHeight > 0",
        arg=captcha_el,
        timeout=5000,
    )
    captcha_b64 = await captcha_el.evaluate(
        """el => {
            const canvas = document.createElement('canvas');
            canvas.width = el.naturalWidth;
            canvas.height = el.naturalHeight;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(el, 0, 0);
            return canvas.toDataURL('image/png').split(',', 2)[1];
        }"""
    )
    return base64.b64decode(captcha_b64)


async def _refresh_captcha(page) -> None:
    refresh = await page.query_selector("a:has-text('klik di sini')")
    if refresh:
        await refresh.click()
    else:
        await page.reload(wait_until="domcontentloaded")
    await page.wait_for_timeout(800)


async def _read_login_error(page) -> str:
    err_el = await page.query_selector(".alert-danger, .alert-error, .error")
    return (await err_el.inner_text()).strip() if err_el else ""


def _save_debug_captcha(img_bytes: bytes, filename: str) -> None:
    """Simpan CAPTCHA hanya saat debug eksplisit; default tidak meninggalkan artefak."""
    if os.environ.get("SPSE_LOGIN_DEBUG_CAPTCHA") != "1":
        return
    path = Path(__file__).parent / "scratch" / filename
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(img_bytes)


async def _solve_captcha(img_bytes: bytes, role: str, attempt: int, log_fn=None) -> tuple[str, str]:
    started = time.perf_counter()
    candidates = await asyncio.to_thread(_ocr_captcha_candidates, img_bytes)
    if log_fn:
        log_fn(f"Tesseract menghasilkan {len(candidates)} kandidat.")

    verified = await asyncio.to_thread(
        _verify_captcha_luna,
        img_bytes,
        candidates,
        timeout=30,
        log_fn=log_fn,
    )
    if verified:
        method = "tesseract+luna"
        _record_login_event(
            "captcha_solve",
            role=role,
            method=method,
            attempt=attempt,
            status="candidate_verified",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return verified, method

    gemini = await asyncio.to_thread(_ocr_captcha_gemini, img_bytes, log_fn)
    if gemini:
        method = "gemini-2.5-flash-lite"
        _record_login_event(
            "captcha_solve",
            role=role,
            method=method,
            attempt=attempt,
            status="candidate_generated",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return gemini, method

    # Semua model gagal: satu kandidat voting lokal masih lebih baik daripada
    # membuang attempt tanpa submit. Server tetap menjadi validator akhir.
    fallback = candidates[0] if candidates else ""
    method = "tesseract-unverified" if fallback else "none"
    _record_login_event(
        "captcha_solve",
        role=role,
        method=method,
        attempt=attempt,
        status="fallback" if fallback else "empty",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    return fallback, method


async def _run_captcha_attempts(
    page,
    username: str,
    password: str,
    role: str,
    log_fn=None,
) -> bool:
    """Pipeline CAPTCHA tunggal untuk login awal dan tombol retry."""
    def _log(message: str) -> None:
        if log_fn:
            log_fn(message)

    for attempt in range(1, _MAX_RETRY + 1):
        detected = await _ensure_loginpass(
            page,
            username,
            role,
            log_fn=_log,
        )
        if detected == role:
            return True
        if detected and detected != role:
            raise RuntimeError(f"Login masuk sebagai {detected}, bukan {role}.")

        _log(f"Percobaan login {attempt}/{_MAX_RETRY}...")
        await page.wait_for_selector("#txtPassword", timeout=10000)
        await page.fill("#txtPassword", password)
        captcha_bytes = await _fetch_captcha_bytes(page)
        _save_debug_captcha(captcha_bytes, f"captcha_attempt_{attempt}.png")

        captcha_text, method = await _solve_captcha(
            captcha_bytes,
            role,
            attempt,
            log_fn=_log,
        )
        if not captcha_text:
            _log("Semua OCR gagal membaca CAPTCHA; refresh.")
            await _refresh_captcha(page)
            continue

        await page.fill("#txtCode", captcha_text)
        await page.click("button[type='submit']")
        await page.wait_for_timeout(2000)

        detected = await _wait_for_authenticated_role(page)
        if detected == role:
            _record_login_event(
                "captcha_submit",
                role=role,
                method=method,
                attempt=attempt,
                status="success",
            )
            _log(f"✅ Login dan role {role} tervalidasi ({method}).")
            return True
        if detected and detected != role:
            _record_login_event(
                "captcha_submit",
                role=role,
                method=method,
                attempt=attempt,
                status="wrong_role",
            )
            raise RuntimeError(f"Login masuk sebagai {detected}, bukan {role}.")

        err_msg = await _read_login_error(page)
        page_state = "loginpass" if "loginpass" in page.url.lower() else "redirect"
        _record_login_event(
            "captcha_submit",
            role=role,
            method=method,
            attempt=attempt,
            status="rejected" if err_msg else f"{page_state}_no_session",
        )
        if any(key in err_msg.lower() for key in ("captcha", "kode", "code")):
            _log(f"CAPTCHA ditolak; refresh ({method}).")
            await _refresh_captcha(page)
        elif err_msg:
            raise RuntimeError(f"Login gagal: {err_msg[:120]}")
        elif page_state == "redirect":
            _log("SPSE kembali ke beranda tanpa sesi; retry akan membuka ulang form login.")
        else:
            _log("Sesi belum tervalidasi; refresh CAPTCHA.")
            await _refresh_captcha(page)

    raise RuntimeError(f"Login gagal setelah {_MAX_RETRY} percobaan CAPTCHA.")


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

    _log(f"Menghubungkan ke Brave CDP (port {_sb.CDP_PORT})...")

    # Reuse page dari spse_browser (sudah di-init via buka_browser sebelum login)
    if _sb._get_page() is None:
        raise RuntimeError("spse_browser belum di-init — panggil buka_browser() dulu.")
    page = _sb._get_page()

    # Session-first: hindari logout/CAPTCHA bila sesi dan role sudah benar.
    existing_role = await _probe_authenticated_role(page)
    if existing_role is None:
        await page.wait_for_timeout(500)
        existing_role = await _probe_authenticated_role(page)
    if existing_role == role:
        _log(f"✅ Sesi {role} masih valid; login ulang dilewati.")
        _record_login_event("session_reuse", role=role, status="success")
        return True
    if existing_role:
        _log(f"Sesi {existing_role} aktif; ganti ke {role}.")
    else:
        # Cookie invalid sering membuat /home 403 dan tombol #login hilang.
        try:
            await page.context.clear_cookies(name="SPSE_SESSION")
            _log("Cookie SPSE invalid/kedaluwarsa dibersihkan.")
        except Exception as exc:
            _log(f"(pembersihan cookie dilewati: {type(exc).__name__})")

    username, password = _get_creds(role)
    await _open_loginpass(page, username, log_fn=log_fn)
    return await _run_captcha_attempts(
        page,
        username,
        password,
        role,
        log_fn=log_fn,
    )


async def _retry_captcha_async(
    username: str,
    password: str,
    role: Literal["PP", "POKJA", "PPK"],
    log_fn=None,
) -> bool:
    """Ulangi pipeline Tesseract → Luna → Gemini pada halaman loginpass."""
    import spse_browser as _sb

    page = _sb._get_page()
    if page is None:
        raise RuntimeError("Browser belum terhubung.")
    return await _run_captcha_attempts(
        page,
        username,
        password,
        role,
        log_fn=log_fn,
    )


def retry_captcha(role: Literal["PP", "POKJA", "PPK"] = "PP", log_fn=None) -> bool:
    """Entry point sinkronus — retry hanya step password+captcha tanpa navigate ulang."""
    import spse_browser as _sb
    _assert_role_allowed(role)
    username, password = _get_creds(role)
    return _sb._run(
        _retry_captcha_async(username, password, role, log_fn=log_fn),
        timeout=_LOGIN_TIMEOUT_SECONDS,
    )


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

    detected = await _probe_authenticated_role(page)
    if detected == role:
        if log_fn:
            log_fn(f"✅ Login manual dan role {role} tervalidasi.")
        _record_login_event("captcha_manual", role=role, method="manual", status="success")
        return True
    if detected and detected != role:
        raise RuntimeError(f"Login manual masuk sebagai {detected}, bukan {role}.")

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
    _assert_role_allowed(role)
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
    _assert_role_allowed(role)
    # Cover Tesseract + Luna verifier + Gemini fallback pada beberapa attempt.
    _sb._ensure_loop()
    return _sb._run(
        _login_async(role, log_fn=log_fn),
        timeout=_LOGIN_TIMEOUT_SECONDS,
    )
