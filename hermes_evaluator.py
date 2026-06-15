"""
hermes_evaluator.py — Trigger Hermes Agent untuk evaluasi dokumen PL JKK.

Flow:
  Streamlit tombol → generate prompt → subprocess hermes --oneshot
  → Hermes baca protokol di folder paket → evaluasi → tulis .md
  → stdout dikembalikan ke Streamlit

Prompt = minimalis (kurir path + trigger).
Protokol lengkap ada di PROTOKOL_*.md dalam folder paket — AI baca sendiri.
"""

import subprocess
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Path hermes CLI
HERMES_BIN = shutil.which("hermes") or r"C:\Users\MSI\bin\hermes"

# Model default untuk evaluasi — AG flash dulu, fallback chain di hermes config
DEFAULT_MODEL  = "ag/gemini-3.5-flash-extra-low"
FALLBACK_MODEL = "gc/gemini-3-flash-preview"

PL_JKK_ROOT = Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung JKK")


def _folder_paket(nomor_urut: int | str, nama_paket: str) -> Path:
    """Cari folder paket berdasarkan nomor urut (prefix N.)."""
    prefix = f"{nomor_urut}."
    for d in PL_JKK_ROOT.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            return d
    # Fallback: cari by nama_paket substring
    for d in PL_JKK_ROOT.iterdir():
        if d.is_dir() and nama_paket and nama_paket[:20].lower() in d.name.lower():
            return d
    return None


def _run_hermes(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 300) -> str:
    """
    Jalankan hermes --oneshot secara sinkron.
    Returns stdout string. Raise RuntimeError jika gagal.
    """
    cmd = [HERMES_BIN, "--oneshot", prompt, "--model", model, "--yolo", "--cli"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            err = (result.stderr or "")[:500]
            # Fallback ke GC model kalau AG exhausted
            if "exhausted" in err.lower() or "quota" in err.lower() or "429" in err:
                return _run_hermes(prompt, model=FALLBACK_MODEL, timeout=timeout)
            raise RuntimeError(f"Hermes exit {result.returncode}: {err}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Hermes timeout ({timeout}s) — paket mungkin terlalu besar.")


# ── PROMPT TEMPLATES ──────────────────────────────────────────────────────────

def _prompt_pra_reviu(folder_paket: Path, nama_paket: str) -> str:
    return f"""Lakukan pra-reviu dokumen PPK untuk paket berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}

Langkah:
1. Baca file PROTOKOL_PRA_REVIU.md di subfolder "0. Draft Dokumen PPK" dalam folder paket di atas.
2. Ikuti seluruh instruksi dalam protokol tersebut — jangan buat protokol sendiri.
3. Tulis output ke _HASIL_PRA_REVIU.md di ROOT folder paket (bukan subfolder).

Mulai sekarang."""


def _prompt_evaluasi_kualifikasi(folder_paket: Path, nama_paket: str) -> str:
    return f"""Lakukan evaluasi administrasi dan kualifikasi (Sesi 1) untuk paket berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}

Langkah:
1. Baca file PROTOKOL_EVALUASI_AI.md di subfolder "5. Evaluator Kualifikasi & Teknis" dalam folder paket di atas.
2. Ikuti seluruh instruksi dalam protokol tersebut.
3. Evaluasi semua penyedia yang ditemukan di subfolder "8. Dokumen Kualifikasi".
4. Output: _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md di ROOT folder paket.

Mulai sekarang."""


def _prompt_evaluasi_teknis(folder_paket: Path, nama_paket: str) -> str:
    return f"""Lakukan evaluasi teknis (Sesi 2) untuk paket berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}

Langkah:
1. Baca file PROTOKOL_EVALUASI_AI.md di subfolder "5. Evaluator Kualifikasi & Teknis" dalam folder paket di atas.
2. Pastikan _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md sudah ada dan statusnya LULUS sebelum lanjut.
3. Evaluasi semua penyedia di subfolder "9. Dokumen Teknis Biaya".
4. Output: _HASIL_EVALUASI_TEKNIS.md di ROOT folder paket.

Mulai sekarang."""


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def evaluasi_pra_reviu_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL) -> dict:
    """Jalankan pra-reviu 1 paket. Returns dict {nama, status, output, error}."""
    folder = _folder_paket(nomor_urut, nama_paket)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_pra_reviu(folder, nama_paket)
        output = _run_hermes(prompt, model=model)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_kualifikasi_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL) -> dict:
    """Evaluasi Admin+Kualifikasi 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_evaluasi_kualifikasi(folder, nama_paket)
        output = _run_hermes(prompt, model=model)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_teknis_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL) -> dict:
    """Evaluasi Teknis (Sesi 2) 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_evaluasi_teknis(folder, nama_paket)
        output = _run_hermes(prompt, model=model)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_bulk(paket_list: list[dict], jenis: str, model=DEFAULT_MODEL, max_workers=3) -> list[dict]:
    """
    Evaluasi paralel N paket.
    paket_list: list of {nomor_urut, nama_paket}
    jenis: "pra_reviu" | "kualifikasi" | "teknis"
    Returns list of result dicts.
    """
    fn_map = {
        "pra_reviu":   evaluasi_pra_reviu_single,
        "kualifikasi": evaluasi_kualifikasi_single,
        "teknis":      evaluasi_teknis_single,
    }
    fn = fn_map.get(jenis)
    if not fn:
        raise ValueError(f"Jenis evaluasi tidak dikenal: {jenis}")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fn, p["nomor_urut"], p["nama_paket"], model): p
            for p in paket_list
        }
        for future in as_completed(futures):
            results.append(future.result())
    return results
