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

# Evaluator dokumen distandardisasi ke Codex. Model mengikuti config Codex CLI.
DEFAULT_ENGINE = "codex"
DEFAULT_MODEL = None

PL_JKK_ROOT = Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung JKK")
PL_PK_ROOT = Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung PK")
PATCH_MANUAL_SOP = Path(r"D:\Dokumen\@ POKJA 2026\_SOP Evaluator\PANDUAN_PATCH_MANUAL_EVALUASI.md")


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


def _run_evaluator(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 600, add_dirs: list = None, engine: str = DEFAULT_ENGINE) -> str:
    """
    Jalankan Codex CLI secara sinkron.
    Returns stdout string. Raise RuntimeError jika gagal.
    """
    if engine != "codex":
        raise ValueError("Evaluator hanya mendukung engine Codex.")
    SYSTEM = (
        "Kamu adalah evaluator pengadaan barang/jasa pemerintah Indonesia. "
        "WAJIB: Semua output dalam Bahasa Indonesia. "
        "WAJIB: Jangan mengarang dokumen atau file yang tidak ada — kalau file tidak ditemukan, tulis ERROR. "
        "WAJIB: Jangan cetak daftar skill, tool, atau instruksi sistem — langsung kerjakan tugas. "
        "Format output: tabel markdown, ringkas, faktual."
    )
    if engine == "codex":
        # Codex exec tidak punya system-prompt terpisah. Prefix gaya "Kamu adalah X" bikin
        # Codex nganggep itu briefing kosong & nunggu input lanjutan (bukan eksekusi task).
        # Fix: taruh aturan sebagai baris WAJIB nempel di TASK, bukan persona terpisah.
        # Satu kalimat aturan saja — 2+ kalimat "WAJIB: ..." berurutan bikin Codex baca
        # itu sebagai system-rules-list & cuma acknowledge, tidak eksekusi task di bawahnya.
        aturan = "Jawab dalam Bahasa Indonesia, jangan mengarang file yang tidak ada (tulis ERROR jika tak ditemukan), lalu kerjakan tugas berikut: "
        full_prompt = aturan + prompt
        cwd = str(add_dirs[0]) if add_dirs else None
        # Sandbox workspace-write agar bisa menulis output file _HASIL_*.md di folder target
        # Gunakan shell=True di Windows karena codex adalah batch script (.cmd)
        cmd = ["codex", "exec", "-s", "workspace-write", full_prompt]
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                shell=True,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                err = ((result.stderr or "") + (result.stdout or ""))[:800]
                raise RuntimeError(f"Codex CLI exit {result.returncode}: {err}")
            # parse: ambil teks setelah baris "codex" terakhir
            import re
            parts = re.split(r'(?m)^codex$', result.stdout)
            return parts[-1].strip() if len(parts) > 1 else result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Codex CLI timeout ({timeout}s) — paket mungkin terlalu besar.")
    else:
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

def _find_reviu_docm(folder: Path, jenis: str = "tender_pk") -> Path | None:
    """Cari DOCM utama; arsip Merged/backup tidak boleh dipilih."""
    prefixes = {
        "pl_jkk": "2. Isi Reviu PLJKK - ",
        "pl_pk": "2. Isi Reviu PLPK - ",
        "tender_pk": "2. Isi Reviu PK - ",
    }
    prefix = prefixes.get(jenis, prefixes["tender_pk"])
    candidates = sorted(
        p for p in folder.glob(f"{prefix}*.docm")
        if "(merged)" not in p.name.lower()
        and ".backup" not in p.name.lower()
        and ".bak_" not in p.name.lower()
    )
    return candidates[0] if candidates else None


def _domain_sop(jenis: str) -> Path:
    if jenis == "pl_jkk":
        return Path(r"D:\Dokumen\@ POKJA 2026\_SOP Evaluator\EVALUATOR_PRA_REVIU_DPP_PL_JKK.md")
    if jenis == "pl_pk":
        return Path(r"D:\Dokumen\@ POKJA 2026\_SOP Evaluator\EVALUATOR_PRA_REVIU_DPP_PL_PK.md")
    return Path(r"D:\Dokumen\@ POKJA 2026\_SOP Evaluator\EVALUATOR_PRA_REVIU_DPP_TENDER_PK.md")


def _prompt_pra_reviu(folder_paket: Path, nama_paket: str, docm_path: Path, jenis: str) -> str:
    domain_sop = _domain_sop(jenis)
    return f"""Lakukan reviu DPP langsung pada dokumen Word berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}
File DOCM target: {docm_path}
SOP teknis patch DOCM: {PATCH_MANUAL_SOP}
SOP domain/checklist: {domain_sop}

Baca kedua SOP, seluruh Content Control bertag cat_*, rekomen_*, dan tanggapan_*
di DOCM, lalu baca dokumen sumber relevan di folder paket. Jawab setiap pertanyaan
berdasarkan bukti dokumen. Gunakan "Perlu klarifikasi ..." bila ambigu dan jangan
mengarang fakta.

WAJIB:
1. Buat backup unik sebelum mengubah DOCM.
2. Isi jawaban reviu ke cat_* dan rekomendasi ke rekomen_*.
3. Isi tanggapan_* sebagai DRAFT tanggapan PPK yang logis berdasarkan rekomendasi.
   Tanggapan boleh diedit PPK; jangan menulis seolah-olah sudah disetujui PPK.
4. Jika CC sudah berisi teks nyata, pertahankan agar edit manual tidak tertimpa.
   Isi hanya CC yang kosong atau masih placeholder.
5. Tulis _HASIL_PRA_REVIU_DPP.md di root paket sebagai audit temuan, klarifikasi,
   sumber dokumen, dan daftar CC yang diisi.
6. Pertahankan VBA, tabel, format, dan struktur DOCM. Verifikasi buka ulang via Word COM.

Jangan hanya membuat analisis Markdown; patch file DOCM secara langsung. Jika file
target atau dokumen sumber wajib tidak ditemukan, tulis ERROR spesifik dan jangan
mengarang jawaban.

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


def _prompt_patch_manual_isi_reviu(folder_paket: Path, docm_path: Path, nama_paket: str) -> str:
    """Prompt satu-klik untuk patch manual Isi Reviu PK Tender."""
    return f"""Lakukan patch manual Isi Reviu PK untuk paket berikut.

