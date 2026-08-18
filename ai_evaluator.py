"""
ai_evaluator.py — Trigger Claude Code CLI untuk evaluasi dokumen Pengadaan Langsung (JKK & PK).

Flow:
  Streamlit tombol → generate prompt → subprocess claude --print
  → Claude baca protokol di folder paket → evaluasi → tulis .md
  → stdout dikembalikan ke Streamlit

Prompt = minimalis (kurir path + trigger).
Protokol lengkap ada di PROTOKOL_*.md dalam folder paket — AI baca sendiri.
"""

import os
import hashlib
import subprocess
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from config import POKJA_ROOT

# Evaluator dokumen distandardisasi ke Codex dengan model tetap.
DEFAULT_ENGINE = "codex"
CODEX_MODEL = "gpt-5.6-luna"
CODEX_REASONING_EFFORT = "medium"
DEFAULT_MODEL = CODEX_MODEL

CODEX_BIN = os.environ.get(
    "POKJA_CODEX_EXE",
    str(Path.home() / "AppData" / "Local" / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"),
)

PL_JKK_ROOT = Path(POKJA_ROOT) / "@ Pejabat Pengadaan 2026" / "@ Pengadaan Langsung JKK"
PL_PK_ROOT = Path(POKJA_ROOT) / "@ Pejabat Pengadaan 2026" / "@ Pengadaan Langsung PK"
SOP_ROOT = Path(POKJA_ROOT) / "_SOP Evaluator"
CORE_SOP = SOP_ROOT / "SOP_ISI_REVIU_DPP_CORE.md"
DOMAIN_SOP = SOP_ROOT / "SOP_ISI_REVIU_DPP_DOMAIN.md"
# Alias dipertahankan agar caller/clone lama yang melakukan monkeypatch tetap aman.
PATCH_MANUAL_SOP = CORE_SOP
EVALUASI_BIAYA_PLJKK_SOP = SOP_ROOT / "EVALUATOR_BIAYA_PL_JKK.md"

_EVIDENCE_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".xlsm", ".docm", ".zip", ".rar", ".7z", ".jpg", ".jpeg", ".png",
    ".bmp", ".tiff",
}


def _stage_evidence_files(root: Path) -> list[Path]:
    """Return dokumen nyata pada satu stage; marker/hasil AI tidak dihitung."""
    if not root.is_dir():
        return []
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        if path.suffix.lower() not in _EVIDENCE_EXTENSIONS:
            continue
        if path.name.startswith("_") or "_teks_ekstrak" in path.parts:
            continue
        files.append(path)
    return sorted(files)


def _stage_document_status(folder: Path, stage_names: tuple[str, ...]) -> dict:
    """Validasi dokumen stage, termasuk marker download yang belum lengkap."""
    roots = [folder / name for name in stage_names if (folder / name).is_dir()]
    markers = sorted(
        marker
        for root in roots
        for marker in root.rglob("_DOWNLOAD_TIDAK_LENGKAP.txt")
        if marker.is_file()
    )
    files = sorted({path for root in roots for path in _stage_evidence_files(root)})
    return {
        "available": bool(files),
        "ok": bool(files) and not markers,
        "roots": roots,
        "files": files,
        "markers": markers,
    }


