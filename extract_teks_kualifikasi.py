import os
import sys
import glob
import re
import traceback
from PIL import Image

# Import library
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


def sanitize_filename(name: str) -> str:
    """Sanitasi nama penyedia agar aman untuk nama file."""
    # Ganti karakter ilegal dan koma dengan underscore
    sanitized = re.sub(r'[\\/:*?"<>|,]', '_', name)
    # Ganti spasi/whitespace berlebih
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized[:80]


def is_scan_pdf(pdf_path: str) -> bool:
    """Deteksi apakah PDF scan atau digital (char < 200 di 3 hal pertama)."""
    if not pdfplumber:
        return True

    total_chars = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_to_check = pdf.pages[:3]
            for page in pages_to_check:
                text = page.extract_text()
                if text:
                    total_chars += len(text)
        return total_chars < 200
    except Exception:
        return True


def ocr_pdf_scan(pdf_path: str, progress_cb=None) -> tuple[str, list[str]]:
    """OCR PDF scan menggunakan PyMuPDF + pytesseract."""
    warnings = []
    text_content = []

    if not fitz or not pytesseract:
        return "", ["fitz atau pytesseract tidak terinstall"]

    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # Batasi halaman scan maks 50
        pages_to_process = total_pages
        if total_pages > 50:
            pages_to_process = 50
            warnings.append(f"File {os.path.basename(pdf_path)} scan > 50 hal, hanya di-OCR 50 hal pertama")

        for i in range(pages_to_process):
            if progress_cb:
                progress_cb(f"      OCR hal {i+1}/{pages_to_process}...")

            page = doc[i]
            # Zoom matrix 2x
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # OCR
            try:
                txt = pytesseract.image_to_string(img, lang='ind')
            except Exception:
                # Fallback ke default (tanpa lang) jika 'ind' error
                try:
                    txt = pytesseract.image_to_string(img)
                    warnings.append(f"Fallback OCR default lang untuk hal {i+1} (ind error)")
                except Exception as e:
                    txt = ""
                    warnings.append(f"Gagal OCR hal {i+1}: {str(e)}")

            if txt:
                text_content.append(txt)

        doc.close()
    except Exception as e:
        warnings.append(f"Gagal memproses OCR {os.path.basename(pdf_path)}: {str(e)}")

    return "\n".join(text_content), warnings


def extract_digital_pdf(pdf_path: str) -> str:
    """Extract teks PDF digital."""
    text_content = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_content.append(text)
    return "\n".join(text_content)


