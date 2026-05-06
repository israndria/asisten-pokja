"""
undangan_pdf_engine.py — Generate PDF Undangan Reviu DPP dari data Supabase.

Format: 2 halaman, kop Pemkab Tapin, nomor surat otomatis, penerima PPK+TimTeknis+Konsultan.
Data dari tabel draft_paket (Supabase) + input user: hari/tanggal/pukul/tempat.
"""

import os
import re
import pathlib
from datetime import date, datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

# ── Font ──────────────────────────────────────────────────────────────────────
_FONT_DIR = pathlib.Path("C:/Windows/Fonts")
pdfmetrics.registerFont(TTFont("Arial",     str(_FONT_DIR / "arial.ttf")))
pdfmetrics.registerFont(TTFont("ArialBd",   str(_FONT_DIR / "arialbd.ttf")))
pdfmetrics.registerFont(TTFont("ArialIt",   str(_FONT_DIR / "ariali.ttf")))
pdfmetrics.registerFont(TTFont("ArialBdIt", str(_FONT_DIR / "arialbi.ttf")))

_F  = "Arial"
_FB = "ArialBd"
_FI = "ArialIt"

# ── Styles ────────────────────────────────────────────────────────────────────
def _s(name, **kw) -> ParagraphStyle:
    base = dict(fontName=_F, fontSize=10, leading=14, spaceAfter=0, spaceBefore=0)
    base.update(kw)
    return ParagraphStyle(name, **base)

ST_NORMAL   = _s("Normal")
ST_CENTER   = _s("Center",   alignment=TA_CENTER)
ST_JUSTIFY  = _s("Justify",  alignment=TA_JUSTIFY)
ST_BOLD     = _s("Bold",     fontName=_FB)
ST_BOLD_C   = _s("BoldC",    fontName=_FB, alignment=TA_CENTER)
ST_KOP_BIG  = _s("KopBig",   fontName=_FB, fontSize=13, leading=16, alignment=TA_CENTER)
ST_KOP_SM   = _s("KopSm",    fontSize=9,  leading=12,  alignment=TA_CENTER)
ST_TITLE    = _s("Title",    fontName=_FB, fontSize=11, leading=14, alignment=TA_CENTER)
ST_SMALL    = _s("Small",    fontSize=9,  leading=12)
ST_SMALL_C  = _s("SmallC",  fontSize=9,  leading=12,  alignment=TA_CENTER)

# ── Helpers ───────────────────────────────────────────────────────────────────
_BULAN = ["Januari","Februari","Maret","April","Mei","Juni",
          "Juli","Agustus","September","Oktober","November","Desember"]
_HARI  = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]


def _fmt_tanggal(d: date) -> str:
    return f"{d.day} {_BULAN[d.month-1]} {d.year}"


def _nama_hari(d: date) -> str:
    return _HARI[d.weekday()]


def _title_case_dinas(nama: str) -> str:
    """Title case nama dinas dengan pengecualian kata hubung."""
    stop = {"dan", "di", "ke", "dari", "yang", "untuk", "dengan", "atau",
            "pada", "dalam", "oleh", "atas", "bagi", "tentang", "no", "nomor"}
    words = nama.lower().split()
    result = []
    for i, w in enumerate(words):
        result.append(w.capitalize() if (i == 0 or w not in stop) else w)
    return " ".join(result)


def _nomor_urut_str(nomor_urut: int) -> str:
    return str(nomor_urut).zfill(2)


def build_nomor_surat(kode_pokja: str, kode_unik: str, tahun: int = 0) -> str:
    """Generate nomor surat: 000.3.3/XX/PokjaYYY/T/Reviu-KODEUNIK/TAHUN"""
    if tahun == 0:
        tahun = date.today().year
    no = _nomor_urut_str(int(kode_pokja)) if kode_pokja.isdigit() else "01"
    return f"000.3.3/{no}/Pokja{kode_pokja.zfill(3)}/T/Reviu-{kode_unik}/{tahun}"


# ── Header Kop ────────────────────────────────────────────────────────────────
def _kop() -> list:
    items = [
        Paragraph("PEMERINTAH KABUPATEN TAPIN", ST_KOP_BIG),
        Paragraph("SEKRETARIAT DAERAH", ST_KOP_BIG),
        Paragraph(
            "Jalan Datu Nuraya RT 1 Kawasan Rantau Baru, Rantau, Kabupaten Tapin 71114",
            ST_KOP_SM,
        ),
        HRFlowable(width="100%", thickness=1.5, color=colors.black, spaceAfter=4),
        HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=6),
    ]
    return items