def _valid_stage_output(path: Path) -> bool:
    """Output AI wajib non-empty dan tidak berhenti dengan ERROR."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return False
    return not any(line.lstrip().upper().startswith("ERROR") for line in text.splitlines())


def teknis_biaya_document_status(folder: Path) -> dict:
    """Gate dokumen Sesi 2; dukung nama folder aktif dan struktur legacy."""
    return _stage_document_status(
        folder,
        ("9. Dokumen Teknis Biaya", "2. Dokumen Teknis Biaya"),
    )


def _compose_final_evaluasi(folder: Path, jenis_pl: str) -> Path:
    """Gabungkan hasil stage menjadi laporan final yang dapat diaudit."""
    kualifikasi = folder / "_HASIL_EVALUASI_ADMIN_KUALIFIKASI.md"
    teknis = folder / "_HASIL_EVALUASI_TEKNIS.md"
    if not _valid_stage_output(kualifikasi):
        raise RuntimeError("Hasil Sesi 1 tidak valid; laporan final tidak dibuat.")
    if not _valid_stage_output(teknis):
        raise RuntimeError("Hasil Sesi 2 tidak valid; laporan final tidak dibuat.")

    biaya = folder / "_HASIL_EVALUASI_BIAYA.md"
    parts = [
        f"# HASIL EVALUASI FINAL {'PL PK' if jenis_pl == 'PK' else 'PL JKK'}",
        "",
        "> Laporan ini disusun engine dari hasil evaluasi bertahap. "
        "Jangan menganggap status tahap yang belum tersedia sebagai hasil evaluasi.",
        "",
        "## Sesi 1 — Administrasi dan Kualifikasi",
        "",
        kualifikasi.read_text(encoding="utf-8", errors="replace").strip(),
        "",
        "## Sesi 2 — Teknis/Biaya" if jenis_pl == "PK" else "## Sesi 2 — Teknis",
        "",
        teknis.read_text(encoding="utf-8", errors="replace").strip(),
    ]
    if jenis_pl == "JKK" and _valid_stage_output(biaya):
        parts.extend([
            "",
            "## Sesi 3 — Biaya",
            "",
            biaya.read_text(encoding="utf-8", errors="replace").strip(),
        ])
    output = folder / (
        "_HASIL_EVALUASI_FINAL_PL_PK.md"
        if jenis_pl == "PK"
        else "_HASIL_EVALUASI_FINAL_PL_JKK.md"
    )
    output.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return output


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
        # Pakai executable Codex asli; alias `codex` dapat menunjuk wrapper Headroom
        # yang memerlukan sandbox Windows setup dan gagal dari proses Streamlit.
        cmd = [
            CODEX_BIN, "exec", "--dangerously-bypass-approvals-and-sandbox",
            "-m", CODEX_MODEL,
            "-c", f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
            full_prompt,
        ]
        proc = None
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", shell=False,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            if proc.returncode != 0:
                err = ((stderr or "") + (stdout or ""))[:800]
                raise RuntimeError(f"Codex CLI exit {proc.returncode}: {err}")
            # parse: ambil teks setelah baris "codex" terakhir
            import re
            parts = re.split(r'(?m)^codex$', stdout or "")
            return parts[-1].strip() if len(parts) > 1 else (stdout or "").strip()
        except subprocess.TimeoutExpired:
            if proc is not None and proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
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
    """Cari hasil mail merge ``(Merged).docm``; template sumber tidak boleh dipatch."""
    prefixes = {
        "pl_jkk": "2. Isi Reviu PLJKK - ",
        "pl_pk": "2. Isi Reviu PLPK - ",
        "tender_pk": "2. Isi Reviu PK - ",
    }
    prefix = prefixes.get(jenis, prefixes["tender_pk"])
    candidates = [
        p for p in folder.glob(f"{prefix}*.docm")
        if "(merged)" in p.name.lower()
        and ".backup" not in p.name.lower()
        and ".bak_" not in p.name.lower()
        and not p.name.startswith("~$")
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime_ns) if candidates else None


def _reviu_fix_docx_path(folder: Path) -> Path:
    """Path output stabil untuk hasil patch AI; source DOCM tidak pernah ditimpa."""
    return Path(folder) / "2. Isi Reviu Fix.docx"


def _file_fingerprint(path: Path):
    """Fingerprint mtime, ukuran, dan isi file untuk guardrail immutable source."""
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size, digest.hexdigest()


def _backup_existing_reviu_output(output_path: Path) -> Path | None:
    """Backup unik output lama sebelum konversi menggantinya."""
    output_path = Path(output_path)
    if not output_path.is_file():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = output_path.with_name(
        f"{output_path.stem}.backup_{stamp}_{uuid.uuid4().hex[:8]}{output_path.suffix}"
    )
    shutil.copy2(output_path, backup)
    return backup


def _validate_docx_zip(docx_path: Path) -> None:
    """Validasi DOCX sebagai ZIP Open XML sebelum diserahkan ke AI/user."""
    docx_path = Path(docx_path)
    if not docx_path.is_file():
        raise RuntimeError(f"Output DOCX tidak ditemukan: {docx_path}")
    try:
        with zipfile.ZipFile(docx_path) as archive:
            broken = archive.testzip()
            if broken:
                raise RuntimeError(f"DOCX ZIP rusak pada entry: {broken}")
            if "word/document.xml" not in archive.namelist():
                raise RuntimeError("DOCX tidak memiliki word/document.xml")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Output bukan DOCX ZIP valid: {docx_path}") from exc


def _validate_docx_with_word(docx_path: Path) -> None:
    """Buka ulang output DOCX via Word COM secara read-only."""
    word = None
    document = None
    com_initialized = False
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        com_initialized = True
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(
            str(Path(docx_path).resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        if hasattr(document, "Repaginate"):
            document.Repaginate()
    except Exception as exc:
        raise RuntimeError(f"Validasi buka Word COM gagal untuk {docx_path}: {exc}") from exc
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit(False)
            except Exception:
                pass
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _convert_reviu_docm_to_docx(docm_path: Path, output_path: Path):
    """Konversi DOCM merge ke DOCX baru memakai Word COM SaveAs2(FileFormat=12)."""
    docm_path = Path(docm_path)
    output_path = Path(output_path)
    if not docm_path.is_file():
        raise RuntimeError(f"DOCM sumber tidak ditemukan: {docm_path}")
    if docm_path.resolve() == output_path.resolve():
        raise RuntimeError("Source DOCM dan output DOCX tidak boleh sama.")

    temp_path = output_path.with_name(
        f".{output_path.stem}.convert_{uuid.uuid4().hex[:8]}{output_path.suffix}"
    )
    word = None
    document = None
    com_initialized = False
    backup_path = None
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        com_initialized = True
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(
            str(docm_path.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        # wdFormatXMLDocument = 12; SaveAs2 mengubah format secara nyata,
        # bukan sekadar mengganti ekstensi file.
        document.SaveAs2(str(temp_path.resolve()), FileFormat=12, AddToRecentFiles=False)
    except Exception as exc:
        raise RuntimeError(f"Konversi DOCM ke DOCX gagal: {exc}") from exc
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit(False)
            except Exception:
                pass
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    try:
        _validate_docx_zip(temp_path)
        backup_path = _backup_existing_reviu_output(output_path)
        os.replace(temp_path, output_path)
        return output_path, backup_path
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise


def _domain_sop(jenis: str) -> Path:
    """Return canonical domain matrix; section selection happens in prompt."""
    return DOMAIN_SOP


def _domain_section(jenis: str) -> str:
    return {
        "pl_jkk": "PL_JKK",
        "pl_pk": "PL_PK",
        "tender_pk": "TENDER_PK",
    }.get(jenis, "TENDER_PK")


def _prompt_pra_reviu(
    folder_paket: Path,
    nama_paket: str,
    docm_path: Path,
    jenis: str,
    docx_path: Path | None = None,
) -> str:
    domain_sop = _domain_sop(jenis)
    docx_path = docx_path or _reviu_fix_docx_path(folder_paket)
    return f"""Lakukan reviu DPP langsung pada dokumen Word berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}
