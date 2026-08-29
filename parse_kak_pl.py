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
    # Format tabel/metadata lama: ``NAMA PPK: ...``.
    m = re.search(r"NAMA\s+PPK\s*[:\-]\s*([^\n]+)", teks, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()

    # KAK PK hasil SPSE biasanya menaruh heading tanpa label:
    # ``PEJABAT PEMBUAT KOMITMEN`` lalu nama dan baris ``NIP. ...``.
    lines = [re.sub(r"\s+", " ", line).strip() for line in teks.splitlines()]
    for i, line in enumerate(lines):
        if not re.fullmatch(r"PEJABAT\s+PEMBUAT\s+KOMITMEN", line, re.IGNORECASE):
            continue
        for candidate in lines[i + 1:i + 4]:
            if not candidate or re.match(r"^(NIP|PROGRAM|KEGIATAN|SUB\s+KEG|PEKERJAAN)\b", candidate, re.IGNORECASE):
                continue
            return candidate
    return ""


def _extract_jangka_waktu(teks: str) -> str:
    """
    Cari pola 'X hari / Y bulan kalender' → kembalikan string "X hari / Y bulan kalender".
    Fallback: cari pola 'X (kata) hari kalender' saja.
    """
    # Pola eksplisit lebih kuat daripada label umum. KAK sering memuat
    # "Masa Pemeliharaan 180 hari" sebelum/bersamaan dengan durasi 90 hari.
    # Jangan pernah mengambil angka dari masa pemeliharaan.
    for pattern in (
        r"PELAKSANAAN(?:\s+KEGIATAN|\s+PEKERJAAN)?\s+(?:DILAKUKAN\s+SELAMA|SELAMA)\s+(\d{1,4})\s*(?:\([^)]*\)\s*)?hari",
        r"JANGKA\s+WAKTU\s+PELAKSANAAN\s*(?:ADALAH|:|-)??\s*(\d{1,4})\s*(?:\([^)]*\)\s*)?hari",
        r"MASA\s+PELAKSANAAN\s+PEKERJAAN\s*(?:ADALAH|:|-)??\s*(\d{1,4})\s*(?:\([^)]*\)\s*)?hari",
    ):
        hit = re.search(pattern, teks, re.IGNORECASE)
        if hit:
            return f"{hit.group(1)} hari kalender"

    # Fallback label umum; potong window sebelum label pemeliharaan.
    for label in (r"JANGKA\s+WAKTU(?:\s+PELAKSANAAN)?", r"WAKTU\s+PELAKSANAAN"):
        labeled = re.search(label, teks, re.IGNORECASE)
        if labeled:
            window = teks[labeled.end():labeled.end() + 220]
            day = re.search(
                r"(\d{1,4})\s*(?:\([^)]*\)\s*)?hari(?:\s+kalender)?",
                window, re.IGNORECASE,
            )
            if day:
                return f"{day.group(1)} hari kalender"

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

    # Fallback: X hari kalender dengan/ tanpa terbilang.
    m2 = re.search(r"(\d+)\s*(?:\([^)]+\)\s*)?(?:hari(?:\s+kalender)?|kalender)", teks, re.IGNORECASE)
    if m2:
        return m2.group(0).strip()

    return ""


def _extract_sbu(teks: str, konteks: str = "") -> tuple[str, str]:
    """Kode SBU + nama lengkap dari master_sbu Supabase.

    Returns: (sbu_baru_lengkap, sbu_lama_lengkap)
    Contoh:
      sbu_baru = "Subklasifikasi RK003 (KBLI 2020) Jasa Rekayasa Pekerjaan Teknik Sipil Transportasi."
      sbu_lama = "Subklasifikasi Jasa Nasehat dan Konsultansi Rekayasa Teknik (KBLI 2017) RE101"
    """
    m = re.search(r"\b(RK\d{3}|AR\d{3}|SI\d{3}|BG\d{3}|SP\d{3}|EL\d{3}|MK\d{3})\b", teks)
    if not m:
        # KAK PUPR sering tidak mencetak kode SBU. Fallback hanya untuk
        # domain konstruksi jalan/drainase/jembatan; jangan menerapkannya pada
        # paket gedung/perdagangan yang memiliki BGxxx sendiri.
        up = (str(konteks) + "\n" + teks).upper()
        title_up = str(konteks).upper()
        if re.search(r"JEMBATAN|BOX\s*CULVERT|FLY\s*OVER|UNDERPASS", title_up):
            return ("SBU BS002 Bangunan Sipil Jembatan, Jalan Layang, Fly Over, dan Underpass KBLI 42102", "")
        if re.search(r"JALAN|DRAINASE|RABAT\s+BETON|ASPAL|LATASIR|MAKADAM", title_up):
            return ("SBU BS001 Konstruksi Bangunan Sipil Jalan atau Konstruksi Jalan Pada Permukaan Tanah KBLI 42101", "")
        if re.search(r"JEMBATAN|BOX\s*CULVERT|FLY\s*OVER|UNDERPASS", up) and not re.search(r"JALAN|DRAINASE|RABAT\s+BETON|ASPAL|LATASIR|MAKADAM", up):
            return ("SBU BS002 Bangunan Sipil Jembatan, Jalan Layang, Fly Over, dan Underpass KBLI 42102", "")
        if re.search(r"JALAN|DRAINASE|RABAT\s+BETON|ASPAL|LATASIR|MAKADAM", up):
            return ("SBU BS001 Konstruksi Bangunan Sipil Jalan atau Konstruksi Jalan Pada Permukaan Tanah KBLI 42101", "")
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

    # KAK PK memakai tabel ``Kebutuhan Personel Minimal``. Ambil jabatan
    # teknis pertama secara eksplisit; jangan memasukkan kolom sertifikat/
    # pengalaman yang pada PDF sering tersambung dalam satu baris.
    personel = re.search(
        r"KEBUTUHAN\s+PERSON(?:EL|IL)\s+MINIMAL(.{0,1200})",
        teks, re.IGNORECASE | re.DOTALL,
    )
    window = personel.group(1) if personel else teks
    for pattern in (
        r"\b(Pelaksana\s+Lapangan)\b",
        r"\b(Site\s+Manager)\b",
        r"\b(Pelaksana\s+Pekerjaan)\b",
        r"\b(Manajer\s+Pelaksanaan)\b",
    ):
        role = re.search(pattern, window, re.IGNORECASE)
        if role:
            return re.sub(r"\s+", " ", role.group(1)).strip().title()

    return ""


def _extract_lokasi(teks: str) -> str:
    """Ambil lokasi hanya jika KAK memberi label eksplisit.

    Jika tidak ditemukan, kembalikan kosong agar lokasi authoritative dari
    ``viewdraftpl`` tidak tertimpa fallback generik Kabupaten Tapin.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in teks.splitlines()]
    label_re = re.compile(
        r"^\s*(?:\d+\.\s*)?LOKASI(?:\s+(?:KEGIATAN|PEKERJAAN))?\s*[:\-]?\s*(.*)$",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        m = label_re.match(line)
        if not m:
            continue
        value = m.group(1).strip(" .:-")
        if not value or value.lower() in {"kegiatan", "pekerjaan"}:
            for candidate in lines[i + 1:i + 3]:
                if candidate and not re.match(r"^(?:\d+\.\s*)?[A-Z][A-Z\s]+$", candidate):
                    value = candidate.strip(" .:-")
                    break
        if value and value.lower() not in {"kegiatan", "pekerjaan"}:
            return value
    return ""


def _extract_sub_kegiatan_dari_kak(teks: str) -> str:
    """Ambil kegiatan/sub-kegiatan KAK; jika dua-duanya ada pilih terpendek."""
    lines = [re.sub(r"\s+", " ", x).strip() for x in teks.splitlines()]
    def _value(label: str) -> str:
        rx = re.compile(rf"^(?:NAMA\s+)?{label}(?:\s*[:=-]\s*|\s+)(.+)$", re.IGNORECASE)
        label_only = re.compile(rf"^(?:NAMA\s+)?{label}\s*$", re.IGNORECASE)
        for i, line in enumerate(lines):
            m = rx.match(line)
            if m:
                value = m.group(1).strip(" .:-")
                if len(value) >= 4 and value.upper() not in {"KEGIATAN", "SUB KEGIATAN"}:
                    return value
            if label_only.match(line) and i + 1 < len(lines):
                value = lines[i + 1].strip(" .:-")
                if len(value) >= 4:
                    return value
        return ""

    sub = _value(r"SUB\s+KEGITA?N")
    keg = _value(r"KEGIATAN")
    values = [v for v in (sub, keg) if v]
    if values:
        return min(values, key=len)
    # Cover KAK lama: label di satu baris, nilai di baris berikutnya.
    m = re.search(r"SUB\s+KEGITA?N\s*\n([^\n]+)", teks, re.IGNORECASE)
    return re.sub(r"\s+", " ", m.group(1)).strip(" .:-") if m else ""


def parse_kak(pdf_path: str) -> dict:
    """
    Parse KAK PDF, kembalikan dict field.
    Semua field bisa kosong string jika tidak ditemukan.
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return {}

    sbu_baru, sbu_lama = _extract_sbu(teks, os.path.basename(pdf_path))
    return {
        "nama_ppk":     _extract_nama_ppk(teks),
        "jangka_waktu": _extract_jangka_waktu(teks),
        "sbu_baru":     sbu_baru,
        "sbu_lama":     sbu_lama,
        "jabatan_teknis": _extract_jabatan_teknis(teks),
        "jabatan_k3":   _extract_jabatan_k3(teks),
        "lokasi":       _extract_lokasi(teks),
        "sub_kegiatan": _extract_sub_kegiatan_dari_kak(teks),
    }


def cari_kak_di_folder(folder: str) -> str | None:
    """
    Cari file KAK PDF di folder paket dan subfolder dokumen.

    Jangan fallback ke PDF pertama: root paket juga berisi Draft_PL/HPS dan
    fallback itu dapat membuat parser membaca dokumen yang salah sebagai KAK.
    Download SPSE menaruh KAK di ``1. KAK & Spesifikasi Teknis``.
    """
    if not os.path.isdir(folder):
        return None

    candidates = []
    try:
        for current, dirs, files in os.walk(folder):
            # Dokumen paket hanya perlu dicari sampai satu level subfolder;
            # batasi traversal agar tidak membaca backup/evaluator besar.
            depth = os.path.relpath(current, folder).count(os.sep)
            if depth > 1:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d.lower() not in {".workflow-backups", "__pycache__"}]
            for f in files:
                fl = f.lower()
                if not fl.endswith(".pdf") or "kak" not in fl:
                    continue
                # SpekTek/Gambar/RK3 bukan KAK walaupun ada di area KAK.
                if any(token in fl for token in ("spektek", "spesifikasi", "gambar", "rk3")):
                    continue
                score = 0
                if re.match(r"^\s*\d+\.\s*kak\b", fl):
                    score += 10
                if os.path.basename(current).lower().startswith("1. kak"):
                    score += 5
                if "draft_pl" in fl or fl.startswith("_hps"):
                    score -= 20
                candidates.append((score, os.path.join(current, f)))
    except OSError:
        return None

    if candidates:
        return sorted(candidates, key=lambda item: (-item[0], item[1].lower()))[0][1]
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


