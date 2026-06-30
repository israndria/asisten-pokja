"""
Convert _HPS_*.md → _HPS_*.pdf
Buang header (judul + kode + ringkasan + anomali), ambil hanya tabel BoQ.
Usage: python _hps_to_pdf.py <path_md>
"""
import sys
import re
import fitz

def _rp(n) -> str:
    try:
        return f"Rp {int(round(float(n))):,}".replace(",", ".")
    except Exception:
        return str(n)


def md_to_pdf(md_path: str, nama_paket: str = None, total_hps: float = None, nilai_pagu: float = None) -> str:
    with open(md_path, encoding="utf-8") as f:
        content = f.read()

    # Ambil hanya bagian tabel BoQ — mulai dari baris header tabel
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

    # Fallback nama paket dari path jika tidak di-pass
    import os
    if not nama_paket:
        folder = os.path.basename(os.path.dirname(md_path))
        m = re.search(r'PL(?:JKK|PK)\s*-\s*(.+)', folder)
        nama_paket = m.group(1).strip() if m else folder

    # Fallback total_hps dari MD jika tidak di-pass
    if total_hps is None:
        for line in lines:
            m = re.search(r'Total Nilai Bulat\*\*.*?Rp\s*([\d.]+)', line)
            if m:
                try:
                    total_hps = float(m.group(1).replace(".", ""))
                except Exception:
                    pass
                break

    def escape(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Info paket: nama + nilai pagu + HPS
    info_rows = f'<tr><td colspan="2"><b>Nama Paket</b></td><td colspan="4">{escape(nama_paket)}</td></tr>'
    if nilai_pagu is not None:
        info_rows += f'<tr><td colspan="2"><b>Nilai Pagu</b></td><td colspan="4">{_rp(nilai_pagu)}</td></tr>'
    if total_hps is not None:
        info_rows += f'<tr><td colspan="2"><b>Nilai HPS</b></td><td colspan="4">{_rp(total_hps)}</td></tr>'

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
h3 {{ font-size: 9pt; margin-bottom: 6px; color: #1a3a6b; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 8px; }}
th, td {{ border: 1px solid #999; padding: 3px 5px; vertical-align: top; word-break: break-word; }}
th {{ background: #2c5f9e; color: white; font-size: 7pt; }}
.info td {{ background: #f5f8ff; border-color: #ccd; font-size: 7.5pt; }}
</style>
</head>
<body>
<h3>Harga Perkiraan Sendiri (HPS)</h3>
<table class="info">
{info_rows}
</table>
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