File DOCM sumber hasil mail merge (READ-ONLY, jangan diubah): {docm_path}
File DOCX target patch AI (WAJIB ditulis): {docx_path}
Target final wajib bernama `2. Isi Reviu Fix.docx`; jangan menulis file output lain.
Runner sudah mengonversi DOCM ke DOCX memakai Word COM sebelum tugas ini dimulai.
Mail merge dilakukan lebih dahulu melalui tombol VBA `Buka Isi Reviu` pada workbook paket.
SOP teknis patch DOCX: {PATCH_MANUAL_SOP}
SOP domain/checklist: {domain_sop}
Section domain yang wajib dipakai: `{_domain_section(jenis)}`. Abaikan dua section domain lain.

Baca kedua SOP, inventarisasi Content Control yang benar-benar ada di DOCX target, lalu
baca dokumen sumber relevan di folder paket. Jawab setiap pertanyaan berdasarkan
bukti dokumen. Gunakan "Perlu klarifikasi ..." bila ambigu dan jangan mengarang
fakta. Patuhi scope/whitelist section `{_domain_section(jenis)}`; pada PL PK,
ini berarti whitelist 45 CC Bagian I. Jangan membuat CC baru dan jangan
menyentuh bagian atau marker yang dikecualikan domain; khusus PL PK jangan menyentuh Bagian II
atau marker peralatan.

WAJIB:
1. Patch hanya DOCX target. DOCM sumber read-only dan hash/mtime-nya wajib tetap sama.
2. Isi jawaban reviu ke CC aktif yang sudah ada dan rekomendasi ke CC rekomen
   yang sudah ada; jangan membuat CC yang hilang.
3. Jika ada tanggapan_* yang memang ada dan diizinkan SOP domain, isi sebagai
   DRAFT tanggapan PPK; jangan menulis seolah-olah sudah disetujui PPK.
   Tanggapan boleh diedit PPK; jangan menulis seolah-olah sudah disetujui PPK.
4. Audit dan isi ulang setiap CC yang sudah ada. Teks lama hanya bahan
   pembanding, bukan jawaban yang dianggap benar; koreksi, hapus, atau ganti
   bila tidak sesuai bukti paket.
5. Jangan membuat Content Control baru. CC yang hilang/gap adalah manual sesuai
   SOP domain; jangan membuat pertanyaan atau fakta baru tanpa dasar.
6. Tulis _HASIL_PRA_REVIU_DPP.md di root paket sebagai audit temuan, klarifikasi,
   sumber dokumen, dan daftar CC yang diisi.
7. Pertahankan tabel, Content Control, MERGEFIELD, format, dan struktur DOCX.
   Konversi DOCM ke DOCX memang tidak membawa VBA; jangan membuat atau memulihkan VBA.
8. Verifikasi DOCX target dapat dibuka ulang via Word COM.

Jangan hanya membuat analisis Markdown; patch DOCX target secara langsung. Jangan
ubah atau ganti nama DOCM sumber. Jika
dokumen sumber tidak ditemukan, jangan mengisi fakta generik: isi CC aktif dengan
"Perlu klarifikasi: sumber ... tidak ditemukan" dan catat sumber yang hilang di
audit Markdown. Jika target DOCX tidak ditemukan atau tidak dapat dibaca, tulis
ERROR spesifik dan jangan mengarang fakta.

Mulai sekarang."""


def _prompt_evaluasi_kualifikasi(
    folder_paket: Path, nama_paket: str, jenis_pl: str = "JKK"
) -> str:
    evaluator_sop = (
        "EVALUATOR_KUALIFIKASI_PL_PK.md"
        if jenis_pl == "PK"
        else "EVALUATOR_KUALIFIKASI_PL_JKK_LUMSUM.md"
    )
    workbook_label = "BAPLPK" if jenis_pl == "PK" else "BAPLJKK"
    return f"""Lakukan evaluasi administrasi dan kualifikasi (Sesi 1) untuk paket berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}

ATURAN AKURASI — WAJIB:
- Dokpil/LDP paket adalah sumber aturan utama. Baca jenis kontrak dan syarat
  paket; jangan menganggap kontrak Lumsum dari nama file SOP.
- Baca PROTOKOL_EVALUASI_AI.md DAN {evaluator_sop}. Nama file lama dipertahankan
  hanya untuk kompatibilitas.
- Sesi ini TERBATAS pada administrasi dan kualifikasi berdasarkan dokumen di
  "8. Dokumen Kualifikasi". Jangan menulis verdict Evaluasi Teknis, Harga,
  atau status akhir paket pada Sesi 1. Peralatan/personel yang tercantum di
  dokumen kualifikasi boleh dicatat sebagai data kualifikasi, tetapi evaluasi
  teknis penawaran baru dilakukan pada Sesi 2 setelah dokumen teknis/biaya
  tersedia nyata.
- Gunakan checklist SPSE, dokumen pendukung, dan workbook 0. {workbook_label}*.xlsm
  sheet Hasil Evaluasi/@ Master Data sebagai satu rangkaian bukti.
- Jangan meminta user memverifikasi ulang bukti yang sudah ada. KSWP VALID,
  perusahaan baru, dan ketiadaan akta perubahan yang sudah tercatat harus
  diputus sendiri.
- Pisahkan verdict saat ini dari pembuktian tahap berikut. Dokumen asli yang
  baru diwajibkan saat pembuktian adalah flag NONBLOCKING.
