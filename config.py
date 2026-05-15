"""Konfigurasi Asisten Pokja — SPSE Automation."""

import os
import re
import pathlib

# === Paths ===
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
POKJA_ROOT = os.path.dirname(BASE_DIR)  # D:\Dokumen\@ POKJA 2026
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
BROWSER_SESSION_DIR = os.path.join(BASE_DIR, ".browser_session")

# === PL Output Dirs ===
OUTPUT_DIR_PL_JKK = os.path.join(POKJA_ROOT, "@ Pejabat Pengadaan 2026", "@ Pengadaan Langsung JKK")
OUTPUT_DIR_PL_PK  = os.path.join(POKJA_ROOT, "@ Pejabat Pengadaan 2026", "@ Pengadaan Langsung PK")

# === Apendo ===
APENDO_EXE  = r"D:\Dokumen\3 @ POKJA 2025\@ POKJA 2025\2. Pokja 009\Apendo v5.1.5u20220905(x64)\release\Apendo.exe"
PYTHON_SYS  = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\MSI\AppData\Local"), "Programs", "Python", "Python312", "python.exe")

# === SPSE ===
SPSE_BASE_URL = "https://spse.inaproc.id/tapinkab/"
KODE_LPSE = "266"

# Pastikan folder download ada
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(BROWSER_SESSION_DIR, exist_ok=True)


def sanitasi_nama_folder(nama: str) -> str:
    """Sanitasi nama folder/path: karakter Windows-illegal → '-', strip spasi tepi."""
    return re.sub(r'[/\\:*?"<>|]', "-", nama).strip()


def sb():
    """Buat Supabase client. Baca env dari secret_supabase.env (V19 atau lokal)."""
    from supabase import create_client
    from dotenv import load_dotenv
    env_path = pathlib.Path(__file__).parent.parent / "V19_Scheduler/WPy64-313110/secret_supabase.env"
    if not env_path.exists():
        env_path = pathlib.Path(__file__).parent / "secret_supabase.env"
    load_dotenv(env_path)
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
