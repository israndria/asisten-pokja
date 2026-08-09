"""Engine deteksi & download update dokumen PPK dari SPSE."""

import os
import re
import json
import shutil
import requests
from difflib import SequenceMatcher
from datetime import datetime
from bs4 import BeautifulSoup

from config import sb, SPSE_BASE_URL

BASE_URL = SPSE_BASE_URL.rstrip("/")

# Endpoint jenis dokumen yang di-track
ENDPOINTS = {
    "spek":        "spek",         # KAK / Spesifikasi Teknis dan Gambar
    "docsskk":     "docsskk",      # Rancangan Kontrak
    "uploaduraian":"uploaduraian", # Uraian Singkat Pekerjaan
    "ldk":         "ldk",          # Persyaratan Kualifikasi
    "lainnya":     "lainnya",      # Informasi Lainnya
}

# Folder kanonik paket Tender untuk arsip update.
DOKUMEN_FOLDER_MAP = {
    "spek": "1. KAK & Spesifikasi Teknis",
    "docsskk": "2. Rancangan Kontrak",
    "uploaduraian": "3. Uraian Singkat Pekerjaan",
    "ldk": "8. Dokumen Kualifikasi",
    "lainnya": "4. Informasi Lainnya",
}


def _headers(referer: str = "") -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer or BASE_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _get_cookies() -> str:
    """Ambil cookie SPSE via spse_browser (ProactorEventLoop dedicated thread)."""
    from spse_browser import get_spse_cookies
    return get_spse_cookies()


def fetch_dokumen_endpoint(kode_tender: str, jenis: str, cookie_str: str) -> list[dict]:
    """
    Fetch satu endpoint dokumen SPSE.
    Return list: [{"nama": str, "tanggal": str, "url_dl": str}]
    """
    url = f"{BASE_URL}/dokumen/{kode_tender}/{jenis}"
    hdrs = {**_headers(f"{BASE_URL}/lelang/{kode_tender}/edit"), "Cookie": cookie_str}
    try:
        r = requests.get(url, headers=hdrs, timeout=15)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    tbl = soup.find("table", id="files")
    if not tbl:
        return []

    hasil = []
    for tr in tbl.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        a = tds[0].find("a")
        if not a:
            continue
        nama = a.get_text(strip=True)
        nama = re.sub(r"\s*-\s*\d+\s*[KkMm][Bb]\s*$", "", nama).strip()
        url_dl = a.get("href", "")
        if url_dl.startswith("/"):
            url_dl = f"https://spse.inaproc.id{url_dl}"
        tanggal = tds[1].get_text(strip=True)
        hasil.append({"nama": nama, "tanggal": tanggal, "url_dl": url_dl})

    return hasil


def _link_dokumen_dari_edit(kode_tender: str, cookie_str: str) -> dict:
    """
    Scrape /lelang/{kode}/edit, ambil href /dokumen/{id}/{jenis} apa adanya.
    SPSE kadang kasih {id} beda dari kode_tender utama untuk endpoint tertentu
    (mis. uploaduraian pakai ID paket lama saat tender diulang) — jangan
    asumsikan id selalu sama dengan kode_tender.
    Return: {jenis: (id_dokumen, href)}
    """
    url = f"{BASE_URL}/lelang/{kode_tender}/edit"
    hdrs = {**_headers(BASE_URL), "Cookie": cookie_str}
    try:
        r = requests.get(url, headers=hdrs, timeout=15)
        if r.status_code != 200:
            return {}
    except Exception:
        return {}
    soup = BeautifulSoup(r.text, "html.parser")
    hasil = {}
    for a in soup.find_all("a", href=re.compile(r"/dokumen/")):
        m = re.search(r"/dokumen/(\d+)/(\w+)", a.get("href", ""))
        if m:
            hasil[m.group(2)] = m.group(1)
    return hasil


def ambil_snapshot(kode_tender: str) -> dict:
    """
    Fetch semua endpoint → return snapshot dict.
    {jenis: [{"nama":..., "tanggal":..., "url_dl":...}]}
    """
    cookie_str = _get_cookies()
    id_per_jenis = _link_dokumen_dari_edit(kode_tender, cookie_str)
    snapshot = {}
    for key, jenis in ENDPOINTS.items():
        id_dok = id_per_jenis.get(jenis, kode_tender)
        snapshot[key] = fetch_dokumen_endpoint(id_dok, jenis, cookie_str)
    return snapshot