- Status Administrasi dan Kualifikasi wajib LULUS atau GUGUR. Jangan gunakan
  LULUS*, BELUM FINAL, atau KLARIFIKASI sebagai pengganti verdict.

ATURAN EFISIENSI:
- Sumber data sudah di-EXTRACT ke teks (.txt) di subfolder "8. Dokumen Kualifikasi/_teks_ekstrak".
- DILARANG Read PDF mentah > 1MB di "8. Dokumen Kualifikasi". PDF besar = boros token ekstrem. Baca .txt saja.
- Tiap penyedia punya 1 file .txt. Di dalamnya: bagian "### SUMBER UTAMA (checklist SPSE) ###" = ringkasan resmi SPSE (NPWP, SBU, NIB, akta, manajerial, pengalaman) — ini SUMBER UTAMA evaluasi.
- Bagian "### DOKUMEN PENDUKUNG ###" hanya untuk VERIFIKASI SILANG poin yang meragukan — JANGAN baca semua kalau checklist sudah cukup menjawab.

Langkah:
1. Baca _INDEX.txt di "8. Dokumen Kualifikasi/_teks_ekstrak" → list penyedia + file .txt mereka.
2. Baca PROTOKOL_EVALUASI_AI.md dan {evaluator_sop} di subfolder
   "5. Evaluator Kualifikasi & Teknis".
3. Untuk tiap penyedia: Read file .txt-nya. Evaluasi dari bagian SUMBER UTAMA (checklist). Cek silang ke DOKUMEN PENDUKUNG hanya jika ada poin yang perlu konfirmasi.
4. Tulis output Sesi 1 ke _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md di ROOT folder paket.
   Kesimpulan hanya boleh menyatakan status Administrasi dan Kualifikasi.
5. Output WAJIB dalam Bahasa Indonesia.

Catatan: jika subfolder "_teks_ekstrak" TIDAK ADA, baru fallback baca PDF di "8. Dokumen Kualifikasi" secara selektif (Glob dulu, baca checklist_kualifikasi*.pdf yang kecil dulu).

Mulai sekarang."""


def _prompt_evaluasi_teknis(
    folder_paket: Path, nama_paket: str, jenis_pl: str = "JKK"
) -> str:
    evaluator_sop = (
        "EVALUATOR_KUALIFIKASI_PL_PK.md"
        if jenis_pl == "PK"
        else "EVALUATOR_KUALIFIKASI_PL_JKK_ADMIN_TEKNIS.md"
    )
    sesi_label = "Teknis/Biaya" if jenis_pl == "PK" else "Teknis"
    scope_label = "teknis dan biaya" if jenis_pl == "PK" else "teknis"
    return f"""Lakukan evaluasi {scope_label} (Sesi 2) untuk paket berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}

PENTING:
- Jangan mengarang atau membuat file yang tidak ada. Jika _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md tidak ditemukan → output "ERROR: Sesi 1 belum selesai." dan berhenti.
- Gunakan Dokpil/LDP sebagai sumber aturan utama dan deteksi jenis kontrak.
  Jangan hardcode Lumsum.
- Baca PROTOKOL_EVALUASI_AI.md DAN {evaluator_sop}.
- Sesi 1 adalah prasyarat. Jangan menggantikan atau mengulang verdict
  kualifikasi dari sumber lain; baca _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md dan
  cantumkan ringkasannya pada laporan gabungan.
- Pisahkan gate SPSE dari verdict dokumen. Jika dokumen teknis tersedia, lakukan
  evaluasi penuh dan tetapkan LULUS/GUGUR walaupun gate SPSE dicatat terpisah.
- Bukti SKK asli atau overlap personel yang menurut Dokpil baru diperiksa saat
  klarifikasi adalah flag NONBLOCKING, bukan alasan BELUM FINAL.
- Unsur wajib penawaran yang tidak ditemukan setelah seluruh file diperiksa
adalah TIDAK MEMENUHI; jangan meminta user menambahkan/verifikasi substansi.
- Nilai setiap Tenaga Ahli pada baris terpisah. Tenaga pendukung/non-ahli
bukan gate pass/fail individual. Klaim durasi ringkas di proposal bukan bukti;
hitung pengalaman Tenaga Ahli dari DRH/referensi bertanggal dan jangan
membulatkan kekurangan durasi.
- Bedakan dokumen wajib penawaran, substansi/rencana proposal, dan produk
kontrak final. Jangan menggugurkan hanya karena RKK/RK3K, RAB, TKDN,
spesifikasi, gambar, atau laporan final belum tersedia saat penawaran.
- Engine hanya memanggil Sesi 2 setelah dokumen teknis/biaya nyata tersedia.
  Jika setelah gate ini dokumen tetap tidak dapat dibaca, tulis ERROR spesifik;
  jangan membuat verdict teknis atau biaya dari asumsi.
- Dokumen yang berada di folder yang keliru bukan otomatis gugur. Cari seluruh
  file pada folder paket, terutama "8. Dokumen Kualifikasi" dan
  "9. Dokumen Teknis Biaya" (atau legacy "2. Dokumen Teknis Biaya"); bila substansinya valid, evaluasi pada tahap yang
  relevan, tandai salah penempatan sebagai catatan audit/nonconformity.
- Untuk PL PK, evaluasi juga unsur biaya yang benar-benar tersedia di folder
  "9. Dokumen Teknis Biaya" dan HPS/Dokpil; jangan membuat kesimpulan harga
  bila dokumen biaya belum tersedia.
- Glob dulu untuk list file dan gunakan anchor untuk navigasi, tetapi kualitas
  keputusan mengalahkan hemat token. Jangan berhenti di halaman awal jika bukti
  wajib berada di halaman lain.
