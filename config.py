"""Konfigurasi Asisten Pokja — SPSE Automation.

Kode boleh berada di clone lokal/GitHub, sedangkan dokumen tetap berada di
Google Drive. Semua state yang sering berubah dipisahkan ke disk lokal agar
Google Drive tidak mencoba menyinkronkan database browser, cache, dan lock.
"""

import os
import re
import pathlib

# === Paths ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.dirname(BASE_DIR)
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local"))

# Source code and Python runtime are per-computer; only documents use Drive.
V19_ROOT = os.path.normpath(
    os.environ.get("POKJA_V19_ROOT", os.path.join(CODE_ROOT, "procurement_core"))
)
POKJA_PYTHON = os.path.normpath(
    os.environ.get(
        "POKJA_PYTHON",
        os.path.join(CODE_ROOT, "Runtime", "WPy64-313110", "python", "python.exe"),
    )
)

if not os.path.isfile(os.path.join(V19_ROOT, "setup_paket_baru.py")):
    raise RuntimeError(
        "Source procurement_core lokal tidak ditemukan. Set POKJA_V19_ROOT "
        "ke clone lokal di luar Google Drive."
    )
if not os.path.isfile(POKJA_PYTHON):
    raise RuntimeError(
        f"Python runtime lokal tidak ditemukan: {POKJA_PYTHON}. "
        "Set POKJA_PYTHON ke runtime per-PC."
    )


def _is_pokja_root(path: str) -> bool:
    """True jika path terlihat sebagai root dokumen POKJA yang tersync Drive."""
    return bool(path) and any(
        os.path.isdir(os.path.join(path, marker))
        for marker in (
            "@ Tender 2026",
            "@ Pejabat Pengadaan 2026",
            "memory",
        )
    )


def _discover_pokja_root() -> str:
    """Cari root dokumen per-PC tanpa mengikat kode ke drive letter tertentu."""
    configured = os.environ.get("POKJA_DRIVE_ROOT", "").strip().strip('"')
    candidates = [
        configured,
        # Laptop saat ini.
        r"D:\Dokumen\@ POKJA 2026",
        # PC kantor sesuai struktur Google Drive yang sudah dipakai.
        r"G:\Other computers\My Laptop\@ POKJA 2026",
        # Kompatibilitas setup lama (sering berupa junction ke Drive).
        r"C:\POKJA2026",
        os.path.dirname(BASE_DIR),
    ]
    for candidate in candidates:
        if _is_pokja_root(candidate):
            return os.path.normpath(candidate)
    raise RuntimeError(
        "Root dokumen POKJA tidak ditemukan. Set environment variable "
        "POKJA_DRIVE_ROOT ke folder '@ POKJA 2026' di Google Drive."
    )


POKJA_ROOT = _discover_pokja_root()

# Runtime lokal per komputer: tidak pernah diletakkan di repo/Google Drive.
RUNTIME_ROOT = os.path.normpath(
    os.environ.get(
        "POKJA_RUNTIME_ROOT",
        os.path.join(LOCALAPPDATA, "POKJA2026", "Asisten_Pokja"),
    )
)
DOWNLOAD_DIR = os.path.join(RUNTIME_ROOT, "downloads")
BROWSER_SESSION_DIR = os.path.join(RUNTIME_ROOT, "browser_session")
STATE_DIR = os.path.join(RUNTIME_ROOT, "state")
LOG_DIR = os.path.join(RUNTIME_ROOT, "logs")

# Secret canonical per-PC berada di LOCALAPPDATA. Folder repo hanya fallback
# migrasi; secret tidak pernah diletakkan di working tree Git.
SECRET_ROOT = os.path.normpath(
    os.environ.get(
        "POKJA_SECRET_ROOT",
        os.path.join(LOCALAPPDATA, "POKJA2026", "Secrets"),
    )
)
# Kredensial SPSE tetap terisolasi di profile user per-PC. Ini menjaga
# kompatibilitas workflow PC kantor/laptop tanpa mencampur credential SPSE
# dengan secret aplikasi canonical (mis. Supabase).
SPSE_SECRET_ROOT = os.path.normpath(
    os.environ.get(
        "POKJA_SPSE_SECRET_ROOT",
        os.path.join(LOCALAPPDATA, "POKJA2026", "Secrets"),
    )
)

for _runtime_dir in (RUNTIME_ROOT, DOWNLOAD_DIR, BROWSER_SESSION_DIR, STATE_DIR, LOG_DIR):
    os.makedirs(_runtime_dir, exist_ok=True)


def find_secret(filename: str) -> pathlib.Path:
    """Return lokasi secret lokal; jangan membaca secret dari Google Drive."""
    candidates = []
    if filename == "secret_spse.env":
        candidates.append(pathlib.Path(SPSE_SECRET_ROOT) / filename)
    candidates.extend(
        [
            pathlib.Path(SECRET_ROOT) / filename,
            pathlib.Path(LOCALAPPDATA) / "POKJA2026" / "Secrets" / filename,
            pathlib.Path(CODE_ROOT) / "Secrets" / filename,
            pathlib.Path(BASE_DIR) / filename,
            pathlib.Path(V19_ROOT) / filename,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return pathlib.Path(SECRET_ROOT) / filename

# === Tender Output Dir ===
TENDER_ROOT = os.path.join(POKJA_ROOT, "@ Tender 2026")
os.makedirs(TENDER_ROOT, exist_ok=True)

# === PL Output Dirs ===
OUTPUT_DIR_PL_JKK = os.path.join(POKJA_ROOT, "@ Pejabat Pengadaan 2026", "@ Pengadaan Langsung JKK")
OUTPUT_DIR_PL_PK  = os.path.join(POKJA_ROOT, "@ Pejabat Pengadaan 2026", "@ Pengadaan Langsung PK")

# === Apendo (opsional; path per-PC, jangan menunjuk Drive) ===
APENDO_EXE  = os.environ.get("POKJA_APENDO_EXE", "").strip().strip('"')
APENDO_CONFIG = os.environ.get("POKJA_APENDO_CONFIG", "").strip().strip('"')
PYTHON_SYS  = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\MSI\AppData\Local"), "Programs", "Python", "Python312", "python.exe")

# === SPSE ===
SPSE_BASE_URL = "https://spse.inaproc.id/tapinkab/"
KODE_LPSE = "266"

def sanitasi_nama_folder(nama: str) -> str:
    """Sanitasi nama folder/path: karakter Windows-illegal → '-', strip spasi tepi."""
    return re.sub(r'[/\\:*?"<>|]', "-", nama).strip()


import streamlit as st

@st.cache_resource
def sb():
    """Buat Supabase client. Baca env dari secret_supabase.env (V19 atau lokal)."""
    from supabase import create_client
    from dotenv import load_dotenv
    env_path = find_secret("secret_supabase.env")
    load_dotenv(env_path, override=True)
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().strip('"')
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip().strip('"')
    if not supabase_url or not supabase_key:
        raise RuntimeError(f"Secret Supabase tidak lengkap: {env_path}")
    return create_client(supabase_url, supabase_key)
