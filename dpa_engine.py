"""
DPA Engine — Parser PDF Dokumen Pelaksanaan Anggaran (DPA/RKA) Pemda.

2 pola yang didukung:
  1. DPA TEKS (RKA-BELANJA Sebelum/Sesudah) — pdfplumber, multi sub kegiatan
  2. DPA SCAN (gambar, format ringkas DPA-SKPD) — OCR Tesseract, 1 sub kegiatan per file

Deteksi otomatis: jika chars==0 → pakai OCR.
Kompatibel lintas tahun selama format Kemendagri tidak berubah.
"""

import re
import io
import os
from typing import Optional
import pdfplumber

# ── Konstanta OCR ─────────────────────────────────────────────────────────────
_TESSERACT_CMD = r"D:\Tesseract OCR\tesseract.exe"
_TESSDATA_PREFIX = r"D:\Tesseract OCR\tessdata"


# ── Regex Patterns ────────────────────────────────────────────────────────────

_RE_SUBKEG_HEADER = re.compile(
    r"Sub Kegiatan\s*:\s*([A-Z0-9X\.]+)\s+(.+)"
)
_RE_PROGRAM = re.compile(r"Program\s*:\s*([A-Z0-9X\.]+)\s+(.+)")
_RE_KEGIATAN = re.compile(r"Kegiatan\s*:\s*([A-Z0-9X\.]+)\s+(.+)")
_RE_URUSAN = re.compile(r"Urusan Pemerintahan\s*:\s*(.+)")
_RE_BIDANG = re.compile(r"Bidang Urusan\s*:\s*(.+)")
_RE_UNIT_ORG = re.compile(r"Unit Organisasi\s*:\s*(.+)")
_RE_SUMBER = re.compile(r"Sumber Pendanaan\s*:\s*(.+)")
_RE_LOKASI = re.compile(r"^Lokasi\s*:\s*(.+)", re.MULTILINE)
_RE_WAKTU = re.compile(r"Waktu Pelaksanaan\s*:\s*(.+)")
_RE_ALOKASI = re.compile(r"Alokasi (\d{4})\s*:\s*Rp\.\s*([\d\.,]+)")
_RE_TAHUN_ANGGARAN = re.compile(r"Tahun Anggaran(?:\s+Pergeseran)?\s+(\d{4})")

# Kode rekening: 5 atau 5.1 atau 5.1.02 dll (level 1-7)
_RE_KODE_REKENING = re.compile(
    r"^(5(?:\.\d+){0,6})\s+(.+?)\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s*$"
)
# Item spesifikasi: "NamaBarangSpesifikasi : N Satuan Satuan harga - jumlah N ..."
_RE_ITEM_SPEK = re.compile(
    r"^(.+?)Spesifikasi\s*:\s*(.*?)\s+(\d[\d\s]*)\s+(\S+)\s+\S+\s+([\d\.]+,\d{2})\s+-\s+([\d\.]+,\d{2})"
)
# Jumlah akhir sub kegiatan
_RE_JUMLAH_SUBKEG = re.compile(
    r"Jumlah Anggaran Sub Kegiatan (?:Sebelum|Sesudah)\s*:\s*([\d\.]+,\d{2})"
)


def _parse_rp(s: str) -> float:
    """'1.234.567,89' → 1234567.89"""
    try:
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return 0.0


def _clean(s: str) -> str:
    return " ".join(s.split()).strip()


def _extract_tahun(text: str) -> Optional[str]:
    m = _RE_TAHUN_ANGGARAN.search(text)
    return m.group(1) if m else None


def _extract_satker(text: str) -> str:
    """Ambil nama satker dari baris Unit Organisasi."""
    m = _RE_UNIT_ORG.search(text)
    if m:
        # "7.01.0.00.0.00.08.0000 Kecamatan Candi Laras Utara" → ambil nama saja
        val = _clean(m.group(1))
        parts = val.split()
        # Skip token pertama jika berupa kode numerik
        if parts and re.match(r"[\d\.]+", parts[0]):
            return " ".join(parts[1:])
        return val
    return ""