- Output WAJIB dalam Bahasa Indonesia.

Langkah:
1. Baca PROTOKOL_EVALUASI_AI.md dan {evaluator_sop} di subfolder
   "5. Evaluator Kualifikasi & Teknis".
2. Cek _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md di ROOT. Jika tidak ada → stop.
3. Glob subfolder "9. Dokumen Teknis Biaya" atau legacy "2. Dokumen Teknis Biaya"
   untuk list file penyedia.
4. Output: _HASIL_EVALUASI_TEKNIS.md (Sesi 2 {sesi_label}) di ROOT folder paket.
   Setelah AI selesai, engine akan menggabungkan hasil Sesi 1 dan Sesi 2 menjadi
   _HASIL_EVALUASI_FINAL_PL_PK.md atau _HASIL_EVALUASI_FINAL_PL_JKK.md.

Mulai sekarang."""


def _prompt_evaluasi_biaya(folder_paket: Path, nama_paket: str) -> str:
    return f"""Lakukan evaluasi biaya (Sesi 3) PLJKK untuk paket berikut.

Nama paket: {nama_paket}
Folder paket: {folder_paket}
SOP evaluasi biaya: {EVALUASI_BIAYA_PLJKK_SOP}

PENTING:
- Sesi 3 hanya boleh dilanjutkan setelah membaca `_HASIL_EVALUASI_TEKNIS.md`.
- Jika teknis GUGUR/TIDAK MEMENUHI, hasil biaya wajib
  `TIDAK DILANJUTKAN — tidak lulus teknis`; jangan audit biaya substantif.
- Gunakan Dokpil paket ini sebagai acuan utama, khususnya LDP, klausul 7.5,
  klausul 10.4, dan bentuk Dokumen Penawaran Biaya.
- Baca dokumen biaya secara selektif dari subfolder `9. Dokumen Teknis Biaya`.
- Jangan mengarang HPS, nilai penawaran, volume, harga satuan, hasil koreksi
  SPSE, atau standar minimum remunerasi.
- Jika tolok ukur remunerasi menurut Dokpil baru dipakai saat negosiasi dan
  tidak tersedia sekarang, catat `AGENDA NEGOSIASI — NONBLOCKING`; jangan
  menahan putusan biaya yang sudah dapat dihitung.
- Dokpil yang dipakai saat fitur ini dibuat memiliki konflik internal:
  klausul 10.4 angka 1 butir 3 menyebut hasil koreksi di atas HPS gugur,
  sedangkan angka 2 menyebut tidak dinyatakan gugur sebelum klarifikasi teknis
  dan negosiasi biaya. Jika konflik tersebut ada pada Dokpil paket, kutip
  keduanya dan beri `KLARIFIKASI WAJIB`; jangan memilih salah satu diam-diam.
- Output WAJIB menyebut file dan halaman/klausul sumber untuk setiap temuan.

Langkah:
1. Baca SOP evaluasi biaya.
2. Baca `_HASIL_EVALUASI_TEKNIS.md`. Jika tidak ditemukan, berhenti dengan
   `ERROR: Sesi 2 belum selesai`.
3. Jika hasil teknis menyatakan GUGUR/TIDAK MEMENUHI, tulis output biaya dengan
   status `TIDAK DILANJUTKAN — tidak lulus teknis`; jangan melakukan penilaian
   biaya substantif.
4. Temukan Dokpil `dokpil_*.pdf`, ambil jenis kontrak dan HPS dari LDP, lalu
   verifikasi aturan biaya paket pada klausul 7.5 dan 10.4.
5. Nilai kelengkapan dokumen biaya, koreksi aritmatik, kesesuaian
   jenis/volume/output, total terkoreksi terhadap HPS, serta kewajaran
   remunerasi Tenaga Ahli sesuai bukti yang tersedia.
6. Tulis `_HASIL_EVALUASI_BIAYA.md` di root folder paket sesuai format SOP.

Mulai sekarang."""


def _prompt_patch_manual_isi_reviu(
    folder_paket: Path,
    docm_path: Path,
    nama_paket: str,
    docx_path: Path | None = None,
) -> str:
    """Prompt satu-klik untuk patch manual Isi Reviu PK Tender."""
    docx_path = docx_path or _reviu_fix_docx_path(folder_paket)
    return f"""Lakukan patch manual Isi Reviu PK untuk paket berikut.

Paket: {nama_paket}
Folder paket: {folder_paket}
File DOCM sumber hasil mail merge (READ-ONLY): {docm_path}
File DOCX target patch AI: {docx_path}
Target final wajib bernama `2. Isi Reviu Fix.docx`; jangan membuat output lain.
Runner sudah mengonversi DOCM ke DOCX memakai Word COM sebelum prompt ini.
SOP WAJIB: {PATCH_MANUAL_SOP}
SOP checklist/domain: {_domain_sop("tender_pk")}
Section domain yang wajib dipakai: `TENDER_PK`. Abaikan section PL_JKK dan PL_PK.

Ikuti kedua SOP tersebut sepenuhnya. Baca SOP dan seluruh dokumen sumber paket yang relevan,
validasi identitas paket sebelum menjawab, lalu periksa seluruh pertanyaan Content Control
di file target. Koreksi/isi jawaban berdasarkan bukti dokumen; jangan mengarang fakta.

Untuk file DOCX target:
- backup unik output lama sudah dibuat runner sebelum konversi jika diperlukan;
- audit Content Control, nested/duplikat, field, dan batas Bagian I sesuai CORE
  dan section TENDER_PK;