def _text_awal_pdf(pdf_path: str, max_pages: int = 2) -> str:
    """Ambil teks awal PDF saja untuk scoring ringan."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(pg.extract_text() or "" for pg in pdf.pages[:max_pages])
    except Exception:
        return ""

def _score_nd_pdf(pdf_path: str) -> int:
    name = os.path.basename(pdf_path).lower()
    score = 0
    if re.search(r"\bnd\b", name):
        score += 2
    if "nota dinas" in name or "nota" in name or "nodin" in name:
        score += 2
    if "ppk" in name:
        score += 1

    teks = _text_awal_pdf(pdf_path).lower()
    if "npwp" in teks:
        score += 3
    if "penyedia" in teks:
        score += 2
    if "nota dinas" in teks or "nota" in teks:
        score += 2
    if "kepada yth" in teks:
        score += 1
    if "pejabat pengadaan" in teks:
        score += 1
    return score

def cari_nd_di_folder(folder: str) -> str | None:
    """Cari PDF Nota Dinas terbaik di subfolder '4. Informasi Lainnya'."""
    if not os.path.isdir(folder):
        return None
    subfolder = os.path.join(folder, "4. Informasi Lainnya")
    if not os.path.isdir(subfolder):
        return None
    pdfs = [
        os.path.join(subfolder, f)
        for f in os.listdir(subfolder)
        if f.lower().endswith(".pdf")
    ]
    if not pdfs:
        return None
    scored = sorted(((_score_nd_pdf(p), p) for p in pdfs), reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 2 else None


def parse_nd_penyedia(pdf_path: str) -> dict:
    """Parse ND/Nota Dinas PDF — ekstrak nama_penyedia + npwp_penyedia.

    Mendukung dua format:
      Format A (baru): "Nama Calon Penyedia : CV. ..."  + "Nomor NPWP : 082..."
      Format B (lama): "Nama Perusahaan : CV. ..."      + "NPWP Perusahaan : 72.112..."
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return {}

    out = {"nama_penyedia": "", "npwp_penyedia": "", "nomor_nota_dinas": "", "tgl_nota_dinas": ""}

    # Format Nota Dinas PUPR: Nomor berada di kepala surat, tanggal pada
    # baris kota/tanggal. Batasi pembacaan ke bagian awal agar nomor surat
    # rekomendasi di halaman berikutnya tidak tertukar.
    awal = teks[:1800]
    m_no = re.search(r"\bNomor\s*:\s*([^\n]+)", awal, re.IGNORECASE)
    if m_no:
        out["nomor_nota_dinas"] = m_no.group(1).strip()
    bulan = {"januari": "01", "februari": "02", "maret": "03", "april": "04", "mei": "05", "juni": "06", "juli": "07", "agustus": "08", "september": "09", "oktober": "10", "november": "11", "desember": "12"}
    m_tgl = re.search(r"(?:^|\n)[A-Za-z .-]+,\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", awal)
    if m_tgl and m_tgl.group(2).lower() in bulan:
        out["tgl_nota_dinas"] = f"{m_tgl.group(3)}-{bulan[m_tgl.group(2).lower()]}-{int(m_tgl.group(1)):02d}"

    # Nama: coba "Nama Calon Penyedia" dulu, fallback "Nama Perusahaan"
    m_nama = re.search(r"Nama\s*Calon\s*Penyedia\s*:\s*(.+?)(?:\n|$)", teks, re.IGNORECASE)
    if not m_nama:
        m_nama = re.search(r"Nama\s*Perusahaan\s*:\s*(.+?)(?:\n|$)", teks, re.IGNORECASE)
    if m_nama:
        out["nama_penyedia"] = m_nama.group(1).strip()

    if not out["nama_penyedia"]:
        m_jasa = re.search(r"Penyedia\s+Jasa\s*:\s*(.+?)(?:\n|$)", teks, re.IGNORECASE)
        if m_jasa:
            out["nama_penyedia"] = m_jasa.group(1).strip()

    # NPWP: coba "Nomor NPWP" (inline/baris pisah), fallback "NPWP Perusahaan"
    # Format angka dengan/tanpa titik-strip: 72.112.192.9-731.000 atau 0826618548735000
    _npwp_pat = r"[\d.\-\s]{10,30}"
    m_npwp = re.search(
        r"Nomor\s*NPWP\s*[:\n\r]+\s*(" + _npwp_pat + r")",
        teks, re.IGNORECASE | re.DOTALL,
    )
    if not m_npwp:
        m_npwp = re.search(
            r"NPWP\s*Perusahaan\s*:\s*(" + _npwp_pat + r")",
            teks, re.IGNORECASE,
        )
    if m_npwp:
        out["npwp_penyedia"] = re.sub(r"[.\-\s]", "", m_npwp.group(1)).strip()

    return out

