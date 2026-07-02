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
    m = re.search(r"NAMA PPK\s*:\s*(.+)", teks, re.IGNORECASE)
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


def _extract_sub_kegiatan_dari_kak(teks: str) -> str:
    """Extract Sub Kegiatan dari KAK PDF (header halaman cover KAK)."""
    # KAK tulis: "SUB KEGITAN\nPENYEDIAAN SARANA..." (typo: KEGITAN bukan KEGIATAN)
    m = re.search(
        r"SUB\s+KEGITA?N\s*\n(.+?)(?=\n[A-Z]{3,}|\nPEKERJAAN|\Z)",
        teks, re.IGNORECASE | re.DOTALL,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


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
        "sub_kegiatan": _extract_sub_kegiatan_dari_kak(teks),
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
    """Cari PDF Draft_PL_*.pdf di folder paket (root atau subfolder 0. Draft Dokumen PPK)."""
    if not os.path.isdir(folder):
        return None
    # Cek subfolder 0. Draft Dokumen PPK dulu (lokasi baru)
    subfolder_0 = os.path.join(folder, "0. Draft Dokumen PPK")
    for search_dir in [subfolder_0, folder]:
        if not os.path.isdir(search_dir):
            continue
        for f in os.listdir(search_dir):
            fl = f.lower()
            if fl.endswith(".pdf") and fl.startswith("draft_pl"):
                return os.path.join(search_dir, f)
    return None


def cari_nd_di_folder(folder: str) -> str | None:
    """Cari 8. ND.pdf di subfolder '4. Informasi Lainnya' dalam folder paket."""
    if not os.path.isdir(folder):
        return None
    subfolder = os.path.join(folder, "4. Informasi Lainnya")
    if not os.path.isdir(subfolder):
        return None
    for f in os.listdir(subfolder):
        if f.lower() == "8. nd.pdf":
            return os.path.join(subfolder, f)
    # fallback: file apapun yang mengandung "nd" dan berakhiran .pdf
    for f in os.listdir(subfolder):
        fl = f.lower()
        if fl.endswith(".pdf") and ("nd" in fl or "nota" in fl):
            return os.path.join(subfolder, f)
    return None


def parse_nd_penyedia(pdf_path: str) -> dict:
    """Parse ND/Nota Dinas PDF — ekstrak nama_penyedia + npwp_penyedia.

    Mendukung dua format:
      Format A (baru): "Nama Calon Penyedia : CV. ..."  + "Nomor NPWP : 082..."
      Format B (lama): "Nama Perusahaan : CV. ..."      + "NPWP Perusahaan : 72.112..."
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return {}

    out = {"nama_penyedia": "", "npwp_penyedia": ""}

    # Nama: coba "Nama Calon Penyedia" dulu, fallback "Nama Perusahaan"
    m_nama = re.search(r"Nama\s+Calon\s+Penyedia\s*:\s*(.+?)(?:\n|$)", teks, re.IGNORECASE)
    if not m_nama:
        m_nama = re.search(r"Nama\s+Perusahaan\s*:\s*(.+?)(?:\n|$)", teks, re.IGNORECASE)
    if m_nama:
        out["nama_penyedia"] = m_nama.group(1).strip()

    # NPWP: coba "Nomor NPWP" (inline/baris pisah), fallback "NPWP Perusahaan"
    # Format angka dengan/tanpa titik-strip: 72.112.192.9-731.000 atau 0826618548735000
    _npwp_pat = r"[\d.\-]{10,25}"
    m_npwp = re.search(
        r"Nomor\s+NPWP\s*[:\n\r]+\s*(" + _npwp_pat + r")",
        teks, re.IGNORECASE | re.DOTALL,
    )
    if not m_npwp:
        m_npwp = re.search(
            r"NPWP\s+Perusahaan\s*:\s*(" + _npwp_pat + r")",
            teks, re.IGNORECASE,
        )
    if m_npwp:
        out["npwp_penyedia"] = re.sub(r"[.\-\s]", "", m_npwp.group(1)).strip()

    return out


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
    """Cari PDF 'Daftar Personil*.pdf' di folder paket atau subfolder '1. KAK*' (case-insensitive)."""
    if not os.path.isdir(folder):
        return None

    def _cari_di(d: str):
        for f in os.listdir(d):
            fl = f.lower()
            if fl.endswith(".pdf") and ("daftar personil" in fl or "personil" in fl):
                if fl.startswith("draft_pl"):
                    continue
                return os.path.join(d, f)
        return None

    # Cari di root folder dulu
    hasil = _cari_di(folder)
    if hasil:
        return hasil
    # Cari di subfolder "1. KAK*" / "KAK*"
    try:
        for sub in os.listdir(folder):
            sub_lower = sub.lower()
            if sub_lower.startswith("1. kak") or sub_lower.startswith("kak"):
                sub_path = os.path.join(folder, sub)
                if os.path.isdir(sub_path):
                    hasil = _cari_di(sub_path)
                    if hasil:
                        return hasil
    except Exception:
        pass
    return None


def _is_petugas_jenjang_rendah(jabatan_str: str) -> bool:
    """Deteksi 'Petugas K3' / 'Petugas Keselamatan' (jenjang petugas 3/4, BUKAN Ahli K3).

    Dipakai untuk mengecualikan baris ini dari Tenaga Ahli walau berada di section
    'TENAGA AHLI' pada tabel HPS (PPK kadang menaruh Petugas K3 di section tsb).
    """
    if not jabatan_str:
        return False
    s = jabatan_str
    # 'Ahli K3' tetap Tenaga Ahli — jangan dikecualikan
    if re.search(r"\bAhli\s+K3\b", s, re.IGNORECASE):
        return False
    return bool(re.search(r"\bPetugas\s+(?:K3|Keselamatan)\b", s, re.IGNORECASE))


def _is_tenaga_ahli(jabatan_str: str) -> bool:
    """Klasifikasi baris personil: Tenaga Ahli atau bukan (untuk sumber PDF Daftar Personil).

    Tenaga Ahli = teks jabatan mengandung 'SKA' (Sertifikat Keahlian, jenjang ahli)
                  ATAU mengandung 'Ahli K3' (K3 jenjang 7, bukan Petugas K3).

    Bukan Tenaga Ahli:
    - SKK saja (Sertifikat Kompetensi Kerja) — bisa jenjang operator/teknisi, bukan ahli
    - Petugas K3 (jenjang 3/4) — SKK, bukan SKA
    - Surveyor, Admin, Estimator, Drafter tanpa SKA

    Catatan: untuk sumber HPS gunakan konteks section (lihat parse_personil_dari_hps)
    yang loloskan semua item di section 'TENAGA AHLI' KECUALI Petugas K3.
    """
    if not jabatan_str:
        return False
    s = jabatan_str
    if re.search(r"\bSKA\b", s, re.IGNORECASE):
        return True
    if re.search(r"\bAhli\s+K3\b", s, re.IGNORECASE):
        return True
    return False


def _extract_sertifikat_dari_jabatan(jabatan_str: str) -> str:
    """Tebak sertifikat dari teks jabatan (regex keyword matching).

    Dipanggil hanya untuk Tenaga Ahli (baris yang lolos _is_tenaga_ahli).
    Pola:
    - "SKA/SKK [Bidang] [Level Muda/Madya/Utama]" -> "SKA [Bidang] - Ahli [Level]"
    - "Ahli K3" -> "SKA Ahli K3 Konstruksi"
    - Fallback: ambil segmen setelah "SKA" sampai koma/paren pertama
    """
    if not jabatan_str:
        return ""
    s = jabatan_str

    # Pattern 0 (prioritas): Ahli K3 Konstruksi (jenjang 7)
    if re.search(r"\bAhli\s+K3\b", s, re.IGNORECASE):
        return "SKA Ahli K3 Konstruksi"

    # Pattern 0.5: "SKK/SKA Ahli Muda Teknik Bangunan Gedung" — level SEBELUM nama bidang
    # Berbeda dari Pattern 1 di mana level di akhir
    m05 = re.search(
        r"\bSK[AK]\b\s+(?:Ahli\s+)?(Muda|Madya|Utama)\s+([\w\s/]+?)(?:\(|,|\)|$)",
        s, re.IGNORECASE,
    )
    if m05:
        level = m05.group(1).strip().title()
        bidang = re.sub(r"\s+", " ", m05.group(2)).strip().rstrip("/").strip()
        bidang = re.sub(r"\s+Ahli$", "", bidang, flags=re.IGNORECASE).strip()
        if bidang:
            return f"SKA {bidang} - Ahli {level}"

    # Pattern 1: SKA/SKK + bidang + level Muda/Madya/Utama
    # Toleransi separator koma (format HPS: "SKK Jembatan/Jalan Ahli Muda").
    m = re.search(
        r"SK[AK](?:/SK[AK])?\s*[,]?\s*([\w/\s]+?)\s+(?:Ahli\s+)?(Muda|Madya|Utama)",
        s, re.IGNORECASE,
    )
    if m:
        bidang = re.sub(r"\s+", " ", m.group(1)).strip().rstrip("/").rstrip(",").strip()
        # Buang kata 'Ahli' yang ikut terserap di ujung bidang
        bidang = re.sub(r"\s+Ahli$", "", bidang, flags=re.IGNORECASE).strip()
        level = m.group(2).strip().title()
        return f"SKA {bidang} - Ahli {level}"

    # Pattern 3: SKA/SKK + bidang (tanpa level eksplisit) — ambil sampai koma/paren
    m3 = re.search(r"\bSK[AK]\b\s*[/,]?\s*([^,\(\)]+?)(?:\)|,|$)", s, re.IGNORECASE)
    if m3:
        bidang = re.sub(r"\s+", " ", m3.group(1)).strip()
        return f"SKA {bidang}" if bidang else "SKA"

    return ""


def _parse_baris_personil(teks: str) -> list[dict]:
    """Parse baris bernomor dari teks PDF ke raw list of {nomor, jabatan, pengalaman}.

    Robustness:
    - Abaikan trailing text kolom KET. (Non Tenaga Ahli, dll) — anchor \b bukan $
    - Baris tanpa nomor di depan di-skip (cegah baris lanjutan tabel masuk)
    - Multiline join: jika baris nomor-N tidak mengandung 'Tahun', gabung dengan
      baris berikutnya hingga 'N Tahun' ditemukan (maks 3 baris lanjutan)
    """
    lines = [l.strip() for l in teks.split("\n") if l.strip()]
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Hanya proses baris yang diawali nomor
        if not re.match(r"^\d+\s", line):
            i += 1
            continue
        # Coba match langsung (jabatan + tahun dalam 1 baris)
        m = re.match(r"^(\d+)\s+(.+?)\s+(\d+\s*[Tt]ahun)\b", line)
        if m:
            result.append({
                "nomor": int(m.group(1)),
                "jabatan": m.group(2).strip(),
                "pengalaman": m.group(3).strip(),
            })
            i += 1
            continue
        # Multiline join: 'N Tahun' belum ditemukan → gabung baris berikutnya (maks 3)
        joined = line
        for j in range(1, 4):
            if i + j >= len(lines):
                break
            next_line = lines[i + j]
            # Stop join jika baris berikutnya dimulai nomor baru
            if re.match(r"^\d+\s", next_line):
                break
            joined = joined + " " + next_line
            m2 = re.match(r"^(\d+)\s+(.+?)\s+(\d+\s*[Tt]ahun)\b", joined)
            if m2:
                result.append({
                    "nomor": int(m2.group(1)),
                    "jabatan": m2.group(2).strip(),
                    "pengalaman": m2.group(3).strip(),
                })
                i += j + 1
                break
        else:
            # Loop selesai tanpa menemukan 'N Tahun' → skip baris ini
            i += 1
    return result


def cari_hps_md_di_folder(folder: str) -> str | None:
    """Cari file '_HPS_*.md' di root folder paket."""
    if not os.path.isdir(folder):
        return None
    for f in os.listdir(folder):
        if f.lower().startswith("_hps_") and f.lower().endswith(".md"):
            return os.path.join(folder, f)
    return None


def _baca_items_dari_hps_md(md_path: str) -> list[dict]:
    """Parse tabel BoQ dari file _HPS_*.md → list {jenis_bj, satuan, vol, is_divisi}.

    Format baris tabel (9 kolom, pipe-separated):
      No | Jenis B/J | Satuan | Vol | Harga | Pajak% | Total SPSE | Total Hitung | Selisih OK
    Divisi/section header: kolom Jenis di-bold (**...**), kolom lain '-'.
    """
    try:
        with open(md_path, "r", encoding="utf-8") as fp:
            teks = fp.read()
    except Exception:
        return []

    items = []
    for line in teks.split("\n"):
        line = line.strip()
        if not line.startswith("|") and " | " not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        # Buang sel kosong di ujung akibat leading/trailing pipe
        cols = [c for c in cols if c != ""]
        if len(cols) < 4:
            continue
        # Skip header tabel + separator
        if cols[0].lower() in ("no", "---") or set(cols[0]) <= set("-"):
            continue
        if not re.match(r"^\d+$", cols[0]):
            continue
        jenis_raw = cols[1]
        satuan = cols[2]
        vol_raw = cols[3]
        is_divisi = jenis_raw.startswith("**") or satuan == "-"
        jenis_bj = jenis_raw.strip("*").strip()
        # Volume → float (buang Rp/koma ribuan tak relevan; vol biasanya angka kecil)
        vol = 0.0
        m_vol = re.search(r"[\d.,]+", vol_raw)
        if m_vol and not is_divisi:
            v = m_vol.group(0).replace(".", "").replace(",", ".")
            try:
                vol = float(v)
            except ValueError:
                vol = 0.0
        items.append({
            "jenis_bj": jenis_bj,
            "satuan": "" if satuan == "-" else satuan,
            "vol": vol,
            "is_divisi": is_divisi,
        })
    return items


def parse_personil_dari_hps(items_or_md) -> list[dict]:
    """Ekstrak Tenaga Ahli dari data HPS (paling akurat untuk PL JKK).

    Input fleksibel:
      - list[dict] items HPS (dari hps_engine: {jenis_bj, satuan, vol, is_divisi, ...})
      - str path file '_HPS_*.md' → di-parse via _baca_items_dari_hps_md

    Logika:
      - Scan berurutan. Divisi 'TENAGA AHLI' → in_ahli=True.
        Divisi lain (TENAGA PENDUKUNG / BIAYA / dll) → in_ahli=False.
      - Ambil item non-divisi saat in_ahli=True, KECUALI 'Petugas K3' (jenjang petugas).
      - Per item: jabatan (sebelum '('), pengalaman ('N tahun' dalam kurung),
        sertifikat (_extract_sertifikat_dari_jabatan), jumlah_orang (int dari vol).

    Return list[{jabatan, pengalaman, sertifikat, jumlah_orang}] (max 3 — slot Excel R32-R40).
    """
    if isinstance(items_or_md, str):
        items = _baca_items_dari_hps_md(items_or_md)
    else:
        items = items_or_md or []

    hasil = []
    in_ahli = False
    for it in items:
        jenis = (it.get("jenis_bj") or "").strip()
        if it.get("is_divisi"):
            up = jenis.upper()
            in_ahli = ("TENAGA AHLI" in up or "PROFESSIONAL STAFF" in up)
            continue
        if not in_ahli:
            continue
        # Di section TENAGA AHLI tapi Petugas K3 jenjang petugas → bukan Tenaga Ahli
        if _is_petugas_jenjang_rendah(jenis):
            continue

        jabatan = jenis

        # pengalaman = 'N tahun' di mana saja
        m_th = re.search(r"(\d+)\s*tahun", jenis, re.IGNORECASE)
        pengalaman = f"{m_th.group(1)} Tahun" if m_th else "1 Tahun"

        sertifikat = _extract_sertifikat_dari_jabatan(jenis)

        hasil.append({
            "jabatan": jabatan,
            "pengalaman": pengalaman,
            "sertifikat": sertifikat,
            "jumlah_orang": 1,
        })
        if len(hasil) >= 3:
            break
    return hasil


def parse_personil_daftar(pdf_path: str) -> list[dict]:
    """Parse Daftar Personil PDF → hanya Tenaga Ahli (baris ber-SKA atau Ahli K3).

    Algoritma 2-pass:
    Pass 1 — filter SKA: ambil hanya baris yang _is_tenaga_ahli() = True.
    Pass 2 — fallback: jika Pass 1 kosong (PDF tidak cantumkan SKA), ambil baris
             nomor 1 saja sebagai Ketua Tim minimum.

    Max 3 slot (slot Excel R32-R40 — praktisnya JKK biasanya 1-2 Tenaga Ahli).
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return []

    semua = _parse_baris_personil(teks)
    if not semua:
        return []

    # Pass 1: filter Tenaga Ahli (SKA / Ahli K3)
    ahli = [p for p in semua if _is_tenaga_ahli(p["jabatan"])]

    # Pass 2: fallback ke baris nomor 1 jika tidak ada SKA ditemukan
    if not ahli:
        baris1 = next((p for p in semua if p["nomor"] == 1), semua[0])
        ahli = [baris1]

    return [
        {
            "jabatan": p["jabatan"],
            "pengalaman": p["pengalaman"],
            "sertifikat": _extract_sertifikat_dari_jabatan(p["jabatan"]),
            "jumlah_orang": 1,
        }
        for p in ahli[:3]
    ]


def parse_personil_dari_draft_pl(pdf_path: str) -> list[dict]:
    """Fallback: parse personil dari Draft_PL PDF section 'Personil Inti' — hanya Tenaga Ahli."""
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return []

    idx = teks.lower().find("personil inti")
    if idx < 0:
        return []

    semua = _parse_baris_personil(teks[idx:idx + 3000])
    if not semua:
        return []

    ahli = [p for p in semua if _is_tenaga_ahli(p["jabatan"])]
    if not ahli:
        baris1 = next((p for p in semua if p["nomor"] == 1), semua[0])
        ahli = [baris1]

    return [
        {
            "jabatan": p["jabatan"],
            "pengalaman": p["pengalaman"],
            "sertifikat": _extract_sertifikat_dari_jabatan(p["jabatan"]),
            "jumlah_orang": 1,
        }
        for p in ahli[:3]
    ]


def ekstrak_personil_3layer(folder: str, fallback_jabatan_teknis: str = "", fallback_jabatan_k3: str = "", require_hps: bool = False) -> list[dict]:
    """Multi-layer extraction Tenaga Ahli (prioritas akurasi):
    Layer 1: HPS markdown (_HPS_*.md) — paling akurat untuk PL JKK (section TENAGA AHLI + vol)
    Layer 2: Daftar Personil PDF
    Layer 3: Draft_PL PDF (section Personil Inti)
    Layer 4: fallback Supabase (jabatan_teknis + jabatan_k3)
    Tiap item: {jabatan, pengalaman, sertifikat, jumlah_orang}

    require_hps=True: kalau HPS tidak ada, return [] tanpa fallback ke layer lain.
    Ini mencegah data stale (SKA lama dari Daftar Personil) menimpa data HPS yang belum tersedia.
    """
    # Layer 1: HPS markdown (sumber utama JKK)
    hps_md = cari_hps_md_di_folder(folder)
    if hps_md:
        result = parse_personil_dari_hps(hps_md)
        if result:
            return result
        # HPS ada tapi parse kosong → skip fallback, kembalikan kosong
        # (HPS mungkin sedang ditulis atau formatnya berubah)
        return []

    # HPS tidak ada sama sekali
    if require_hps:
        # Caller minta strict HPS → skip semua fallback
        return []

    # Layer 2: Daftar Personil PDF
    daftar_pdf = cari_daftar_personil_di_folder(folder)
    if daftar_pdf:
        result = parse_personil_daftar(daftar_pdf)
        if result:
            return result

    # Layer 3: Draft_PL PDF
    draft_pdf = cari_draft_pl_di_folder(folder)
    if draft_pdf:
        result = parse_personil_dari_draft_pl(draft_pdf)
        if result:
            return result

    # Layer 4: fallback Supabase
    result = []
    if fallback_jabatan_teknis:
        result.append({
            "jabatan": fallback_jabatan_teknis,
            "pengalaman": "1 Tahun",
            "sertifikat": "",
            "jumlah_orang": 1,
        })
    if fallback_jabatan_k3:
        result.append({
            "jabatan": fallback_jabatan_k3,
            "pengalaman": "1 Tahun",
            "sertifikat": "",
            "jumlah_orang": 1,
        })
    return result


def _nomor_dari_folder(folder_basename: str) -> str:
    """Ekstrak nomor urut dari nama folder, misal '16. PLJKK - ...' → '16'."""
    import re as _re
    m = _re.match(r'^(\d+)\.', folder_basename.strip())
    return m.group(1) if m else ""


def _resolve_folder_pl(nomor_urut, nama_paket: str, jenis_pl: str, is_ulang: bool = False) -> tuple[str | None, str]:
    """Cari folder paket PL di OUTPUT_DIR_PL_{JKK|PK}.

    Return: (path_folder | None, nomor_urut_dari_folder)
    nomor_urut_dari_folder terisi jika folder ditemukan via scan (bukan dari arg).
    Caller bisa pakai ini untuk auto-update nomor_urut ke Supabase.
    """
    from config import OUTPUT_DIR_PL_JKK, OUTPUT_DIR_PL_PK, sanitasi_nama_folder

    jenis = (jenis_pl or "JKK").upper()
    root = OUTPUT_DIR_PL_JKK if jenis == "JKK" else OUTPUT_DIR_PL_PK
    if not os.path.isdir(root):
        return None, ""

    nama_clean = sanitasi_nama_folder(nama_paket or "")
    nomor = nomor_urut or ""
    nama_lower = nama_clean.lower()

    def _ret(full):
        return full, _nomor_dari_folder(os.path.basename(full))

    if is_ulang:
        if nomor:
            folder_ulang_name = f"{nomor}. PL{jenis} - {nama_clean} (PL - Ulang)"
            folder_ulang = os.path.join(root, folder_ulang_name)
            if os.path.isdir(folder_ulang):
                return _ret(folder_ulang)

    folder_name = f"{nomor}. PL{jenis} - {nama_clean}"
    candidate = os.path.join(root, folder_name)
    if os.path.isdir(candidate):
        if not is_ulang:
            return _ret(candidate)

    # Prioritas 0.5: match by nomor prefix saja (kalau nomor ada)
    if nomor:
        prefix = f"{nomor}. pl{jenis}".lower()
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
            if fl.startswith(prefix):
                return _ret(full)

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
        # Prioritas 1: exact suffix nama (case-insensitive)
        suffix_ulang = nama_lower + " (pl - ulang)"
        if is_ulang and fl.rstrip().endswith(suffix_ulang):
            return _ret(full)
        if not is_ulang and fl.endswith(nama_lower):
            return _ret(full)
        # Prioritas 2: word-set match — semua kata nama ada di folder
        words = set(nama_lower.split())
        folder_words = set(fl.split())
        common = words & folder_words
        if len(common) == len(words) and len(common) > best_score:
            best_score = len(common)
            best = full
            continue
    return _ret(best) if best else (None, "")


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
    rows = _sb().table("draft_paket_pl").select("kode_paket,nama_paket,nomor_urut,jenis_pl,jabatan_teknis,jabatan_k3,is_ulang,tahap_spse,status").execute().data or []
    if kode_paket_filter:
        rows = [r for r in rows if r["kode_paket"] == kode_paket_filter]
    _SELESAI_KW = ("penandatanganan kontrak", "paket sudah selesai", "sudah selesai")
    rows_aktif = [r for r in rows if not any(k in (r.get("tahap_spse") or r.get("status") or "").lower() for k in _SELESAI_KW)]
    log(0.10, f"Total {len(rows)} paket, {len(rows_aktif)} aktif (skip {len(rows)-len(rows_aktif)} selesai)")
    rows = rows_aktif

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
            folder, nomor_dari_folder = _resolve_folder_pl(p.get("nomor_urut"), nama, p.get("jenis_pl") or "JKK", is_ulang=p.get("is_ulang", False))
            if not folder:
                not_found += 1
                log(prog, f"  - {kode}: folder tidak ditemukan")
                continue
            # Auto-update nomor_urut ke Supabase jika sebelumnya NULL
            if not p.get("nomor_urut") and nomor_dari_folder:
                try:
                    _sb().table("draft_paket_pl").update({"nomor_urut": nomor_dari_folder}).eq("kode_paket", kode).execute()
                    log(prog, f"  🔢 {kode}: nomor_urut auto-set → {nomor_dari_folder}")
                except Exception:
                    pass

            personil = []

            nd_pdf = cari_nd_di_folder(folder)
            if nd_pdf:
                data = parse_nd_penyedia(nd_pdf)
                log(prog, f"  📄 {kode}: parse ND.pdf → nama={data.get('nama_penyedia','')[:20]}")
                # We still need to parse sub_kegiatan from Draft_PL if it exists
                pdf = cari_draft_pl_di_folder(folder)
                if pdf:
                    sub_keg = parse_sub_kegiatan_dari_draft_pl(pdf)
                    if sub_keg:
                        data["sub_kegiatan"] = sub_keg
            else:
                pdf = cari_draft_pl_di_folder(folder)
                if not pdf:
                    not_found += 1
                    log(prog, f"  - {kode}: ND.pdf + Draft_PL tidak ditemukan di {os.path.basename(folder)}")
                    continue
                data = parse_draft_pl(pdf)
                log(prog, f"  📄 {kode}: parse Draft_PL → nama={data.get('nama_penyedia','')[:20]}")

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
            log(prog, f"  OK {kode}: penyedia={pn} sub_keg={bool(sk)} personil={len(personil)}")
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