- isi hanya CC aktif yang benar-benar ada dan berada dalam scope; jangan membuat
  ulang CC yang hilang, meng-unlock CC, atau mengubah Bagian II;
  koreksi jawaban lama bila tidak sesuai;
- isi `tanggapan_*` sebagai DRAFT tanggapan PPK berdasarkan rekomendasi; jangan
  menulis seolah-olah tanggapan tersebut sudah disetujui PPK;
- teks nyata lama bukan bukti benar dan boleh diganti setelah dibandingkan dengan
  sumber paket; jangan menghapus perubahan manual tanpa membuat backup;
- pertahankan format, tabel, MERGEFIELD, Content Control, dan isi lain yang tidak perlu diubah;
- jangan mengubah DOCM sumber; VBA memang tidak dibawa ke output DOCX;
- simpan file target dan buka ulang melalui Word COM untuk verifikasi;
- pastikan tag/CC aktual tetap sesuai target dan seluruh CC di luar scope tidak
  disentuh.

Setelah selesai, tulis log singkat ke folder paket dengan nama
PATCH_MANUAL_ISI_REVIU_LOG.md yang memuat file target, backup, jumlah CC sebelum/sesudah,
perubahan jawaban, tanggapan draft, dan hasil verifikasi. Jangan hanya menjelaskan
langkah; kerjakan langsung pada DOCX target.
Selain log teknis, tulis `_HASIL_PRA_REVIU_DPP.md` di root paket berisi ringkasan
temuan, daftar klarifikasi, rekomendasi, dan sumber dokumen yang dipakai.
Jika sumber atau file target tidak ditemukan, tulis ERROR dan jangan mengarang.

Mulai sekarang."""


def _validate_reviu_patch_result(
    *,
    source_path: Path,
    source_before,
    target_path: Path,
    target_before,
    audit_path: Path,
    audit_before,
    output: str,
) -> None:
    """Pastikan AI menulis output baru tanpa mengubah source DOCM."""
    import re as _re

    errors = [
        line.strip(" -*")
        for line in (output or "").splitlines()
        if _re.search(r"(?i)\bERROR\b", line)
    ]
    if errors:
        raise RuntimeError(" | ".join(errors[:3]))
    if _file_fingerprint(source_path) != source_before:
        raise RuntimeError("DOCM sumber berubah; proses dihentikan karena source wajib immutable.")
    target_after = _file_fingerprint(target_path)
    if target_after is None:
        raise RuntimeError(f"DOCX target tidak dibuat: {target_path}")
    if target_after == target_before:
        raise RuntimeError("DOCX target tidak berubah setelah AI selesai; patch belum terbukti dilakukan.")
    _validate_docx_zip(target_path)
    _validate_docx_with_word(target_path)
    audit_after = _file_fingerprint(audit_path)
    if audit_after is None or audit_after == audit_before:
        raise RuntimeError("DOCX berubah, tetapi _HASIL_PRA_REVIU_DPP.md belum dibuat/diperbarui.")


def patch_manual_isi_reviu_single(folder_paket, nama_paket: str, engine: str = "codex") -> dict:
    """Jalankan patch manual Isi Reviu PK satu paket via AI CLI."""
    folder = Path(folder_paket)
    docm_path = _find_reviu_docm(folder, "tender_pk")
    docx_path = _reviu_fix_docx_path(folder)
    if not docm_path:
        return {"nama": nama_paket, "status": "error", "output": "", "error": "File hasil mail merge 2. Isi Reviu PK - *(Merged).docm tidak ditemukan. Jalankan Buka Isi Reviu dari Excel terlebih dahulu."}
    if not PATCH_MANUAL_SOP.is_file():
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"SOP tidak ditemukan: {PATCH_MANUAL_SOP}"}
    output = ""
    try:
        source_before = _file_fingerprint(docm_path)
        audit_path = folder / "_HASIL_PRA_REVIU_DPP.md"
        audit_before = _file_fingerprint(audit_path)
        docx_path, backup_path = _convert_reviu_docm_to_docx(docm_path, docx_path)
        target_before = _file_fingerprint(docx_path)
        prompt = _prompt_patch_manual_isi_reviu(folder, docm_path, nama_paket, docx_path)
        output = _run_evaluator(
            prompt, model=DEFAULT_MODEL, timeout=1800,
            add_dirs=[folder, PATCH_MANUAL_SOP.parent], engine=engine,
        )
        _validate_reviu_patch_result(
            source_path=docm_path,
            source_before=source_before,
            target_path=docx_path,
            target_before=target_before,
            audit_path=audit_path,
            audit_before=audit_before,
            output=output,
        )
        return {
            "nama": nama_paket,
            "status": "ok",
            "output": output,
            "error": "",
            "file": str(docx_path),
            "source_file": str(docm_path),
            "backup_file": str(backup_path) if backup_path else "",
        }
    except Exception as e:
        return {
            "nama": nama_paket,
            "status": "error",
            "output": output,
            "error": str(e),
            "file": str(docx_path),
            "source_file": str(docm_path),
        }


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
            return {"nama": nama_paket, "status": "error", "output": "", "error": f"DOCM hasil mail merge {jenis} tidak ditemukan di {folder}. Jalankan Buka Isi Reviu dari Excel terlebih dahulu."}
        domain_sop = _domain_sop(jenis)
        if not domain_sop.is_file() or not PATCH_MANUAL_SOP.is_file():
            return {"nama": nama_paket, "status": "error", "output": "", "error": "SOP reviu atau SOP patch tidak ditemukan."}
        output = ""
        docx_path = _reviu_fix_docx_path(folder)
        source_before = _file_fingerprint(docm_path)
        audit_path = folder / "_HASIL_PRA_REVIU_DPP.md"
        audit_before = _file_fingerprint(audit_path)
        docx_path, backup_path = _convert_reviu_docm_to_docx(docm_path, docx_path)
        target_before = _file_fingerprint(docx_path)
        prompt = _prompt_pra_reviu(folder, nama_paket, docm_path, jenis, docx_path)
        output = _run_evaluator(
            prompt, model=model, timeout=900,
            add_dirs=[folder, PATCH_MANUAL_SOP.parent], engine=engine,
        )
        _validate_reviu_patch_result(
            source_path=docm_path,
            source_before=source_before,
            target_path=docx_path,
            target_before=target_before,
            audit_path=audit_path,
            audit_before=audit_before,
            output=output,
        )
        return {
            "nama": nama_paket,
            "status": "ok",
            "output": output,
            "error": "",
            "file": str(docx_path),
            "source_file": str(docm_path),
            "backup_file": str(backup_path) if backup_path else "",
        }
    except Exception as e:
        return {
            "nama": nama_paket,
            "status": "error",
            "output": output,
            "error": str(e),
            "file": str(locals().get("docx_path", "")),
            "source_file": str(locals().get("docm_path", "")),
        }


def evaluasi_kualifikasi_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False, engine=DEFAULT_ENGINE) -> dict:
    """Evaluasi Admin+Kualifikasi 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl, is_ulang=is_ulang)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    dokumen = _stage_document_status(folder, ("8. Dokumen Kualifikasi",))
    if dokumen["markers"]:
        detail = "; ".join(str(path.relative_to(folder)) for path in dokumen["markers"])
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": f"Dokumen kualifikasi belum lengkap. Marker: {detail}",
        }
    if not dokumen["available"]:
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": "Dokumen kualifikasi belum tersedia; download dan parse dulu.",
        }
    hasil_kualifikasi = folder / "_HASIL_EVALUASI_ADMIN_KUALIFIKASI.md"
    sebelum = hasil_kualifikasi.stat().st_mtime_ns if hasil_kualifikasi.exists() else 0
    try:
        prompt = _prompt_evaluasi_kualifikasi(folder, nama_paket, jenis_pl=jenis_pl)
        # Hanya grant subfolder relevan + root (untuk tulis output .md)
        sub_protokol = folder / "5. Evaluator Kualifikasi & Teknis"
        sub_dokkual = folder / "8. Dokumen Kualifikasi"
        sub_teks = sub_dokkual / "_teks_ekstrak"  # teks hasil pre-extract (hemat token)
        dirs = [d for d in [folder, sub_protokol, sub_dokkual, sub_teks] if d.exists()]
        output = _run_evaluator(prompt, model=model, add_dirs=dirs, engine=engine)
        sesudah = hasil_kualifikasi.stat().st_mtime_ns if hasil_kualifikasi.exists() else 0
        if sesudah <= sebelum or not _valid_stage_output(hasil_kualifikasi):
            return {
                "nama": nama_paket,
                "status": "error",
                "output": output,
                "error": "_HASIL_EVALUASI_ADMIN_KUALIFIKASI.md belum dibuat/diperbarui atau berstatus ERROR.",
            }
        return {
            "nama": nama_paket,
            "status": "ok",
            "output": output,
            "error": "",
            "file": str(hasil_kualifikasi),
        }
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": locals().get("output", ""), "error": str(e)}