def serap_identitas_penyedia_pl(kode_paket_filter: str = None, progress_cb=None) -> dict:
    """Serap ringan identitas penyedia PL dari Nota Dinas. Tidak ekstrak personil."""
    from config import sb as _sb

    def log(p, m):
        if progress_cb:
            progress_cb(p, m)

    _cols = "kode_paket,nama_paket,nomor_urut,jenis_pl,is_ulang"
    _q = _sb().table("draft_paket_pl").select(_cols)
    if kode_paket_filter:
        _q = _q.eq("kode_paket", kode_paket_filter)
    rows = _q.execute().data or []

    updated = 0
    not_found = 0
    no_data = 0
    errors = []
    total = max(len(rows), 1)
    for i, p in enumerate(rows):
        prog = (i + 1) / total
        kode = p.get("kode_paket")
        try:
            folder, nomor_dari_folder = _resolve_folder_pl(
                p.get("nomor_urut"),
                p.get("nama_paket") or "",
                p.get("jenis_pl") or "JKK",
                is_ulang=p.get("is_ulang", False),
            )
            if not folder:
                not_found += 1
                log(prog, f"{kode}: folder tidak ditemukan")
                continue
            if not p.get("nomor_urut") and nomor_dari_folder:
                _sb().table("draft_paket_pl").update({"nomor_urut": nomor_dari_folder}).eq("kode_paket", kode).execute()

            nd_pdf = cari_nd_di_folder(folder)
            if not nd_pdf:
                not_found += 1
                log(prog, "Identitas penyedia: Nota Dinas tidak ditemukan")
                continue

            data = parse_nd_penyedia(nd_pdf)
            update = {k: v for k, v in data.items() if k in ("nama_penyedia", "npwp_penyedia") and v}
            if not update:
                no_data += 1
                log(prog, f"Identitas penyedia: data tidak terbaca dari {os.path.basename(nd_pdf)}")
                continue

            _sb().table("draft_paket_pl").update(update).eq("kode_paket", kode).execute()
            updated += 1
            log(prog, f"Identitas penyedia: {update.get('nama_penyedia', '-')} / NPWP {update.get('npwp_penyedia', '-')}")
        except Exception as e:
            errors.append(f"{kode}: {e}")

    return {"ok": True, "updated": updated, "not_found": not_found, "no_data": no_data, "errors": errors}


