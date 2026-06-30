"""
Convert _HPS_*.md → _HPS_*.pdf
Buang header (judul + kode + ringkasan + anomali), ambil hanya tabel BoQ.
Usage: python _hps_to_pdf.py <path_md>
"""
import sys
import re
import fitz

def md_to_pdf(md_path: str) -> str:
    with open(md_path, encoding="utf-8") as f:
        content = f.read()

    # Ambil hanya bagian tabel BoQ — mulai dari baris header tabel
    # Header tabel = baris yang mengandung "No | Jenis B/J"
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("No |") or line.strip().startswith("No|"):
            start = i
            break

    if start is None:
        raise ValueError("Tabel BoQ tidak ditemukan di file MD")

    table_lines = lines[start:]
    # Buang baris separator markdown (---|---|...)
    table_lines = [l for l in table_lines if not re.match(r'^[\s\-|]+$', l)]

    # Parse nama paket dari path untuk judul PDF
    import os
    folder = os.path.basename(os.path.dirname(md_path))
    # Ambil nama setelah "PLJKK - " atau "PLPK - "
    m = re.search(r'PL(?:JKK|PK)\s*-\s*(.+)', folder)
    nama_paket = m.group(1).strip() if m else folder

    # Build HTML
    def escape(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Parse tabel dari markdown pipe format
    rows_html = []
    for i, line in enumerate(table_lines):
        if not line.strip():
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")][:6]  # buang Total SPSE, Total Hitung, Selisih OK
        tag = "th" if i == 0 else "td"
        cells_html = "".join(
            f'<{tag} style="padding:3px 6px;border:1px solid #999;{"font-weight:bold;" if re.match(r"^\*\*.+\*\*$", c) else ""}">'
            f'{escape(re.sub(r"^\*\*(.+)\*\*$", r"\1", c))}</{tag}>'
            for c in cells
        )
        tr_style = 'style="background:#f0f4ff;"' if i == 0 else ('style="background:#f9f9f9;"' if i % 2 == 0 else '')
        rows_html.append(f"<tr {tr_style}>{cells_html}</tr>")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: Arial, sans-serif; font-size: 7.5pt; margin: 10px; }}
h3 {{ font-size: 9pt; margin-bottom: 6px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #999; padding: 3px 5px; vertical-align: top; word-break: break-word; }}
th {{ background: #2c5f9e; color: white; font-size: 7pt; }}
</style>
</head>
<body>
<h3>Tabel BoQ HPS — {escape(nama_paket)}</h3>
<table>
{"".join(rows_html)}
</table>
</body>
</html>"""

    # Render via fitz.Story (A3 landscape untuk tabel lebar)
    # A3 landscape = 420mm x 297mm = 1191 x 842 pt
    mediabox = fitz.paper_rect("a3-l")
    margin = 20
    where = mediabox + (margin, margin, -margin, -margin)

    story = fitz.Story(html=html)
    writer = fitz.DocumentWriter(md_path.replace(".md", ".pdf"))

    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()

    writer.close()
    pdf_path = md_path.replace(".md", ".pdf")
    print(f"OK: {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python _hps_to_pdf.py <path_md>")
        sys.exit(1)
    md_to_pdf(sys.argv[1])
