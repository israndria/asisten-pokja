"""
parse_kak_pl.py — Ekstrak field dari KAK PDF Pengadaan Langsung Konsultan.

Field yang di-extract:
  nama_ppk       — dari baris "NAMA PPK : ..."
  jangka_waktu   — dari pola "X hari / Y bulan kalender"
  sbu_baru       — kode SBU (RK003, AR001, dll) dari klausul Klasifikasi
  jabatan_teknis — dari baris Ketua Tim di tabel personil
  lokasi         — dari poin "Lokasi Kegiatan"

Dipanggil dari app.py Tab 1 setelah buat folder paket PL.
"""
import re
import os


def _text_dari_pdf(pdf_path: str) -> str:
    """Gabung teks semua halaman PDF."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(pg.extract_text() or "" for pg in pdf.pages)
    except Exception:
        return ""


def _extract_nama_ppk(teks: str) -> str:
    m = re.search(r"NAMA PPK\s*:\s*(.+)", teks)
    if m:
        return m.group(1).strip()
    return ""


def _extract_jangka_waktu(teks: str) -> str:
    """
    Cari pola 'X hari / Y bulan kalender' → kembalikan string "X hari / Y bulan kalender".
    Fallback: cari pola 'X (kata) hari kalender' saja.
    """
    # Pola lengkap: 30 hari / 1 bulan kalender
    m = re.search(
        r"(\d+)\s*\([^)]+\)\s*hari\s*/?\s*\d*\s*\([^)]+\)\s*bulan\s*kalender",
        teks, re.IGNORECASE,
    )
    if m:
        hari = re.search(r"(\d+)\s*\([^)]+\)\s*hari", m.group(0), re.IGNORECASE)
        bulan = re.search(r"(\d+)\s*\([^)]+\)\s*bulan", m.group(0), re.IGNORECASE)
        if hari and bulan:
            return f"{hari.group(1)} hari / {bulan.group(1)} bulan kalender"

    # Fallback: X hari kalender
    m2 = re.search(r"(\d+)\s*\([^)]+\)\s*(?:hari|kalender)", teks, re.IGNORECASE)
    if m2:
        return m2.group(0).strip()

    return ""


def _extract_sbu(teks: str) -> tuple[str, str]:
    """Kode SBU + nama lengkap dari master_sbu Supabase.

    Returns: (sbu_baru_lengkap, sbu_lama_lengkap)
    Contoh:
      sbu_baru = "Subklasifikasi RK003 (KBLI 2020) Jasa Rekayasa Pekerjaan Teknik Sipil Transportasi."
      sbu_lama = "Subklasifikasi Jasa Nasehat dan Konsultansi Rekayasa Teknik (KBLI 2017) RE101"
    """
    m = re.search(r"\b(RK\d{3}|AR\d{3}|SI\d{3}|BG\d{3}|SP\d{3}|EL\d{3}|MK\d{3})\b", teks)
    if not m:
        return ("", "")

    kode = m.group(1)

    # Lookup master_sbu
    try:
        from config import sb as _sb
        r = _sb().table("master_sbu").select("sbu_baru,sbu_lama").like("sbu_baru", f"%{kode}%").execute()
        if r.data:
            row = r.data[0]
            return (row.get("sbu_baru") or kode, row.get("sbu_lama") or "")
    except Exception:
        pass

    return (kode, "")


def _extract_jabatan_k3(teks: str) -> str:
    """
    Dari tabel personil KAK, baris K3:
    - 'Petugas K3 Konstruksi' (konsultan kecil/PL)
    - 'Ahli K3 Konstruksi' (risiko tinggi)
    """
    m = re.search(r"(Ahli K3 Konstruksi|Petugas K3(?:\s+Konstruksi)?|Petugas Keselamatan Konstruksi)",
                  teks, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        # Normalisasi ke nama lengkap
        if re.search(r"Ahli K3", raw, re.IGNORECASE):
            return "Ahli K3 Konstruksi"
        if re.search(r"Petugas K3", raw, re.IGNORECASE):
            return "Petugas K3 Konstruksi"
        return raw.title()
    return ""


def _extract_jabatan_teknis(teks: str) -> str:
    """
    Baris pertama tabel personil = Ketua Tim.
    Pola: 'Ketua Tim[/Ahli ...]'
    """
    m = re.search(r"Ketua Tim\s*/?\s*Ahli\s+([\w\s]+?)(?:\s*\(|$)", teks, re.IGNORECASE)
    if m:
        return ("Ahli " + m.group(1).strip()).title()

    m2 = re.search(r"Ketua Tim\s*(.{0,40}?)(?:\n|\(|$)", teks, re.IGNORECASE)
    if m2:
        raw = m2.group(1).strip().rstrip("/")
        return ("Ketua Tim " + raw).strip() if raw else "Ketua Tim"

    return ""


def _extract_lokasi(teks: str) -> str:
    """Default 'Kabupaten Tapin'. Tidak parse dari KAK karena selalu sama."""
    return "Kabupaten Tapin"


def parse_kak(pdf_path: str) -> dict:
    """
    Parse KAK PDF, kembalikan dict field.
    Semua field bisa kosong string jika tidak ditemukan.
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return {}

    sbu_baru, sbu_lama = _extract_sbu(teks)
    return {
        "nama_ppk":     _extract_nama_ppk(teks),
        "jangka_waktu": _extract_jangka_waktu(teks),
        "sbu_baru":     sbu_baru,
        "sbu_lama":     sbu_lama,
        "jabatan_k3":   _extract_jabatan_k3(teks),
        "lokasi":       _extract_lokasi(teks),
    }


