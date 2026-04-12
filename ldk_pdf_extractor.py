"""
LDK PDF Extractor v4 — Extract 2 row Izin Usaha + Kinerja Penyedia dari DOKPIL PDF.

Alur:
1. Upload PDF DOKPIL
2. Extract semua teks (per halaman)
3. Cari BAB V (Lembar Data Kualifikasi)
4. Parse:
   - Row 1: Sertifikat Badan Usaha SBU + deskripsi
   - Row 2: Izin Usaha di bidang Jasa Konstruksi + deskripsi
   - Kinerja Penyedia (checkbox + text)
5. Return data terstruktur untuk auto-fill
"""

import re
from pypdf import PdfReader
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IzinUsahaRow:
    """Satu row Izin Usaha."""
    jenis_izin: str = ""
    klasifikasi: str = ""


@dataclass
class LDKData:
    """Hasil extract LDK dari DOKPIL."""
    # Multi-row Izin Usaha
    izin_usaha_rows: list = field(default_factory=list)  # List[IzinUsahaRow]
    
    # Kinerja Penyedia
    kinerja_penyedia: str = ""
    kinerja_required: bool = False
    
    # SBU detail
    sbu_kualifikasi: str = "Kecil"
    sbu_kode: str = ""
    sbu_deskripsi: str = ""
    
    # Persyaratan lain
    pengalaman_min: int = 0
    skp_kp: int = 5
    
    raw_text: str = ""
    halaman_ldk: int = 0
    extracted: bool = False
    errors: list = field(default_factory=list)


def extract_pages_from_pdf(pdf_path: str) -> list[tuple[int, str]]:
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append((i + 1, text))
    return pages


def find_ldk_pages(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    ldk_pages = []
    in_ldk = False
    for page_num, text in pages:
        text_lower = text.lower()
        has_bab_v_heading = (
            'bab v.' in text_lower[:300] and 
            'lembar data kualifikasi' in text_lower[:400]
        )
        if has_bab_v_heading:
            in_ldk = True
        if in_ldk:
            ldk_pages.append((page_num, text))
        if in_ldk and 'bab vi' in text_lower:
            break
    return ldk_pages


def _clean_trailing(text: str) -> str:
    """Hapus sisa nomor poin (misal '3.' atau '2.') di ujung teks hasil regex."""
    return re.sub(r'\s*\d+\.\s*$', '', text.strip()).strip()


def parse_ldk_content(ldk_pages: list[tuple[int, str]]) -> LDKData:
    result = LDKData()

    full_ldk = "\n".join(text for _, text in ldk_pages)
    result.raw_text = full_ldk[:3000]
    result.halaman_ldk = ldk_pages[0][0] if ldk_pages else 0

    # Normalisasi whitespace (pertahankan untuk regex greedy)
    clean = re.sub(r'\n+', ' ', full_ldk)
    clean = re.sub(r'\s+', ' ', clean)

    # ═══════════════════════════════════════════════════════════════
    # ROW 1 (DOKPIL poin 1): Izin Usaha di bidang Jasa Konstruksi
    # Cari dari "perizinan berusaha di bidang Jasa Konstruksi" s/d sebelum poin 2
    # ═══════════════════════════════════════════════════════════════
    izin_match = re.search(
        r'(?:Peserta\s+yang\s+berbadan\s+usaha\s+harus\s+memiliki\s+)?(perizinan\s+berusaha\s+di\s+bidang\s+Jasa\s+Konstruksi.*?)'
        r'(?=\s*2\.\s*Memiliki\s+Sertifikat|\s*Memiliki\s+Sertifikat\s+Badan\s+Usaha\s+\(SBU\))',
        clean, re.IGNORECASE
    )

    if izin_match:
        klasifikasi_izin = _clean_trailing(izin_match.group(1))
        result.izin_usaha_rows.append(IzinUsahaRow(
            jenis_izin="Izin Usaha di bidang Jasa Konstruksi",
            klasifikasi=klasifikasi_izin,
        ))

    # ═══════════════════════════════════════════════════════════════
    # ROW 2 (DOKPIL poin 2): Sertifikat Badan Usaha SBU
    # Cari dari "Memiliki Sertifikat Badan Usaha (SBU)" s/d sebelum poin 3
    # ═══════════════════════════════════════════════════════════════
    sbu_match = re.search(
        r'(Memiliki\s+Sertifikat\s+Badan\s+Usaha\s+\(SBU\)\s+dengan\s+Kualifikasi\s+\w+(?:\s+\w+)?,\s+serta\s+disyaratkan:.*?)'
        r'(?=\s*3\.\s*Memiliki\s+pengalaman|\s*Memiliki\s+pengalaman\s+paling\s+kurang)',
        clean, re.IGNORECASE
    )

    if sbu_match:
        teks_sbu = _clean_trailing(sbu_match.group(1))

        # Extract kualifikasi dan kode SBU untuk metadata
        kual_match = re.search(r'Kualifikasi\s+(Usaha\s+\w+)', teks_sbu, re.IGNORECASE)
        if kual_match:
            result.sbu_kualifikasi = kual_match.group(1).replace("Usaha ", "").strip()
        kode_match = re.findall(r'\b([A-Z]{2}\d{3})\b', teks_sbu)
        if kode_match:
            result.sbu_kode = ", ".join(kode_match[:3])
        result.sbu_deskripsi = teks_sbu[:300]

        result.izin_usaha_rows.append(IzinUsahaRow(
            jenis_izin="Sertifikat Badan Usaha SBU",
            klasifikasi=teks_sbu,
        ))

    # ═══════════════════════════════════════════════════════════════
    # Kinerja Penyedia (DOKPIL poin 4)
    # Cari dari "Memiliki kinerja penyedia" s/d sebelum poin 5
    # ═══════════════════════════════════════════════════════════════
    kinerja_match = re.search(
        r'(Memiliki\s+kinerja\s+penyedia\s+dengan\s+nilai\s+baik.*?)'
        r'(?=\s*5\.\s*Memperhitungkan|\s*Memperhitungkan\s+Sisa\s+Kemampuan)',
        clean, re.IGNORECASE
    )

    if kinerja_match:
        result.kinerja_penyedia = _clean_trailing(kinerja_match.group(1))
        result.kinerja_required = True

    # ═══════════════════════════════════════════════════════════════
    # Persyaratan lain
    # ═══════════════════════════════════════════════════════════════
    if re.search(r'pengalaman\s+paling\s+kurang\s+1', clean, re.IGNORECASE):
        result.pengalaman_min = 1
    if re.search(r'Kemampuan\s+Paket.*?5', clean, re.IGNORECASE):
        result.skp_kp = 5

    result.extracted = True
    return result


def extract_ldk_from_pdf(pdf_path: str) -> LDKData:
    result = LDKData()
    try:
        pages = extract_pages_from_pdf(pdf_path)
        ldk_pages = find_ldk_pages(pages)
        if not ldk_pages:
            result.errors.append("BAB V (Lembar Data Kualifikasi) tidak ditemukan")
            result.extracted = False
            return result
        result = parse_ldk_content(ldk_pages)
    except Exception as e:
        result.errors.append(str(e))
        result.extracted = False
    return result