def parse_dpa_pdf(file_bytes: bytes, nama_file: str = "") -> dict:
    """
    Auto-detect format PDF DPA lalu parse:
      - PDF teks (pdfplumber)  → format RKA-BELANJA Sebelum/Sesudah
      - PDF scan (OCR Tesseract) → format DPA-SKPD ringkas

    Return dict:
      - meta: info dokumen (satker, tahun, dll.)
      - subkegiatan: list[dict] tiap sub kegiatan
        - setiap sub kegiatan punya 'items': list[dict] rincian belanja
    """
    if _is_scan_pdf(file_bytes):
        return parse_dpa_scan_pdf(file_bytes, nama_file)
    result = {
        "meta": {
            "nama_file": nama_file,
            "satker": "",
            "tahun_anggaran": "",
            "urusan": "",
            "bidang_urusan": "",
            "unit_organisasi": "",
        },
        "subkegiatan": [],
    }

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        all_lines = []
        for page in pdf.pages:
            txt = page.extract_text() or ""
            all_lines.extend(txt.splitlines())

    # ── Ambil meta global dari halaman awal ──────────────────────────────────
    full_text = "\n".join(all_lines)

    m = _RE_URUSAN.search(full_text)
    if m:
        result["meta"]["urusan"] = _clean(m.group(1))

    m = _RE_BIDANG.search(full_text)
    if m:
        result["meta"]["bidang_urusan"] = _clean(m.group(1))

    m = _RE_UNIT_ORG.search(full_text)
    if m:
        val = _clean(m.group(1))
        result["meta"]["unit_organisasi"] = val
        parts = val.split()
        if parts and re.match(r"[\d\.]+", parts[0]):
            result["meta"]["satker"] = " ".join(parts[1:])
        else:
            result["meta"]["satker"] = val

    m = _RE_TAHUN_ANGGARAN.search(full_text)
    if m:
        result["meta"]["tahun_anggaran"] = m.group(1)

    # ── Parse per sub kegiatan ────────────────────────────────────────────────
    # Tiap sub kegiatan dimulai dengan baris "Sub Kegiatan : KODE Nama"
    # di dalam blok header Formulir RKA-BELANJA

    current_sk: Optional[dict] = None
    in_rincian = False  # True setelah baris "Rincian Anggaran Belanja Sub Kegiatan"
    skip_header_lines = 0  # skip baris header tabel rincian
    current_rekening: Optional[dict] = None  # rekening level 6 terakhir
    alokasi_buf: dict = {}

    i = 0
    while i < len(all_lines):
        line = all_lines[i].strip()

        # ── Deteksi header sub kegiatan baru ──────────────────────────────────
        if line.startswith("Sub Kegiatan :") or line.startswith("Sub Kegiatan:"):
            m = _RE_SUBKEG_HEADER.match(line)
            if m:
                # Simpan sub kegiatan sebelumnya
                if current_sk is not None:
                    result["subkegiatan"].append(current_sk)

                kode_sk = m.group(1).strip()
                nama_sk = _clean(m.group(2))

                current_sk = {
                    "subkegiatan_kode": kode_sk,
                    "subkegiatan_nama": nama_sk,
                    "program_kode": "",
                    "program_nama": "",
                    "kegiatan_kode": "",
                    "kegiatan_nama": "",
                    "sumber_pendanaan": "",
                    "lokasi": "",
                    "waktu_pelaksanaan": "",
                    "alokasi_sebelum": 0.0,
                    "alokasi_sesudah": 0.0,
                    "selisih": 0.0,
                    "items": [],
                }
                alokasi_buf = {}
                in_rincian = False
                skip_header_lines = 0

        # ── Isi field header sub kegiatan (sebelum tabel rincian) ─────────────
        if current_sk is not None and not in_rincian:
            m = _RE_PROGRAM.match(line)
            if m:
                current_sk["program_kode"] = m.group(1).strip()
                current_sk["program_nama"] = _clean(m.group(2))

            m = _RE_KEGIATAN.match(line)
            if m and not line.startswith("Sub Kegiatan"):
                current_sk["kegiatan_kode"] = m.group(1).strip()
                current_sk["kegiatan_nama"] = _clean(m.group(2))

            m = _RE_SUMBER.match(line)
            if m and not current_sk["sumber_pendanaan"]:
                current_sk["sumber_pendanaan"] = _clean(m.group(1))

            m = _RE_LOKASI.match(line)
            if m and not current_sk["lokasi"]:
                current_sk["lokasi"] = _clean(m.group(1))

            m = _RE_WAKTU.match(line)
            if m:
                current_sk["waktu_pelaksanaan"] = _clean(m.group(1))

            # Alokasi — mungkin muncul beberapa baris
            for mm in _RE_ALOKASI.finditer(line):
                tahun_a = mm.group(1)
                nilai_a = _parse_rp(mm.group(2))
                alokasi_buf[tahun_a] = nilai_a

        # ── Deteksi masuk ke bagian rincian ───────────────────────────────────
        if "Rincian Anggaran Belanja Sub Kegiatan" in line and current_sk is not None:
            in_rincian = True
            skip_header_lines = 4  # skip baris "Satuan Kerja...", "Rincian Perhitungan...", dll

            # Assign alokasi dari buf ke sub kegiatan
            tahun_dok = result["meta"]["tahun_anggaran"] or "2024"
            tahun_prev = str(int(tahun_dok) - 1)
            tahun_next = str(int(tahun_dok) + 1)
            sebelum = alokasi_buf.get(tahun_dok, 0.0)
            sesudah = alokasi_buf.get(tahun_dok, 0.0)
            # Jika ada dua nilai berbeda (pergeseran), ambil dari Alokasi X sesudah
            # PDF ini duplicate "Sesudah" di kolom kanan tapi Alokasi label sama
            current_sk["alokasi_sebelum"] = sebelum
            current_sk["alokasi_sesudah"] = sesudah
            current_sk["selisih"] = sesudah - sebelum

        # ── Parse baris dalam tabel rincian ───────────────────────────────────
        if in_rincian and current_sk is not None:
            if skip_header_lines > 0:
                skip_header_lines -= 1
                i += 1
                continue

            # Akhir sub kegiatan
            m = _RE_JUMLAH_SUBKEG.search(line)
            if m:
                # Update alokasi dari total aktual
                val = _parse_rp(m.group(1))
                if val > 0:
                    current_sk["alokasi_sebelum"] = val
                    current_sk["alokasi_sesudah"] = val
                    current_sk["selisih"] = 0.0
                in_rincian = False
                i += 1
                continue

            # Skip baris kosong / header berulang / tanda tangan
            if (not line
                    or "Rincian Perhitungan" in line
                    or "Kode Rekening" in line
                    or "Satuan Kerja Perangkat" in line
                    or "Formulir" in line
                    or "RENCANA KERJA" in line
                    or "RKA-BELANJA" in line
                    or "Pembahasan" in line
                    or "Tim Anggaran" in line
                    or line.startswith("No ")
                    or re.match(r"^\d+\s+[A-Z].*NIP", line)
                    or "Kab. Tapin" in line
                    or "Camat " in line
                    or "NIP." in line
                    or re.match(r"^\d+\s+[A-Z]{2,}", line)):
                i += 1
                continue

            # Baris kode rekening (level 1-7): "5 BELANJA..." "5.1.02..." dll
            m_rek = re.match(
                r"^(5(?:\.\d+){0,6})\s+(.+?)\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s*$",
                line
            )
            if m_rek:
                kode = m_rek.group(1)
                uraian = _clean(m_rek.group(2))
                jumlah_seb = _parse_rp(m_rek.group(3))
                jumlah_ses = _parse_rp(m_rek.group(4))
                selisih = _parse_rp(m_rek.group(5))

                item = {
                    "tipe": "rekening",
                    "kode_rekening": kode,
                    "level": len(kode.split(".")),
                    "uraian": uraian,
                    "koefisien": None,
                    "satuan": None,
                    "harga_sebelum": None,
                    "jumlah_sebelum": jumlah_seb,
                    "harga_sesudah": None,
                    "jumlah_sesudah": jumlah_ses,
                    "selisih": selisih,
                    "spesifikasi": None,
                    "sumber_dana_item": None,
                }
                current_sk["items"].append(item)

                # Simpan rekening level 6 sebagai parent item spesifikasi
                if len(kode.split(".")) >= 6:
                    current_rekening = item
                i += 1
                continue

            # Baris [ # ] nama grup
            if line.startswith("[ # ]"):
                i += 1
                continue

            # Baris sumber dana item
            if line.startswith("Sumber Dana :"):
                if current_rekening is not None:
                    current_rekening["sumber_dana_item"] = _clean(line.split(":", 1)[1])
                i += 1
                continue

            # Baris [ - ] Disediakan untuk
            if line.startswith("[ - ]"):
                i += 1
                continue

            # Baris item spesifikasi: "NamaSpesifikasi : N Satuan Satuan harga - jumlah ..."
            # Contoh: "FotocopySpesifikasi : 647 Lembar Lembar 400,00 - 258.800,00 647 Lembar - 400,00 - 258.800,00 0,00"
            if "Spesifikasi" in line:
                m_sp = re.match(
                    r"^(.+?)Spesifikasi\s*:\s*(.*?)\s+"
                    r"(\d[\d\s\.]*)\s+(\S+)\s+\S+\s+"       # koef_seb satuan satuan
                    r"([\d\.]+,\d{2})\s+-\s+([\d\.]+,\d{2})" # harga_seb - jumlah_seb
                    r".*?([\d\.]+,\d{2})\s+-\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})",  # sesudah selisih
                    line
                )
                if not m_sp:
                    # fallback: coba ambil minimal nama + jumlah
                    m_sp = re.match(
                        r"^(.+?)Spesifikasi\s*:\s*(.*?)\s+"
                        r"(\d[\d\s\.]*)\s+(\S+)\s+\S+\s+"
                        r"([\d\.]+,\d{2})\s+-\s+([\d\.]+,\d{2})",
                        line
                    )

                if m_sp:
                    nama_item = _clean(m_sp.group(1))
                    spek = _clean(m_sp.group(2)) if m_sp.group(2).strip() else None
                    koef = _clean(m_sp.group(3))
                    satuan = m_sp.group(4)
                    harga_seb = _parse_rp(m_sp.group(5))
                    jumlah_seb = _parse_rp(m_sp.group(6))

                    try:
                        harga_ses = _parse_rp(m_sp.group(7))
                        jumlah_ses = _parse_rp(m_sp.group(8))
                        selisih_item = _parse_rp(m_sp.group(9))
                    except IndexError:
                        harga_ses = harga_seb
                        jumlah_ses = jumlah_seb
                        selisih_item = 0.0

                    parent_kode = current_rekening["kode_rekening"] if current_rekening else None

                    current_sk["items"].append({
                        "tipe": "item",
                        "kode_rekening": parent_kode,
                        "level": None,
                        "uraian": nama_item,
                        "koefisien": koef,
                        "satuan": satuan,
                        "harga_sebelum": harga_seb,
                        "jumlah_sebelum": jumlah_seb,
                        "harga_sesudah": harga_ses,
                        "jumlah_sesudah": jumlah_ses,
                        "selisih": selisih_item,
                        "spesifikasi": spek,
                        "sumber_dana_item": current_rekening["sumber_dana_item"] if current_rekening else None,
                    })

        i += 1

    # Simpan sub kegiatan terakhir
    if current_sk is not None:
        result["subkegiatan"].append(current_sk)

    return result


