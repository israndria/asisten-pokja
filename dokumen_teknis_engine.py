"""
Parse Dokumen Teknis peserta tender dari PDF.

File target (ada di folder Dokumen Evaluasi/{urutan}. {nama}/):
  04E*.pdf / *peralatan*.pdf → daftar peralatan utama
  04D*.pdf / *personel*.pdf  → daftar personel manajerial

Output: update kolom personel_1/2 dan alat_1/2/3 di peserta_identitas Supabase.
"""

import os
import re
from config import sb as _sb


def _find_pdf(folder: str, *keywords: str) -> str | None:
    """Cari file PDF di folder yang namanya mengandung salah satu keyword (case-insensitive)."""
    try:
        files = os.listdir(folder)
    except Exception:
        return None
    for kw in keywords:
        kw_l = kw.lower()
        for f in files:
            if f.lower().endswith(".pdf") and kw_l in f.lower():
                return os.path.join(folder, f)
    return None


def parse_peralatan(pdf_path: str) -> list[str]:
    """
    Parse daftar peralatan dari PDF 04E.
    Return list string, misal ["Motor Grader (1 Unit)", "Dump Truck (2 Unit)"]
    """
    import pdfplumber

    alat_list = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for tbl in tables:
                    for row in tbl:
                        if not row or len(row) < 2:
                            continue
                        # Kolom 0 = jumlah/no, kolom 1 = jenis alat
                        jumlah = (row[0] or "").strip()
                        nama   = (row[1] or "").strip()
                        if not nama:
                            continue
                        # Skip header
                        nama_up = nama.upper()
                        if any(h in nama_up for h in ["JENIS", "PERALATAN", "ALAT", "NO", "KAPASITAS"]):
                            continue
                        # Skip baris kosong atau nomor urut saja
                        if re.match(r"^\d+$", nama):
                            continue
                        # Gabungkan multiline cell (pisah \n)
                        for sub_nama in nama.split("\n"):
                            sub_nama = sub_nama.strip()
                            if not sub_nama or re.match(r"^\d+$", sub_nama):
                                continue
                            if any(h in sub_nama.upper() for h in ["JENIS", "PERALATAN", "ALAT", "NO"]):
                                continue
                            # Cari jumlah yang bersesuaian (mungkin juga multiline)
                            sub_jml = jumlah.split("\n")[len(alat_list) % max(1, len(jumlah.split("\n")))].strip() if "\n" in jumlah else jumlah
                            if sub_jml and not re.match(r"^[Nn][Oo]\.?$", sub_jml):
                                alat_list.append(f"{sub_nama} ({sub_jml})")
                            else:
                                alat_list.append(sub_nama)
                        if len(alat_list) >= 5:
                            break
                    if len(alat_list) >= 5:
                        break
                if alat_list:
                    break
    except Exception:
        pass
    return alat_list[:5]


def parse_personel(pdf_path: str) -> list[str]:
    """
    Parse daftar personel manajerial dari PDF 04D.
    Return list nama, misal ["NOPIE ARIE YANDI", "RAHMAT KURNIAWAN S"]
    """
    import pdfplumber

    nama_list = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for tbl in tables:
                    for row in tbl:
                        if not row or len(row) < 2:
                            continue
                        nama_cell = (row[1] or "").strip()
                        if not nama_cell:
                            continue
                        nama_up = nama_cell.upper()
                        if any(h in nama_up for h in ["NAMA", "NO", "PERSONEL", "MANAJERIAL"]):
                            continue
                        for sub in nama_cell.split("\n"):
                            sub = sub.strip()
                            if not sub:
                                continue
                            if any(h in sub.upper() for h in ["NAMA", "NO"]):
                                continue
                            if re.match(r"^\d+$", sub):
                                continue
                            nama_list.append(sub)
                            if len(nama_list) >= 4:
                                break
                        if len(nama_list) >= 4:
                            break
                    if nama_list:
                        break
                if nama_list:
                    break
    except Exception:
        pass
    return nama_list[:4]


def parse_dan_upsert(
    kode_tender: str,
    peserta_id: str,
    folder_peserta: str,
    progress_cb=None,
) -> dict:
    """
    Parse dokumen teknis PDF dari folder_peserta, update peserta_identitas.

    Return: {"ok": bool, "personel": [...], "alat": [...], "pesan": str}
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    # Cari PDF peralatan
    pdf_alat = _find_pdf(folder_peserta, "04e", "peralatan utama", "peralatan")
    # Cari PDF personel
    pdf_personel = _find_pdf(folder_peserta, "04d", "personel", "personil")

    alat_list = []
    personel_list = []

    if pdf_alat:
        log(f"  Parse peralatan: {os.path.basename(pdf_alat)}")
        alat_list = parse_peralatan(pdf_alat)
        log(f"  → {len(alat_list)} alat: {alat_list}")
    else:
        log("  ⚠️ PDF peralatan (04E) tidak ditemukan")

    if pdf_personel:
        log(f"  Parse personel: {os.path.basename(pdf_personel)}")
        personel_list = parse_personel(pdf_personel)
        log(f"  → {len(personel_list)} personel: {personel_list}")
    else:
        log("  ⚠️ PDF personel (04D) tidak ditemukan")

    if not alat_list and not personel_list:
        return {"ok": False, "personel": [], "alat": [], "pesan": "PDF tidak ditemukan atau kosong"}

    # Format label: "1. Alat A, 2. Alat B"
    def _label_list(items):
        return ", ".join(f"{i+1}. {x}" for i, x in enumerate(items))

    update = {
        "personel_1": personel_list[0] if len(personel_list) > 0 else "",
        "personel_2": personel_list[1] if len(personel_list) > 1 else "",
        "alat_1":     alat_list[0] if len(alat_list) > 0 else "",
        "alat_2":     alat_list[1] if len(alat_list) > 1 else "",
        "alat_3":     alat_list[2] if len(alat_list) > 2 else "",
    }

    try:
        _sb().table("peserta_identitas").update(update)\
            .eq("kode_tender", kode_tender)\
            .eq("peserta_id", peserta_id)\
            .execute()
        log("  ✅ peserta_identitas diperbarui.")
    except Exception as e:
        return {"ok": False, "personel": personel_list, "alat": alat_list, "pesan": str(e)}

    return {
        "ok": True,
        "personel": personel_list,
        "alat": alat_list,
        "pesan": f"{len(personel_list)} personel, {len(alat_list)} alat",
    }