def simpan_snapshot(kode_tender: str, snapshot: dict):
    """Upsert snapshot ke kolom dokumen_snapshot di draft_paket."""
    sb().table("draft_paket").update(
        {"dokumen_snapshot": json.dumps(snapshot)}
    ).eq("kode_tender", kode_tender).execute()


_AMBIGUOUS_NAME_MARKERS = {
    "baru", "copy", "final", "fix", "lama", "new", "old", "revisi",
    "rev", "update", "updated", "versi", "version",
}


def _nama_file_key(nama: str) -> tuple[str, str]:
    """Normalisasi nama untuk mencocokkan file tanpa mengubah nama asli."""
    raw = str(nama or "").strip().lower()
    stem, ext = os.path.splitext(raw)
    stem = re.sub(r"[\W_]+", " ", stem, flags=re.UNICODE)
    return " ".join(stem.split()), ext.lower()


def _nama_file_semantic_key(nama: str) -> set[str]:
    """Token nama yang berguna untuk mencari kandidat ambigu secara konservatif."""
    stem, _ = _nama_file_key(nama)
    return {
        token for token in stem.split()
        if len(token) > 1 and token not in _AMBIGUOUS_NAME_MARKERS
    }


def _skor_nama_ambigu(nama_lama: str, nama_baru: str) -> float:
    """Skor kandidat rename; skor hanya untuk verifikasi, bukan auto-update."""
    _, ext_lama = _nama_file_key(nama_lama)
    _, ext_baru = _nama_file_key(nama_baru)
    if ext_lama != ext_baru:
        return 0.0
    lama_stem, _ = _nama_file_key(nama_lama)
    baru_stem, _ = _nama_file_key(nama_baru)
    lama_tokens = _nama_file_semantic_key(nama_lama)
    baru_tokens = _nama_file_semantic_key(nama_baru)
    shared = lama_tokens & baru_tokens
    if not shared:
        return 0.0
    ratio = SequenceMatcher(None, lama_stem, baru_stem).ratio()
    token_ratio = len(shared) / max(len(lama_tokens | baru_tokens), 1)
    # Ambang sengaja konservatif; hasilnya tetap perlu verifikasi manual.
    return max(ratio, token_ratio)


def _buat_perlu_verifikasi(jenis: str, lama: dict, baru: dict, skor: float, alasan: str) -> dict:
    return {
        "jenis": jenis,
        "nama_lama": lama.get("nama", ""),
        "tanggal_lama": lama.get("tanggal", ""),
        "nama_baru": baru.get("nama", ""),
        "tanggal_baru": baru.get("tanggal", ""),
        "url_dl": baru.get("url_dl", ""),
        "skor": round(skor, 3),
        "alasan": alasan,
    }


