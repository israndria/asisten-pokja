"""
undangan_pdf_engine.py — Generate PDF Undangan Reviu DPP via Word COM.

Flow: copy template .docx → replace placeholder teks → export PDF via Word COM.
Template: Paket Experiment/4. Undangan Full PK - Template.docx
Data dari Supabase draft_paket + input user (tanggal, hari_tgl_rapat, pukul, tempat).
"""

import os
import re
import shutil
from datetime import date
from typing import Optional

import docx

_BULAN = ["Januari","Februari","Maret","April","Mei","Juni",
          "Juli","Agustus","September","Oktober","November","Desember"]
_HARI  = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]

_TEMPLATE_REL    = r"Paket Experiment\4. Undangan Full PK - Template.docx"
_TEMPLATE_REL_PL = r"Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi\Development\4. Undangan Full PLJK - Template.docx"


def _fmt_tanggal(d: date) -> str:
    return f"{d.day} {_BULAN[d.month-1]} {d.year}"


def _title_case_dinas(nama: str) -> str:
    stop = {"dan", "di", "ke", "dari", "yang", "untuk", "dengan", "atau",
            "pada", "dalam", "oleh", "atas", "bagi", "tentang", "no", "nomor"}
    words = nama.lower().split()
    return " ".join(w.capitalize() if (i == 0 or w not in stop) else w
                    for i, w in enumerate(words))


def _build_nomor_surat(kode_pokja: str, kode_unik: str, tahun: int) -> str:
    no = str(int(kode_pokja)).zfill(2) if kode_pokja.isdigit() else "01"
    return f"000.3.3/{no}/Pokja{kode_pokja.zfill(3)}/T/Reviu-{kode_unik}/{tahun}"


