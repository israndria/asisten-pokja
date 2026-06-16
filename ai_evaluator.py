"""
ai_evaluator.py — Trigger Claude Code CLI untuk evaluasi dokumen Pengadaan Langsung (JKK & PK).

Flow:
  Streamlit tombol → generate prompt → subprocess claude --print
  → Claude baca protokol di folder paket → evaluasi → tulis .md
  → stdout dikembalikan ke Streamlit

Prompt = minimalis (kurir path + trigger).
Protokol lengkap ada di PROTOKOL_*.md dalam folder paket — AI baca sendiri.
"""

import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Path claude CLI
CLAUDE_BIN = shutil.which("claude") or r"D:\nodejs\claude"

# Model default untuk evaluasi
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

PL_JKK_ROOT = Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung JKK")
PL_PK_ROOT = Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung PK")


def _folder_paket(nomor_urut, nama_paket: str, jenis_pl="JKK") -> Path:
    """Cari folder paket — prioritas nomor urut, fallback nama paket substring."""
    root = PL_PK_ROOT if jenis_pl == "PK" else PL_JKK_ROOT
    if nomor_urut:
        prefix = f"{nomor_urut}."
        for d in root.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                return d
    # Fallback: cari by nama_paket substring (case-insensitive)
    if nama_paket:
        nama_lower = nama_paket[:30].lower()
        for d in root.iterdir():
            if d.is_dir() and nama_lower in d.name.lower():
                return d
    return None


def _run_evaluator(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 300) -> str:
    """
    Jalankan claude --print secara sinkron.
    Returns stdout string. Raise RuntimeError jika gagal.
    """
    cmd = [CLAUDE_BIN, "--print", "--dangerously-skip-permissions", "--model", model, prompt]
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
            raise RuntimeError(f"Claude CLI exit {result.returncode}: {err}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timeout ({timeout}s) — paket mungkin terlalu besar.")


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

def evaluasi_pra_reviu_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK") -> dict:
    """Jalankan pra-reviu 1 paket. Returns dict {nama, status, output, error}."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_pra_reviu(folder, nama_paket)
        output = _run_evaluator(prompt, model=model)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_kualifikasi_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK") -> dict:
    """Evaluasi Admin+Kualifikasi 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_evaluasi_kualifikasi(folder, nama_paket)
        output = _run_evaluator(prompt, model=model)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_teknis_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK") -> dict:
    """Evaluasi Teknis (Sesi 2) 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_evaluasi_teknis(folder, nama_paket)
        output = _run_evaluator(prompt, model=model)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_bulk(paket_list: list[dict], jenis: str, model=DEFAULT_MODEL, max_workers=3, jenis_pl="JKK") -> list[dict]:
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
            pool.submit(fn, p["nomor_urut"], p["nama_paket"], model, jenis_pl): p
            for p in paket_list
        }
        for future in as_completed(futures):
            results.append(future.result())
    return results
