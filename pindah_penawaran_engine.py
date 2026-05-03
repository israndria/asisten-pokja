"""
pindah_penawaran_engine.py — Tab 7 Dokumen Penawaran
Scan D:\data\biddings, lookup Supabase, pindah file ke folder paket, gabung PDF teknis.
"""
import os
import re
import shutil
from config import sb as _sb, POKJA_ROOT, sanitasi_nama_folder

APENDO_ROOT       = r"D:\data\biddings"
DEST_SUBFOLDER    = "1. Dokumen Penawaran"
TEKNIS_DIR        = "administrasi-dan-teknis"
HARGA_DIR         = "harga"
SKIP_DIRS         = {"harga rhs"}


def _nomor_pokja(folder_dibuat: str) -> str:
    """Ekstrak nomor pokja dari nama folder, misal '1. Pokja 086 - ...' → '086'."""
    m = re.search(r"Pokja\s+(\d+)", folder_dibuat, re.IGNORECASE)
    return m.group(1) if m else ""


def scan_apendo() -> list[dict]:
    """
    Scan D:/data/biddings dan return list peserta yang sudah di-unpack.
    Return: [{"kode_tender", "peserta_id", "path_teknis", "path_harga"}]
    """
    hasil = []
    if not os.path.isdir(APENDO_ROOT):
        return hasil
    for lpse_id in os.listdir(APENDO_ROOT):
        lpse_path = os.path.join(APENDO_ROOT, lpse_id)
        if not os.path.isdir(lpse_path):
            continue
        for kode_tender in os.listdir(lpse_path):
            kt_path = os.path.join(lpse_path, kode_tender)
            if not os.path.isdir(kt_path):
                continue
            for peserta_id in os.listdir(kt_path):
                unpacked = os.path.join(kt_path, peserta_id, "unpacked")
                if not os.path.isdir(unpacked):
                    continue
                path_teknis = os.path.join(unpacked, TEKNIS_DIR)
                path_harga  = os.path.join(unpacked, HARGA_DIR)
                # Skip jika kedua folder kosong (sudah dipindah)
                ada_teknis = os.path.isdir(path_teknis) and bool(_collect_files(path_teknis))
                ada_harga  = os.path.isdir(path_harga)  and bool(_collect_files(path_harga))
                if not ada_teknis and not ada_harga:
                    continue
                hasil.append({
                    "kode_tender": kode_tender,
                    "peserta_id":  peserta_id,
                    "path_teknis": path_teknis if ada_teknis else None,
                    "path_harga":  path_harga  if ada_harga  else None,
                })
    return hasil


def _collect_files(folder: str, ext_filter=None) -> list[str]:
    """Kumpulkan file rekursif dari folder, skip SKIP_DIRS. ext_filter=".pdf" untuk PDF saja."""
    hasil = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if ext_filter is None or f.lower().endswith(ext_filter):
                hasil.append(os.path.join(root, f))
    return sorted(hasil)


def lookup_supabase(items: list[dict]) -> list[dict]:
    """
    Enrichment: tambah nama_perusahaan dan folder_paket ke setiap item.
    Hitung urutan peserta per paket untuk penamaan subfolder.
    """
    kode_tenders = list({i["kode_tender"] for i in items})
    peserta_ids  = list({i["peserta_id"]  for i in items})

    sb = _sb()
    paket_map, nama_map = {}, {}

    try:
        r = sb.table("draft_paket").select("kode_tender,nama_tender,folder_dibuat").in_("kode_tender", kode_tenders).execute()
        for row in (r.data or []):
            paket_map[row["kode_tender"]] = row
    except Exception:
        pass

    try:
        r = sb.table("peserta_identitas").select("peserta_id,nama_perusahaan").in_("peserta_id", peserta_ids).execute()
        for row in (r.data or []):
            nama_map[row["peserta_id"]] = row.get("nama_perusahaan", "")
    except Exception:
        pass

    urutan_counter: dict[str, int] = {}
    hasil = []
    for item in items:
        kt = item["kode_tender"]
        urutan_counter[kt] = urutan_counter.get(kt, 0) + 1
        paket = paket_map.get(kt, {})
        folder_nama = paket.get("folder_dibuat", "")
        hasil.append({
            **item,
            "urutan":          urutan_counter[kt],
            "nama_tender":     paket.get("nama_tender", kt),
            "folder_dibuat":   folder_nama,
            "nomor_pokja":     _nomor_pokja(folder_nama),
            "folder_paket":    os.path.join(POKJA_ROOT, folder_nama) if folder_nama else "",
            "nama_perusahaan": nama_map.get(item["peserta_id"], f"Peserta {item['peserta_id']}"),
        })
    return hasil


