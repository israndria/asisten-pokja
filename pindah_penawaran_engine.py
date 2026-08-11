"""
pindah_penawaran_engine.py — Tab 7 Dokumen Penawaran
Scan D:\data\biddings, lookup Supabase, pindah file ke folder paket, gabung PDF teknis.
"""
import os
import re
import shutil
from config import sb as _sb, POKJA_ROOT, TENDER_ROOT, sanitasi_nama_folder

APENDO_ROOT       = os.path.join(os.path.splitdrive(POKJA_ROOT)[0] + os.sep, "data", "biddings")
DEST_SUBFOLDER    = "1. Dokumen Penawaran"
TEKNIS_DIR        = "administrasi-dan-teknis"
HARGA_DIR         = "harga"
SKIP_DIRS         = {"harga rhs"}


def _nomor_pokja(folder_dibuat: str) -> str:
    """Ekstrak nomor pokja dari nama folder, misal '1. Pokja 086 - ...' → '086'."""
    m = re.search(r"Pokja\s*[-]?\s*(\d+)", folder_dibuat, re.IGNORECASE)
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
                # Skip peserta tanpa dokumen teknis (tidak submit penawaran lengkap)
                ada_teknis = os.path.isdir(path_teknis) and bool(_collect_files(path_teknis))
                if not ada_teknis:
                    continue
                ada_harga = os.path.isdir(path_harga) and bool(_collect_files(path_harga))
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
    Enrichment: tambah nama_perusahaan, urutan SPSE, dan folder_paket ke setiap item.
    Urutan peserta ikut ranking di tender_peserta (bukan urutan filesystem).
    Nama peserta: cari dari peserta_identitas → kk_evaluasi_peserta → fallback ID.
    """
    _excluded = {"10096884000"}  # legacy 2025 Hatungun
    items = [i for i in items if str(i.get("kode_tender")) not in _excluded]
    if not items:
        return []
    kode_tenders = list({i["kode_tender"] for i in items})
    peserta_ids  = list({i["peserta_id"]  for i in items})

    sb = _sb()
    paket_map, nama_map, urutan_map = {}, {}, {}

    try:
        r = sb.table("draft_paket").select("kode_tender,nama_tender,folder_dibuat,status_tahap").in_("kode_tender", kode_tenders).execute()
        for row in (r.data or []):
            paket_map[row["kode_tender"]] = row
    except Exception:
        pass

    # Nama dari peserta_identitas (sudah terisi setelah Download+Parse KK)
    try:
        r = sb.table("peserta_identitas").select("peserta_id,nama_perusahaan").in_("peserta_id", peserta_ids).execute()
        for row in (r.data or []):
            if row.get("nama_perusahaan"):
                nama_map[row["peserta_id"]] = row["nama_perusahaan"]
    except Exception:
        pass

    # Urutan + nama dari kk_evaluasi_peserta (urutan = ranking harga terendah SPSE)
    # kk tidak punya kualifikasi_id — join by nama setelah nama_map terisi
    _kk_rows: list[dict] = []
    try:
        r = sb.table("kk_evaluasi_peserta").select("kode_tender,urutan,nama").in_("kode_tender", kode_tenders).execute()
        _kk_rows = r.data or []
    except Exception:
        pass

    # Urutan peserta dari tender_peserta (fallback jika ada)
    try:
        r = sb.table("tender_peserta").select("kode_tender,kualifikasi_id,urutan").in_("kode_tender", kode_tenders).execute()
        for row in (r.data or []):
            urutan_map[(row["kode_tender"], row.get("kualifikasi_id", ""))] = row.get("urutan", 999)
    except Exception:
        pass

    # Fallback: scrape /preview untuk peserta yang belum ada namanya (sebelum sort)
    missing_ids = [i["peserta_id"] for i in items if i["peserta_id"] not in nama_map]
    if missing_ids:
        try:
            import identitas_engine as _ie
            for pid in missing_ids:
                try:
                    d = _ie.scrape_preview(pid)
                    if d.get("nama_perusahaan"):
                        nama_map[pid] = d["nama_perusahaan"]
                except Exception:
                    pass
        except Exception:
            pass

    # Build urutan dari kk_evaluasi_peserta by nama match (setelah nama_map lengkap)
    for row in _kk_rows:
        kt = row.get("kode_tender", "")
        nama_kk = (row.get("nama") or "").strip().upper()
        urutan_kk = row.get("urutan", 999)
        # Cari peserta_id yang nama_map-nya cocok
        for item in items:
            if item["kode_tender"] != kt:
                continue
            pid = item["peserta_id"]
            nama_pid = (nama_map.get(pid) or "").strip().upper()
            if nama_pid and nama_pid == nama_kk:
                if (kt, pid) not in urutan_map:
                    urutan_map[(kt, pid)] = urutan_kk

    # Sort items per paket by urutan SPSE
    from collections import defaultdict
    by_paket: dict[str, list] = defaultdict(list)
    for item in items:
        by_paket[item["kode_tender"]].append(item)
    for kt in by_paket:
        by_paket[kt].sort(key=lambda x: urutan_map.get((kt, x["peserta_id"]), 999))

    hasil = []
    for kt in by_paket:
        for seq, item in enumerate(by_paket[kt], 1):
            paket = paket_map.get(kt, {})
            folder_nama = paket.get("folder_dibuat", "")
            hasil.append({
                **item,
                "urutan":          seq,
                "nama_tender":     paket.get("nama_tender", kt),
                "folder_dibuat":   folder_nama,
                "status_tahap":    paket.get("status_tahap", ""),
                "nomor_pokja":     _nomor_pokja(folder_nama),
                "folder_paket":    os.path.join(TENDER_ROOT, folder_nama) if folder_nama else "",
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


GABUNGAN_SUBFOLDER = "1. Dokumen Gabungan"


def cari_dokumen_lengkap(folder_paket: str) -> list[str]:
    """Cari DokFull hasil gabungan yang valid untuk sumber Evaluasi AI."""
    root = os.path.join(folder_paket, GABUNGAN_SUBFOLDER)
    if not os.path.isdir(root):
        return []
    hasil = []
    for dirpath, _, filenames in os.walk(root):
        for nama in filenames:
            if nama.startswith("1. DokFull_") and nama.endswith(".pdf"):
                path = os.path.join(dirpath, nama)
                try:
                    if os.path.getsize(path) > 0:
                        hasil.append(path)
                except OSError:
                    continue
    return sorted(hasil)


def cari_checklist_kualifikasi(folder_paket: str) -> list[str]:
    """Cari checklist kualifikasi SPSE untuk sumber utama admin/kualifikasi."""
    root = os.path.join(folder_paket, "1. Dokumen Kualifikasi")
    if not os.path.isdir(root):
        return []
    hasil = []
    for dirpath, _, filenames in os.walk(root):
        for nama in filenames:
            if nama.lower().startswith("checklist_kualifikasi_") and nama.lower().endswith(".pdf"):
                path = os.path.join(dirpath, nama)
                try:
                    if os.path.getsize(path) > 0:
                        hasil.append(path)
                except OSError:
                    continue
    return sorted(hasil)


def gabung_dokumen_lengkap(folder_paket: str, log=None) -> dict:
    """
    Gabung DoktekFull + DokkualifFull per peserta → 1. Dokumen Gabungan/{urutan}. {nama}/1. DokFull_{nama}_{pokja}.pdf

    Scan:
      - {folder_paket}/1. Dokumen Penawaran/{urutan}. {nama}/1. DoktekFull_*.pdf
      - {folder_paket}/1. Dokumen Kualifikasi/{urutan}. {nama}/1. DokkualifFull_*.pdf

    Return: {"ok": int, "gagal": [...]}
    """
    def _log(m):
        if log: log(m)

    try:
        import fitz
    except ImportError:
        return {"ok": 0, "gagal": ["PyMuPDF tidak tersedia"]}

    folder_penawaran  = os.path.join(folder_paket, DEST_SUBFOLDER)
    folder_kualifikasi = os.path.join(folder_paket, "1. Dokumen Kualifikasi")
    folder_gabungan   = os.path.join(folder_paket, GABUNGAN_SUBFOLDER)

    if not os.path.isdir(folder_penawaran):
        return {"ok": 0, "gagal": [f"Folder Dokumen Penawaran tidak ditemukan: {folder_penawaran}"]}

    ok_count = 0
    gagal = []

    # Iterasi peserta dalam dua format:
    # - nested: 1. Dokumen Penawaran/{urutan}. {nama}/1. DoktekFull_*.pdf
    # - flat:   1. Dokumen Penawaran/1. DoktekFull_*.pdf
    peserta_entries = []
    for entry in sorted(os.listdir(folder_penawaran)):
        sub_penawaran = os.path.join(folder_penawaran, entry)
        if os.path.isdir(sub_penawaran):
            peserta_entries.append((entry, sub_penawaran, None))
        elif entry.startswith("1. DoktekFull_") and entry.endswith(".pdf"):
            # Format flat tidak menyimpan nama peserta sebagai folder.
            # Ambil nama dari filename dan buang suffix kode pokja.
            nama = entry[len("1. DoktekFull_"):-len(".pdf")]
            if "_" in nama:
                nama = nama.rsplit("_", 1)[0]
            peserta_entries.append((f"1. {nama}", folder_penawaran, os.path.join(folder_penawaran, entry)))

    for entry, sub_penawaran, direct_doktek in peserta_entries:

        # Cari DoktekFull_*.pdf
        doktek = direct_doktek or next(
            (os.path.join(sub_penawaran, f) for f in os.listdir(sub_penawaran)
             if f.startswith("1. DoktekFull_") and f.endswith(".pdf")),
            None,
        )
        if not doktek:
            _log(f"  ⚠️ {entry}: DoktekFull tidak ditemukan, skip")
            continue

        # Cari subfolder kualifikasi yang cocok (nama prefix sama)
        dokkualif = None
        if os.path.isdir(folder_kualifikasi):
            sub_kualif = os.path.join(folder_kualifikasi, entry)
            if os.path.isdir(sub_kualif):
                dokkualif = next(
                    (os.path.join(sub_kualif, f) for f in os.listdir(sub_kualif)
                     if f.startswith("1. DokkualifFull_") and f.endswith(".pdf")),
                    None,
                )
            if not dokkualif:
                # Coba cari subfolder dengan prefix urutan yang sama (e.g. "1. " prefix)
                urutan_prefix = entry.split(".")[0].strip() + "."
                for sub in os.listdir(folder_kualifikasi):
                    if sub.startswith(urutan_prefix) and os.path.isdir(os.path.join(folder_kualifikasi, sub)):
                        sub_kualif2 = os.path.join(folder_kualifikasi, sub)
                        dokkualif = next(
                            (os.path.join(sub_kualif2, f) for f in os.listdir(sub_kualif2)
                             if f.startswith("1. DokkualifFull_") and f.endswith(".pdf")),
                            None,
                        )
                        if dokkualif:
                            break

        # Tentukan nama output dari nama DoktekFull (ganti prefix)
        doktek_basename = os.path.basename(doktek)
        # "1. DoktekFull_CV. SAMATA_001.pdf" → "1. DokFull_CV. SAMATA_001.pdf"
        out_name = doktek_basename.replace("DoktekFull_", "DokFull_", 1)

        dest_sub = os.path.join(folder_gabungan, entry)
        os.makedirs(dest_sub, exist_ok=True)
        out_path = os.path.join(dest_sub, out_name)

        pdf_list = [p for p in [doktek, dokkualif] if p and os.path.isfile(p)]
        _log(f"  {entry}: gabung {len(pdf_list)} PDF → {out_name}")

        try:
            merged = fitz.open()
            for p in pdf_list:
                doc = fitz.open(p)
                merged.insert_pdf(doc)
                doc.close()
            merged.save(out_path)
            merged.close()
            ok_count += 1
        except Exception as e:
            gagal.append(f"{entry}: {e}")
            _log(f"  ❌ {entry}: {e}")

    return {"ok": ok_count, "gagal": gagal}