def _download_teknis_tidak_lengkap(folder: Path) -> list[Path]:
    return teknis_biaya_document_status(folder)["markers"]


def evaluasi_teknis_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False, engine=DEFAULT_ENGINE) -> dict:
    """Evaluasi Teknis (Sesi 2) 1 paket."""
    folder = _folder_paket(nomor_urut, nama_paket, jenis_pl=jenis_pl, is_ulang=is_ulang)
    if not folder:
        return {"nama": nama_paket, "status": "error", "output": "", "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})"}
    hasil_kualifikasi = folder / "_HASIL_EVALUASI_ADMIN_KUALIFIKASI.md"
    if not _valid_stage_output(hasil_kualifikasi):
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": "Sesi 1 belum selesai: _HASIL_EVALUASI_ADMIN_KUALIFIKASI.md belum valid.",
        }
    dokumen = teknis_biaya_document_status(folder)
    incomplete = dokumen["markers"]
    if incomplete:
        detail = "; ".join(str(path.relative_to(folder)) for path in incomplete)
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": (
                "Dokumen teknis/biaya belum lengkap. Jalankan ulang download "
                f"sebelum evaluasi AI. Marker: {detail}"
            ),
        }
    if not dokumen["available"]:
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": (
                "Dokumen teknis/biaya belum tersedia. Download dari SPSE setelah "
                "evaluasi kualifikasi, lalu jalankan Sesi 2."
            ),
        }
    hasil_teknis = folder / "_HASIL_EVALUASI_TEKNIS.md"
    sebelum = hasil_teknis.stat().st_mtime_ns if hasil_teknis.exists() else 0
    try:
        prompt = _prompt_evaluasi_teknis(folder, nama_paket, jenis_pl=jenis_pl)
        # Hanya grant subfolder relevan + root (untuk baca hasil sesi 1 + tulis output .md)
        sub_protokol = folder / "5. Evaluator Kualifikasi & Teknis"
        sub_dokteknis = folder / "9. Dokumen Teknis Biaya"
        dirs = [d for d in [folder, sub_protokol, sub_dokteknis, *dokumen["roots"]] if d.exists()]
        output = _run_evaluator(prompt, model=model, add_dirs=dirs, engine=engine)
        sesudah = hasil_teknis.stat().st_mtime_ns if hasil_teknis.exists() else 0
        if sesudah <= sebelum:
            return {
                "nama": nama_paket,
                "status": "error",
                "output": output,
                "error": "_HASIL_EVALUASI_TEKNIS.md belum dibuat/diperbarui.",
            }
        isi_teknis = hasil_teknis.read_text(encoding="utf-8", errors="replace").strip()
        if not isi_teknis or not _valid_stage_output(hasil_teknis):
            return {
                "nama": nama_paket,
                "status": "error",
                "output": output,
                "error": "Output evaluasi teknis kosong atau berstatus ERROR.",
            }
        final_path = _compose_final_evaluasi(folder, jenis_pl)
        return {
            "nama": nama_paket,
            "status": "ok",
            "output": output,
            "error": "",
            "file": str(hasil_teknis),
            "final_file": str(final_path),
        }
    except Exception as e:
        return {"nama": nama_paket, "status": "error", "output": "", "error": str(e)}