def cari_kak_di_folder(folder: str) -> str | None:
    """
    Cari file KAK PDF di folder.
    Prioritas: nama mengandung 'KAK' (case-insensitive).
    """
    if not os.path.isdir(folder):
        return None
    candidates = []
    for f in os.listdir(folder):
        fl = f.lower()
        if fl.endswith(".pdf") and "kak" in fl:
            candidates.append(os.path.join(folder, f))
    if candidates:
        return sorted(candidates)[0]
    # Fallback: PDF pertama
    for f in os.listdir(folder):
        if f.lower().endswith(".pdf"):
            return os.path.join(folder, f)
    return None


# ============================================================
# Parse Draft_PL PDF — extract nama_penyedia + NPWP penyedia
# ============================================================

def cari_draft_pl_di_folder(folder: str) -> str | None:
    """Cari PDF Draft_PL_*.pdf di folder paket."""
    if not os.path.isdir(folder):
        return None
    for f in os.listdir(folder):
        fl = f.lower()
        if fl.endswith(".pdf") and fl.startswith("draft_pl"):
            return os.path.join(folder, f)
    return None


def parse_draft_pl(pdf_path: str) -> dict:
    """Parse Draft_PL PDF — ekstrak nama_penyedia + npwp_penyedia dari halaman SURAT REKOMENDASI.

    Format yang dicari:
        Nama Perusahaan : CV. MEDIA TALENTA MUDA
        NPWP Perusahaan : 31854730733000
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return {}

    out = {"nama_penyedia": "", "npwp_penyedia": ""}

    m_nama = re.search(
        r"Nama\s+Perusahaan\s*:\s*(.+?)(?:\n|$)",
        teks, re.IGNORECASE,
    )
    if m_nama:
        out["nama_penyedia"] = m_nama.group(1).strip()

    m_npwp = re.search(
        r"NPWP\s+Perusahaan\s*:\s*([0-9.\-\s]+)",
        teks, re.IGNORECASE,
    )
    if m_npwp:
        npwp = re.sub(r"[.\-\s]", "", m_npwp.group(1)).strip()
        out["npwp_penyedia"] = npwp

    return out


def _resolve_folder_pl(nomor_urut, nama_paket: str, jenis_pl: str) -> str | None:
    """Cari folder paket PL di OUTPUT_DIR_PL_{JKK|PK}.

    Pola: '{nomor}. PL{jenis} - {nama_clean}'.
    Fallback: scan folder yg endswith nama_clean.
    """
    from config import OUTPUT_DIR_PL_JKK, OUTPUT_DIR_PL_PK, sanitasi_nama_folder

    jenis = (jenis_pl or "JKK").upper()
    root = OUTPUT_DIR_PL_JKK if jenis == "JKK" else OUTPUT_DIR_PL_PK
    if not os.path.isdir(root):
        return None

    nama_clean = sanitasi_nama_folder(nama_paket or "")
    nomor = nomor_urut or ""
    folder_name = f"{nomor}. PL{jenis} - {nama_clean}"
    candidate = os.path.join(root, folder_name)
    if os.path.isdir(candidate):
        return candidate
    # Fallback: cari folder yg endswith nama_clean
    for f in os.listdir(root):
        full = os.path.join(root, f)
        if os.path.isdir(full) and (f.endswith(nama_clean) or nama_clean in f):
            return full
    return None


def serap_penyedia_pl(progress_cb=None) -> dict:
    """Bulk: loop semua paket PL di Supabase, cari Draft_PL.pdf di folder,
    parse nama_penyedia + npwp_penyedia, upsert ke draft_paket_pl.
    """
    from config import sb as _sb

    def log(p, m):
        if progress_cb:
            progress_cb(p, m)

    log(0.05, "Fetch daftar paket PL dari Supabase...")
    rows = _sb().table("draft_paket_pl").select("kode_paket,nama_paket,nomor_urut,jenis_pl").execute().data or []
    log(0.10, f"Total {len(rows)} paket")

    updated = 0
    not_found = 0
    no_data = 0
    errors = []
    total = max(len(rows), 1)
    for i, p in enumerate(rows):
        prog = 0.10 + 0.85 * ((i + 1) / total)
        kode = p["kode_paket"]
        nama = p["nama_paket"] or ""
        try:
            folder = _resolve_folder_pl(p.get("nomor_urut"), nama, p.get("jenis_pl") or "JKK")
            if not folder:
                not_found += 1
                log(prog, f"  - {kode}: folder paket tidak ditemukan")
                continue

            pdf = cari_draft_pl_di_folder(folder)
            if not pdf:
                not_found += 1
                log(prog, f"  - {kode}: Draft_PL PDF tidak ditemukan di {os.path.basename(folder)}")
                continue

            data = parse_draft_pl(pdf)
            update = {k: v for k, v in data.items() if v}
            if not update:
                no_data += 1
                log(prog, f"  - {kode}: PDF ada tapi tidak ada Nama/NPWP Perusahaan")
                continue

            _sb().table("draft_paket_pl").update(update).eq("kode_paket", kode).execute()
            updated += 1
            log(prog, f"  OK {kode}: {update.get('nama_penyedia', '')[:30]} / {update.get('npwp_penyedia', '')}")
        except Exception as e:
            errors.append(f"{kode}: {e}")

    log(1.0, f"Selesai: updated={updated} not_found={not_found} no_data={no_data} errors={len(errors)}")
    return {"ok": True, "updated": updated, "not_found": not_found, "no_data": no_data, "errors": errors}


# ── CLI self-test ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python parse_kak_pl.py path/to/KAK.pdf")
        sys.exit(1)
    result = parse_kak(path)
    for k, v in result.items():
        print(f"  {k:20s}: {v}")