def cek_update_dokumen(kode_tender: str) -> dict:
    """
    Bandingkan snapshot SPSE terkini vs snapshot tersimpan di Supabase.

    Return:
    {
        "berubah": [{"jenis", "nama_lama", "nama_baru", "tanggal_lama", "tanggal_baru", "url_dl"}],
        "baru":    [{"jenis", "nama", "tanggal", "url_dl"}],
        "perlu_verifikasi": [{"jenis", "nama_lama", "nama_baru", ...}],
        "sama":    [jenis, ...],
        "snapshot_baru": dict,
    }
    """
    # Ambil snapshot lama dari Supabase
    r = sb().table("draft_paket").select("dokumen_snapshot").eq("kode_tender", kode_tender).execute()
    snapshot_lama = {}
    if r.data and r.data[0].get("dokumen_snapshot"):
        raw = r.data[0]["dokumen_snapshot"]
        snapshot_lama = raw if isinstance(raw, dict) else json.loads(raw)

    # Fetch snapshot terbaru dari SPSE
    cookie_str = _get_cookies()
    id_per_jenis = _link_dokumen_dari_edit(kode_tender, cookie_str)
    snapshot_baru = {}
    for key, jenis in ENDPOINTS.items():
        id_dok = id_per_jenis.get(jenis, kode_tender)
        snapshot_baru[key] = fetch_dokumen_endpoint(id_dok, jenis, cookie_str)

    berubah = []
    baru = []
    perlu_verifikasi = []
    hilang_global = []
    sama = []

    for key in ENDPOINTS:
        lama_list = snapshot_lama.get(key, [])
        baru_list = snapshot_baru.get(key, [])

        # URL /dl/ tidak stabil (session token berubah tiap request), jadi
        # identity memakai nama + tanggal upload, bukan URL.
        lama_used: set[int] = set()
        baru_used: set[int] = set()
        lama_by_key = {}
        baru_by_key = {}
        for i, item in enumerate(lama_list):
            lama_by_key.setdefault(
                (_nama_file_key(item.get("nama")), str(item.get("tanggal", "")).strip()), []
            ).append(i)
        for i, item in enumerate(baru_list):
            baru_by_key.setdefault(
                (_nama_file_key(item.get("nama")), str(item.get("tanggal", "")).strip()), []
            ).append(i)

        # Match exact identity first. This avoids false changes when SPSE only
        # reorders rows or refreshes the download URL.
        for identity in lama_by_key.keys() & baru_by_key.keys():
            for old_i, new_i in zip(lama_by_key[identity], baru_by_key[identity]):
                lama_used.add(old_i)
                baru_used.add(new_i)

        # Same normalized filename + different upload date = safe update.
        lama_by_name = {}
        baru_by_name = {}
        for i, item in enumerate(lama_list):
            if i not in lama_used:
                lama_by_name.setdefault(_nama_file_key(item.get("nama")), []).append(i)
        for i, item in enumerate(baru_list):
            if i not in baru_used:
                baru_by_name.setdefault(_nama_file_key(item.get("nama")), []).append(i)

        for name_key in lama_by_name.keys() & baru_by_name.keys():
            old_ids = lama_by_name[name_key]
            new_ids = baru_by_name[name_key]
            if len(old_ids) == len(new_ids) == 1:
                old_i, new_i = old_ids[0], new_ids[0]
                f_lama, f_baru = lama_list[old_i], baru_list[new_i]
                berubah.append({
                    "jenis": key,
                    "nama_lama": f_lama["nama"],
                    "tanggal_lama": f_lama["tanggal"],
                    "nama_baru": f_baru["nama"],
                    "tanggal_baru": f_baru["tanggal"],
                    "url_dl": f_baru["url_dl"],
                })
                lama_used.add(old_i)
                baru_used.add(new_i)
            else:
                # Duplicate same-name rows have no stable SPSE identity.
                for old_i, new_i in zip(old_ids, new_ids):
                    lama_used.add(old_i)
                    baru_used.add(new_i)
                    perlu_verifikasi.append(_buat_perlu_verifikasi(
                        key, lama_list[old_i], baru_list[new_i], 1.0,
                        "nama sama tetapi kandidat lebih dari satu",
                    ))

        # Different names are never auto-paired. Only expose a high-similarity
        # pair for manual verification; unrelated files remain genuinely new.
        candidates = []
        for old_i, f_lama in enumerate(lama_list):
            if old_i in lama_used:
                continue
            for new_i, f_baru in enumerate(baru_list):
                if new_i in baru_used:
                    continue
                score = _skor_nama_ambigu(f_lama.get("nama"), f_baru.get("nama"))
                if score >= 0.72:
                    candidates.append((score, old_i, new_i))
        for score, old_i, new_i in sorted(candidates, reverse=True):
            if old_i in lama_used or new_i in baru_used:
                continue
            lama_used.add(old_i)
            baru_used.add(new_i)
            perlu_verifikasi.append(_buat_perlu_verifikasi(
                key, lama_list[old_i], baru_list[new_i], score,
                "nama mirip, tetapi SPSE tidak menyediakan relasi revisi",
            ))

        for i, f_hilang in enumerate(lama_list):
            if i not in lama_used:
                hilang_global.append({"jenis": key, **f_hilang})
        for i, f_baru in enumerate(baru_list):
            if i not in baru_used:
                baru.append({"jenis": key, **f_baru})

        ada_perubahan = bool(
            any(item.get("jenis") == key for item in berubah)
            or any(item.get("jenis") == key for item in baru)
            or any(item.get("jenis") == key for item in perlu_verifikasi)
            or any(item.get("jenis") == key for item in hilang_global)
        )

        if not ada_perubahan:
            sama.append(key)

    return {
        "berubah": berubah,
        "baru": baru,
        "perlu_verifikasi": perlu_verifikasi,
        "hilang": hilang_global,
        "sama": sama,
        "snapshot_baru": snapshot_baru,
    }


