"""
Parse Dokumen Teknis peserta tender dari PDF.

File target (ada di folder 1. Dokumen Kualifikasi/{urutan}. {nama}/):
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


def _parse_peralatan_lines(text: str) -> list[str]:
    """Fallback untuk PDF native/OCR yang tabelnya tidak terdeteksi."""
    hasil = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not re.match(r"^[|Il\[({]*\s*\d+\s+", line):
            continue
        line = re.sub(r"^[|Il\[({]*\s*\d+\s+", "", line)
        # OCR sering membaca Unit sebagai Unt/Une dan Set sebagai SSet.
        line = re.sub(r"\b(\d+)\s*(?:Unt|Une|Unlt)\b", r"\1 Unit", line, flags=re.I)
        line = re.sub(r"\b(\d+)\s*SSet\b", r"\1 Set", line, flags=re.I)
        match = re.match(
            r"(.+?)\s+(\d+(?:[.,]\d+)?\s*(?:unit|set|buah|pcs|buah/unit))\b",
            line,
            flags=re.I,
        )
        if not match:
            continue
        nama = re.sub(r"\s+", " ", match.group(1)).strip(" |:-")
        jumlah = re.sub(r"\s+", " ", match.group(2)).strip()
        if nama and not any(k in nama.upper() for k in ("PERALATAN UTAMA", "NAMA PERALATAN")):
            hasil.append(f"{nama} ({jumlah})")
    return hasil[:6]


def parse_peralatan(pdf_path: str) -> list[str]:
    """
    Parse daftar peralatan dari PDF 04E.
    Return list string, misal ["Motor Grader (1 Unit)", "Dump Truck (2 Unit)"]

    Header-aware: deteksi index kolom JENIS dan JUMLAH dari baris header tabel.
    Mendukung variasi format: SAMATA (JUMLAH idx2), BAYU/EXTRA (JUMLAH idx4), dll.
    """
    import pdfplumber

    def _norm(cell) -> str:
        """Normalisasi cell: strip, ganti newline jadi spasi, buang karakter aneh."""
        if cell is None:
            return ""
        return re.sub(r"\s+", " ", str(cell)).strip()

    def _cari_indeks_header(header_row):
        """
        Dari baris header, cari index kolom JENIS dan JUMLAH.
        Return (idx_jenis, idx_jumlah) — idx_jumlah bisa None kalau tidak ditemukan.
        """
        idx_jenis = None
        idx_jumlah = None
        for i, cell in enumerate(header_row):
            teks = (cell or "").upper().replace("\n", " ").strip()
            # Deteksi kolom JENIS: mengandung kata kunci nama peralatan
            if idx_jenis is None and any(k in teks for k in ["JENIS", "NAMA PERALATAN", "PERALATAN", "NAMA ALAT"]):
                # Hindari mencocokkan kolom yang hanya berisi "PERALATAN" sebagai bagian dari frasa panjang
                # tapi pastikan bukan kolom NO (biasanya indeks 0 dan nilai sangat pendek)
                idx_jenis = i
            # Deteksi kolom JUMLAH: persis mengandung "JUMLAH"
            if idx_jumlah is None and "JUMLAH" in teks:
                idx_jumlah = i
        # Default jenis ke index 1 kalau tidak ditemukan
        if idx_jenis is None:
            idx_jenis = 1
        return idx_jenis, idx_jumlah

    def _is_header_row(row, idx_jenis):
        """Cek apakah baris ini adalah baris header (bukan data)."""
        teks = (row[idx_jenis] or "").upper().replace("\n", " ").strip()
        return any(k in teks for k in ["JENIS", "NAMA PERALATAN", "PERALATAN", "NAMA ALAT"])

    alat_list = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Sebagian PDF native hanya punya text layer tanpa garis tabel.
                if not alat_list:
                    alat_list = _parse_peralatan_lines(page.extract_text() or "")
                if alat_list:
                    break
                tables = page.extract_tables()
                for tbl in tables:
                    if not tbl or len(tbl) < 2:
                        continue
                    # Cari baris header: baris pertama dengan >= 3 kolom yang mengandung keyword
                    header_row = tbl[0]
                    if not header_row or len(header_row) < 3:
                        continue
                    header_teks = " ".join((c or "").upper().replace("\n", " ") for c in header_row)
                    # Tabel valid: header mengandung kata terkait peralatan
                    if not any(k in header_teks for k in ["JENIS", "PERALATAN", "NAMA ALAT"]):
                        continue

                    idx_jenis, idx_jumlah = _cari_indeks_header(header_row)

                    # Iterasi baris data (lewati baris header)
                    for row in tbl[1:]:
                        if not row or len(row) <= idx_jenis:
                            continue
                        jenis_raw = row[idx_jenis] or ""
                        # Peralatan multiline di sel JENIS → tiap baris = satu alat terpisah
                        # (berbeda dengan personil yang multiline = 1 orang)
                        jenis_lines = [s.strip() for s in str(jenis_raw).split("\n") if s.strip()]

                        # Ambil jumlah dari kolom JUMLAH jika tersedia
                        jumlah_lines = []
                        if idx_jumlah is not None and len(row) > idx_jumlah:
                            jml_raw = row[idx_jumlah] or ""
                            jumlah_lines = [s.strip() for s in str(jml_raw).split("\n") if s.strip()]

                        for li, jenis in enumerate(jenis_lines):
                            if not jenis:
                                continue
                            # Skip baris header yang mungkin muncul ulang di tengah tabel
                            if _is_header_row([None, jenis], 1):
                                continue
                            # Skip kalau isinya cuma angka (nomor urut)
                            if re.match(r"^\d+\.?$", jenis):
                                continue
                            # Ambil jumlah yang bersesuaian (index sama dengan jenis_lines)
                            jumlah = jumlah_lines[li] if li < len(jumlah_lines) else ""
                            # Jangan ambil jumlah dari kolom NO (nilai seperti "1." "2.")
                            if jumlah and re.match(r"^\d+\.?$", jumlah):
                                jumlah = ""
                            if jumlah:
                                alat_list.append(f"{jenis} ({jumlah})")
                            else:
                                alat_list.append(jenis)
                            if len(alat_list) >= 6:
                                break
                        if len(alat_list) >= 6:
                            break
                    if alat_list:
                        break
    except Exception:
        pass

    # PDF scan/image-only: render halaman pertama, hilangkan garis tabel,
    # lalu OCR hanya sebagai fallback terakhir.
    if not alat_list:
        try:
            import fitz
            import cv2
            import numpy as np
            import pytesseract

            page = fitz.open(pdf_path)[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            image = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)[1]
            hline = cv2.morphologyEx(
                255 - binary, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1)),
            )
            vline = cv2.morphologyEx(
                255 - binary, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (1, 50)),
            )
            clean = cv2.bitwise_or(binary, cv2.bitwise_or(hline, vline))
            raw_ocr = pytesseract.image_to_string(clean, config="--psm 6")
            alat_list = _parse_peralatan_lines(raw_ocr)
        except Exception:
            pass
    return alat_list[:6]


def parse_personel(pdf_path: str) -> list[str]:
    """
    Parse daftar personel manajerial dari PDF 04D.
    Return list string, misal ["AULIA RAHMAN, A.Md (Pelaksana Lapangan)", "JUSUF BOBBY MANOREK (Petugas K3)"]

    Header-aware: deteksi index kolom NAMA dan JABATAN dari baris header tabel.
    Nama multiline (newline dalam satu cell) digabung jadi 1 string — 1 orang, bukan 2 entri.
    """
    import pdfplumber

    def _norm_spasi(teks) -> str:
        """Gabungkan newline menjadi spasi, bersihkan spasi ganda."""
        if teks is None:
            return ""
        return re.sub(r"\s+", " ", str(teks).replace("\n", " ")).strip()

    def _cari_indeks_personil(header_row):
        """
        Dari baris header, cari index kolom NAMA dan JABATAN.
        Return (idx_nama, idx_jabatan) — idx_jabatan bisa None.
        """
        idx_nama = None
        idx_jabatan = None
        for i, cell in enumerate(header_row):
            teks = (cell or "").upper().replace("\n", " ").strip()
            # NAMA: mengandung "NAMA" tapi BUKAN "NAMA PERALATAN" / "NAMA ALAT"
            if idx_nama is None and "NAMA" in teks:
                if not any(k in teks for k in ["PERALATAN", "ALAT"]):
                    idx_nama = i
            # JABATAN: mengandung "JABATAN"
            if idx_jabatan is None and "JABATAN" in teks:
                idx_jabatan = i
        # Default NAMA ke index 1
        if idx_nama is None:
            idx_nama = 1
        return idx_nama, idx_jabatan

    personel_list = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                if personel_list:
                    break
                tables = page.extract_tables()
                for tbl in tables:
                    if not tbl or len(tbl) < 2:
                        continue
                    header_row = tbl[0]
                    if not header_row or len(header_row) < 2:
                        continue
                    header_teks = " ".join((c or "").upper().replace("\n", " ") for c in header_row)
                    # Tabel valid: header mengandung "NAMA" (untuk personil)
                    if "NAMA" not in header_teks:
                        continue
                    # Pastikan bukan tabel peralatan yang kebetulan ada kolom bernama "NAMA"
                    if any(k in header_teks for k in ["PERALATAN", "NAMA ALAT"]):
                        continue

                    idx_nama, idx_jabatan = _cari_indeks_personil(header_row)

                    # Iterasi baris data (lewati baris header)
                    for row in tbl[1:]:
                        if not row or len(row) <= idx_nama:
                            continue
                        # Nama: GABUNG multiline jadi 1 string (1 baris = 1 orang)
                        nama = _norm_spasi(row[idx_nama])
                        if not nama:
                            continue
                        # Skip baris header yang muncul ulang
                        if any(k in nama.upper() for k in ["NAMA", "PERSONEL", "PERSONIL"]):
                            continue
                        # Skip kalau nama cuma angka (nomor urut)
                        if re.match(r"^\d+\.?$", nama):
                            continue
                        # Ambil jabatan jika ada kolom JABATAN
                        jabatan = ""
                        if idx_jabatan is not None and len(row) > idx_jabatan:
                            jabatan = _norm_spasi(row[idx_jabatan])
                            # Buang teks yang terlalu panjang / jelas bukan jabatan
                            if len(jabatan) > 80:
                                jabatan = jabatan[:80]
                        if jabatan:
                            personel_list.append(f"{nama} ({jabatan})")
                        else:
                            personel_list.append(nama)
                        if len(personel_list) >= 4:
                            break
                    if personel_list:
                        break
    except Exception:
        pass
    return personel_list[:4]


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
    pdf_personel = _find_pdf(folder_peserta, "04d", "personel", "personil", "tenaga teknis")

    alat_list = []
    personel_list = []

    if pdf_alat:
        log(f"  Parse peralatan: {os.path.basename(pdf_alat)}")
        alat_list = parse_peralatan(pdf_alat)
        if not alat_list:
            log("PDF peralatan ditemukan tetapi belum terbaca otomatis; data tidak diubah")
        log(f"  → {len(alat_list)} alat: {alat_list}")
    else:
        log("  ⚠️ PDF peralatan (04E) tidak ditemukan")

    if pdf_personel:
        log(f"  Parse personel: {os.path.basename(pdf_personel)}")
        personel_list = parse_personel(pdf_personel)
        if not personel_list:
            log("PDF personel ditemukan tetapi belum terbaca otomatis; data tidak diubah")
        log(f"  → {len(personel_list)} personel: {personel_list}")
    else:
        log("  ⚠️ PDF personel (04D) tidak ditemukan")

    if not alat_list and not personel_list:
        pesan = (
            "PDF ditemukan tetapi belum terbaca otomatis"
            if pdf_alat or pdf_personel
            else "PDF teknis tidak ditemukan"
        )
        return {"ok": False, "personel": [], "alat": [], "pesan": pesan}

    # Format label: "1. Alat A, 2. Alat B"
    def _label_list(items):
        return ", ".join(f"{i+1}. {x}" for i, x in enumerate(items))

    update = {
        "personel_1": personel_list[0] if len(personel_list) > 0 else "",
        "personel_2": personel_list[1] if len(personel_list) > 1 else "",
        "alat_1":     alat_list[0] if len(alat_list) > 0 else "",
        "alat_2":     alat_list[1] if len(alat_list) > 1 else "",
        "alat_3":     alat_list[2] if len(alat_list) > 2 else "",
        "alat_4":     alat_list[3] if len(alat_list) > 3 else "",
        "alat_5":     alat_list[4] if len(alat_list) > 4 else "",
        "alat_6":     alat_list[5] if len(alat_list) > 5 else "",
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
