"""
refresh_template.py — Copy file template terbaru ke folder paket existing.

Logika matching (per file template):
  - Ambil nomor prefix + kata pertama dari nama template, misal:
    "0. BAPLJKK - Template.xlsm" → prefix="0", keyword="BAPLJKK"
  - Cari file di root paket dengan: nomor prefix sama + ekstensi sama
  - Skip: *(Merged)*, *bak*, *.pdf, subfolder, file tanpa angka prefix

Safe-delete: send2trash (ke Recycle Bin), bukan os.remove.
Relink: panggil relink_pl.py atau relink_templates.py via subprocess.
"""

import os
import re
import shutil
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

import send2trash

# ─── konstanta ──────────────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).resolve().parent.parent / "V19_Scheduler" / "WPy64-313110"
PYTHON_EXE = str(BASE_DIR / "python" / "python.exe")

RELINK_PL     = str(BASE_DIR / "relink_pl.py")
RELINK_TENDER = str(BASE_DIR / "relink_templates.py")

LOG_FILE = Path(__file__).resolve().parent / "refresh_template.log"

# ─── helper ─────────────────────────────────────────────────────────────────

def _setup_log():
    logger = logging.getLogger("refresh_template")
    if not logger.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)
    return logger


_PREFIX_RE = re.compile(r"^(\d+)\.")


def _prefix(name: str) -> str | None:
    """Ambil nomor prefix dari nama file, misal '0' dari '0. BAPK - Template.xlsm'."""
    m = _PREFIX_RE.match(name)
    return m.group(1) if m else None


def get_template_files(template_source: Path) -> list[Path]:
    """
    Kembalikan daftar file template di root template_source.
    Filter: *.xlsm + *.docx + *.docm, skip *.bak, skip Header*.docx,
    skip file tanpa nomor prefix.
    """
    result = []
    for p in template_source.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".xlsm", ".docx", ".docm"):
            continue
        if p.suffix.lower() == ".bak" or p.name.endswith(".bak"):
            continue
        if p.name.startswith("Header"):
            continue
        if "(Merged)" in p.name:
            continue
        if _prefix(p.name) is None:
            continue
        result.append(p)
    return sorted(result, key=lambda p: p.name)


def get_paket_files_to_delete(paket_folder: Path, template_files: list[Path]) -> list[Path]:
    """
    Temukan file lama di root paket_folder yang cocok dengan template.

    Matching rule:
      - nomor prefix sama (misal '0', '1', '2', '3', '4')
      - ekstensi sama (.xlsm / .docx / .docm)
      - BUKAN: (Merged), bak, subfolder, file tanpa prefix

    File aman (tidak tersentuh):
      - *(Merged)* — output mail merge
      - *.pdf — download SPSE / output cetak
      - subfolder
      - file dengan nomor prefix BERBEDA (misal 4.1, 4.2, 4.3)
    """
    # Buat set nomor prefix yang dimiliki template per ekstensi
    # format: {("0", ".xlsm"), ("1", ".docx"), ...}
    template_keys = set()
    for tf in template_files:
        pfx = _prefix(tf.name)
        if pfx:
            template_keys.add((pfx, tf.suffix.lower()))

    to_delete = []
    for p in paket_folder.iterdir():
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in (".xlsm", ".docx", ".docm"):
            continue
        if "(Merged)" in p.name:
            continue
        if p.name.endswith(".bak"):
            continue
        pfx = _prefix(p.name)
        if pfx is None:
            continue
        # Cek format nomor prefix — harus persis "N. " (satu angka + titik + spasi)
        # Contoh OK  : "0. BAPK - 003.xlsm", "4. Undangan - 003.docx"
        # Contoh SKIP: "4.1 RK3K.docx", "4.2 Program K3.xlsx", "4.3. Pakta.docx"
        standard_prefix_m = re.match(r"^(\d+)\. ", p.name)
        if not standard_prefix_m:
            # bukan format "N. " standar (mungkin "4.1 " atau "4.3.") → aman, skip
            continue
        if (pfx, ext) in template_keys:
            to_delete.append(p)
    return to_delete