def resolve_dest(item: dict, total_per_paket: dict) -> str:
    """
    Folder tujuan per peserta:
    1 peserta  → 1. Dokumen Penawaran/ (flat)
    ≥2 peserta → 1. Dokumen Penawaran/{urutan}. {nama_perusahaan}/
    """
    base = os.path.join(item["folder_paket"], DEST_SUBFOLDER)
    if total_per_paket.get(item["kode_tender"], 1) >= 2:
        nama_safe = sanitasi_nama_folder(item["nama_perusahaan"])
        return os.path.join(base, f"{item['urutan']}. {nama_safe}")
    return base


def pindah_dan_gabung(item: dict, dest_dir: str, log=None) -> dict:
    """
    Pindah semua file teknis + harga ke dest_dir.
    Gabung PDF teknis → DoktekFull_{nama}_{nomor_pokja}.pdf (dari dest_dir setelah move).
    Return: {"sukses": [...], "gagal": [...], "gabung_path": str|None}
    """
    os.makedirs(dest_dir, exist_ok=True)
    sukses, gagal = [], []

    # Kumpulkan list nama PDF teknis SEBELUM move
    pdf_teknis_names = []
    if item.get("path_teknis"):
        pdf_teknis_names = [os.path.basename(p) for p in _collect_files(item["path_teknis"], ext_filter=".pdf")]

    def _move(fpath: str, suffix_konflik: str):
        fname = os.path.basename(fpath)
        tujuan = os.path.join(dest_dir, fname)
        if os.path.exists(tujuan):
            base, ext = os.path.splitext(fname)
            tujuan = os.path.join(dest_dir, f"{base}_{suffix_konflik}{ext}")
        try:
            shutil.move(fpath, tujuan)
            sukses.append(fname)
        except Exception as e:
            gagal.append(f"{fname}: {e}")

    if item.get("path_teknis"):
        for f in _collect_files(item["path_teknis"]):
            _move(f, "teknis")
    if item.get("path_harga"):
        for f in _collect_files(item["path_harga"]):
            _move(f, "harga")

    # Gabung PDF teknis dari dest_dir (setelah move)
    gabung_path = None
    if pdf_teknis_names:
        pdf_list = [os.path.join(dest_dir, n) for n in pdf_teknis_names if os.path.exists(os.path.join(dest_dir, n))]
        if pdf_list:
            nama_safe   = sanitasi_nama_folder(item["nama_perusahaan"])
            nomor_pokja = item.get("nomor_pokja", "")
            suffix      = f"_{nomor_pokja}" if nomor_pokja else ""
            out_path    = os.path.join(dest_dir, f"1. DoktekFull_{nama_safe}{suffix}.pdf")
            try:
                import fitz
                merged = fitz.open()
                for p in pdf_list:
                    doc = fitz.open(p)
                    merged.insert_pdf(doc)
                    doc.close()
                merged.save(out_path)
                merged.close()
                gabung_path = out_path
                if log:
                    log(f"PDF digabung: {len(pdf_list)} file → {os.path.basename(out_path)}")
            except Exception as e:
                gagal.append(f"Gabung PDF: {e}")

    return {"sukses": sukses, "gagal": gagal, "gabung_path": gabung_path}
