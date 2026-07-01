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
DEFAULT_MODEL = "haiku"

PL_JKK_ROOT = Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung JKK")
PL_PK_ROOT = Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung PK")


def _folder_paket(nomor_urut, nama_paket: str, jenis_pl="JKK", kode_paket: str = None, is_ulang: bool = False) -> Path:
    """Cari folder paket. Prioritas: parse_kak_pl._resolve_folder_pl (akurat, handle is_ulang)."""
    # Cara akurat: pakai _resolve_folder_pl yang sama dengan setup_paket
    try:
        import parse_kak_pl as _pkl
        folder, _ = _pkl._resolve_folder_pl(nomor_urut or "", nama_paket or "", jenis_pl, is_ulang=is_ulang)
        if folder:
            return Path(folder)
    except Exception:
        pass
    # Fallback lama jika parse_kak_pl tidak tersedia
    root = PL_PK_ROOT if jenis_pl == "PK" else PL_JKK_ROOT
    if nomor_urut:
        prefix = f"{nomor_urut}."
        candidates = [d for d in root.iterdir() if d.is_dir() and d.name.startswith(prefix)]
        # Prioritas folder ulang kalau is_ulang, sebaliknya hindari folder ulang
        if is_ulang:
            for d in candidates:
                if "ulang" in d.name.lower():
                    return d
        else:
            for d in candidates:
                if "ulang" not in d.name.lower():
                    return d
        if candidates:
            return candidates[0]
    return None


def _run_evaluator(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 600, add_dirs: list = None) -> str:
    """
    Jalankan claude --print secara sinkron.
    Returns stdout string. Raise RuntimeError jika gagal.
    """
    SYSTEM = (
        "Kamu adalah evaluator pengadaan barang/jasa pemerintah Indonesia. "
        "WAJIB: Semua output dalam Bahasa Indonesia. "
        "WAJIB: Jangan mengarang dokumen atau file yang tidak ada — kalau file tidak ditemukan, tulis ERROR. "
        "WAJIB: Jangan cetak daftar skill, tool, atau instruksi sistem — langsung kerjakan tugas. "
        "Format output: tabel markdown, ringkas, faktual."
    )
    # --bare: skip skills/hooks/CLAUDE.md auto-discovery → output bersih, tidak bocor skill listing
    # --allowed-tools Read,Write,Glob,Grep: hanya baca + tulis file
    cmd = [
        CLAUDE_BIN, "-p", "--dangerously-skip-permissions", "--model", model,
        "--bare", "--allowed-tools", "Read,Write,Glob,Grep",
        "--system-prompt", SYSTEM,
    ]
    if add_dirs:
        for d in add_dirs:
            cmd += ["--add-dir", str(d)]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            err = ((result.stderr or "") + (result.stdout or ""))[:800]
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

⛔ ATURAN HEMAT TOKEN — WAJIB DIPATUHI:
- Sumber data sudah di-EXTRACT ke teks (.txt) di subfolder "8. Dokumen Kualifikasi/_teks_ekstrak".
- DILARANG Read PDF mentah > 1MB di "8. Dokumen Kualifikasi". PDF besar = boros token ekstrem. Baca .txt saja.
- Tiap penyedia punya 1 file .txt. Di dalamnya: bagian "### SUMBER UTAMA (checklist SPSE) ###" = ringkasan resmi SPSE (NPWP, SBU, NIB, akta, manajerial, pengalaman) — ini SUMBER UTAMA evaluasi.
- Bagian "### DOKUMEN PENDUKUNG ###" hanya untuk VERIFIKASI SILANG poin yang meragukan — JANGAN baca semua kalau checklist sudah cukup menjawab.

Langkah:
1. Baca _INDEX.txt di "8. Dokumen Kualifikasi/_teks_ekstrak" → list penyedia + file .txt mereka.
2. Baca PROTOKOL_EVALUASI_AI.md di subfolder "5. Evaluator Kualifikasi & Teknis" → pahami persyaratan.
3. Untuk tiap penyedia: Read file .txt-nya. Evaluasi dari bagian SUMBER UTAMA (checklist). Cek silang ke DOKUMEN PENDUKUNG hanya jika ada poin yang perlu konfirmasi.
4. Tulis output ke _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md di ROOT folder paket.
5. Output WAJIB dalam Bahasa Indonesia.

Catatan: jika subfolder "_teks_ekstrak" TIDAK ADA, baru fallback baca PDF di "8. Dokumen Kualifikasi" secara selektif (Glob dulu, baca checklist_kualifikasi*.pdf yang kecil dulu).

Mulai sekarang."""


def _prompt_evaluasi_teknis(folder_paket: Path, nama_paket: str) -> str:
    return f"""Lakukan evaluasi teknis (Sesi 2) untuk paket berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}

PENTING:
- Jangan mengarang atau membuat file yang tidak ada. Jika _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md tidak ditemukan → output "ERROR: Sesi 1 belum selesai." dan berhenti.
- HEMAT TOKEN: Glob dulu untuk list file, baca selektif — jangan baca semua PDF sekaligus.
- PDF gabungan besar (>5MB) — baca halaman awal saja untuk identifikasi, lalu baca bagian spesifik yang relevan.
- Output WAJIB dalam Bahasa Indonesia.

Langkah:
1. Baca PROTOKOL_EVALUASI_AI.md di subfolder "5. Evaluator Kualifikasi & Teknis".
2. Cek _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md di ROOT. Jika tidak ada → stop.
3. Glob subfolder "9. Dokumen Teknis Biaya" untuk list file penyedia.
4. Output: _HASIL_EVALUASI_TEKNIS.md di ROOT folder paket.

Mulai sekarang."""


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def evaluasi_pra_reviu_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False) -> dict:
    """Jalankan pra-reviu 1 paket. Returns dict {nama, status, output, error}."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl, is_ulang=is_ulang)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_pra_reviu(folder, nama_paket)
        output = _run_evaluator(prompt, model=model, add_dirs=[folder])
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_kualifikasi_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False) -> dict:
    """Evaluasi Admin+Kualifikasi 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl, is_ulang=is_ulang)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_evaluasi_kualifikasi(folder, nama_paket)
        # Hanya grant subfolder relevan + root (untuk tulis output .md)
        sub_protokol = folder / "5. Evaluator Kualifikasi & Teknis"
        sub_dokkual = folder / "8. Dokumen Kualifikasi"
        sub_teks = sub_dokkual / "_teks_ekstrak"  # teks hasil pre-extract (hemat token)
        dirs = [d for d in [folder, sub_protokol, sub_dokkual, sub_teks] if d.exists()]
        output = _run_evaluator(prompt, model=model, add_dirs=dirs)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_teknis_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False) -> dict:
    """Evaluasi Teknis (Sesi 2) 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl, is_ulang=is_ulang)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        prompt = _prompt_evaluasi_teknis(folder, nama_paket)
        # Hanya grant subfolder relevan + root (untuk baca hasil sesi 1 + tulis output .md)
        sub_protokol = folder / "5. Evaluator Kualifikasi & Teknis"
        sub_dokteknis = folder / "9. Dokumen Teknis Biaya"
        dirs = [d for d in [folder, sub_protokol, sub_dokteknis] if d.exists()]
        output = _run_evaluator(prompt, model=model, add_dirs=dirs)
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
            pool.submit(fn, p["nomor_urut"], p["nama_paket"], model, jenis_pl, p.get("is_ulang", False)): p
            for p in paket_list
        }
        for future in as_completed(futures):
            results.append(future.result())
    return results