def _derive_suffix(folder_name: str) -> str:
    """
    Ambil suffix rename dari nama folder paket — sama persis dengan setup_paket_baru.py.
    Tender : "1. Pokja 086 - Nama"  → "086"
    PL JKK : "1. PLJKK - Nama Paket" → "Nama Paket"
    PL PK  : "1. PLPK - Nama Paket"  → "Nama Paket"
    """
    m_pokja = re.search(r"Pokja\s+(\d+)", folder_name, re.IGNORECASE)
    if m_pokja:
        return m_pokja.group(1)
    m_pl = re.search(r"PL(?:JKK|PK)\s+-\s+(.+)$", folder_name, re.IGNORECASE)
    if m_pl:
        return m_pl.group(1).strip()
    return ""


def refresh_template_paket(
    paket_folders: list[Path],
    template_source: Path,
    mode: Literal["tender", "pl_jkk", "pl_pk"],
    auto_relink: bool = True,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """
    Copy template terbaru ke setiap folder paket.

    Returns:
        dict: {str(paket_folder): [log lines]}
    """
    logger = _setup_log()
    log_header = f"=== refresh_template {mode} dry_run={dry_run} {datetime.now().isoformat()} ==="
    logger.info(log_header)

    template_files = get_template_files(template_source)
    if not template_files:
        return {str(p): [f"❌ Tidak ada file template di {template_source}"] for p in paket_folders}

    hasil: dict[str, list[str]] = {}

    for folder in paket_folders:
        log: list[str] = []
        folder = Path(folder)

        if not folder.exists():
            log.append(f"⚠️ Folder tidak ditemukan, dilewati: {folder}")
            hasil[str(folder)] = log
            logger.info(f"SKIP (not found): {folder}")
            continue

        # 1. Cari file lama yang akan dihapus
        to_delete = get_paket_files_to_delete(folder, template_files)

        for f in to_delete:
            if dry_run:
                log.append(f"[DRY-RUN] 🗑 Akan hapus: {f.name}")
            else:
                try:
                    send2trash.send2trash(str(f))
                    log.append(f"🗑 Hapus: {f.name}")
                    logger.info(f"DELETE: {f}")
                except Exception as e:
                    log.append(f"❌ Gagal hapus {f.name}: {e}")
                    logger.warning(f"DELETE FAIL: {f} — {e}")

        # 2. Copy template segar — rename "Template" → suffix nama paket
        suffix = _derive_suffix(folder.name)
        excel_copied: Path | None = None
        for tf in template_files:
            dest_name = tf.name.replace("Template", suffix) if suffix and "Template" in tf.name else tf.name
            dest = folder / dest_name
            if dry_run:
                log.append(f"[DRY-RUN] 📋 Akan copy: {tf.name} → {dest_name}")
            else:
                try:
                    shutil.copy(str(tf), str(dest))
                    log.append(f"📋 Copy: {tf.name} → {dest_name}")
                    logger.info(f"COPY: {tf} → {dest}")
                    if tf.suffix.lower() == ".xlsm":
                        excel_copied = dest
                except Exception as e:
                    log.append(f"❌ Gagal copy {tf.name}: {e}")
                    logger.warning(f"COPY FAIL: {tf} → {dest} — {e}")

        # 3. Relink Word → Excel
        if auto_relink and not dry_run and excel_copied:
            relink_script = RELINK_PL if mode in ("pl_jkk", "pl_pk") else RELINK_TENDER
            try:
                result = subprocess.run(
                    [PYTHON_EXE, relink_script, str(excel_copied)],
                    capture_output=True, text=True, timeout=60,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                if result.returncode == 0:
                    log.append(f"🔗 Relink OK")
                    logger.info(f"RELINK OK: {excel_copied}")
                else:
                    log.append(f"⚠️ Relink selesai (kode {result.returncode}): {result.stderr.strip()[:120]}")
                    logger.warning(f"RELINK WARN: {excel_copied} — {result.stderr.strip()[:200]}")
            except subprocess.TimeoutExpired:
                log.append("❌ Relink timeout (>60s)")
                logger.warning(f"RELINK TIMEOUT: {excel_copied}")
            except Exception as e:
                log.append(f"❌ Relink error: {e}")
                logger.warning(f"RELINK ERROR: {excel_copied} — {e}")
        elif dry_run and auto_relink:
            log.append("[DRY-RUN] 🔗 Akan relink Word → Excel")

        hasil[str(folder)] = log

    logger.info(f"=== selesai {len(paket_folders)} paket ===\n")
    return hasil