def parse_jenis_kontrak_dari_draft_pl(pdf_path: str) -> str:
    """Ambil jenis kontrak dari baris eksplisit Draft PPK.

    Draft PPK adalah sumber lokal yang lebih spesifik daripada nilai template
    atau cache database. Hanya kembalikan nilai bila label dan nilainya benar-
    benar terbaca; jangan menebak dari jenis pekerjaan.
    """
    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return ""
    m = re.search(r"JENIS\s+KONTRAK\s*:\s*([^\n\r]+)", teks, re.IGNORECASE)
    if not m:
        return ""
    value = re.sub(r"\s+", " ", m.group(1)).strip(" .:-")
    if re.match(r"harga\s+satuan$", value, re.IGNORECASE):
        return "Harga Satuan"
    if re.match(r"lumsum$", value, re.IGNORECASE):
        return "Lumsum"
    if re.match(r"gabungan\s+lumsum\s+dan\s+harga\s+satuan$", value, re.IGNORECASE):
        # PLPK hanya mengenal Lumsum atau Harga Satuan. Frasa gabungan
        # merupakan boilerplate/artefak tender yang kadang ikut terbawa ke
        # Draft PPK; default aman untuk pola HPS PLPK ini adalah Harga Satuan.
        return "Harga Satuan"
    return value


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
        r"Nama\s*Perusahaan\s*:\s*(.+?)(?:\n|$)",
        teks, re.IGNORECASE,
    )
    if m_nama:
        out["nama_penyedia"] = m_nama.group(1).strip()

    m_npwp = re.search(
        r"NPWP\s*Perusahaan\s*:\s*([0-9.\-\s]+)",
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

    # Fallback: sebagian paket punya layout kepala-surat "Nomor : ... " SEBELUM
    # heading "NOTA DINAS" (bukan sesudah) — regex utama di atas nyasar ke nomor
    # lain yang muncul lebih jauh di isi surat. Cari ulang persis sebelum heading.
    if not out["nomor_nota_dinas"] or "Tanggal" in out["nomor_nota_dinas"]:
        # Cari "Nomor : X" yang berjarak dekat (<300 char) SEBELUM heading NOTA
        # DINAS asli — dokumen draft sering berisi banyak halaman template
        # placeholder ("Nomor : __________") lebih awal yang harus dilewati.
        m_nota2 = re.search(
            r"Nomor\s*:\s*(\S+).{0,250}?NOTA\s+DINAS",
            teks, re.IGNORECASE | re.DOTALL,
        )
        if m_nota2 and "_" not in m_nota2.group(1) and "." * 5 not in m_nota2.group(1):
            out["nomor_nota_dinas"] = m_nota2.group(1).strip()

    # Nota Dinas sekaligus berfungsi sebagai usulan rekomendasi kalau tidak ada
    # section "SURAT REKOMENDASI" terpisah (nomor+tanggal sama).
    if not out["nomor_rekomendasi"] or "Tanggal" in out["nomor_rekomendasi"]:
        if out["nomor_nota_dinas"]:
            out["nomor_rekomendasi"] = out["nomor_nota_dinas"]
    if not out["tgl_rekomendasi"]:
        m_heading = re.search(r"NOTA\s+DINAS", teks, re.IGNORECASE)
        m_nota_tgl = None
        if m_heading:
            # Ambil kemunculan tanggal ("Kota, D Bulan YYYY") TERDEKAT sebelum
            # heading — dokumen draft berisi banyak tanggal placeholder lain.
            for cand in re.finditer(r"[A-Za-z]+,\s*(\d{1,2})\s+(\w+)\s+(\d{4})", teks[:m_heading.start()]):
                m_nota_tgl = cand
        if m_nota_tgl:
            hari = int(m_nota_tgl.group(1))
            bln = _BULAN.get(m_nota_tgl.group(2).lower())
            thn = int(m_nota_tgl.group(3))
            if bln:
                try:
                    out["tgl_rekomendasi"] = datetime.date(thn, bln, hari).isoformat()
                except ValueError:
                    pass

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
    """Cari daftar personel PDF/DOCX di folder paket atau subfolder KAK."""
    if not os.path.isdir(folder):
        return None

    def _cari_di(d: str):
        for f in os.listdir(d):
            fl = f.lower()
            if fl.endswith((".pdf", ".docx")) and ("daftar personil" in fl or "personil" in fl or "personel" in fl):
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
    # DOCX ListPersonil PK memiliki tabel native dengan kolom yang jelas.
    if str(pdf_path).lower().endswith(".docx"):
        try:
            from docx import Document
            doc = Document(pdf_path)
            for table in doc.tables:
                raw_rows = [[re.sub(r"\s+", " ", c.text or "").strip() for c in row.cells] for row in table.rows]
                rows = [[v.lower() for v in row] for row in raw_rows]
                if not rows:
                    continue
                header = rows[0]
                def col(*names):
                    return next((i for i, v in enumerate(header) if any(n in v for n in names)), -1)
                c_jab, c_exp, c_ket = col("jabatan"), col("pengalaman"), col("ket")
                if c_jab < 0:
                    continue
                result = []
                for raw_row, row in zip(raw_rows[1:], rows[1:]):
                    if c_jab >= len(row) or not row[c_jab]:
                        continue
                    jab = raw_row[c_jab]
                    exp = raw_row[c_exp] if c_exp >= 0 and c_exp < len(raw_row) else ""
                    # Kolom KET pertama sering hanya berisi "S K K"; kolom
                    # KET terakhir berisi nama sertifikat yang sebenarnya.
                    cert_candidates = [v for i, v in enumerate(raw_row) if i != c_jab and i != c_exp and v and not re.fullmatch(r"\d+[.]?", v)]
                    ket = cert_candidates[-1] if cert_candidates else ""
                    result.append({"jabatan": jab, "pengalaman": exp or "0 Tahun", "sertifikat": ket, "jumlah_orang": 1})
                if result:
                    return result[:3]
        except Exception:
            pass

    # PDF ListPersonil PK memiliki tabel native dengan kolom yang jelas.
    # Ambil berdasarkan posisi tabel agar sertifikat yang terpotong newline
    # tidak bergabung ke jabatan/pengalaman.
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table:
                        continue
                    header = [re.sub(r"\s+", " ", str(x or "")).strip().lower() for x in table[0]]
                    required = {"jabatan", "sertifikat", "pengalaman kerja"}
                    if not required.issubset(set(header)):
                        continue
                    col = {name: header.index(name) for name in required}
                    hasil_tabel = []
                    for row in table[1:]:
                        if not row or not str(row[0] or "").strip().isdigit():
                            continue
                        values = [re.sub(r"\s+", " ", str(x or "")).strip() for x in row]
                        jabatan = values[col["jabatan"]] if col["jabatan"] < len(values) else ""
                        sertifikat = values[col["sertifikat"]] if col["sertifikat"] < len(values) else ""
                        pengalaman = values[col["pengalaman kerja"]] if col["pengalaman kerja"] < len(values) else ""
                        if not jabatan:
                            continue
                        jumlah = 1
                        jumlah_match = re.search(r"\((\d+)\s*orang\)", jabatan, re.IGNORECASE)
                        if jumlah_match:
                            jumlah = int(jumlah_match.group(1))
                            jabatan = re.sub(r"\s*\(\d+\s*orang\)\s*", " ", jabatan, flags=re.IGNORECASE).strip()
                        hasil_tabel.append({
                            "jabatan": jabatan,
                            "pengalaman": pengalaman,
                            "sertifikat": sertifikat,
                            "jumlah_orang": jumlah,
                        })
                    if hasil_tabel:
                        return hasil_tabel[:3]
    except Exception:
        # Fallback text parser di bawah untuk PDF lama/non-table.
        pass

    teks = _text_dari_pdf(pdf_path)
    if not teks:
        return []

    semua = _parse_baris_personil(teks)
    if not semua:
        return []

    # Pass 1: filter Tenaga Ahli (SKA / Ahli K3)
    ahli = [p for p in semua if _is_tenaga_ahli(p["jabatan"])]

    # PK sering memakai SKK Pelaksana/Petugas, bukan SKA. Jika tidak ada
    # penanda Tenaga Ahli, semua baris tetap merupakan kebutuhan minimal.
    if not ahli:
        ahli = semua

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
        if require_hps:
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


def _resolve_folder_pl(
    nomor_urut,
    nama_paket: str,
    jenis_pl: str,
    is_ulang: bool = False,
    strict_name: bool = False,
) -> tuple[str | None, str]:
    """Cari folder paket PL di OUTPUT_DIR_PL_{JKK|PK}.

    Return: (path_folder | None, nomor_urut_dari_folder)
    nomor_urut_dari_folder terisi jika folder ditemukan via scan (bukan dari arg).
    Caller bisa pakai ini untuk auto-update nomor_urut ke Supabase.
    ``strict_name=True`` dipakai gate UI operasional agar nomor urut stale tidak
    pernah fallback ke folder paket lain dengan prefix nomor sama.
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

    # Folder PL dibuat memakai truncate_nama_folder() agar workbook tidak
    # melewati batas MAX_PATH Windows. Strict mode tetap boleh menerima nama
    # truncated resmi, selama nomor + jenis + prefix nama paket sama persis.
    try:
        from pl_engine import truncate_nama_folder

        truncated_name = truncate_nama_folder(root, folder_name)
        truncated_candidate = os.path.join(root, truncated_name)
        if truncated_name != folder_name and os.path.isdir(truncated_candidate):
            return _ret(truncated_candidate)
    except (ImportError, OSError, TypeError, ValueError):
        pass

    if strict_name:
        # Folder lama kadang dibuat dari nama paket yang dipendekkan, misalnya
        # nama DB memuat uraian pekerjaan lengkap tetapi folder hanya memakai
        # nama induk. Tetap jaga identitas: nomor + jenis PL harus sama, lalu
        # nama fisik harus menjadi prefix nama DB (atau sebaliknya), dan hanya
        # kandidat tunggal yang boleh dipilih.
        def _nama_pencocokan(value: str) -> str:
            value = re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE)
            return re.sub(r"\s+", " ", value).strip()

        def _kandidat_nama(folder_label: str) -> tuple[str, bool] | None:
            prefix_re = rf"^\s*{re.escape(str(nomor).strip())}\.\s*PL{re.escape(jenis)}\s*-\s*(.+?)\s*$"
            match = re.match(prefix_re, folder_label, flags=re.IGNORECASE)
            if not match:
                return None
            suffix = match.group(1)
            ulang_match = re.search(r"\s*\(\s*PL\s*-\s*Ulang\s*\)\s*$", suffix, flags=re.IGNORECASE)
            if ulang_match:
                suffix = suffix[: ulang_match.start()]
            return _nama_pencocokan(suffix), bool(ulang_match)

        expected_name = _nama_pencocokan(nama_clean)
        matches = []
        for folder_label in os.listdir(root):
            full = os.path.join(root, folder_label)
            if not os.path.isdir(full):
                continue
            parsed = _kandidat_nama(folder_label)
            if not parsed:
                continue
            physical_name, physical_is_ulang = parsed
            if physical_is_ulang != bool(is_ulang) or not physical_name or not expected_name:
                continue
            if (
                physical_name == expected_name
                or physical_name.startswith(expected_name + " ")
                or expected_name.startswith(physical_name + " ")
            ):
                matches.append(full)
        if len(matches) == 1:
            return _ret(matches[0])
        return (None, "")

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
    _cols = "kode_paket,nama_paket,nomor_urut,jenis_pl,jabatan_teknis,jabatan_k3,is_ulang,tahap_spse,status"
    _q = _sb().table("draft_paket_pl").select(_cols)
    if kode_paket_filter:
        _q = _q.eq("kode_paket", kode_paket_filter)  # hindari fetch full table saat filter tunggal (paralel bulk)
    rows = _q.execute().data or []
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

            # KAK paket adalah sumber authoritative untuk field parser yang
            # sering konflik dengan template Draft_PL/RK3K lama.
            kak_pdf = cari_kak_di_folder(folder)
            kak_data = parse_kak(kak_pdf) if kak_pdf else {}

            nd_pdf = cari_nd_di_folder(folder)
            if nd_pdf:
                data = parse_nd_penyedia(nd_pdf)
                log(prog, f"  📄 {kode}: parse ND.pdf → nama={data.get('nama_penyedia','')[:20]}")
                # ND menjadi sumber identitas penyedia. Draft_PL tetap wajib
                # dipakai untuk nomor/tanggal Nota Dinas dan Surat Rekomendasi;
                # sebelumnya field ini hilang setiap kali ND.pdf ditemukan.
                pdf = cari_draft_pl_di_folder(folder)
                if pdf:
                    draft_data = parse_draft_pl(pdf)
                    for key in ("nomor_nota_dinas", "nomor_rekomendasi", "tgl_rekomendasi"):
                        if draft_data.get(key):
                            data[key] = draft_data[key]
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

            for key in ("sub_kegiatan", "jangka_waktu", "sbu_baru", "sbu_lama", "jabatan_teknis", "jabatan_k3"):
                if kak_data.get(key):
                    data[key] = kak_data[key]
            if data.get("tgl_nota_dinas") and not data.get("tgl_rekomendasi"):
                data["tgl_rekomendasi"] = data["tgl_nota_dinas"]
            data.pop("tgl_nota_dinas", None)

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