def evaluasi_biaya_single(nomor_urut, nama_paket: str, model=DEFAULT_MODEL, jenis_pl="JKK", is_ulang=False, engine=DEFAULT_ENGINE) -> dict:
    """Evaluasi Biaya PLJKK (Sesi 3) untuk 1 paket."""
    if jenis_pl != "JKK":
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": "Evaluasi Biaya Sesi 3 saat ini khusus PLJKK.",
        }
    folder = _folder_paket(
        nomor_urut, nama_paket, jenis_pl=jenis_pl, is_ulang=is_ulang
    )
    if not folder:
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": f"Folder paket tidak ditemukan (nomor {nomor_urut})",
        }

    hasil_teknis = folder / "_HASIL_EVALUASI_TEKNIS.md"
    if not hasil_teknis.is_file():
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": "Sesi 2 belum selesai: _HASIL_EVALUASI_TEKNIS.md tidak ditemukan.",
        }
    isi_teknis = hasil_teknis.read_text(encoding="utf-8", errors="replace").strip()
    if not isi_teknis or any(
        line.lstrip().upper().startswith("ERROR")
        for line in isi_teknis.splitlines()
    ):
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": "Sesi 2 belum valid: hasil evaluasi teknis kosong atau ERROR.",
        }
    dokumen = teknis_biaya_document_status(folder)
    if dokumen["markers"]:
        detail = "; ".join(str(path.relative_to(folder)) for path in dokumen["markers"])
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": f"Dokumen teknis/biaya belum lengkap. Marker: {detail}",
        }
    if not dokumen["available"]:
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": "Dokumen teknis/biaya belum tersedia; download dulu sebelum evaluasi biaya.",
        }
    if not EVALUASI_BIAYA_PLJKK_SOP.is_file():
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": f"SOP evaluasi biaya tidak ditemukan: {EVALUASI_BIAYA_PLJKK_SOP}",
        }

    hasil_biaya = folder / "_HASIL_EVALUASI_BIAYA.md"
    sebelum = hasil_biaya.stat().st_mtime_ns if hasil_biaya.exists() else 0
    try:
        prompt = _prompt_evaluasi_biaya(folder, nama_paket)
        sub_dokteknis = folder / "9. Dokumen Teknis Biaya"
        dirs = [
            d
            for d in [folder, sub_dokteknis, *dokumen["roots"], EVALUASI_BIAYA_PLJKK_SOP.parent]
            if d.exists()
        ]
        output = _run_evaluator(
            prompt, model=model, add_dirs=dirs, engine=engine
        )
        sesudah = hasil_biaya.stat().st_mtime_ns if hasil_biaya.exists() else 0
        if sesudah <= sebelum:
            return {
                "nama": nama_paket,
                "status": "error",
                "output": output,
                "error": "_HASIL_EVALUASI_BIAYA.md belum dibuat/diperbarui.",
            }
        isi_biaya = hasil_biaya.read_text(
            encoding="utf-8", errors="replace"
        ).strip()
        if not isi_biaya or any(
            line.lstrip().upper().startswith("ERROR")
            for line in isi_biaya.splitlines()
        ):
            return {
                "nama": nama_paket,
                "status": "error",
                "output": output,
                "error": "Output evaluasi biaya kosong atau berstatus ERROR.",
            }
        return {
            "nama": nama_paket,
            "status": "ok",
            "output": output,
            "error": "",
            "file": str(hasil_biaya),
            "final_file": str(_compose_final_evaluasi(folder, jenis_pl)),
        }
    except Exception as e:
        return {
            "nama": nama_paket,
            "status": "error",
            "output": "",
            "error": str(e),
        }


def evaluasi_bulk(paket_list: list[dict], jenis: str, model=DEFAULT_MODEL,
                  max_workers=3, jenis_pl="JKK", engine=DEFAULT_ENGINE,
                  progress_cb=None) -> list[dict]:
    """
    Evaluasi paralel N paket.
    paket_list: list of {nomor_urut, nama_paket}
    jenis: "pra_reviu" | "kualifikasi" | "teknis" | "biaya"
    Returns list of result dicts.
    """
    fn_map = {
        "pra_reviu":   evaluasi_pra_reviu_single,
        "kualifikasi": evaluasi_kualifikasi_single,
        "teknis":      evaluasi_teknis_single,
        "biaya":       evaluasi_biaya_single,
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
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=2, return_when=FIRST_COMPLETED)
            if not done:
                if progress_cb:
                    progress_cb(None, len(results), len(paket_list), "Masih menunggu Codex/Word COM…")
                continue
            for future in done:
                result = future.result()
                results.append(result)
                if progress_cb:
                    progress_cb(result, len(results), len(paket_list), "Selesai diproses")
    return results
