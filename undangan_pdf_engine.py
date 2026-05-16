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
_TEMPLATE_REL_PL = (
    r"Paket Experiment - Pengadaan Langsung - Konsultan Konstuksi"
    r"\Development\4. Undangan Full PLJK - Template.docx"
)
_TEMPAT_UKPBJ = (
    "Ruang Aula Rapat Lantai 2 Kantor UKPBJ Kabupaten Tapin, "
    "Jl. Datu Suban RT. 01, Kelurahan Rangda Malingkung, Kecamatan Tapin Utara, "
    "Rantau, Kabupaten Tapin. Kode Pos : 71111"
)


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
        # Matikan gridlines agar tidak ikut ter-print ke PDF
        try:
            word.ActiveWindow.DisplayGridLines = False
        except Exception:
            pass
        try:
            doc.ShowGrammaticalErrors = False
            doc.ShowSpellingErrors = False
        except Exception:
            pass
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

    import re as _re2

    nama_satker  = _title_case_dinas(data.get("satker", ""))
    nama_paket   = data.get("nama_paket", "")
    kode_unik    = data.get("kode_unik") or "DPP"
    jenis        = data.get("jenis_pl", "JKK")

    # Nomor + Perihal surat Permohonan PPK — extract dari PDF di folder paket PL
    nomor_pp = ""
    perihal_pp = ""
    import glob as _glob
    _base_pl = os.path.join(POKJA_ROOT, "@ Pejabat Pengadaan 2026",
                            f"@ Pengadaan Langsung {jenis}")
    _pdf_list = []
    for _pat in ["Permohonan PPK*.pdf", "*ermohonan*.pdf"]:
        _pdf_list = _glob.glob(os.path.join(_base_pl, "**", _pat), recursive=True)
        if _pdf_list:
            break
    if _pdf_list:
        try:
            import pdfplumber
            with pdfplumber.open(_pdf_list[0]) as _pdf:
                _txt = _pdf.pages[0].extract_text() or ""
            _mn = _re2.search(r"(?i)nomor\s*:\s*([^\n]+)", _txt)
            if _mn:
                nomor_pp = _mn.group(1).strip()
            _mp = _re2.search(r"(?i)perihal\s*:\s*(.+?)(?=\n(?:Lampiran|Kepada|Nomor|\s*$))", _txt, _re2.DOTALL)
            if _mp:
                perihal_pp = " ".join(_mp.group(1).split())
        except Exception:
            pass

    # Berdasarkan no. 2: "Surat Nomor: {nomor} tentang {perihal}"
    if nomor_pp and perihal_pp:
        berdasarkan_pp = f"Surat Nomor: {nomor_pp} tentang {perihal_pp}."
    elif perihal_pp:
        berdasarkan_pp = f"Surat tentang {perihal_pp}."
    else:
        berdasarkan_pp = "Surat Permohonan Pengadaan dari PPK."

    # Singkatan SKPD: huruf kapital tiap kata, skip stop words
    _SKIP = {"Dan", "Di", "Ke", "Dari", "Yang", "Untuk", "Dengan", "Atau",
             "Pada", "Dalam", "Oleh", "Atas", "Bagi", "Tentang", "Kabupaten",
             "Kota", "Provinsi", "No", "Nomor"}
    _singkatan = "".join(
        w[0] for w in nama_satker.split()
        if w and w[0].isupper() and w not in _SKIP
    )

    # Nomor paket dari digit akhir kode_unik, zero-pad 2 digit
    _no_m = _re2.search(r"\d+$", kode_unik)
    _no_paket_str = _no_m.group().zfill(2) if _no_m else "01"

    if not nomor_surat:
        nomor_surat = (
            f"000.3.3/PP-{_no_paket_str}/{_singkatan}"
            f"/Reviu-{kode_unik}/{tanggal_kirim.year}"
        )

    NAMA_PP = "Muhammad Isra Andria, S.T."
    NIP_PP  = "NIP. 19941211 202012 1 006"

    NAMA_PP = "Muhammad Isra Andria, S.T."
    NIP_PP  = "NIP. 19941211 202012 1 006"

    replacements = {
        "\xabTANGGAL_KIRIM\xbb":  _fmt_tanggal(tanggal_kirim),
        "\xabNOMOR_SURAT\xbb":    nomor_surat,
        "\xabPENERIMA_1\xbb":     f"PPK & Tim Teknis {nama_satker} Kabupaten Tapin",
        "\xabNOMOR_PP\xbb":       berdasarkan_pp,
        "\xabHARI_TGL_RAPAT\xbb": hari_tgl_rapat,
        "\xabPUKUL\xbb":          pukul_rapat,
        "\xabACARA\xbb":          f"Reviu Dokumen Persiapan Pengadaan {nama_paket}",
        "\xabTEMPAT_RAPAT\xbb":   tempat_rapat,
        "\xabTTD_PP\xbb":         "TTD_PP",  # marker inject gambar
        "\xabNAMA_NIP_PP\xbb":    f"{NAMA_PP}||NIP||{NIP_PP}",
        "UKPBJ Kabupaten Tapin":  f"Pejabat Pengadaan {nama_satker}",
        "Kelompok Kerja Pemilihan PP": f"Pejabat Pengadaan {nama_satker}",
    }

    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    tmp_docx = os.path.join(output_dir, f"_tmp_undangan_pl_{os.getpid()}.docx")

    # Cari file TTD gambar di folder Development template
    _template_dir = os.path.dirname(template_path)
    _ttd_path = os.path.join(_template_dir, "ttd_pp.png")
    # Fallback: cari di semua subfolder paket PL
    if not os.path.isfile(_ttd_path):
        import glob as _glob2
        from config import POKJA_ROOT as _PR
        _cands = _glob2.glob(os.path.join(_PR, "@ Pejabat Pengadaan 2026", "**", "ttd_pp.png"), recursive=True)
        if _cands:
            _ttd_path = _cands[0]

    try:
        shutil.copy2(template_path, tmp_docx)

        # Replace placeholder + inject TTD langsung di XML zip (hindari lxml reconstruct)
        import zipfile as _zf, re as _re3
        from PIL import Image as _PIL_Image

        with _zf.ZipFile(tmp_docx, "r") as _zin:
            _files = {n: _zin.read(n) for n in _zin.namelist()}

        _doc_xml = _files["word/document.xml"].decode()
        # Hapus paragraph borders (pBdr) — sumber 853 garis "single" di PDF
        _doc_xml = _re3.sub(r'<w:pBdr>.*?</w:pBdr>', '', _doc_xml, flags=_re3.DOTALL)
        # Hapus tabel style + tblLook (conditional formatting inject border)
        _doc_xml = _re3.sub(r'<w:tblStyle[^/]*/>', '', _doc_xml)
        _doc_xml = _re3.sub(r'<w:tblLook[^/]*/>', '', _doc_xml)
        # Inject tcBorders none ke semua cell
        _NO_TC_BORDER = (
            '<w:tcBorders>'
            '<w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '<w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '</w:tcBorders>'
        )
        def _inject_tc(m):
            c = m.group(0)
            if '<w:tcBorders>' not in c:
                c = c[:-len('</w:tcPr>')] + _NO_TC_BORDER + '</w:tcPr>'
            return c
        _doc_xml = _re3.sub(r'<w:tcPr>.*?</w:tcPr>', _inject_tc, _doc_xml, flags=_re3.DOTALL)
        # Gabung run tersplit: </w:t></w:r>...<w:r...><w:t...> → bisa split placeholder
        _doc_xml = _re3.sub(
            r'</w:t></w:r><w:r(?:\s[^>]*)?>(?:<w:rPr>.*?</w:rPr>)?<w:t(?:\s[^>]*)?>',
            '', _doc_xml, flags=_re3.DOTALL
        )
        for ph, val in replacements.items():
            _escaped = (str(val)
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;"))
            _doc_xml = _doc_xml.replace(ph, _escaped)
        _RPR = (
            '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>'
            '<w:color w:val="000000" w:themeColor="text1"/>'
            '<w:sz w:val="28"/><w:szCs w:val="28"/>'
            '<w:lang w:eastAsia="id-ID"/></w:rPr>'
        )
        # Fix nama+NIP: ||NIP|| → line break Word dengan rPr Arial 14pt
        _doc_xml = _doc_xml.replace(
            "||NIP||",
            f'</w:t></w:r><w:r>{_RPR}<w:br/></w:r><w:r>{_RPR}<w:t xml:space="preserve">'
        )
        # Fix TEMPAT_RAPAT: run tanpa rPr (ListParagraph style) → inject rPr Arial 14pt
        # Cari run <w:r><w:t>...hasil replace tempat...</w:t></w:r> dan tambah rPr
        _tempat_val = replacements.get("\xabTEMPAT_RAPAT\xbb", "")
        if _tempat_val:
            _tempat_escaped = (_tempat_val.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))
            _doc_xml = _doc_xml.replace(
                f'<w:r><w:t>{_tempat_escaped}</w:t></w:r>',
                f'<w:r>{_RPR}<w:t xml:space="preserve">{_tempat_escaped}</w:t></w:r>',
            )
        _files["word/document.xml"] = _doc_xml.encode()

        # Fix Content_Types — python-docx drop entry png dari header
        _ct = _files["[Content_Types].xml"].decode()
        if 'Extension="png"' not in _ct:
            _files["[Content_Types].xml"] = _ct.replace(
                "</Types>", '<Default Extension="png" ContentType="image/png"/></Types>'
            ).encode()

        # Inject TTD gambar
        if os.path.isfile(_ttd_path):
            with _PIL_Image.open(_ttd_path) as _im:
                _px_w, _px_h = _im.size
            _emu_target_w = int(2 / 2.54 * 914400)
            _emu_target_h = int(_emu_target_w * _px_h / _px_w)

            with open(_ttd_path, "rb") as _fimg:
                _png_bytes = _fimg.read()

            _rels_xml = _files["word/_rels/document.xml.rels"].decode()
            _existing_ids = list(map(int, _re3.findall(r'Id="rId(\d+)"', _rels_xml)))
            _new_rid_num = max(_existing_ids, default=10) + 1
            _new_rid = f"rId{_new_rid_num}"

            _files["word/media/ttd_pp.png"] = _png_bytes
            _files["word/_rels/document.xml.rels"] = _rels_xml.replace(
                "</Relationships>",
                f'<Relationship Id="{_new_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/ttd_pp.png"/></Relationships>',
            ).encode()

            _doc_xml = _files["word/document.xml"].decode()
            _drawing = (
                f'<w:drawing>'
                f'<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
                f'<wp:extent cx="{_emu_target_w}" cy="{_emu_target_h}"/>'
                f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
                f'<wp:docPr id="{_new_rid_num}" name="ttd_pp"/>'
                f'<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
                f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:nvPicPr><pic:cNvPr id="0" name="ttd_pp"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="{_new_rid}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
                f'<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{_emu_target_w}" cy="{_emu_target_h}"/></a:xfrm>'
                f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
                f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>'
            )
            _ttd_pos = _doc_xml.find(">TTD_PP</w:t>")
            if _ttd_pos >= 0:
                _run_matches = list(_re3.finditer(r'<w:r[ >]', _doc_xml[:_ttd_pos]))
                if _run_matches:
                    _rs = _run_matches[-1].start()
                    _re_end = _doc_xml.find("</w:r>", _ttd_pos) + len("</w:r>")
                    _doc_xml = _doc_xml[:_rs] + f'<w:r>{_drawing}</w:r>' + _doc_xml[_re_end:]
            _files["word/document.xml"] = _doc_xml.encode()

        with _zf.ZipFile(tmp_docx, "w", _zf.ZIP_DEFLATED) as _zout:
            for _n, _data in _files.items():
                _zout.writestr(_n, _data)

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
