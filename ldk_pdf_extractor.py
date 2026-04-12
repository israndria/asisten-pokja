"""
LDK PDF Extractor v3 — Extract persyaratan kualifikasi dari DOKPIL PDF.

Alur:
1. Upload PDF DOKPIL
2. Extract semua teks (per halaman)
3. Cari BAB V (Lembar Data Kualifikasi)
4. Parse persyaratan: Izin Usaha, SBU, KBLI, Kualifikasi
5. Return data terstruktur untuk auto-fill
"""

import re
from pypdf import PdfReader
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IzinUsahaRequirement:
    jenis_izin: str = "Izin Usaha"
    deskripsi: str = ""
    kbli_codes: list = field(default_factory=list)
    tahun_kbli: str = "2020"


@dataclass
class SBURequirement:
    kualifikasi: str = "Kecil"
    subklasifikasi: str = ""
    kode_sbu: str = ""
    tahun_kbli: str = "2020"
    deskripsi: str = ""
    max_sbu: int = 1


@dataclass
class LDKData:
    izin_usaha: list = field(default_factory=list)
    sbu: list = field(default_factory=list)
    pengalaman_min: int = 0
    skp_kp: int = 5
    syarat_npwp: bool = True
    syarat_akta: bool = True
    syarat_daftar_hitam: bool = True
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
    """
    Cari halaman BAB V (Lembar Data Kualifikasi) yang sebenarnya.
    Prioritas: halaman yang punya "BAB V" + "LEMBAR DATA KUALIFIKASI" sebagai HEADING.
    """
    ldk_pages = []
    in_ldk = False
    
    for page_num, text in pages:
        text_lower = text.lower()
        
        # Deteksi heading BAB V: "BAB V." muncul di awal halaman + "LEMBAR DATA KUALIFIKASI"
        has_bab_v_heading = (
            'bab v.' in text_lower[:300] and 
            'lembar data kualifikasi' in text_lower[:400]
        )
        
        if has_bab_v_heading:
            in_ldk = True
        
        if in_ldk:
            ldk_pages.append((page_num, text))
        
        # Berakhir: BAB VI
        if in_ldk and 'bab vi' in text_lower:
            break
    
    return ldk_pages


def parse_ldk_content(ldk_pages: list[tuple[int, str]]) -> LDKData:
    result = LDKData()
    
    # Gabungkan semua teks LDK
    full_ldk = "\n".join(text for _, text in ldk_pages)
    result.raw_text = full_ldk[:3000]
    result.halaman_ldk = ldk_pages[0][0] if ldk_pages else 0
    
    # KEY FIX: Join semua baris jadi satu string panjang (hapus newlines)
    # Karena "Konstruksi\nBangunan Sipil Jalan" harus jadi "Konstruksi Bangunan Sipil Jalan"
    clean_ldk = re.sub(r'\n+', ' ', full_ldk)  # Newline → space
    clean_ldk = re.sub(r'\s+', ' ', clean_ldk)  # Multiple space → single
    
    # ── 1. Parse Izin Usaha ──
    if re.search(r'perizinan\s*berusaha\s*di\s*bidang\s*Jasa\s*Konstruksi', clean_ldk, re.IGNORECASE):
        result.izin_usaha.append(IzinUsahaRequirement(
            jenis_izin="Izin Usaha di bidang Jasa Konstruksi",
            deskripsi="Izin Usaha dari DOKPIL",
        ))
    
    # ── 2. Parse SBU ──
    # Pattern: Subklasifikasi BS001 (KBLI 2020) Konstruksi Bangunan Sipil Jalan  atau
    sbu_pattern = r'Subklasifikasi\s*([A-Z]{0,2}\d{3})\s*\(\s*KBLI\s*(\d{4})\s*\)\s*([A-Za-z\s\(\),/]+?)(?=\s*Subklasifikasi|\s*atau\s*[;.]|\s*\d\.\s*Memiliki|\s*\.?\s*(?:\d|Memiliki|Peserta|Pokja)|$)'
    sbu_matches = re.findall(sbu_pattern, clean_ldk, re.IGNORECASE)
    
    for kode, tahun, desk in sbu_matches:
        result.sbu.append(SBURequirement(
            kode_sbu=kode.strip(),
            tahun_kbli=tahun,
            subklasifikasi=desk.strip()[:150],
            kualifikasi="Kecil",
        ))
    
    # ── 3. Parse Kualifikasi ──
    if re.search(r'Kualifikasi\s*Usaha\s*Kecil', clean_ldk, re.IGNORECASE):
        for s in result.sbu:
            s.kualifikasi = "Kecil"
        result.skp_kp = 5
    elif re.search(r'Kualifikasi\s*Usaha\s*Menengah', clean_ldk, re.IGNORECASE):
        for s in result.sbu:
            s.kualifikasi = "Menengah"
    elif re.search(r'Kualifikasi\s*Usaha\s*Besar', clean_ldk, re.IGNORECASE):
        for s in result.sbu:
            s.kualifikasi = "Besar"
    
    # ── 4. Parse Persyaratan Lain ──
    if re.search(r'pengalaman\s*paling\s*kurang\s*1', clean_ldk, re.IGNORECASE):
        result.pengalaman_min = 1
    if re.search(r'Kemampuan\s*Paket.*?5', clean_ldk, re.IGNORECASE):
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


def generate_ijin_config(ldk_data: LDKData) -> dict:
    if not ldk_data.extracted:
        return {"nama": "Izin Usaha", "klasifikasi": "41001 - Konstruksi Umum"}
    
    klas_parts = []
    for sbu in ldk_data.sbu:
        if sbu.kode_sbu and sbu.subklasifikasi:
            klas_parts.append(f"{sbu.kode_sbu} (KBLI {sbu.tahun_kbli}) {sbu.subklasifikasi[:80]}")
        elif sbu.subklasifikasi:
            klas_parts.append(f"KBLI {sbu.tahun_kbli} - {sbu.subklasifikasi[:80]}")
    
    if not klas_parts:
        klas_parts.append("41001 - Konstruksi Umum")
    
    return {
        "nama": ldk_data.izin_usaha[0].jenis_izin if ldk_data.izin_usaha else "Izin Usaha di bidang Jasa Konstruksi",
        "klasifikasi": "; ".join(klas_parts),
    }
