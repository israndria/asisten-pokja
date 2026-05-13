"""Engine deteksi & download update dokumen PPK dari SPSE."""

import os
import re
import json
import shutil
import requests
from datetime import datetime
from bs4 import BeautifulSoup

from config import sb, SPSE_BASE_URL

BASE_URL = SPSE_BASE_URL.rstrip("/")

# Endpoint jenis dokumen yang di-track
ENDPOINTS = {
    "spek":    "spek",       # KAK / Spesifikasi Teknis
    "docsskk": "docsskk",   # Rancangan Kontrak (SSUK+SSKK)
    "ldk":     "ldk",        # Persyaratan Kualifikasi
    "lainnya": "lainnya",    # Informasi Lainnya
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


def ambil_snapshot(kode_tender: str) -> dict:
    """
    Fetch semua endpoint → return snapshot dict.
    {jenis: [{"nama":..., "tanggal":..., "url_dl":...}]}
    """
    cookie_str = _get_cookies()
    snapshot = {}
    for key, jenis in ENDPOINTS.items():
        snapshot[key] = fetch_dokumen_endpoint(kode_tender, jenis, cookie_str)
    return snapshot


def simpan_snapshot(kode_tender: str, snapshot: dict):
    """Upsert snapshot ke kolom dokumen_snapshot di draft_paket."""
    sb().table("draft_paket").update(
        {"dokumen_snapshot": json.dumps(snapshot)}
    ).eq("kode_tender", kode_tender).execute()


def cek_update_dokumen(kode_tender: str) -> dict:
    """
    Bandingkan snapshot SPSE terkini vs snapshot tersimpan di Supabase.

    Return:
    {
        "berubah": [{"jenis", "nama_lama", "nama_baru", "tanggal_lama", "tanggal_baru", "url_dl"}],
        "baru":    [{"jenis", "nama", "tanggal", "url_dl"}],
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
    snapshot_baru = {}
    for key, jenis in ENDPOINTS.items():
        snapshot_baru[key] = fetch_dokumen_endpoint(kode_tender, jenis, cookie_str)

    berubah = []
    baru = []
    hilang_global = []
    sama = []

    for key in ENDPOINTS:
        lama_list = snapshot_lama.get(key, [])
        baru_list = snapshot_baru.get(key, [])

        # Track by (nama, tanggal) — URL /dl/ tidak stabil (session token berubah tiap request)
        def _key(f):
            return (f["nama"].strip().lower(), f["tanggal"].strip())

        lama_keys = {_key(f): f for f in lama_list}
        baru_keys  = {_key(f): f for f in baru_list}

        lama_set = set(lama_keys)
        baru_set  = set(baru_keys)

        hilang = lama_set - baru_set   # ada di lama, tidak di baru = diganti/dihapus
        masuk  = baru_set - lama_set   # ada di baru, tidak di lama = baru/pengganti

        ada_perubahan = False

        if hilang and masuk:
            # Replace: cocokkan berdasarkan urutan
            hilang_list = [lama_keys[k] for k in hilang]
            masuk_list  = [baru_keys[k] for k in masuk]
            for i, f_lama in enumerate(hilang_list):
                f_baru = masuk_list[i] if i < len(masuk_list) else None
                if f_baru:
                    berubah.append({
                        "jenis": key,
                        "nama_lama": f_lama["nama"],
                        "tanggal_lama": f_lama["tanggal"],
                        "nama_baru": f_baru["nama"],
                        "tanggal_baru": f_baru["tanggal"],
                        "url_dl": f_baru["url_dl"],
                    })
                    ada_perubahan = True
            for f_hilang in hilang_list[len(masuk_list):]:
                hilang_global.append({"jenis": key, "nama": f_hilang["nama"], "tanggal": f_hilang["tanggal"], "url_dl": f_hilang.get("url_dl", "")})
                ada_perubahan = True
            for f_baru in masuk_list[len(hilang_list):]:
                baru.append({"jenis": key, **f_baru})
                ada_perubahan = True

        elif hilang and not masuk:
            for k in hilang:
                hilang_global.append({"jenis": key, **lama_keys[k]})
            ada_perubahan = True

        elif masuk and not hilang:
            # Tambahan murni (endpoint sebelumnya kosong atau bertambah)
            for k in masuk:
                baru.append({"jenis": key, **baru_keys[k]})
                ada_perubahan = True

        if not ada_perubahan:
            sama.append(key)

    return {
        "berubah": berubah,
        "baru": baru,
        "hilang": hilang_global,
        "sama": sama,
        "snapshot_baru": snapshot_baru,
    }


def download_update_dokumen(
    kode_tender: str,
    folder_paket: str,
    items_berubah: list[dict],
    items_baru: list[dict],
    snapshot_lama: dict,
    progress_cb=None,
) -> dict:
    """
    Download file update dari SPSE via requests (tanpa Playwright).
    - items_berubah: simpan _REV{n} di File Baru/ + root, hapus file lama di root
    - items_baru: simpan di File Baru/ saja
    Return: {"ok": [...], "error": [...]}
    """
    import urllib.parse

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    cookie_str = _get_cookies()
    folder_baru = os.path.join(folder_paket, "File Baru")
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

        # Arsip REV di File Baru/
        n_rev = _hitung_rev(folder_baru, nama_lama)
        ext = os.path.splitext(nama_baru_raw)[1] or os.path.splitext(nama_lama)[1]
        stem_lama = os.path.splitext(nama_lama)[0]
        nama_rev = f"{stem_lama}_REV{n_rev}{ext}"
        dst_arsip = os.path.join(folder_baru, nama_rev)

        log(f"⬇️ [{jenis}] {nama_lama} → {nama_baru_raw}")
        try:
            # Download ke File Baru/ dengan nama REV (arsip)
            downloaded = _download_file(url_dl, dst_arsip)
            if downloaded:
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
            # Download ke File Baru/ sekaligus copy ke root
            dst_arsip2 = os.path.join(folder_baru, nama)
            downloaded = _download_file(url_dl, dst_arsip2)
            if downloaded:
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
    """Hitung nomor REV berikutnya untuk file ini di folder File Baru/."""
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