def _replace_all(doc: docx.Document, placeholder: str, value: str):
    """
    Replace placeholder di seluruh dokumen via XML level.

    Merged cells di python-docx bisa menghasilkan objek Cell berbeda
    untuk elemen XML yang sama, sehingga filter via id(cell._tc) tidak reliable.
    Solusi: replace langsung di XML string body dokumen.
    """
    from lxml import etree
    import re as _re

    body = doc.element.body
    xml_str = etree.tostring(body, encoding="unicode")

    if placeholder not in xml_str:
        return

    # Escape value agar aman di XML (ganti & < > " ')
    escaped = (value
               .replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;"))

    new_xml = xml_str.replace(placeholder, escaped)
    new_body = etree.fromstring(new_xml)

    # Ganti isi body dengan hasil baru
    doc.element.body.clear()
    for child in new_body:
        doc.element.body.append(child)


def _export_pdf_via_word(docx_path: str, pdf_path: str) -> None:
    """Export .docx ke PDF via Word COM (ExportAsFixedFormat)."""
    import win32com.client
    import pythoncom
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(
            docx_path,
            ReadOnly=False,
            AddToRecentFiles=False,
        )
        doc.ExportAsFixedFormat(
            OutputFileName=pdf_path,
            ExportFormat=17,  # wdExportFormatPDF
            OpenAfterExport=False,
            OptimizeFor=0,
            Range=0,
            IncludeDocProps=True,
            KeepIRM=True,
            CreateBookmarks=0,
            DocStructureTags=True,
            BitmapMissingFonts=True,
            UseISO19005_1=False,
        )
        doc.Close(SaveChanges=False)
    finally:
        if word:
            try:
                word.Quit(SaveChanges=False)
            except Exception:
                pass
        pythoncom.CoUninitialize()


def generate_undangan_pdf(
    kode_tender: str,
    tanggal_kirim: date,
    hari_tgl_rapat: str,
    pukul_rapat: str,
    tempat_rapat: str,
    output_path: Optional[str] = None,
    nomor_surat: Optional[str] = None,
) -> dict:
    """
    Generate PDF Undangan Reviu DPP.

    Args:
        kode_tender:    PK Supabase draft_paket
        tanggal_kirim:  Tanggal surat
        hari_tgl_rapat: Misal "Senin, 11 Mei 2026"
        pukul_rapat:    Misal "10.00 Wita s/d Selesai"
        tempat_rapat:   Lokasi rapat
        output_path:    Path PDF output; None → simpan ke folder paket
        nomor_surat:    Override nomor surat; None → generate otomatis

    Returns:
        {"sukses": bool, "pdf_path": str, "pdf_bytes": bytes, "pesan": str}
    """
    # ── Ambil data Supabase ──
    try:
        from config import sb, POKJA_ROOT
        client = sb()
        r = client.table("draft_paket").select("*").eq("kode_tender", kode_tender).single().execute()
        data: dict = r.data or {}
    except Exception as e:
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"", "pesan": f"Gagal ambil data Supabase: {e}"}

    if not data:
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"", "pesan": f"Paket {kode_tender} tidak ditemukan"}

    # ── Tentukan output path ──
    if not output_path:
        folder_rel = data.get("folder_dibuat", "")
        if folder_rel:
            folder_abs = folder_rel if os.path.isabs(folder_rel) else os.path.join(POKJA_ROOT, folder_rel)
        else:
            folder_abs = POKJA_ROOT
        safe_kode = re.sub(r'[\\/]', '-', kode_tender)
        output_path = os.path.join(folder_abs, f"Undangan_{safe_kode}.pdf")

    # ── Template path ──
    template_path = os.path.join(POKJA_ROOT, _TEMPLATE_REL)
    if not os.path.isfile(template_path):
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"",
                "pesan": f"Template tidak ditemukan: {template_path}"}

    # ── Susun nilai placeholder ──
    nama_dinas   = _title_case_dinas(data.get("nama_dinas", ""))
    nama_tender  = data.get("nama_tender", "")
    kode_pokja   = data.get("kode_pokja", "001")
    kode_unik    = data.get("kode_unik") or "DPP"
    nomor_sd     = data.get("nomor_surat_dinas", "")
    nomor_pp_val = data.get("nomor_pp", "")

    if not nomor_surat:
        nomor_surat = _build_nomor_surat(kode_pokja, kode_unik, tanggal_kirim.year)

    tempat_default = (
        "Ruang Aula Rapat Lantai 2 Kantor UKPBJ Kabupaten Tapin, "
        "Jl. Datu Suban RT. 01, Kelurahan Rangda Malingkung, Kecamatan Tapin Utara, "
        "Rantau, Kabupaten Tapin. Kode Pos : 71111"
    )

    replacements = {
        "«TANGGAL_KIRIM»":    _fmt_tanggal(tanggal_kirim),
        "«NOMOR_SURAT»":      nomor_surat,
        "«PENERIMA_1»":       f"KPA/PPK {nama_dinas} Kabupaten Tapin",
        "«PENERIMA_2»":       f"Tim Teknis PPK {nama_dinas} Kabupaten Tapin",
        "«PENERIMA_3»":       f"Konsultan Perencana/Perancang Paket Pekerjaan {nama_tender}",
        "«NOMOR_SURAT_DINAS»": nomor_sd,
        "«NOMOR_PP»":         nomor_pp_val,
        "«HARI_TGL_RAPAT»":   hari_tgl_rapat,
        "«PUKUL»":            pukul_rapat,
        "«ACARA»":            f"Reviu Dokumen Persiapan Pengadaan {nama_tender}",
        "«TEMPAT»":           tempat_rapat or tempat_default,
        "«NAMA_POKJA»":       kode_pokja.zfill(3),
    }

    # ── Copy template → tmp docx → replace → export PDF ──
    # Simpan tmp di folder output agar Word COM tidak anggap read-only
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    tmp_docx = os.path.join(output_dir, f"_tmp_undangan_{os.getpid()}.docx")
    try:
        shutil.copy2(template_path, tmp_docx)

        doc = docx.Document(tmp_docx)
        for ph, val in replacements.items():
            _replace_all(doc, ph, str(val))
        doc.save(tmp_docx)

        _export_pdf_via_word(
            os.path.abspath(tmp_docx),
            os.path.abspath(output_path),
        )
    except Exception as e:
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"",
                "pesan": f"Gagal generate PDF: {e}"}
    finally:
        if tmp_docx and os.path.exists(tmp_docx):
            try:
                os.remove(tmp_docx)
            except Exception:
                pass

    if not os.path.exists(output_path):
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"",
                "pesan": "PDF tidak terbuat (Word COM tidak menghasilkan file)"}

    try:
        with open(output_path, "rb") as f:
            pdf_bytes = f.read()
    except Exception as e:
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"",
                "pesan": f"PDF terbuat tapi gagal dibaca: {e}"}

    return {
        "sukses": True,
        "pdf_path": output_path,
        "pdf_bytes": pdf_bytes,
        "pesan": f"PDF berhasil: {os.path.basename(output_path)} ({len(pdf_bytes)//1024} KB)",
    }