# ── Halaman 1 ─────────────────────────────────────────────────────────────────
def _hal1(data: dict, tanggal_kirim: date) -> list:
    nama_dinas  = _title_case_dinas(data.get("nama_dinas", ""))
    nama_tender = data.get("nama_tender", "")
    kode_pokja  = data.get("kode_pokja", "001")
    kode_unik   = data.get("kode_unik") or "DPP"
    nomor_surat = data.get("_nomor_surat") or build_nomor_surat(kode_pokja, kode_unik, tanggal_kirim.year)

    nomor_pp    = data.get("nomor_pp", "")
    nomor_sd    = data.get("nomor_surat_dinas", "")

    tanggal_str = f"Rantau, {_fmt_tanggal(tanggal_kirim)}"
    hari_tgl_rapat = data.get("_hari_tgl_rapat", "")
    pukul_rapat    = data.get("_pukul_rapat", "14.00 Wita s/d Selesai")

    items = _kop()
    items.append(Spacer(1, 4 * mm))
    items.append(Paragraph("1. SURAT UNDANGAN REVIU", ST_TITLE))
    items.append(Spacer(1, 6 * mm))

    # Kanan: tanggal + nomor
    tbl_header = Table(
        [[Paragraph(tanggal_str, ST_NORMAL)]],
        colWidths=["100%"],
    )
    tbl_header.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "RIGHT")]))
    items.append(tbl_header)
    items.append(Spacer(1, 2 * mm))

    # Nomor / Lampiran / Perihal
    surat_rows = [
        ["Nomor", ":", nomor_surat],
        ["Lampiran", ":", "-"],
        ["Perihal", ":", "Undangan Reviu Dokumen\nPersiapan Pengadaan"],
    ]
    tbl_surat = Table(surat_rows, colWidths=[25 * mm, 5 * mm, None])
    tbl_surat.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _F),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN",   (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 1),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1),
    ]))
    items.append(tbl_surat)
    items.append(Spacer(1, 4 * mm))

    # Kepada
    items.append(Paragraph("Kepada Yth :", ST_NORMAL))
    penerima = [
        f"1. KPA/PPK {nama_dinas} Kabupaten Tapin",
        f"2. Tim Teknis PPK {nama_dinas} Kabupaten Tapin",
        f"3. Konsultan Perencana/Perancang Paket Pekerjaan {nama_tender}",
    ]
    for p in penerima:
        items.append(Paragraph(p, _s("Recv", leftIndent=4 * mm, leading=13)))
    items.append(Paragraph("Di -", _s("Di", leftIndent=4 * mm)))
    items.append(Paragraph("Tempat", _s("Tempat", leftIndent=4 * mm)))
    items.append(Spacer(1, 4 * mm))

    # Pembuka
    items.append(Paragraph("Dengan hormat,", ST_NORMAL))
    items.append(Spacer(1, 2 * mm))
    items.append(Paragraph("Berdasarkan:", ST_NORMAL))

    dasar = [
        "Peraturan Lembaga Kebijakan Pengadaan Barang/Jasa Pemerintah Nomor 12 Tahun 2021 "
        "Tentang Pedoman Pelaksanaan Pengadaan Barang/Jasa Melalui Penyedia, Lampiran I BAB III "
        "Angka 3.1 tentang Reviu Dokumen Persiapan Pengadaan;",
        f"Surat Permohonan Pemilihan Penyedia Barang/Jasa Nomor: {nomor_sd};",
        f"Surat Tugas Kepala UKPBJ Nomor: {nomor_pp}.",
    ]
    for i, d in enumerate(dasar, 1):
        items.append(Paragraph(
            f"{i}. {d}",
            _s(f"Dasar{i}", leftIndent=6 * mm, firstLineIndent=-6 * mm, leading=13, alignment=TA_JUSTIFY),
        ))

    items.append(Spacer(1, 3 * mm))
    items.append(Paragraph("Diharapkan kehadirannya pada:", ST_NORMAL))
    items.append(Spacer(1, 1 * mm))

    jadwal_rows = [
        ["Hari / Tanggal", ":", hari_tgl_rapat],
        ["Pukul", ":", pukul_rapat],
    ]
    tbl_jadwal = Table(jadwal_rows, colWidths=[35 * mm, 5 * mm, None])
    tbl_jadwal.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), _F),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("VALIGN",   (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 1),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1),
    ]))
    items.append(tbl_jadwal)
    return items