def extract_folder_kualifikasi(folder_dok_kualifikasi: str, out_dir: str = None,
                                progress_cb=None) -> dict:
    """
    Ekstrak semua PDF kualifikasi penyedia, dedup, dan tulis output per penyedia + index.
    """
    folder_dok_kualifikasi = os.path.abspath(folder_dok_kualifikasi)
    if not out_dir:
        out_dir = os.path.join(folder_dok_kualifikasi, "_teks_ekstrak")

    os.makedirs(out_dir, exist_ok=True)

    result = {
        "ok": False,
        "penyedia": [],
        "total_token_estimasi": 0,
        "skipped_dedup": [],
        "warnings": [],
        "out_dir": out_dir
    }

    if not os.path.exists(folder_dok_kualifikasi):
        result["warnings"].append(f"Folder input tidak ditemukan: {folder_dok_kualifikasi}")
        return result

    # 1. Cari semua PDF secara rekursif
    pdf_pattern = os.path.join(folder_dok_kualifikasi, "**", "*.pdf")
    pdf_files = glob.glob(pdf_pattern, recursive=True)

    # Kelompokkan file per penyedia
    # Penyedia adalah nama subfolder langsung di bawah folder_dok_kualifikasi
    # Kalau langsung di root, masukkan ke "_root"
    penyedia_groups = {}

    for pdf_path in pdf_files:
        # Cari relpath dari folder input
        rel_path = os.path.relpath(pdf_path, folder_dok_kualifikasi)
        parts = rel_path.split(os.sep)

        # Abaikan file di dalam _teks_ekstrak
        if parts[0] == "_teks_ekstrak" or "_teks_ekstrak" in parts:
            continue

        if len(parts) > 1:
            group_name = parts[0]
        else:
            group_name = "_root"

        if group_name not in penyedia_groups:
            penyedia_groups[group_name] = []
        penyedia_groups[group_name].append(pdf_path)

    if not penyedia_groups:
        result["warnings"].append("Tidak ada file PDF ditemukan")
        return result

    total_token_estimasi = 0

    # 2. Proses per penyedia
    for penyedia_name, files in penyedia_groups.items():
        if progress_cb:
            progress_cb(f"Memproses penyedia: {penyedia_name}")

        extracted_docs = [] # list of dict: {name, text, is_checklist, pages, token, mode, path}

        for pdf_path in files:
            file_name = os.path.basename(pdf_path)
            if progress_cb:
                progress_cb(f"  Membaca: {file_name}")

            is_checklist = "checklist" in file_name.lower()

            try:
                # Deteksi Scan vs Digital
                is_scan = is_scan_pdf(pdf_path)
                mode = "SCAN" if is_scan else "DIGITAL"

                # Hitung jumlah halaman
                num_pages = 0
                if fitz:
                    try:
                        with fitz.open(pdf_path) as doc:
                            num_pages = len(doc)
                    except Exception:
                        pass

                # Ekstrak teks
                text = ""
                file_warnings = []
                if is_scan:
                    if progress_cb:
                        progress_cb(f"    [SCAN] Menjalankan OCR ({num_pages} hal)...")
                    text, file_warnings = ocr_pdf_scan(pdf_path, progress_cb)
                    result["warnings"].extend([f"[{file_name}] {w}" for w in file_warnings])
                else:
                    if progress_cb:
                        progress_cb(f"    [DIGITAL] Mengekstrak teks ({num_pages} hal)...")
                    text = extract_digital_pdf(pdf_path)

                token_est = len(text) // 4
                extracted_docs.append({
                    "name": file_name,
                    "text": text,
                    "is_checklist": is_checklist,
                    "pages": num_pages,
                    "token": token_est,
                    "mode": mode,
                    "path": pdf_path
                })

            except Exception as e:
                err_msg = f"Gagal mengekstrak {file_name}: {str(e)}"
                result["warnings"].append(err_msg)
                if progress_cb:
                    progress_cb(f"    ERROR: {err_msg}")

        if not extracted_docs:
            continue

        # 3. Dedup logic (per pasang dokumen dalam satu penyedia)
        # Bikin set baris unik untuk tiap dokumen
        doc_line_sets = []
        for doc in extracted_docs:
            # Tokenisasi baris, strip, ambil yang panjang > 15
            lines = [line.strip() for line in doc["text"].split("\n") if len(line.strip()) > 15]
            doc_line_sets.append(set(lines))

        skip_indices = set()

        # Bandingkan tiap pasang
        n_docs = len(extracted_docs)
        for i in range(n_docs):
            for j in range(n_docs):
                if i == j:
                    continue
                # Jangan skip checklist
                if extracted_docs[i]["is_checklist"]:
                    continue

                set_i = doc_line_sets[i]
                set_j = doc_line_sets[j]

                if not set_i:
                    continue

                # Cek irisan
                irisan = set_i.intersection(set_j)
                ratio = len(irisan) / len(set_i) if set_i else 0

                if ratio >= 0.90:
                    # i adalah subset dari j. Skip i jika j lebih besar (atau j dipertahankan)
                    # Jika ukuran set_j lebih besar atau sama, skip i
                    if len(set_j) >= len(set_i):
                        skip_indices.add(i)

        # 4. Tulis output gabungan untuk penyedia ini
        # Kelompokkan: Checklist dulu, lalu pendukung
        checklist_docs = [d for idx, d in enumerate(extracted_docs) if d["is_checklist"] and idx not in skip_indices]
        support_docs = [d for idx, d in enumerate(extracted_docs) if not d["is_checklist"] and idx not in skip_indices]

        for idx, d in enumerate(extracted_docs):
            if idx in skip_indices:
                result["skipped_dedup"].append({
                    "penyedia": penyedia_name,
                    "file": d["name"],
                    "token": d["token"]
                })

        # Gabungkan teks
        final_sections = []

        # Checklist ditaruh di paling atas
        for d in checklist_docs:
            final_sections.append(f"### SUMBER UTAMA (checklist SPSE) ###\n\n{d['text']}")

        # Dokumen pendukung di bawah
        for d in support_docs:
            final_sections.append(f"### DOKUMEN PENDUKUNG: {d['name']} ###\n\n{d['text']}")

        combined_text = "\n\n" + "\n\n".join(final_sections) + "\n"
        penyedia_token = len(combined_text) // 4
        total_token_estimasi += penyedia_token

        # Tulis ke file
        out_filename = f"{sanitize_filename(penyedia_name)}.txt"
        out_filepath = os.path.join(out_dir, out_filename)

        with open(out_filepath, "w", encoding="utf-8") as f:
            f.write(combined_text)

        result["penyedia"].append({
            "nama": penyedia_name,
            "out_file": out_filename,
            "token": penyedia_token,
            "files": [
                {
                    "name": d["name"],
                    "mode": d["mode"],
                    "pages": d["pages"],
                    "token": d["token"],
                    "status": "SKIP (subset)" if idx in skip_indices else "OK"
                }
                for idx, d in enumerate(extracted_docs)
            ]
        })

    result["total_token_estimasi"] = total_token_estimasi

    # 5. Tulis _INDEX.txt
    index_path = os.path.join(out_dir, "_INDEX.txt")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("INDEX EKSTRAK TEKS KUALIFIKASI\n")
        f.write(f"Folder: {folder_dok_kualifikasi}\n")
        f.write(f"Total penyedia: {len(result['penyedia'])}\n")
        f.write(f"Total token estimasi: ~{total_token_estimasi}\n\n")

        for p in result["penyedia"]:
            f.write(f"Penyedia: {p['nama']}\n")
            for file_info in p["files"]:
                status_str = f" | {file_info['status']}" if file_info['status'] != "OK" else ""
                f.write(f"  - {file_info['name']} | {file_info['mode']} | {file_info['pages']} hal | ~{file_info['token']} token{status_str}\n")
            f.write("\n")

    result["ok"] = True
    return result


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    if not folder:
        print("Usage: python extract_teks_kualifikasi.py <folder_8_dok_kualifikasi>")
        sys.exit(1)

    print(f"Memulai ekstraksi kualifikasi di: {folder}")
    res = extract_folder_kualifikasi(folder, progress_cb=lambda m: print("  >", m))

    print("\n=== RINGKASAN EKSTRAKSI ===")
    print(f"Status: {'OK' if res['ok'] else 'GAGAL'}")
    print(f"Total Token Estimasi: ~{res['total_token_estimasi']}")
    print(f"Output folder: {res['out_dir']}")
    print(f"Penyedia diproses: {len(res['penyedia'])}")
    print(f"File didedup (skip): {len(res['skipped_dedup'])}")
    if res["warnings"]:
        print(f"Warnings ({len(res['warnings'])}):")
        for w in res["warnings"][:10]:
            print(f"  - {w}")
        if len(res["warnings"]) > 10:
            print("  - ...")