def deduplicate_subkegiatan(subkegiatan_list: list) -> list:
    """
    Hapus entri sub kegiatan duplikat — pertahankan entri yang punya items.
    Tiap sub kegiatan muncul 2x di PDF: halaman header (kosong) + halaman rincian (berisi).
    """
    seen: dict[str, dict] = {}
    for sk in subkegiatan_list:
        kode = sk["subkegiatan_kode"]
        if kode not in seen:
            seen[kode] = sk
        else:
            existing = seen[kode]
            # Pilih yang punya lebih banyak items atau alokasi > 0
            if len(sk["items"]) > len(existing["items"]) or (
                sk["alokasi_sesudah"] > 0 and existing["alokasi_sesudah"] == 0
            ):
                seen[kode] = sk
    return list(seen.values())


# ══════════════════════════════════════════════════════════════════════════════
# POLA 2 — DPA SCAN (OCR via Tesseract)
# Format: DPA-SKPD ringkas, tiap file biasanya 1 sub kegiatan, kolom tunggal
# Contoh: DPA Cytotoxic2026.pdf (scan gambar dari printer/scanner)
# ══════════════════════════════════════════════════════════════════════════════

# Regex untuk format scan (kolom tunggal tanpa Sebelum/Sesudah)
_RE_SCAN_URUSAN   = re.compile(r"URUSAN PEMERINTAHAN\s*[:\=]\s*(.+)", re.I)
_RE_SCAN_BIDANG   = re.compile(r"BIDANG URUSAN\s*[:\=]\s*(.+)", re.I)
_RE_SCAN_ORG      = re.compile(r"ORGANISASI\s*[:\=]\s*(.+)", re.I)
_RE_SCAN_TAHUN    = re.compile(r"TAHUN ANGGARAN\s+(\d{4})", re.I)
_RE_SCAN_PROGRAM  = re.compile(r"Program\s*[:\=]\s*([0-9X\.]+)\s+(.+)", re.I)
_RE_SCAN_KEGIATAN = re.compile(r"Kegiatan\s*[:\=]\s*([0-9X\.]+)\s+(.+)", re.I)
_RE_SCAN_SUBKEG   = re.compile(r"Sub Kegiatan\s*[:\=]\s*([0-9X\.]+)\s+(.+)", re.I)
_RE_SCAN_SUMBER   = re.compile(r"Sumber Dana\s*[:\=]\s*(.+)", re.I)
_RE_SCAN_JUMLAH   = re.compile(r"Jumlah Anggaran Sub Kegiatan\s+Rp([\d\.,]+)", re.I)