# ── Halaman 2 ─────────────────────────────────────────────────────────────────
def _hal2(data: dict) -> list:
    nama_tender = data.get("nama_tender", "")
    kode_pokja  = data.get("kode_pokja", "001")
    tempat_rapat = data.get("_tempat_rapat",
        "Ruang Aula Rapat Lantai 2 Kantor UKPBJ Kabupaten Tapin, "
        "Jl. Datu Suban RT. 01, Kelurahan Rangda Malingkung, Kecamatan Tapin Utara, "
        "Rantau, Kabupaten Tapin. Kode Pos : 71111")

    items = _kop()
    items.append(Spacer(1, 6 * mm))

    lanjutan_rows = [
        ["Acara", ":", f"Reviu Dokumen Persiapan Pengadaan {nama_tender}"],
        ["Dokumen Yang Dibawa", ":",
         "1. Spesifikasi Teknis\n2. Dokumen HPS\n3. Rancangan Kontrak\n4. Dokumen Anggaran Belanja"],
        ["Tempat", ":", tempat_rapat],
    ]
    tbl_lanjutan = Table(lanjutan_rows, colWidths=[42 * mm, 5 * mm, None])
    tbl_lanjutan.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (-1,-1), _F),
        ("FONTSIZE",    (0,0), (-1,-1), 10),
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",  (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    items.append(tbl_lanjutan)
    items.append(Spacer(1, 6 * mm))

    items.append(Paragraph(
        "Demikian kami sampaikan, atas kehadirannya kami ucapkan terima kasih.",
        ST_JUSTIFY,
    ))
    items.append(Spacer(1, 8 * mm))

    # TTD
    ttd_rows = [[
        "",
        Paragraph("UKPBJ Kabupaten Tapin\n\nTtd\n\n"
                  f"<b>Kelompok Kerja Pemilihan {kode_pokja.zfill(3)}</b>", ST_CENTER),
    ]]
    tbl_ttd = Table(ttd_rows, colWidths=["50%", "50%"])
    tbl_ttd.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    items.append(tbl_ttd)
    return items


# ── PUBLIC API ────────────────────────────────────────────────────────────────
def generate_undangan_pdf(
    kode_tender: str,
    tanggal_kirim: date,
    hari_tgl_rapat: str,
    pukul_rapat: str,
    tempat_rapat: str,
    output_path: Optional[str] = None,
) -> dict:
    """
    Generate PDF undangan reviu DPP.

    Args:
        kode_tender:    Kode tender (primary key Supabase draft_paket)
        tanggal_kirim:  Tanggal surat dikirim (tanggal hari ini atau dipilih user)
        hari_tgl_rapat: "Senin, 11 Mei 2026" — ditampilkan di Hari/Tanggal
        pukul_rapat:    "14.00 Wita s/d Selesai"
        tempat_rapat:   Lokasi rapat
        output_path:    Path PDF output. Jika None, simpan ke folder paket.

    Return:
        {"sukses": bool, "pdf_path": str, "pdf_bytes": bytes, "pesan": str}
    """
    try:
        from config import sb, POKJA_ROOT
        client = sb()
        r = client.table("draft_paket").select("*").eq("kode_tender", kode_tender).single().execute()
        data = r.data or {}
    except Exception as e:
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"", "pesan": f"Gagal ambil data Supabase: {e}"}

    if not data:
        return {"sukses": False, "pdf_path": "", "pdf_bytes": b"", "pesan": f"Paket {kode_tender} tidak ditemukan"}

    # Tentukan output path
    if not output_path:
        folder_rel = data.get("folder_dibuat", "")
        if folder_rel:
            folder_abs = folder_rel if os.path.isabs(folder_rel) else os.path.join(POKJA_ROOT, folder_rel)
        else:
            folder_abs = POKJA_ROOT
        safe_kode = kode_tender.replace("/", "-").replace("\\", "-")
        output_path = os.path.join(folder_abs, f"Undangan_{safe_kode}.pdf")

    # Inject runtime fields
    data["_hari_tgl_rapat"] = hari_tgl_rapat
    data["_pukul_rapat"]    = pukul_rapat
    data["_tempat_rapat"]   = tempat_rapat

    # Build PDF
    try:
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            leftMargin=25 * mm,
            rightMargin=20 * mm,
        )
        story = _hal1(data, tanggal_kirim) + [PageBreak()] + _hal2(data)
        doc.build(story)
    except Exception as e:
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"", "pesan": f"Gagal build PDF: {e}"}

    if not os.path.exists(output_path):
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"", "pesan": "PDF tidak terbuat"}

    try:
        with open(output_path, "rb") as f:
            pdf_bytes = f.read()
    except Exception as e:
        return {"sukses": False, "pdf_path": output_path, "pdf_bytes": b"", "pesan": f"PDF terbuat tapi gagal dibaca: {e}"}

    return {
        "sukses": True,
        "pdf_path": output_path,
        "pdf_bytes": pdf_bytes,
        "pesan": f"PDF berhasil: {os.path.basename(output_path)} ({len(pdf_bytes)//1024} KB)",
    }
