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

    return {
        "nama_ppk":     _extract_nama_ppk(teks),
        "jangka_waktu": _extract_jangka_waktu(teks),
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
    """Parse Draft_PL PDF — ekstrak nama_penyedia, npwp_penyedia, nomor_rekomendasi,
    tgl_rekomendasi, nomor_nota_dinas dari halaman SURAT REKOMENDASI + NOTA DINAS.

    Format yang dicari:
        Nama Perusahaan : CV. MEDIA TALENTA MUDA
        NPWP Perusahaan : 31854730733000
        SURAT REKOMENDASI
        Nomor : 600.1.15.4/009/Srt-Rekom/PPK/BM/V/2026
        Tanggal : 12 Mei 2026
        NOTA DINAS
        Nomor : 000.4.1/066/PPK/DPUPR-BM/V/2026
    """
    import datetime
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return {}

    out = {
        "nama_penyedia": "",
        "npwp_penyedia": "",
        "nomor_rekomendasi": "",
        "tgl_rekomendasi": None,
        "nomor_nota_dinas": "",
    }

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

    # Nomor Surat Rekomendasi
    m_rekom_no = re.search(
        r"SURAT\s+REKOMENDASI\s*\n[^\n]*Nomor\s*:\s*(.+?)[\n\r]",
        teks, re.IGNORECASE,
    )
    if not m_rekom_no:
        m_rekom_no = re.search(
            r"SURAT\s+REKOMENDASI.*?Nomor\s*:\s*(.+?)[\n\r]",
            teks, re.IGNORECASE | re.DOTALL,
        )
    if m_rekom_no:
        out["nomor_rekomendasi"] = m_rekom_no.group(1).strip()

    # Tanggal Surat Rekomendasi → date
    _BULAN = {
        "januari": 1, "februari": 2, "maret": 3, "april": 4,
        "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
        "september": 9, "oktober": 10, "november": 11, "desember": 12,
    }
    m_rekom_tgl = re.search(
        r"SURAT\s+REKOMENDASI.*?Tanggal\s*:\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
        teks, re.IGNORECASE | re.DOTALL,
    )
    if m_rekom_tgl:
        hari = int(m_rekom_tgl.group(1))
        bln = _BULAN.get(m_rekom_tgl.group(2).lower())
        thn = int(m_rekom_tgl.group(3))
        if bln:
            try:
                out["tgl_rekomendasi"] = datetime.date(thn, bln, hari).isoformat()
            except ValueError:
                pass

    # Nomor Nota Dinas
    m_nota = re.search(
        r"NOTA\s+DINAS\s*\n[^\n]*Nomor\s*:\s*(.+?)[\n\r]",
        teks, re.IGNORECASE,
    )
    if not m_nota:
        m_nota = re.search(
            r"NOTA\s+DINAS.*?Nomor\s*:\s*(.+?)[\n\r]",
            teks, re.IGNORECASE | re.DOTALL,
        )
    if m_nota:
        out["nomor_nota_dinas"] = m_nota.group(1).strip()

    return out


def parse_sub_kegiatan_dari_draft_pl(pdf_path: str) -> str:
    """Extract Sub Kegiatan atau Kegiatan dari Draft_PL PDF — pilih yang lebih pendek.

    Keduanya valid secara substansi; Sub Kegiatan biasanya lebih spesifik tapi lebih panjang.
    Jika keduanya tersedia, ambil yang karakternya lebih sedikit.
    Fallback: jika hanya satu tersedia, ambil itu.
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return ""

    sub_keg = ""
    keg = ""

    # Toleransi: spasi ganda, separator : atau - atau =, multi-line value
    m = re.search(
        r"NAMA\s+SUB\s+KEGIATAN\s*[:\-=]\s*(.+?)(?=NAMA\s+PAKET|TAHUN\s+ANGGARAN|\n\s*\n)",
        teks, re.IGNORECASE | re.DOTALL,
    )
    if m:
        sub_keg = re.sub(r"\s+", " ", m.group(1).strip()).strip()

    # Stop terminator tidak bergantung urutan sub kegiatan vs kegiatan
    m2 = re.search(
        r"NAMA\s+KEGIATAN\s*[:\-=]\s*(.+?)(?=NAMA\s+(?:SUB\s+)?(?:KEGIATAN|PAKET)|TAHUN|\n)",
        teks, re.IGNORECASE,
    )
    if m2:
        raw2 = re.sub(r"\s+", " ", m2.group(1).strip()).strip()
        # Pastikan tidak menangkap label berikutnya (artefak OCR tanpa newline)
        raw2 = re.split(r"\bNAMA\b", raw2, maxsplit=1)[0].strip()
        keg = raw2

    if sub_keg and keg:
        return sub_keg if len(sub_keg) <= len(keg) else keg
    return sub_keg or keg


def cari_daftar_personil_di_folder(folder: str) -> str | None:
    """Cari PDF 'Daftar Personil*.pdf' di folder paket (case-insensitive)."""
    if not os.path.isdir(folder):
        return None
    for f in os.listdir(folder):
        fl = f.lower()
        if fl.endswith(".pdf") and ("daftar personil" in fl or "personil" in fl):
            if fl.startswith("draft_pl"):
                continue
            return os.path.join(folder, f)
    return None


def _extract_sertifikat_dari_jabatan(jabatan_str: str) -> str:
    """Tebak sertifikat dari teks jabatan (regex keyword matching).

    Pola:
    - "SKA/SKK [Bidang] [Level]" -> "SKK [Bidang] - Ahli [Level]"
    - "K3 Konstruksi" + "Petugas/Ahli" -> "SKK Petugas K3 Konstruksi" / "SKA Ahli K3 Konstruksi"
    - "Sertifikasi ..." -> "Sertifikat ..."
    - Fallback: "" kosong (tidak memaksa tebakan)
    """
    if not jabatan_str:
        return ""
    s = jabatan_str

    # Pattern 1: SKK/SKA eksplisit + bidang + level (Muda/Madya/Utama)
    m = re.search(
        r"SK[AK]/?SK[AK]?\s+([\w/\s]+?)\s+(?:Ahli\s+)?(Muda|Madya|Utama)",
        s, re.IGNORECASE,
    )
    if m:
        bidang = re.sub(r"\s+", " ", m.group(1)).strip().rstrip("/")
        level = m.group(2).strip().title()
        return f"SKK {bidang} - Ahli {level}"

    # Pattern 2: K3 Konstruksi
    if re.search(r"K3\s+Konstruksi", s, re.IGNORECASE):
        if re.search(r"\bAhli\b", s, re.IGNORECASE):
            return "SKA Ahli K3 Konstruksi"
        return "SKK Petugas K3 Konstruksi"

    # Pattern 3: Sertifikasi eksplisit
    m2 = re.search(r"Sertifikasi\s+([^,\)]+?)(?:\)|,|$)", s, re.IGNORECASE)
    if m2:
        return f"Sertifikat {m2.group(1).strip()}"

    return ""


def parse_personil_daftar(pdf_path: str) -> list[dict]:
    """Parse Daftar Personil PDF ke list of {jabatan, pengalaman, sertifikat} (max 6).

    Pola tiap baris: '<no> <jabatan...> <N Tahun>'.
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return []

    personil = []
    for line in teks.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s+(.+?)\s+(\d+\s*[Tt]ahun)\s*$", line)
        if m:
            jabatan = m.group(2).strip()
            idx_p = len(personil)
            sertifikat = _extract_sertifikat_dari_jabatan(jabatan) if idx_p < 2 else "(Tidak Dipersyaratkan)"
            personil.append({
                "jabatan": jabatan,
                "pengalaman": m.group(3).strip(),
                "sertifikat": sertifikat,
            })
            if len(personil) >= 6:
                break
    return personil


def parse_personil_dari_draft_pl(pdf_path: str) -> list[dict]:
    """Fallback: parse personil dari Draft_PL PDF section 'Personil Inti'."""
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return []

    idx = teks.lower().find("personil inti")
    if idx < 0:
        return []

    sub = teks[idx:idx + 3000]
    personil = []
    for line in sub.split("\n"):
        line = line.strip()
        m = re.match(r"^(\d+)\s+(.+?)\s+(\d+\s*[Tt]ahun)\s*$", line)
        if m:
            jabatan = m.group(2).strip()
            idx_p = len(personil)
            sertifikat = _extract_sertifikat_dari_jabatan(jabatan) if idx_p < 2 else "(Tidak Dipersyaratkan)"
            personil.append({
                "jabatan": jabatan,
                "pengalaman": m.group(3).strip(),
                "sertifikat": sertifikat,
            })
            if len(personil) >= 6:
                break
    return personil


def ekstrak_personil_3layer(folder: str, fallback_jabatan_teknis: str = "", fallback_jabatan_k3: str = "") -> list[dict]:
    """3-layer extraction:
    Layer 1: Daftar Personil PDF
    Layer 2: Draft_PL PDF (section Personil Inti)
    Layer 3: fallback Supabase (jabatan_teknis + jabatan_k3 — slot 1+2)
    Tiap item: {jabatan, pengalaman, sertifikat}
    """
    daftar_pdf = cari_daftar_personil_di_folder(folder)
    if daftar_pdf:
        result = parse_personil_daftar(daftar_pdf)
        if result:
            return result

    draft_pdf = cari_draft_pl_di_folder(folder)
    if draft_pdf:
        result = parse_personil_dari_draft_pl(draft_pdf)
        if result:
            return result

    result = []
    if fallback_jabatan_teknis:
        result.append({
            "jabatan": fallback_jabatan_teknis,
            "pengalaman": "1 Tahun",
            "sertifikat": _extract_sertifikat_dari_jabatan(fallback_jabatan_teknis),
        })
    if fallback_jabatan_k3:
        result.append({
            "jabatan": fallback_jabatan_k3,
            "pengalaman": "1 Tahun",
            "sertifikat": _extract_sertifikat_dari_jabatan(fallback_jabatan_k3),
        })
    return result


def _resolve_folder_pl(nomor_urut, nama_paket: str, jenis_pl: str, is_ulang: bool = False) -> str | None:
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

    if is_ulang:
        folder_ulang_name = f"{nomor}. PL{jenis} - {nama_clean} (PL - Ulang)"
        folder_ulang = os.path.join(root, folder_ulang_name)
        if os.path.isdir(folder_ulang):
            return folder_ulang

    nama_lower = nama_clean.lower()
    folder_name = f"{nomor}. PL{jenis} - {nama_clean}"
    candidate = os.path.join(root, folder_name)
    if os.path.isdir(candidate):
        if not is_ulang:
            return candidate
    best = None
    best_score = 0
    for f in os.listdir(root):
        full = os.path.join(root, f)
        if not os.path.isdir(full):
            continue
        fl = f.lower()
        ulang_in_f = "(pl - ulang)" in fl or "(pl-ulang)" in fl
        if is_ulang and not ulang_in_f:
            continue
        if not is_ulang and ulang_in_f:
            continue
        # Prioritas 1: exact suffix (case-insensitive)
        if fl.endswith(nama_lower) or fl.rstrip().endswith(nama_lower + " (pl - ulang)"):
            return full
        # Prioritas 2: semua kata nama ada di nama folder (word-set match)
        words = set(nama_lower.split())
        folder_words = set(fl.split())
        common = len(words & folder_words)
        if common > best_score and common == len(words):
            best_score = common
            best = full
    return best


def serap_penyedia_pl(progress_cb=None, kode_paket_filter: str = None) -> dict:
    """Bulk: loop semua paket PL di Supabase, cari Draft_PL.pdf di folder,
    parse nama_penyedia + npwp_penyedia, upsert ke draft_paket_pl.
    Jika kode_paket_filter diisi, hanya proses paket dengan kode tersebut.
    """
    from config import sb as _sb

    def log(p, m):
        if progress_cb:
            progress_cb(p, m)

    log(0.05, "Fetch daftar paket PL dari Supabase...")
    rows = _sb().table("draft_paket_pl").select("kode_paket,nama_paket,nomor_urut,jenis_pl,jabatan_teknis,jabatan_k3,is_ulang").execute().data or []
    if kode_paket_filter:
        rows = [r for r in rows if r["kode_paket"] == kode_paket_filter]
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
            folder = _resolve_folder_pl(p.get("nomor_urut"), nama, p.get("jenis_pl") or "JKK", is_ulang=p.get("is_ulang", False))
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

            # Sub Kegiatan dari Draft_PL
            sub_keg = parse_sub_kegiatan_dari_draft_pl(pdf)
            if sub_keg:
                data["sub_kegiatan"] = sub_keg

            # Personil 3-layer
            personil = ekstrak_personil_3layer(
                folder,
                fallback_jabatan_teknis=p.get("jabatan_teknis") or "",
                fallback_jabatan_k3=p.get("jabatan_k3") or "",
            )
            if personil:
                data["personil_json"] = personil  # supabase-py auto-encode list ke JSONB

            update = {k: v for k, v in data.items() if v}
            if not update:
                no_data += 1
                log(prog, f"  - {kode}: PDF ada tapi tidak ada data yang bisa diekstrak")
                continue

            _sb().table("draft_paket_pl").update(update).eq("kode_paket", kode).execute()
            updated += 1
            pn = update.get("nama_penyedia", "")[:25]
            sk = update.get("sub_kegiatan", "")[:30]
            np = len(personil)
            log(prog, f"  OK {kode}: penyedia={pn} sub_keg={bool(sk)} personil={np}")
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