# Kode rekening format scan: "5.2.03.01.001 Uraian ... Rp1.234.567,00"
_RE_SCAN_REKENING = re.compile(
    r"^(5(?:\.\d+){1,6})\s+(.+?)\s+Rp([\d\.,]+)", re.I
)
# Item baris: "NamaSpesifikasi: ...\n koef M2 Rpx,xx 0% Rpjumlah"
_RE_SCAN_ITEM_JUMLAH = re.compile(r"Rp([\d\.,]+(?:\.000|\.00)?)\s*$")


def _is_scan_pdf(file_bytes: bytes) -> bool:
    """Return True jika PDF berupa gambar scan (tidak ada karakter teks)."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        total_chars = sum(len(p.chars) for p in pdf.pages[:3])
    return total_chars == 0


def _ocr_pages(file_bytes: bytes, resolution: int = 250) -> list[str]:
    """OCR semua halaman PDF → list teks per halaman."""
    try:
        import pytesseract
        from PIL import Image as _PILImage
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
        os.environ["TESSDATA_PREFIX"] = _TESSDATA_PREFIX
    except ImportError:
        raise RuntimeError("pytesseract tidak terinstall — pip install pytesseract")

    pages_text = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=resolution).original
            txt = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
            pages_text.append(txt)
    return pages_text


def _parse_rp_ocr(s: str) -> float:
    """Parse nilai rupiah dari hasil OCR — toleran noise (spasi, huruf O→0 dll)."""
    # Hapus semua non-digit non-koma non-titik
    s = re.sub(r"[^\d\.,]", "", s)
    # Format Indonesia: titik = separator ribuan, koma = desimal
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except Exception:
        return 0.0


_RE_SCAN_KODE_REK_LOOSE = re.compile(
    # Toleran OCR noise: karakter awal kode rekening sering rusak
    # Contoh: "�.2.03.01.001", "5.2.03.01.001", "pe |", "sae |"
    r"(?:^|\s)([1-9][\d]{0,1}(?:\.\d+){1,6})\s+(.+?)\s+Rp([\d\.,]+)",
    re.I | re.MULTILINE
)
_RE_SCAN_RP_LINE = re.compile(r"Rp([\d\.,]+(?:\.000|\.00)?)\s*(?:,00)?$")


def parse_dpa_scan_pdf(file_bytes: bytes, nama_file: str = "") -> dict:
    """
    Parse PDF scan (gambar) DPA-SKPD via OCR Tesseract.
    Mengembalikan struktur sama dengan parse_dpa_pdf().
    """
    pages_text = _ocr_pages(file_bytes)
    full_text = "\n".join(pages_text)
    lines = full_text.splitlines()

    result = {
        "meta": {
            "nama_file": nama_file,
            "satker": "",
            "tahun_anggaran": "",
            "urusan": "",
            "bidang_urusan": "",
            "unit_organisasi": "",
            "sumber": "ocr",
        },
        "subkegiatan": [],
    }

    # ── Meta global ───────────────────────────────────────────────────────────
    for line in lines:
        line_s = line.strip()
        if not result["meta"]["tahun_anggaran"]:
            m = _RE_SCAN_TAHUN.search(line_s)
            if m:
                result["meta"]["tahun_anggaran"] = m.group(1)
        if not result["meta"]["urusan"]:
            m = _RE_SCAN_URUSAN.search(line_s)
            if m:
                result["meta"]["urusan"] = _clean(m.group(1))
        if not result["meta"]["bidang_urusan"]:
            m = _RE_SCAN_BIDANG.search(line_s)
            if m:
                result["meta"]["bidang_urusan"] = _clean(m.group(1))
        if not result["meta"]["unit_organisasi"]:
            m = _RE_SCAN_ORG.search(line_s)
            if m:
                val = _clean(m.group(1))
                result["meta"]["unit_organisasi"] = val
                parts = val.split()
                # Buang prefix kode numerik dan tanda "-"
                start = 0
                while start < len(parts) and (
                    re.match(r"[\d\.]+", parts[start]) or parts[start] == "-"
                ):
                    start += 1
                result["meta"]["satker"] = " ".join(parts[start:]) if start < len(parts) else val

    # ── Strategi parse sub kegiatan untuk format scan ─────────────────────────
    # Format DPA-SKPD scan memiliki 2 varian:
    #   A) Ada "Sub Kegiatan :" berulang di halaman rincian (seperti DPA teks)
    #   B) "Sub Kegiatan :" hanya muncul di halaman cover — halaman rincian
    #      berisi kode rekening langsung tanpa header sub kegiatan

    # Kumpulkan semua sub kegiatan dari seluruh teks
    sk_headers = []
    for line in lines:
        m = _RE_SCAN_SUBKEG.match(line.strip())
        if m:
            sk_headers.append({
                "kode": m.group(1).strip(),
                "nama": _clean(m.group(2)),
            })

    # Jika tidak ditemukan, coba lebih toleran (OCR kadang ada spasi ekstra)
    if not sk_headers:
        for line in lines:
            m = re.search(r"Sub\s+Kegiatan\s*[:\=]\s*([0-9X\.]+)\s+(.+)", line.strip(), re.I)
            if m:
                sk_headers.append({
                    "kode": m.group(1).strip(),
                    "nama": _clean(m.group(2)),
                })

    # Ambil info tambahan (program/kegiatan) dari teks awal
    prog_kode, prog_nama, keg_kode, keg_nama = "", "", "", ""
    sumber_pendanaan = ""
    for line in lines:
        line_s = line.strip()
        if not prog_kode:
            m = _RE_SCAN_PROGRAM.match(line_s)
            if m:
                prog_kode = m.group(1).strip()
                prog_nama = _clean(m.group(2))
        if not keg_kode:
            m = _RE_SCAN_KEGIATAN.match(line_s)
            if m and "Sub" not in line_s:
                keg_kode = m.group(1).strip()
                keg_nama = _clean(m.group(2))
        if not sumber_pendanaan:
            m = _RE_SCAN_SUMBER.search(line_s)
            if m:
                sumber_pendanaan = _clean(m.group(1))

    # ── Buat template sub kegiatan ────────────────────────────────────────────
    def _make_sk(kode, nama):
        return {
            "subkegiatan_kode": kode,
            "subkegiatan_nama": nama,
            "program_kode": prog_kode,
            "program_nama": prog_nama,
            "kegiatan_kode": keg_kode,
            "kegiatan_nama": keg_nama,
            "sumber_pendanaan": sumber_pendanaan,
            "lokasi": "",
            "waktu_pelaksanaan": "",
            "alokasi_sebelum": 0.0,
            "alokasi_sesudah": 0.0,
            "selisih": 0.0,
            "items": [],
        }

    # ── Parse kode rekening dan item dari seluruh teks ────────────────────────
    # Gunakan 1 sub kegiatan sebagai container (varian B: 1 sub keg per file)
    # atau bagi per sub kegiatan (varian A: multi sub keg)

    if sk_headers:
        # Varian B atau A: buat sk dari header yang ditemukan
        # Karena format scan sering 1 sub keg per file, pakai sk pertama sebagai container
        current_sk = _make_sk(sk_headers[0]["kode"], sk_headers[0]["nama"])
        if len(sk_headers) > 1:
            # Multi sub kegiatan — tandai untuk parse lanjut
            pass
    else:
        # Fallback: buat sk placeholder dari nama file
        kode_fallback = "UNKNOWN"
        nama_fallback = re.sub(r"\.pdf$", "", nama_file, flags=re.I)
        current_sk = _make_sk(kode_fallback, nama_fallback)

    current_rekening: Optional[dict] = None
    in_rincian = False

    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        # Deteksi masuk rincian (setelah "Kode Rekening" header atau "Sumber Dana")
        if "Kode Rekening" in line_s and "Uraian" in line_s:
            in_rincian = True
            continue

        if not in_rincian:
            continue

        # Jumlah total sub kegiatan
        m = _RE_SCAN_JUMLAH.search(line_s)
        if m:
            val = _parse_rp_ocr(m.group(1))
            current_sk["alokasi_sebelum"] = val
            current_sk["alokasi_sesudah"] = val
            continue

        # Skip baris noise / header berulang
        if any(kw in line_s for kw in [
            "Kode Rekening", "Uraian", "Koefisien", "Volume", "Satuan", "Harga",
            "Rencana Realisasi", "Januari", "Februari", "Maret", "April",
            "Rantau", "KEPALA", "NIP", "PPKD", "Mengesahkan", "Disetujui",
            "Jumlah (Rp)", "Spesifikasi:",
        ]):
            continue

        # Kode rekening — parse toleran OCR noise
        # Coba pola bersih dulu: "5.x.xx..." di awal baris
        m_rek = re.match(
            r"^(5(?:\.\d+){1,6})\s+(.+?)\s+Rp([\d\._\,]+)",
            line_s, re.I
        )
        if not m_rek:
            # Toleran: kode awalan rusak OCR (misal "�.2.03.01.001")
            m_rek = re.match(
                r"^[^\d\s]{0,3}(\d[\d\.]+(?:\.\d{3}){0,5})\s+(.+?)\s+Rp([\d\._\,]+)",
                line_s, re.I
            )

        if m_rek:
            kode_raw = m_rek.group(1)
            # Perbaiki kode yang mungkin diawali digit bukan 5 (OCR error)
            kode = kode_raw if kode_raw.startswith("5") else "5." + kode_raw.lstrip("5.")
            uraian = _clean(m_rek.group(2))
            # Hapus noise "_" dari angka (OCR artefak)
            jumlah_str = m_rek.group(3).replace("_", "")
            jumlah = _parse_rp_ocr(jumlah_str)

            item = {
                "tipe": "rekening",
                "kode_rekening": kode,
                "level": len(kode.split(".")),
                "uraian": uraian,
                "koefisien": None,
                "satuan": None,
                "harga_sebelum": None,
                "jumlah_sebelum": jumlah,
                "harga_sesudah": None,
                "jumlah_sesudah": jumlah,
                "selisih": 0.0,
                "spesifikasi": None,
                "sumber_dana_item": sumber_pendanaan,
            }
            current_sk["items"].append(item)
            if len(kode.split(".")) >= 5:
                current_rekening = item
            continue

        # Item detail — pola: angka koef + satuan + Rpx + % + Rpjumlah
        m_item = re.search(
            r"([\d\s\.]+)\s+(M2|m2|Unit|unit|Ls|ls|Paket|paket|Buah|buah|Bh|bh)\s+"
            r"Rp([\d\.,]+)\s+(\d+)%\s+Rp([\d\.,]+)",
            line_s, re.I
        )
        if m_item and current_rekening is not None:
            koef_raw = re.sub(r"\s+", "", m_item.group(1))
            satuan = m_item.group(2)
            harga = _parse_rp_ocr(m_item.group(3))
            jumlah = _parse_rp_ocr(m_item.group(5))

            uraian_item = re.sub(
                r"([\d\s\.]+)\s+(M2|m2|Unit|unit|Ls|ls|Paket|paket|Buah|buah|Bh|bh)\s+.*",
                "", line_s, flags=re.I
            ).strip() or current_rekening["uraian"]

            current_sk["items"].append({
                "tipe": "item",
                "kode_rekening": current_rekening["kode_rekening"],
                "level": None,
                "uraian": uraian_item,
                "koefisien": koef_raw,
                "satuan": satuan,
                "harga_sebelum": harga,
                "jumlah_sebelum": jumlah,
                "harga_sesudah": harga,
                "jumlah_sesudah": jumlah,
                "selisih": 0.0,
                "spesifikasi": None,
                "sumber_dana_item": sumber_pendanaan,
            })

    result["subkegiatan"].append(current_sk)
    return result


def flatten_to_rows(parsed: dict) -> list[dict]:
    """
    Flatten hasil parse ke list baris datar — siap upsert ke Supabase
    tabel dpa_item_belanja.
    """
    rows = []
    meta = parsed["meta"]
    clean_sk = deduplicate_subkegiatan(parsed["subkegiatan"])
    for sk in clean_sk:
        sk_base = {
            "satker": meta["satker"],
            "tahun_anggaran": meta["tahun_anggaran"],
            "urusan": meta["urusan"],
            "bidang_urusan": meta["bidang_urusan"],
            "unit_organisasi": meta["unit_organisasi"],
            "nama_file": meta["nama_file"],
            "program_kode": sk["program_kode"],
            "program_nama": sk["program_nama"],
            "kegiatan_kode": sk["kegiatan_kode"],
            "kegiatan_nama": sk["kegiatan_nama"],
            "subkegiatan_kode": sk["subkegiatan_kode"],
            "subkegiatan_nama": sk["subkegiatan_nama"],
            "sumber_pendanaan": sk["sumber_pendanaan"],
            "lokasi_subkeg": sk["lokasi"],
            "waktu_pelaksanaan": sk["waktu_pelaksanaan"],
            "alokasi_sebelum": sk["alokasi_sebelum"],
            "alokasi_sesudah": sk["alokasi_sesudah"],
        }
        for item in sk["items"]:
            row = {**sk_base, **item}
            rows.append(row)
    return rows
