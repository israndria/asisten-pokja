"""Konfigurasi Asisten Pokja — SPSE Automation."""

import os

# === Paths ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
BROWSER_SESSION_DIR = os.path.join(BASE_DIR, ".browser_session")

# === SPSE ===
SPSE_BASE_URL = "https://spse.inaproc.id/tapinkab/"
KODE_LPSE = "266"

# Pastikan folder download ada
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(BROWSER_SESSION_DIR, exist_ok=True)
