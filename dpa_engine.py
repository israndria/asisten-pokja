"""
DPA Engine — Parser PDF Dokumen Pelaksanaan Anggaran (DPA/RKA) Pemda.

3 pola yang didukung:
  1. DPA TEKS (RKA-BELANJA Sebelum/Sesudah) — pdfplumber, multi sub kegiatan
  2. DPA SCAN (gambar, format ringkas DPA-SKPD) — OCR Tesseract, 1 sub kegiatan per file
  3. DPPA-SKPD (font corrupt dari SIPD) — chars > 0 tapi teks rusak → fallback OCR

Deteksi:
  - chars==0 → scan murni → OCR
  - chars>0 tapi parse menghasilkan 0 sub kegiatan → font corrupt → retry OCR
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

# Separator toleran: ':', '+', '=', atau spasi langsung
# Kode toleran: digit, huruf kapital (O/I sering OCR-error untuk 0/1), titik, koma, dash
_RE_SUBKEG_HEADER = re.compile(
    r"Sub\s+Kegiatan\s*[:\+=\s]+([0-9A-Z,\.X]+(?:[-\.][0-9A-Z,\.X]+)*)\s*[-–]\s*(.+)", re.I
)
_RE_PROGRAM = re.compile(r"Program\s*[:\+=\s]+([0-9A-Z,\.X]+(?:[-\.][0-9A-Z,\.X]+)*)\s*[-–]\s*(.+)", re.I)
_RE_KEGIATAN = re.compile(r"Kegiatan\s*[:\+=\s]+([0-9A-Z,\.X]+(?:[-\.][0-9A-Z,\.X]+)*)\s*[-–]\s*(.+)", re.I)
_RE_URUSAN = re.compile(r"Urusan Pemerintahan\s*:\s*(.+)")
_RE_BIDANG = re.compile(r"Bidang Urusan\s*:\s*(.+)")
_RE_UNIT_ORG = re.compile(r"Unit Organisasi\s*:\s*(.+)")
_RE_SUMBER = re.compile(r"Sumber Pendanaan\s*:\s*(.+)")
_RE_LOKASI = re.compile(r"^Lokasi\s*:\s*(.+)", re.MULTILINE)
_RE_WAKTU = re.compile(r"Waktu Pelaksanaan\s*:\s*(.+)")
_RE_ALOKASI = re.compile(r"Alokasi (\d{4}|Tahun)\s*:\s*Rp\.?\s*([\d\.,]+)")
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
    r"Jumlah Anggaran Sub Kegiatan(?:\s+(?:Sebelum|Sesudah)\s*:)?\s*Rp?([\d\.]+,\d{2})"
)


def _normalize_kode(kode: str) -> str:
    """Normalisasi kode sub kegiatan dari OCR: ganti koma → titik, buang spasi."""
    return re.sub(r",", ".", kode.strip())


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
      - DPPA-SKPD font corrupt (SIPD) → chars>0 tapi 0 subkegiatan → fallback OCR

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
    current_item_nama: Optional[str] = None  # nama item dari baris [ - ] terakhir
    current_paket_nama: Optional[str] = None  # nama paket dari baris [ # ] terakhir
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

        # ── Alokasi — di luar blok current_sk agar tertangkap meski muncul sebelum header SK ──
        for mm in _RE_ALOKASI.finditer(line):
            tahun_a = mm.group(1)
            nilai_a = _parse_rp(mm.group(2))
            alokasi_buf[tahun_a] = nilai_a

        # ── Deteksi masuk ke bagian rincian ───────────────────────────────────
        _trigger_rincian = (
            "Rincian Anggaran Belanja Sub Kegiatan" in line
            or "Rincian Perhitungan Jumlah" in line
        )
        if _trigger_rincian and current_sk is not None and not in_rincian:
            in_rincian = True
            skip_header_lines = 1 if "Rincian Perhitungan Jumlah" in line else 4

            # Assign alokasi dari buf ke sub kegiatan
            tahun_dok = result["meta"]["tahun_anggaran"] or "2024"
            sebelum = alokasi_buf.get(tahun_dok, 0.0)
            # Format baru: alokasi_buf pakai key "Tahun" jika tidak ada tahun eksplisit
            if sebelum == 0.0:
                sebelum = alokasi_buf.get("Tahun", 0.0)
            sesudah = sebelum
            current_sk["alokasi_sebelum"] = sebelum
            current_sk["alokasi_sesudah"] = sesudah
            current_sk["selisih"] = 0.0

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
                    "nama_paket": current_paket_nama,
                }
                current_sk["items"].append(item)
                current_item_nama = None
                current_paket_nama = None

                # Simpan rekening level 6 sebagai parent item spesifikasi
                if len(kode.split(".")) >= 6:
                    current_rekening = item
                i += 1
                continue

            # Format 1-kolom: "5.x.x Uraian Rp1.234.567,00" (tanpa kolom sebelum/selisih)
            m_rek1 = re.match(
                r"^(5(?:\.\d+){1,6})\s+(.+?)\s+Rp([\d\.]+,\d{2})\s*$",
                line
            )
            if m_rek1:
                kode = m_rek1.group(1)
                uraian = _clean(m_rek1.group(2))
                jumlah = _parse_rp(m_rek1.group(3))

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
                    "sumber_dana_item": None,
                    "nama_paket": current_paket_nama,
                }
                current_sk["items"].append(item)
                current_item_nama = None
                current_paket_nama = None

                if len(kode.split(".")) >= 6:
                    current_rekening = item
                i += 1
                continue

            # Baris [ # ] nama paket/pekerjaan
            if line.startswith("[ # ]"):
                raw_paket = _clean(line[5:].strip())
                current_paket_nama = re.sub(r"\s+Rp[\d\.,]+\s*$", "", raw_paket).strip()
                i += 1
                continue

            # Baris sumber dana item
            if line.startswith("Sumber Dana :") or line.startswith("Sumber Dana:"):
                if current_rekening is not None:
                    current_rekening["sumber_dana_item"] = _clean(line.split(":", 1)[1])
                i += 1
                continue

            # Baris [ - ] nama item — simpan nama untuk baris koef berikutnya
            if line.startswith("[ - ]"):
                current_item_nama = _clean(line[5:].strip())
                # Hapus jumlah Rp di akhir jika ada (format: "[ - ] Nama Item Rp1.234,00")
                current_item_nama = re.sub(r"\s+Rp[\d\.,]+\s*$", "", current_item_nama).strip()
                i += 1
                continue

            # Baris item koef 1-kolom: "100 Buah Buah Rp12.700,00 0% Rp1.270.000,00"
            m_koef1 = re.match(
                r"^([\d\s\.]+)\s+(\S+)\s+\S+\s+Rp([\d\.]+,\d{2})\s+\d+%\s+Rp([\d\.]+,\d{2})\s*$",
                line
            )
            if m_koef1 and current_sk is not None:
                koef = m_koef1.group(1).strip()
                satuan = m_koef1.group(2)
                harga = _parse_rp(m_koef1.group(3))
                jumlah = _parse_rp(m_koef1.group(4))
                parent_kode = current_rekening["kode_rekening"] if current_rekening else None
                current_sk["items"].append({
                    "tipe": "item",
                    "kode_rekening": parent_kode,
                    "level": None,
                    "uraian": current_item_nama or "—",
                    "koefisien": koef,
                    "satuan": satuan,
                    "harga_sebelum": harga,
                    "jumlah_sebelum": jumlah,
                    "harga_sesudah": harga,
                    "jumlah_sesudah": jumlah,
                    "selisih": 0.0,
                    "spesifikasi": None,
                    "sumber_dana_item": current_rekening["sumber_dana_item"] if current_rekening else None,
                    "nama_paket": current_paket_nama,
                })
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
                        "nama_paket": current_paket_nama,
                    })

        i += 1

    # Simpan sub kegiatan terakhir
    if current_sk is not None:
        result["subkegiatan"].append(current_sk)

    # Deteksi format SIPD Ringkasan Paket — teks bisa dibaca tapi struktur berbeda
    _all_empty = all(len(sk["items"]) == 0 for sk in result["subkegiatan"]) if result["subkegiatan"] else True
    if _all_empty and "RINGKASAN PAKET" in full_text.upper():
        sipd_result = parse_sipd_ringkasan(all_lines, nama_file)
        if sipd_result["subkegiatan"] and any(len(sk["items"]) > 0 for sk in sipd_result["subkegiatan"]):
            return sipd_result

    # Fallback: jika teks pdfplumber tidak menghasilkan sub kegiatan (font corrupt SIPD),
    # coba OCR — PDF dengan embedded font rusak tetap punya chars > 0
    if not result["subkegiatan"]:
        ocr_result = parse_dpa_scan_pdf(file_bytes, nama_file)
        ocr_result["meta"]["sumber"] = "ocr_fallback"
        return ocr_result

    return result


def parse_sipd_ringkasan(all_lines: list[str], nama_file: str = "") -> dict:
    """
    Parser format SIPD 'Ringkasan Paket / Pengelompokan Belanja'.
    Struktur:
      Sub Kegiatan : KODE Nama
      Jumlah YYYY  : Rp. xxx
      [ # ] Nama Paket
      Rp. xxx
      Sumber Dana : ...
      [ - ] Uraian Item Rp. xxx
    """
    _RE_RP = re.compile(r"Rp\.?\s*([\d\.]+,\d{2})")
    _RE_JUMLAH_TAHUN = re.compile(r"Jumlah\s+(\d{4})\s*:\s*Rp\.?\s*([\d\.]+,\d{2})")
    _RE_ITEM_INLINE = re.compile(r"^\[\s*-\s*\]\s*(.+?)\s+Rp\.?\s*([\d\.]+,\d{2})\s*$")
    _RE_ITEM_MULTILINE = re.compile(r"^\[\s*-\s*\]\s*(.+)")

    result = {
        "meta": {
            "nama_file": nama_file,
            "satker": "", "tahun_anggaran": "",
            "urusan": "", "bidang_urusan": "", "unit_organisasi": "",
            "sumber": "sipd_ringkasan",
        },
        "subkegiatan": [],
    }

    full_text = "\n".join(all_lines)

    # Meta global
    m = _RE_URUSAN.search(full_text)
    if m: result["meta"]["urusan"] = _clean(m.group(1))
    m = _RE_BIDANG.search(full_text)
    if m: result["meta"]["bidang_urusan"] = _clean(m.group(1))
    m = _RE_UNIT_ORG.search(full_text)
    if m:
        val = _clean(m.group(1))
        result["meta"]["unit_organisasi"] = val
        parts = val.split()
        result["meta"]["satker"] = " ".join(parts[1:]) if parts and re.match(r"[\d\.]+", parts[0]) else val

    # Ambil tahun dari "Pemerintahan ... Tahun Anggaran YYYY" atau "Jumlah YYYY"
    m = re.search(r"Tahun Anggaran\s+(\d{4})", full_text)
    if m: result["meta"]["tahun_anggaran"] = m.group(1)

    current_sk: Optional[dict] = None
    current_paket: Optional[str] = None
    current_sumber: Optional[str] = None
    pending_rp: Optional[float] = None  # nilai Rp. setelah baris [ # ]
    pending_item_nama: Optional[str] = None  # nama [ - ] multiline yang belum ada Rp

    def _new_sk(kode, nama):
        return {
            "subkegiatan_kode": kode,
            "subkegiatan_nama": nama,
            "program_kode": "", "program_nama": "",
            "kegiatan_kode": "", "kegiatan_nama": "",
            "sumber_pendanaan": "",
            "lokasi": "", "waktu_pelaksanaan": "",
            "alokasi_sebelum": 0.0, "alokasi_sesudah": 0.0, "selisih": 0.0,
            "items": [],
        }

    tahun_dok = result["meta"]["tahun_anggaran"] or "2026"

    i = 0
    while i < len(all_lines):
        line = all_lines[i].strip()

        # Program / Kegiatan
        if not current_sk:
            m = _RE_PROGRAM.match(line)
            if m and not line.startswith("Sub"):
                pass  # simpan jika perlu
            m = re.match(r"Program\s*:\s*([^\s]+)\s+(.+)", line)
            if m:
                _prog_kode = m.group(1).strip()
                _prog_nama = _clean(m.group(2))
            m = re.match(r"Kegiatan\s*:\s*([^\s]+)\s+(.+)", line)
            if m and not line.startswith("Sub"):
                _keg_kode = m.group(1).strip()
                _keg_nama = _clean(m.group(2))

        # Header Sub Kegiatan — format "Sub Kegiatan : KODE Nama" (spasi sebagai separator)
        m_sk = _RE_SUBKEG_HEADER.match(line)
        if not m_sk:
            m_sk = re.match(r"Sub\s+Kegiatan\s*[:\s]+([0-9][0-9\.]+)\s+(.+)", line, re.I)
        if m_sk:
            if current_sk is not None:
                result["subkegiatan"].append(current_sk)
            current_sk = _new_sk(m_sk.group(1).strip(), _clean(m_sk.group(2)))
            current_paket = None
            pending_rp = None
            pending_item_nama = None
            i += 1
            continue

        if current_sk is None:
            # Alokasi dari "Jumlah YYYY : Rp. xxx" di header (sebelum SK terdeteksi)
            # — ambil saja, assign ke SK pertama nanti
            i += 1
            continue

        # Alokasi "Jumlah YYYY : Rp. xxx"
        m_j = _RE_JUMLAH_TAHUN.search(line)
        if m_j and m_j.group(1) == tahun_dok:
            current_sk["alokasi_sesudah"] = _parse_rp(m_j.group(2))
            current_sk["alokasi_sebelum"] = current_sk["alokasi_sesudah"]
            i += 1
            continue

        # Sumber pendanaan global SK
        if line.startswith("Sumber Pendanaan :") and not current_sk["sumber_pendanaan"]:
            current_sk["sumber_pendanaan"] = _clean(line.split(":", 1)[1])
            i += 1
            continue

        # Lokasi / Waktu
        m_lok = _RE_LOKASI.match(line)
        if m_lok and not current_sk["lokasi"]:
            current_sk["lokasi"] = _clean(m_lok.group(1))
            i += 1
            continue
        m_wkt = _RE_WAKTU.match(line)
        if m_wkt:
            current_sk["waktu_pelaksanaan"] = _clean(m_wkt.group(1))
            i += 1
            continue

        # [ # ] Nama Paket — bisa inline "[ # ] Nama\nRp. xxx" atau "[ # ] Nama Rp. xxx"
        if re.match(r"^\[\s*#\s*\]", line):
            raw = re.sub(r"^\[\s*#\s*\]\s*", "", line)
            # Cek apakah Rp ada di baris ini
            m_rp = _RE_RP.search(raw)
            if m_rp:
                current_paket = re.sub(r"\s+Rp\.?\s*[\d\.]+,\d{2}\s*$", "", raw).strip()
                pending_rp = _parse_rp(m_rp.group(1))
            else:
                current_paket = _clean(raw)
                pending_rp = None
            current_sumber = None
            i += 1
            continue

        # Baris "Rp. xxx" setelah [ # ] (nilai paket)
        if pending_rp is None and current_paket is not None:
            m_rp2 = re.match(r"^Rp\.?\s*([\d\.]+,\d{2})\s*$", line)
            if m_rp2:
                pending_rp = _parse_rp(m_rp2.group(1))
                i += 1
                continue

        # Sumber Dana item
        if line.startswith("Sumber Dana :") or line.startswith("Sumber Dana:"):
            current_sumber = _clean(line.split(":", 1)[1])
            i += 1
            continue

        # [ - ] Uraian Item — inline: "[ - ] Nama Rp. xxx" atau multiline
        if re.match(r"^\[\s*-\s*\]", line):
            raw_item = re.sub(r"^\[\s*-\s*\]\s*", "", line)
            m_inline = re.match(r"^(.+?)\s+Rp\.?\s*([\d\.]+,\d{2})\s*$", raw_item)
            if m_inline:
                uraian = _clean(m_inline.group(1))
                jumlah = _parse_rp(m_inline.group(2))
                current_sk["items"].append({
                    "tipe": "item",
                    "kode_rekening": None,
                    "level": None,
                    "uraian": uraian,
                    "koefisien": None,
                    "satuan": None,
                    "harga_sebelum": None,
                    "jumlah_sebelum": jumlah,
                    "harga_sesudah": None,
                    "jumlah_sesudah": jumlah,
                    "selisih": 0.0,
                    "spesifikasi": None,
                    "sumber_dana_item": current_sumber,
                    "nama_paket": current_paket,
                })
                pending_item_nama = None
            else:
                # Multiline — nama di baris ini, lanjut ke baris berikutnya
                pending_item_nama = _clean(raw_item)
            i += 1
            continue

        # Lanjutan multiline [ - ]: baris dengan Rp
        if pending_item_nama is not None:
            m_rp3 = re.match(r"^(.+?)\s+Rp\.?\s*([\d\.]+,\d{2})\s*$", line)
            if m_rp3:
                uraian = pending_item_nama + " " + _clean(m_rp3.group(1))
                jumlah = _parse_rp(m_rp3.group(2))
                current_sk["items"].append({
                    "tipe": "item",
                    "kode_rekening": None,
                    "level": None,
                    "uraian": uraian.strip(),
                    "koefisien": None,
                    "satuan": None,
                    "harga_sebelum": None,
                    "jumlah_sebelum": jumlah,
                    "harga_sesudah": None,
                    "jumlah_sesudah": jumlah,
                    "selisih": 0.0,
                    "spesifikasi": None,
                    "sumber_dana_item": current_sumber,
                    "nama_paket": current_paket,
                })
                pending_item_nama = None
            else:
                # Masih lanjutan nama
                pending_item_nama += " " + line
            i += 1
            continue

        i += 1

    if current_sk is not None:
        result["subkegiatan"].append(current_sk)

    # Fix alokasi dari "Jumlah YYYY" di header (sebelum SK loop, ambil dari full_text)
    for sk in result["subkegiatan"]:
        if sk["alokasi_sesudah"] == 0.0:
            m_j2 = _RE_JUMLAH_TAHUN.search(full_text)
            while m_j2:
                if m_j2.group(1) == tahun_dok:
                    sk["alokasi_sesudah"] = _parse_rp(m_j2.group(2))
                    sk["alokasi_sebelum"] = sk["alokasi_sesudah"]
                    break
                m_j2 = _RE_JUMLAH_TAHUN.search(full_text, m_j2.end())

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
_RE_SCAN_PROGRAM  = re.compile(r"Program\s*[:\+=\s]+([0-9A-Z,\.X]+(?:[-\.][0-9A-Z,\.X]+)*)\s*[-–]\s*(.+)", re.I)
_RE_SCAN_KEGIATAN = re.compile(r"Kegiatan\s*[:\+=\s]+([0-9A-Z,\.X]+(?:[-\.][0-9A-Z,\.X]+)*)\s*[-–]\s*(.+)", re.I)
_RE_SCAN_SUBKEG   = re.compile(r"Sub\s+Kegiatan\s*[:\+=\s]+([0-9A-Z,\.X]+(?:[-\.][0-9A-Z,\.X]+)*)\s*[-–]\s*(.+)", re.I)
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

    # ── Ambil info program/kegiatan global dari teks awal ────────────────────
    prog_kode, prog_nama, keg_kode, keg_nama = "", "", "", ""
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

    # ── Buat template sub kegiatan ────────────────────────────────────────────
    def _make_sk(kode, nama, sumber=""):
        return {
            "subkegiatan_kode": kode,
            "subkegiatan_nama": nama,
            "program_kode": prog_kode,
            "program_nama": prog_nama,
            "kegiatan_kode": keg_kode,
            "kegiatan_nama": keg_nama,
            "sumber_pendanaan": sumber,
            "lokasi": "",
            "waktu_pelaksanaan": "",
            "alokasi_sebelum": 0.0,
            "alokasi_sesudah": 0.0,
            "selisih": 0.0,
            "items": [],
        }

    # ── Parse multi sub kegiatan ─────────────────────────────────────────────
    # Iterasi baris: setiap "Sub Kegiatan ..." mulai blok baru.
    # "Kode Rekening ... Uraian/Berkurang" → aktifkan rincian.
    # Item bisa berupa kode rekening 5.x.x atau baris [#] nama Rp...

    current_sk: Optional[dict] = None
    current_rekening: Optional[dict] = None
    current_sumber = ""
    pending_alokasi = 0.0  # alokasi buffer — muncul sebelum header SK di halaman ini
    in_rincian = False

    def _flush_sk():
        if current_sk is not None:
            result["subkegiatan"].append(current_sk)

    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        # ── Alokasi — bisa muncul sebelum header SK di halaman yang sama ─────
        m_alok = re.search(r"Alokasi\s+Tah[uo]n\s*[;:+]?\s*(?:1\s+)?Rp([\d\.,]+)", line_s, re.I)
        if m_alok and "-1" not in line_s and "+1" not in line_s and "+4" not in line_s:
            val = _parse_rp_ocr(m_alok.group(1))
            if val > 0:
                if current_sk is not None and not in_rincian:
                    current_sk["alokasi_sebelum"] = val
                    current_sk["alokasi_sesudah"] = val
                else:
                    pending_alokasi = val  # simpan buffer, akan dipakai SK berikutnya
            continue

        # ── Deteksi header sub kegiatan baru ─────────────────────────────────
        m_sk = _RE_SCAN_SUBKEG.search(line_s)
        if m_sk and "Keluaran" not in line_s:
            _flush_sk()
            current_sk = _make_sk(
                _normalize_kode(m_sk.group(1)),
                _clean(m_sk.group(2)),
            )
            # Terapkan alokasi yang sudah di-buffer
            if pending_alokasi > 0:
                current_sk["alokasi_sebelum"] = pending_alokasi
                current_sk["alokasi_sesudah"] = pending_alokasi
                pending_alokasi = 0.0
            current_rekening = None
            in_rincian = False
            current_sumber = ""
            continue

        if current_sk is None:
            # Sebelum SK pertama — ambil sumber global jika ada
            m_s = _RE_SCAN_SUMBER.search(line_s)
            if m_s:
                current_sumber = _clean(m_s.group(1))
            continue

        # ── Sumber pendanaan per sub kegiatan ─────────────────────────────────
        m_s = _RE_SCAN_SUMBER.search(line_s)
        if m_s and not in_rincian:
            sumber_raw = _clean(m_s.group(1))
            sumber_raw = re.sub(r"\s+[a-z]{2,}[aeiou]{3,}.*$", "", sumber_raw)
            current_sumber = sumber_raw.strip()
            current_sk["sumber_pendanaan"] = current_sumber
            continue

        # ── Deteksi masuk rincian ─────────────────────────────────────────────
        if "Kode Rekening" in line_s and any(
            kw in line_s for kw in ("Uraian", "Berkurang", "Setelah", "Jumlah", "Koefisien", "Volume")
        ):
            in_rincian = True
            continue

        if not in_rincian:
            continue

        # ── Jumlah total sub kegiatan ─────────────────────────────────────────
        m = _RE_SCAN_JUMLAH.search(line_s)
        if m:
            val = _parse_rp_ocr(m.group(1))
            if val > 0:
                current_sk["alokasi_sebelum"] = val
                current_sk["alokasi_sesudah"] = val
            in_rincian = False
            continue

        # ── Skip baris noise / header berulang ───────────────────────────────
        if any(kw in line_s for kw in [
            "Kode Rekening", "Koefisien", "Volume", "Satuan", "Harga",
            "Rencana Realisasi", "Januari", "Februari", "Maret",
            "KEPALA", "NIP", "PPKD", "Mengesahkan", "Disetujui",
            "Jumlah (Rp)", "Spesifikasi:",
        ]):
            continue

        # ── Kode rekening (5.x.x...) ─────────────────────────────────────────
        m_rek = re.match(r"^(5(?:\.\d+){1,6})\s+(.+?)\s+Rp([\d\._\,]+)", line_s, re.I)
        if not m_rek:
            m_rek = re.match(
                r"^[^\d\s]{0,3}(\d[\d\.]+(?:\.\d{3}){0,5})\s+(.+?)\s+Rp([\d\._\,]+)",
                line_s, re.I
            )
        if m_rek:
            kode_raw = m_rek.group(1)
            kode = kode_raw if kode_raw.startswith("5") else "5." + kode_raw.lstrip("5.")
            uraian = _clean(m_rek.group(2))
            jumlah = _parse_rp_ocr(m_rek.group(3).replace("_", ""))
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
                "sumber_dana_item": current_sumber or current_sk["sumber_pendanaan"],
            }
            current_sk["items"].append(item)
            if len(kode.split(".")) >= 5:
                current_rekening = item
            continue

        # ── Baris [#] nama item Rp0,00 Rp0,00 Rpjumlah ──────────────────────
        # Format DPPA: "[ # ] Nama Barang/Jasa Rp0,00 Rp70.164.000,00 Rp70.164.000,00"
        if line_s.startswith("[") and "#" in line_s[:5]:
            # Ambil nilai Rp terakhir sebagai jumlah sesudah
            rp_vals = re.findall(r"Rp([\d\.,]+)", line_s)
            jumlah = _parse_rp_ocr(rp_vals[-1]) if rp_vals else 0.0
            # Nama item: strip "[#]" dan nilai Rp di belakang
            uraian_raw = re.sub(r"\[.*?\]", "", line_s)
            uraian_raw = re.sub(r"\s*Rp[\d\.,]+.*$", "", uraian_raw).strip()
            if uraian_raw:
                current_sk["items"].append({
                    "tipe": "item",
                    "kode_rekening": current_rekening["kode_rekening"] if current_rekening else None,
                    "level": None,
                    "uraian": uraian_raw,
                    "koefisien": None,
                    "satuan": None,
                    "harga_sebelum": None,
                    "jumlah_sebelum": 0.0,
                    "harga_sesudah": None,
                    "jumlah_sesudah": jumlah,
                    "selisih": jumlah,
                    "spesifikasi": None,
                    "sumber_dana_item": current_sumber or current_sk["sumber_pendanaan"],
                })
            continue

        # ── Item detail — pola koef + satuan + Rp + % + Rp ──────────────────
        m_item = re.search(
            r"([\d\s\.]+)\s+(M2|m2|Unit|unit|Ls|ls|Paket|paket|Buah|buah|Bh|bh|Pekerjaan|pekerjaan)\s+"
            r"Rp([\d\.,]+)\s+(\d+)%\s+Rp([\d\.,]+)",
            line_s, re.I
        )
        if m_item and current_rekening is not None:
            koef_raw = re.sub(r"\s+", "", m_item.group(1))
            satuan = m_item.group(2)
            harga = _parse_rp_ocr(m_item.group(3))
            jumlah = _parse_rp_ocr(m_item.group(5))
            uraian_item = re.sub(
                r"([\d\s\.]+)\s+(M2|m2|Unit|unit|Ls|ls|Paket|paket|Buah|buah|Bh|bh|Pekerjaan|pekerjaan)\s+.*",
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
                "sumber_dana_item": current_sumber or current_sk["sumber_pendanaan"],
            })

    _flush_sk()

    # Fallback: PDF DPA-SKPD lama tanpa header "Sub Kegiatan" eksplisit
    # Buat 1 SK dummy dari nama file, kumpulkan semua item yang berhasil di-parse
    if not result["subkegiatan"]:
        _sk_dummy = _make_sk("UNKNOWN", nama_file.replace(".pdf", "").strip())
        # Re-parse: aktifkan in_rincian dari awal, kumpulkan semua item
        _in_rin = False
        _cur_rek2: Optional[dict] = None
        _cur_src2 = ""
        for line in lines:
            line_s = line.strip()
            if not line_s:
                continue
            # Trigger rincian lebih longgar
            if "Kode Rekening" in line_s:
                _in_rin = True
                continue
            if "BELANJA MODAL" in line_s or "BELANJA OPERASI" in line_s:
                _in_rin = True
            if not _in_rin:
                continue
            # Jumlah total
            m_j = _RE_SCAN_JUMLAH.search(line_s)
            if m_j:
                val = _parse_rp_ocr(m_j.group(1))
                if val > 0:
                    _sk_dummy["alokasi_sebelum"] = val
                    _sk_dummy["alokasi_sesudah"] = val
                continue
            # Sumber dana
            m_src = _RE_SCAN_SUMBER.search(line_s)
            if m_src:
                _cur_src2 = _clean(m_src.group(1))
                _cur_src2 = re.sub(r"\s+[a-z]{2,}[aeiou]{3,}.*$", "", _cur_src2).strip()
                if not _sk_dummy["sumber_pendanaan"]:
                    _sk_dummy["sumber_pendanaan"] = _cur_src2
                continue
            # Kode rekening
            m_rek2 = re.match(r"^(5(?:\.\d+){1,6})\s+(.+?)\s+Rp([\d\.,]+)", line_s, re.I)
            if not m_rek2:
                m_rek2 = re.match(r"^[^\d\s]{0,3}(\d[\d\.]+)\s+(.+?)\s+Rp([\d\.,]+)", line_s, re.I)
            if m_rek2:
                kode = m_rek2.group(1)
                if not kode.startswith("5"):
                    kode = "5." + kode.lstrip("5.")
                uraian = _clean(m_rek2.group(2))
                jumlah = _parse_rp_ocr(m_rek2.group(3))
                _item2 = {
                    "tipe": "rekening",
                    "kode_rekening": kode,
                    "level": len(kode.split(".")),
                    "uraian": uraian,
                    "koefisien": None, "satuan": None,
                    "harga_sebelum": None, "jumlah_sebelum": jumlah,
                    "harga_sesudah": None, "jumlah_sesudah": jumlah,
                    "selisih": 0.0, "spesifikasi": None,
                    "sumber_dana_item": _cur_src2,
                }
                _sk_dummy["items"].append(_item2)
                if len(kode.split(".")) >= 5:
                    _cur_rek2 = _item2
                continue
            # Item koef+satuan+Rp
            m_it2 = re.search(
                r"([\d\s\.]+)\s+(M2|m2|Unit|unit|Ls|ls|Paket|paket|Buah|buah|Bh|bh|Pekerjaan|pekerjaan)\s+"
                r"Rp([\d\.,]+)\s+(\d+)%\s+Rp([\d\.,]+)",
                line_s, re.I
            )
            if m_it2 and _cur_rek2 is not None:
                koef_raw = re.sub(r"\s+", "", m_it2.group(1))
                satuan = m_it2.group(2)
                harga = _parse_rp_ocr(m_it2.group(3))
                jumlah = _parse_rp_ocr(m_it2.group(5))
                uraian_item = re.sub(
                    r"([\d\s\.]+)\s+(M2|m2|Unit|unit|Ls|ls|Paket|paket|Buah|buah|Bh|bh|Pekerjaan|pekerjaan)\s+.*",
                    "", line_s, flags=re.I
                ).strip() or _cur_rek2["uraian"]
                _sk_dummy["items"].append({
                    "tipe": "item",
                    "kode_rekening": _cur_rek2["kode_rekening"],
                    "level": None, "uraian": uraian_item,
                    "koefisien": koef_raw, "satuan": satuan,
                    "harga_sebelum": harga, "jumlah_sebelum": jumlah,
                    "harga_sesudah": harga, "jumlah_sesudah": jumlah,
                    "selisih": 0.0, "spesifikasi": None,
                    "sumber_dana_item": _cur_src2,
                })
        result["subkegiatan"].append(_sk_dummy)

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