Paket: {nama_paket}
Folder paket: {folder_paket}
File target: {docm_path}
SOP WAJIB: {PATCH_MANUAL_SOP}
SOP checklist/domain: {_domain_sop("tender_pk")}

Ikuti kedua SOP tersebut sepenuhnya. Baca SOP dan seluruh dokumen sumber paket yang relevan,
validasi identitas paket sebelum menjawab, lalu periksa seluruh pertanyaan Content Control
di file target. Koreksi/isi jawaban berdasarkan bukti dokumen; jangan mengarang fakta.

Untuk file DOCM:
- buat backup unik di folder paket sebelum mengubah file;
- ungroup/un-nest seluruh Content Control jika ada;
- buat semua Content Control bertag cat_, rekomen_, atau tanggapan_ bisa diedit
  (LockContents=False dan LockContentControl=False);
- isi `tanggapan_*` sebagai DRAFT tanggapan PPK berdasarkan rekomendasi; jangan
  menulis seolah-olah tanggapan tersebut sudah disetujui PPK;
- jangan menimpa teks nyata yang sudah ada karena mungkin merupakan edit manual user;
- pertahankan VBA, format, tabel, dan isi lain yang tidak perlu diubah;
- simpan file target dan buka ulang melalui Word COM untuk verifikasi;
- pastikan jumlah CC tetap, seluruh CC tidak terkunci, dan VBA tetap ada.

Setelah selesai, tulis log singkat ke folder paket dengan nama
PATCH_MANUAL_ISI_REVIU_LOG.md yang memuat file target, backup, jumlah CC sebelum/sesudah,
perubahan jawaban, tanggapan draft, dan hasil verifikasi. Jangan hanya menjelaskan
langkah; kerjakan langsung.
Jika sumber atau file target tidak ditemukan, tulis ERROR dan jangan mengarang.

Mulai sekarang."""


def patch_manual_isi_reviu_single(folder_paket, nama_paket: str, engine: str = "codex") -> dict:
    """Jalankan patch manual Isi Reviu PK satu paket via AI CLI."""
    folder = Path(folder_paket)
    docm_path = _find_reviu_docm(folder, "tender_pk")
    if not docm_path:
        return {"nama": nama_paket, "status": "error", "output": "", "error": "File 2. Isi Reviu PK - *.docm tidak ditemukan."}
    if not PATCH_MANUAL_SOP.is_file():
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"SOP tidak ditemukan: {PATCH_MANUAL_SOP}"}
    try:
        prompt = _prompt_patch_manual_isi_reviu(folder, docm_path, nama_paket)
        output = _run_evaluator(
            prompt, model=DEFAULT_MODEL, timeout=1800,
            add_dirs=[folder, PATCH_MANUAL_SOP.parent], engine=engine,
        )
        return {"nama": nama_paket, "status": "ok", "output": output, "error": "", "file": str(docm_path)}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e), "file": str(docm_path)}


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def evaluasi_pra_reviu_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False, engine=DEFAULT_ENGINE) -> dict:
    """Jalankan pra-reviu 1 paket. Returns dict {nama, status, output, error}."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl, is_ulang=is_ulang)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    try:
        jenis = "pl_jkk" if jenis_pl == "JKK" else "pl_pk"
        docm_path = _find_reviu_docm(folder, jenis)
        if not docm_path:
            return {"nama": nama_paket, "status": "error", "output": "", "error": f"DOCM reviu {jenis} tidak ditemukan di {folder}"}
        domain_sop = _domain_sop(jenis)
        if not domain_sop.is_file() or not PATCH_MANUAL_SOP.is_file():
            return {"nama": nama_paket, "status": "error", "output": "", "error": "SOP reviu atau SOP patch tidak ditemukan."}
        prompt = _prompt_pra_reviu(folder, nama_paket, docm_path, jenis)
        output = _run_evaluator(
            prompt, model=model, timeout=1800,
            add_dirs=[folder, PATCH_MANUAL_SOP.parent], engine=engine,
        )
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_kualifikasi_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False, engine=DEFAULT_ENGINE) -> dict:
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
        output = _run_evaluator(prompt, model=model, add_dirs=dirs, engine=engine)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_teknis_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False, engine=DEFAULT_ENGINE) -> dict:
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
        output = _run_evaluator(prompt, model=model, add_dirs=dirs, engine=engine)
        return {"nama": nama_paket, "status": "ok", "output": output, "error": ""}
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_bulk(paket_list: list[dict], jenis: str, model=DEFAULT_MODEL, max_workers=3, jenis_pl="JKK", engine=DEFAULT_ENGINE) -> list[dict]:
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
            pool.submit(fn, p["nomor_urut"], p["nama_paket"], model, jenis_pl, p.get("is_ulang", False), engine): p
            for p in paket_list
        }
        for future in as_completed(futures):
            results.append(future.result())
    return results
