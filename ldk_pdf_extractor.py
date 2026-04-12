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


def parse_ldk_content(ldk_pages: list[tuple[int, str]]) -> LDKData:
    result = LDKData()
    
    full_ldk = "\n".join(text for _, text in ldk_pages)
    result.raw_text = full_ldk[:3000]
    result.halaman_ldk = ldk_pages[0][0] if ldk_pages else 0
    
    # Join lines untuk handle text split
    clean = re.sub(r'\n+', ' ', full_ldk)
    clean = re.sub(r'\s+', ' ', clean)
    
    # ═══════════════════════════════════════════════════════════════
    # ROW 1: Sertifikat Badan Usaha SBU
    # ═══════════════════════════════════════════════════════════════
    sbu_match = re.search(
        r'Memiliki\s*Sertifikat\s*Badan\s*Usaha\s*\(SBU\)\s*dengan\s*Kualifikasi\s*(Usaha\s*\w+),\s*serta\s*disyaratkan:\s*(.*?)(?=Memiliki\s*pengalaman|Memiliki\s*kinerja|Memperhitungkan|$)',
        clean, re.IGNORECASE
    )
    
    if sbu_match:
        kual = sbu_match.group(1).strip()
        desk = sbu_match.group(2).strip()
        
        result.sbu_kualifikasi = kual.replace("Usaha ", "").strip()
        result.sbu_deskripsi = desk[:300]
        
        # Extract kode SBU
        kode_match = re.findall(r'([A-Z]{0,2}\d{3})', desk)
        if kode_match:
            result.sbu_kode = ", ".join(kode_match[:3])
        
        # Build Row 1: Sertifikat Badan Usaha SBU
        result.izin_usaha_rows.append(IzinUsahaRow(
            jenis_izin="Sertifikat Badan Usaha SBU",
            klasifikasi=f"Memiliki Sertifikat Badan Usaha SBU dengan Kualifikasi {kual} serta disyaratkan {desk[:250]}",
        ))
    
    # ═══════════════════════════════════════════════════════════════
    # ROW 2: Izin Usaha di bidang Jasa Konstruksi
    # ═══════════════════════════════════════════════════════════════
    izin_match = re.search(
        r'(perizinan\s*berusaha\s*di\s*bidang\s*Jasa\s*Konstruksi.*?)\s*(?:Memiliki\s*Sertifikat\s*Badan|Peserta\s*yang|b\)|\.?\s*(?:\d|Memiliki|Peserta|Pokja)|$)',
        clean, re.IGNORECASE
    )
    
    # Cari lebih spesifik
    if not izin_match:
        izin_match = re.search(
            r'peserta\s*yang\s*berbadan\s*usaha\s*harus\s*memiliki\s*(perizinan\s*berusaha\s*di\s*bidang\s*Jasa\s*Konstruksi[^\n]{0,500})',
            clean, re.IGNORECASE
        )
    
    if izin_match:
        result.izin_usaha_rows.append(IzinUsahaRow(
            jenis_izin="Izin Usaha di bidang Jasa Konstruksi",
            klasifikasi=izin_match.group(1).strip()[:300],
        ))
    
    # ═══════════════════════════════════════════════════════════════
    # Kinerja Penyedia
    # ═══════════════════════════════════════════════════════════════
    kinerja_match = re.search(
        r'(Memiliki\s*kinerja\s*penyedia\s*dengan\s*nilai\s*baik.*?)(?=Pengecualian|persyaratan\s*kinerja|\.?\s*(?:\d|Memiliki|Peserta|Pokja)|$)',
        clean, re.IGNORECASE
    )
    
    if kinerja_match:
        result.kinerja_penyedia = kinerja_match.group(1).strip()
        result.kinerja_required = True
    
    # ═══════════════════════════════════════════════════════════════
    # Persyaratan lain
    # ═══════════════════════════════════════════════════════════════
    if re.search(r'pengalaman\s*paling\s*kurang\s*1', clean, re.IGNORECASE):
        result.pengalaman_min = 1
    if re.search(r'Kemampuan\s*Paket.*?5', clean, re.IGNORECASE):
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
