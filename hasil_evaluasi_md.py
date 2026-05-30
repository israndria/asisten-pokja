"""
Export hasil evaluasi penyedia ke _HASIL_EVALUASI.md per folder paket.

Desain 2-zona dengan marker comment:
  Zona [DATA]    : auto-generate engine (regenerate tiap evaluasi ulang)
  Zona [ANALISIS]: diisi AI evaluator — engine TIDAK PERNAH menimpa

Aturan:
- Kalau marker penyedia sudah ada → replace HANYA isi DATA di antara marker.
- Kalau penyedia baru → append blok DATA + ANALISIS kosong di akhir file.
- Zona [ANALISIS] SELALU preserve apa adanya.
"""

import os
import re
from datetime import datetime


# ── Konstanta marker ───────────────────────────────────────────────────────────

_FILENAME = "_HASIL_EVALUASI.md"
_HEADER_TEMPLATE = "# Hasil Evaluasi — {nama_paket}\n> Zona [DATA] auto-generate engine (regenerate tiap evaluasi ulang). Zona [ANALISIS] diisi AI evaluator manual — engine TIDAK menimpa.\n\n"
_DATA_START = "<!-- DATA:START:{key} -->"
_DATA_END   = "<!-- DATA:END:{key} -->"


def _norm_key(nama: str) -> str:
    """Normalize nama penyedia jadi key marker: strip, lowercase, ganti spasi/titik/koma → _."""
    return re.sub(r"[^\w]", "_", nama.strip().lower()).strip("_")


def _escape_pipe(s) -> str:
    """Escape pipe | di string agar tidak rusak tabel Markdown."""
    return str(s).replace("|", "\\|")


def _build_data_block(nama_penyedia: str, rows: list, eval_date: str) -> str:
    """Bangun blok [DATA] lengkap untuk satu penyedia (termasuk marker)."""
    key = _norm_key(nama_penyedia)
    lines = []
    lines.append(_DATA_START.format(key=key))
    lines.append(f"## [DATA] {nama_penyedia}  (eval: {eval_date})")
    lines.append("| No | Field | Kategori | Sumber | Status | Catatan |")
    lines.append("|---|---|---|---|---|---|")
    for row in rows:
        # row = [No, Field, Kategori, Sumber, Status, Catatan]
        cells = [_escape_pipe(c) for c in row]
        # pad ke 6 kolom jika kurang
        while len(cells) < 6:
            cells.append("")
        lines.append("| " + " | ".join(cells[:6]) + " |")
    lines.append(_DATA_END.format(key=key))
    return "\n".join(lines) + "\n"


def _analisis_placeholder(nama_penyedia: str) -> str:
    """Blok [ANALISIS] kosong untuk penyedia baru."""
    return (
        f"\n## [ANALISIS] {nama_penyedia}\n"
        "<!-- AI evaluator tulis verdict/kekurangan di sini. Engine TIDAK sentuh blok ini. -->\n\n"
    )


def export_hasil_md(
    folder_paket: str,
    nama_paket: str,
    peserta_rows: list,
    log=None,
) -> bool:
    """
    Tulis/update _HASIL_EVALUASI.md di folder_paket.

    Args:
        folder_paket : path absolut folder paket (tempat tulis _HASIL_EVALUASI.md)
        nama_paket   : judul paket (untuk header file)
        peserta_rows : list of dict, tiap dict = 1 penyedia:
                       {"nama": str, "rows": [[No, Field, Kategori, Sumber, Status, Catatan], ...]}
        log          : callable(str) opsional untuk progress

    Return: True jika sukses, False jika gagal.
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    if not folder_paket or not os.path.isdir(folder_paket):
        _log(f"[MD Export] Folder tidak valid: {folder_paket}")
        return False

    output_path = os.path.join(folder_paket, _FILENAME)
    eval_date = datetime.now().strftime("%Y-%m-%d")

    # Baca file existing (kalau ada)
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
    else:
        # Buat header baru
        content = _HEADER_TEMPLATE.format(nama_paket=nama_paket)

    # Proses tiap penyedia
    for peserta in peserta_rows:
        nama = peserta.get("nama", "Tidak Diketahui")
        rows = peserta.get("rows", [])
        key  = _norm_key(nama)

        data_block = _build_data_block(nama, rows, eval_date)

        # Cek apakah marker sudah ada di file
        pattern = re.compile(
            re.escape(_DATA_START.format(key=key))
            + r".*?"
            + re.escape(_DATA_END.format(key=key)),
            re.DOTALL,
        )

        if pattern.search(content):
            # Penyedia sudah ada → replace HANYA zona DATA, ANALISIS dibiarkan
            content = pattern.sub(data_block.rstrip("\n"), content)
            _log(f"[MD Export] Update DATA: {nama}")
        else:
            # Penyedia baru → append blok DATA + ANALISIS kosong
            if not content.endswith("\n"):
                content += "\n"
            content += data_block
            content += _analisis_placeholder(nama)
            _log(f"[MD Export] Append penyedia baru: {nama}")

    # Tulis ke file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    _log(f"[MD Export] Selesai → {output_path}")
    return True