def generate_undangan_pdf_pl(
    kode_paket: str,
    tanggal_kirim: date,
    hari_tgl_rapat: str,
    pukul_rapat: str,
    tempat_rapat: str,
    output_path: Optional[str] = None,
    nomor_surat: Optional[str] = None,
) -> dict:
    """
    Generate PDF Undangan Reviu DPP mode Pengadaan Langsung.

    Args:
        kode_paket:     PK Supabase draft_paket_pl
        tanggal_kirim:  Tanggal surat
        hari_tgl_rapat: Misal "Senin, 19 Mei 2026"
        pukul_rapat:    Misal "09.00 s.d. 11.00 Wita"
        tempat_rapat:   Lokasi rapat
        output_path:    Path PDF output; None → temp folder
        nomor_surat:    Override nomor surat; None → generate otomatis

    Returns:
        {"sukses": bool, "pdf_path": str, "pdf_bytes": bytes, "pesan": str}
    """
    try:
        from config import sb, POKJA_ROOT
        client = sb()
        r = client.table("draft_paket_pl").select("*").eq("kode_paket", kode_paket).single().execute()
        data: dict = r.data or {}
    except Exception as e:
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"", "pesan": f"Gagal ambil data Supabase: {e}"}

    if not data:
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"", "pesan": f"Paket {kode_paket} tidak ditemukan"}

    if not output_path:
        import tempfile
        output_path = os.path.join(tempfile.gettempdir(), f"Undangan_PL_{kode_paket}.pdf")

    template_path = os.path.join(POKJA_ROOT, _TEMPLATE_REL_PL)
    if not os.path.isfile(template_path):
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"",
                "pesan": f"Template tidak ditemukan: {template_path}"}

    nama_satker  = _title_case_dinas(data.get("satker", ""))
    nama_paket   = data.get("nama_paket", "")
    nama_ppk     = data.get("nama_ppk", "")
    nomor_sd     = data.get("nomor_surat_dinas", "")
    nomor_pp_val = data.get("id_nontender", kode_paket)

    if not nomor_surat:
        nomor_surat = f"000.3.3/PP/Reviu-DPP/{tanggal_kirim.year}"

    replacements = {
        "«TANGGAL_KIRIM»":     _fmt_tanggal(tanggal_kirim),
        "«NOMOR_SURAT»":        nomor_surat,
        "«PENERIMA_1»":         f"PPK {nama_satker} Kabupaten Tapin",
        "«PENERIMA_2»":         nama_ppk,
        "«PENERIMA_3»":         f"Terkait Paket {nama_paket}",
        "«NOMOR_SURAT_DINAS»":  nomor_sd,
        "«NOMOR_PP»":           nomor_pp_val,
        "«HARI_TGL_RAPAT»":     hari_tgl_rapat,
        "«PUKUL»":              pukul_rapat,
        "«ACARA»":              f"Reviu Dokumen Persiapan Pengadaan {nama_paket}",
        "«NAMA_POKJA»":         "PP",
    }

    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    tmp_docx = os.path.join(output_dir, f"_tmp_undangan_pl_{os.getpid()}.docx")
    try:
        shutil.copy2(template_path, tmp_docx)
        doc = docx.Document(tmp_docx)
        for ph, val in replacements.items():
            _replace_all(doc, ph, str(val))
        doc.save(tmp_docx)
        _export_pdf_via_word(os.path.abspath(tmp_docx), os.path.abspath(output_path))
    except Exception as e:
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"",
                "pesan": f"Gagal generate PDF: {e}"}
    finally:
        if tmp_docx and os.path.exists(tmp_docx):
            try:
                os.remove(tmp_docx)
            except Exception:
                pass

    if not os.path.exists(output_path):
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"",
                "pesan": "PDF tidak terbuat (Word COM tidak menghasilkan file)"}

    try:
        with open(output_path, "rb") as f:
            pdf_bytes = f.read()
    except Exception as e:
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"",
                "pesan": f"PDF terbuat tapi gagal dibaca: {e}"}

    return {
        "sukses": True,
        "pdf_path": output_path,
        "pdf_bytes": pdf_bytes,
        "pesan": f"PDF berhasil: {os.path.basename(output_path)} ({len(pdf_bytes)//1024} KB)",
    }