def snapshot_setelah_download_aman(
    snapshot_lama: dict,
    snapshot_baru: dict,
    items_berubah: list[dict],
    items_baru: list[dict],
) -> dict:
    """Majukan baseline hanya untuk file yang benar-benar diproses sukses."""
    if isinstance(snapshot_lama, str):
        snapshot_lama = json.loads(snapshot_lama or "{}")
    hasil = {key: list(snapshot_lama.get(key, [])) for key in ENDPOINTS}

    def identity(item):
        return (_nama_file_key(item.get("nama")), str(item.get("tanggal", "")).strip())

    def current_record(jenis: str, item: dict) -> dict:
        expected = (
            _nama_file_key(item.get("nama_baru") or item.get("nama")),
            str(item.get("tanggal_baru") or item.get("tanggal", "")).strip(),
        )
        for record in snapshot_baru.get(jenis, []):
            if identity(record) == expected:
                return dict(record)
        return {
            "nama": item.get("nama_baru") or item.get("nama", ""),
            "tanggal": item.get("tanggal_baru") or item.get("tanggal", ""),
            "url_dl": item.get("url_dl", ""),
        }

    for item in items_berubah:
        jenis = item["jenis"]
        old_id = (_nama_file_key(item.get("nama_lama")), str(item.get("tanggal_lama", "")).strip())
        hasil[jenis] = [f for f in hasil[jenis] if identity(f) != old_id]
        hasil[jenis].append(current_record(jenis, item))
    for item in items_baru:
        jenis = item["jenis"]
        hasil[jenis].append(current_record(jenis, item))

    for jenis, items in hasil.items():
        seen = set()
        deduped = []
        for item in items:
            key = identity(item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        hasil[jenis] = deduped
    return hasil


def download_update_dokumen(
    kode_tender: str,
    folder_paket: str,
    items_berubah: list[dict],
    items_baru: list[dict],
    snapshot_lama: dict,
    progress_cb=None,
    *,
    organize_by_type: bool = False,
) -> dict:
    """
    Download file update dari SPSE via requests (tanpa Playwright).
    - mode lama: items_berubah disimpan _REV{n} di File Baru/ + root,
      sedangkan items_baru disimpan di File Baru/ + root.
    - organize_by_type=True: items_berubah masuk ke kategori/1. File Update
      dan items_baru masuk ke kategori/2. File Baru; file kanonik lama
      tidak ditimpa.
    Return: {"ok": [...], "error": [...]}
    """
    import urllib.parse

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    cookie_str = _get_cookies()
    folder_baru = os.path.join(folder_paket, "File Baru")
    if not organize_by_type:
        os.makedirs(folder_baru, exist_ok=True)
    hasil = {"ok": [], "error": []}

    def _download_file(url_dl: str, dst_path: str) -> str | None:
        hdrs = {**_headers(BASE_URL), "Cookie": cookie_str}
        r = requests.get(url_dl, headers=hdrs, timeout=60, stream=True, allow_redirects=True)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        # Ambil nama file dari Content-Disposition jika ada
        cd = r.headers.get("Content-Disposition", "")
        fname = ""
        if "filename" in cd:
            fname = re.findall(r'filename[^;=\n]*=([^;\n]*)', cd)
            fname = fname[0].strip().strip('"\'') if fname else ""
            fname = urllib.parse.unquote_plus(fname)
        if fname:
            clean = re.sub(r'[<>:"/\\|?*]', "_", fname).strip()
            dst_path = os.path.join(os.path.dirname(dst_path), clean)
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
        return dst_path

    # ── File BERUBAH ─────────────────────────────────────────────
    for item in items_berubah:
        jenis = item["jenis"]
        nama_lama = item["nama_lama"]
        nama_baru_raw = item["nama_baru"]
        url_dl = item["url_dl"]

        ext = os.path.splitext(nama_baru_raw)[1] or os.path.splitext(nama_lama)[1]
        stem_lama = os.path.splitext(nama_lama)[0]
        if organize_by_type:
            folder_update = os.path.join(
                folder_paket,
                DOKUMEN_FOLDER_MAP.get(jenis, DOKUMEN_FOLDER_MAP["lainnya"]),
                "1. File Update",
            )
        else:
            folder_update = folder_baru
        # Arsip REV di folder update yang sesuai.
        n_rev = _hitung_rev(folder_update, nama_lama)
        nama_rev = f"{stem_lama}_REV{n_rev}{ext}"
        dst_arsip = os.path.join(folder_update, nama_rev)

        log(f"⬇️ [{jenis}] {nama_lama} → {nama_baru_raw}")
        try:
            os.makedirs(os.path.dirname(dst_arsip), exist_ok=True)
            # Download ke folder arsip dengan nama REV.
            downloaded = _download_file(url_dl, dst_arsip)
            if downloaded:
                if organize_by_type:
                    log(f"  ✅ File Update: {os.path.relpath(downloaded, folder_paket)}")
                    hasil["ok"].append(downloaded)
                else:
                    # Copy ke root dengan nama baru asli (untuk parse_reviu)
                    nama_root = re.sub(r'[<>:"/\\|?*]', "_", nama_baru_raw).strip()
                    dst_root = os.path.join(folder_paket, nama_root)
                    shutil.copy2(downloaded, dst_root)
                    # Pindahkan file lama ke File Lama/
                    path_lama = os.path.join(folder_paket, nama_lama)
                    if os.path.exists(path_lama):
                        folder_lama_dir = os.path.join(folder_paket, "File Lama")
                        os.makedirs(folder_lama_dir, exist_ok=True)
                        shutil.move(path_lama, os.path.join(folder_lama_dir, nama_lama))
                        log(f"  📦 File lama diarsip: File Lama/{nama_lama}")
                    log(f"  ✅ Root: {nama_root} | Arsip: {nama_rev}")
                    hasil["ok"].append(dst_root)
            else:
                hasil["error"].append(f"{jenis}: download gagal")
        except Exception as e:
            log(f"  ❌ Error: {e}")
            hasil["error"].append(f"{jenis}/{nama_baru_raw}: {e}")

    # ── File BARU MURNI ──────────────────────────────────────────
    for item in items_baru:
        jenis = item["jenis"]
        nama = item["nama"]
        url_dl = item["url_dl"]

        log(f"🆕 [{jenis}] File baru: {nama}")
        try:
            # Download ke folder arsip; mode lama juga menyalin ke root.
            if organize_by_type:
                folder_baru_jenis = os.path.join(
                    folder_paket,
                    DOKUMEN_FOLDER_MAP.get(jenis, DOKUMEN_FOLDER_MAP["lainnya"]),
                    "2. File Baru",
                )
                nama_arsip2 = re.sub(r'[<>:"/\\|?*]', "_", nama).strip()
                dst_arsip2 = os.path.join(folder_baru_jenis, nama_arsip2)
            else:
                dst_arsip2 = os.path.join(folder_baru, nama)
            os.makedirs(os.path.dirname(dst_arsip2), exist_ok=True)
            downloaded = _download_file(url_dl, dst_arsip2)
            if downloaded:
                if organize_by_type:
                    log(f"  ✅ File Baru: {os.path.relpath(downloaded, folder_paket)}")
                    hasil["ok"].append(downloaded)
                else:
                    nama_root2 = re.sub(r'[<>:"/\\|?*]', "_", nama).strip()
                    dst_root2 = os.path.join(folder_paket, nama_root2)
                    shutil.copy2(downloaded, dst_root2)
                    log(f"  ✅ Root: {nama_root2} | Arsip di File Baru/")
                    hasil["ok"].append(dst_root2)
            else:
                hasil["error"].append(f"{jenis}/{nama}: download gagal")
        except Exception as e:
            log(f"  ❌ Error: {e}")
            hasil["error"].append(f"{jenis}/{nama}: {e}")

    return hasil


def _hitung_rev(folder_baru: str, nama_lama: str) -> int:
    """Hitung nomor REV berikutnya untuk file ini di folder arsip."""
    stem = os.path.splitext(nama_lama)[0]
    if not os.path.exists(folder_baru):
        return 1
    existing = [f for f in os.listdir(folder_baru) if f.startswith(stem + "_REV")]
    # Ekstrak nomor REV terbesar
    nums = []
    for f in existing:
        m = re.search(r"_REV(\d+)", f)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1
