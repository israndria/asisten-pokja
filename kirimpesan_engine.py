"""
Kirim Pesan / Undangan Engine — via pure requests.

Endpoint GET : /lelang/[ID]/kirimpesan
Endpoint POST: /lelang/[ID]/submitkirimpesan

Payload:
  authenticityToken  : dari hidden input
  waktu              : format "DD-MM-YYYY HH:mm" (waktu mulai) — pakai tanda -
  sampai             : format "DD-MM-YYYY HH:mm" (waktu selesai) — pakai tanda -
  tempat             : string (lokasi undangan)
  is_online          : "false" (Offline) | "true" (Online)
  link_pembuktian    : URL (wajib jika Online, kosong jika Offline)
  dibawa             : string (dokumen yang harus dibawa)
  hadir              : string (yang harus hadir)
  path               : "" (kosong, opsional untuk lampiran)
  fileId             : "" (kosong, opsional untuk lampiran)

Response sukses: HTTP 302 redirect kembali ke /kirimpesan
"""

import os
import json
import time
import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser

# ── Cache file — persist lintas browser refresh ───────────────────────────────
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".paket_cache.json")
_CACHE_TTL = 3600  # detik — 1 jam sebelum dianggap stale


def load_paket_cache() -> dict:
    """Baca cache paket dari file. Return None jika tidak ada / expired."""
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("_ts", 0) > _CACHE_TTL:
            return None  # expired
        return data
    except Exception:
        return None


def save_paket_cache(draft: dict, aktif: dict):
    """Simpan hasil fetch ke cache file."""
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"draft": draft, "aktif": aktif, "_ts": time.time()}, f, ensure_ascii=False)
    except Exception:
        pass


def clear_paket_cache():
    """Hapus cache paksa — dipakai saat user klik Refresh."""
    try:
        if os.path.exists(_CACHE_FILE):
            os.remove(_CACHE_FILE)
    except Exception:
        pass

# ── Default isi undangan (sesuai kebiasaan pokja) ────────────────────────────
DEFAULT_TEMPAT = (
    "Ruang Aula Rapat Lantai 2 Kantor UKPBJ Kabupaten Tapin, "
    "Jl. Datu Suban RT. 01, Kelurahan Rangda Malingkung, "
    "Kecamatan Tapin Utara, Rantau, Kabupaten Tapin. Kode Pos : 71111"
)
DEFAULT_DIBAWA = (
    "Dokumen Persiapan Pengadaan yang tidak terbatas pada :\n"
    "1. Spesifikasi Teknis 2. Dokumen HPS. 3. Rancangan Kontrak. 4. Dokumen Anggaran Belanja"
)
DEFAULT_HADIR = (
    "Pejabat Pembuat Komitmen (PPK), Tim Teknis PPK, "
    "dan Konsultan Perancang/Konsultan Perencana"
)

# ── Konstanta kolom dt/paketpanitia ──────────────────────────────────────────
_COL_KODE = 0       # ID row internal tabel (bukan kode tender resmi)
_COL_NAMA = 1       # nama paket
_COL_STATUS = 2     # status: "Draft" / "Tender Sudah Selesai" / dll
_COL_ID_LELANG = 5  # Kode Tender resmi SPSE (untuk /lelang/, /peserta/, /dokumen/)
_COL_POKJA = 21     # nama pokja


def _get_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}lelang/{paket_id}/kirimpesan"


def _submit_url(paket_id: str) -> str:
    return f"{SPSE_BASE_URL}lelang/{paket_id}/submitkirimpesan"


def scrap_token(paket_id: str, cookie_str: str) -> dict:
    """GET halaman kirimpesan, ambil authenticityToken + info penerima."""
    resp = requests.get(
        _get_url(paket_id),
        headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
        timeout=15,
        allow_redirects=True,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GET kirimpesan gagal: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    token_el = soup.find("input", {"name": "authenticityToken"})
    if not token_el:
        raise RuntimeError("authenticityToken tidak ditemukan di halaman kirimpesan")

    # Ambil nama penerima dari isi teks halaman
    penerima = ""
    inner = soup.find(class_="inner-form")
    if inner:
        p_el = inner.find("p")
        if p_el:
            lines = [ln.strip() for ln in p_el.get_text("\n").split("\n") if ln.strip()]
            # Baris ke-2 biasanya nama penerima (setelah "Kepada Yth.")
            if len(lines) >= 2:
                penerima = lines[1]

    # Ambil nama tender dari halaman
    nama_tender = ""
    for b in soup.find_all("b"):
        txt = b.get_text(strip=True)
        if len(txt) > 20 and txt != paket_id:
            nama_tender = txt
            break

    return {
        "authenticityToken": token_el.get("value", ""),
        "penerima": penerima,
        "nama_tender": nama_tender,
    }


def upload_lampiran(paket_id: str, file_bytes: bytes, file_name: str, cookie_str: str) -> dict:
    """
    Upload lampiran PDF ke GCS via SPSE signed URL.

    Flow:
      1. POST /lelang/[ID]/getSignedUrl  → dapat signedUrl (GCS) + fileId + path
      2. PUT signedUrl                   → upload file ke GCS
      3. POST /uploadCheckStatus         → tunggu status UPLOAD_SUCCESS

    Return:
        {"sukses": bool, "path": str, "fileId": str, "pesan": str}
    """
    base = f"{SPSE_BASE_URL}lelang/{paket_id}"
    headers = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": _get_url(paket_id),
    }

    # Step 1: getSignedUrl
    try:
        r1 = requests.post(
            f"{base}/getSignedUrl",
            data={
                "input[uploadSignedUrlReq][0][contentType]": "application/pdf",
                "input[uploadSignedUrlReq][0][identifier]": "",
                "input[uploadSignedUrlReq][0][fileName]": file_name,
                "input[uploadSignedUrlReq][0][isPublic]": "false",
                "isArchieve": "true",
            },
            headers=headers,
            timeout=15,
        )
        r1.raise_for_status()
        data = r1.json()
        file_id = data["result"]["data"]["fileId"]
        signed_url = data["result"]["data"]["signedUrl"]
        path = data["path"]
    except Exception as e:
        return {"sukses": False, "path": "", "fileId": "", "pesan": f"getSignedUrl gagal: {e}"}

    # Step 2: PUT ke GCS
    try:
        r2 = requests.put(
            signed_url,
            data=file_bytes,
            headers={"Content-Type": "multipart/formdata; charset=UTF-8"},
            timeout=60,
        )
        r2.raise_for_status()
    except Exception as e:
        return {"sukses": False, "path": "", "fileId": "", "pesan": f"Upload GCS gagal: {e}"}

    # Step 3: uploadCheckStatus (polling max 5x)
    import time as _time
    for _ in range(5):
        try:
            r3 = requests.post(
                f"{SPSE_BASE_URL}uploadCheckStatus",
                data={"input": file_id},
                headers=headers,
                timeout=10,
            )
            status_data = r3.json()
            if status_data.get("errors"):
                return {"sukses": False, "path": "", "fileId": "", "pesan": "Upload check error"}
            st = (status_data.get("data") or {}).get("status", "UPLOAD_SUCCESS")
            if st == "UPLOAD_SUCCESS" or status_data.get("data") is None:
                break
            if st == "UPLOAD_FAILED":
                return {"sukses": False, "path": "", "fileId": "", "pesan": "Upload gagal di server"}
        except Exception:
            pass
        _time.sleep(2)

    return {"sukses": True, "path": path, "fileId": file_id, "pesan": "Upload berhasil"}


def kirim_undangan(
    paket_id: str,
    waktu: str,
    sampai: str,
    tempat: str,
    dibawa: str,
    hadir: str,
    is_online: bool = False,
    link_pembuktian: str = "",
    lampiran_bytes: bytes | None = None,
    lampiran_nama: str = "",
) -> dict:
    """
    Kirim undangan/pesan ke PPK via pure requests.

    Args:
        paket_id       : ID paket tender
        waktu          : waktu mulai format "DD-MM-YYYY HH:mm"
        sampai         : waktu selesai format "DD-MM-YYYY HH:mm"
        tempat         : lokasi undangan
        dibawa         : dokumen/hal yang harus dibawa
        hadir          : yang harus hadir
        is_online      : True jika Online, False jika Offline
        link_pembuktian: URL meeting (wajib jika is_online=True)
        lampiran_bytes : bytes PDF lampiran (opsional)
        lampiran_nama  : nama file lampiran (opsional)

    Return:
        {"sukses": bool, "status_code": int, "pesan": str, "penerima": str}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung atau cookie kosong"}

    try:
        scraped = scrap_token(paket_id, cookie_str)
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e)}

    # Upload lampiran jika ada
    lamp_path = ""
    lamp_file_id = ""
    if lampiran_bytes:
        up = upload_lampiran(paket_id, lampiran_bytes, lampiran_nama or "undangan.pdf", cookie_str)
        if not up["sukses"]:
            return {"sukses": False, "pesan": f"Upload lampiran gagal: {up['pesan']}"}
        lamp_path = up["path"]
        lamp_file_id = up["fileId"]

    payload = {
        "authenticityToken": scraped["authenticityToken"],
        "waktu": waktu,
        "sampai": sampai,
        "tempat": tempat,
        "is_online": "true" if is_online else "false",
        "link_pembuktian": link_pembuktian if is_online else "",
        "dibawa": dibawa,
        "hadir": hadir,
        "path": lamp_path,
        "fileId": lamp_file_id,
    }

    resp = requests.post(
        _submit_url(paket_id),
        data=payload,
        headers={
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": _get_url(paket_id),
        },
        timeout=15,
        allow_redirects=True,  # ikuti redirect — sukses = redirect ke /edit
    )

    # Sukses: redirect ke /edit (bukan kembali ke /kirimpesan dengan error)
    # Gagal: redirect kembali ke /kirimpesan dengan flash message "Gagal..."
    sukses = resp.status_code == 200 and "edit" in resp.url
    pesan_server = ""
    if not sukses:
        from bs4 import BeautifulSoup as _BS
        soup = _BS(resp.text, "html.parser")
        for el in soup.find_all("div", class_=lambda c: c and "alert" in str(c)):
            txt = el.get_text(strip=True)
            if txt and "JavaScript" not in txt and len(txt) > 5:
                pesan_server = txt[:200]
                break

    return {
        "sukses": sukses,
        "status_code": resp.status_code,
        "pesan": "Undangan berhasil dikirim" if sukses else (pesan_server or f"Gagal: HTTP {resp.status_code}"),
        "penerima": scraped.get("penerima", ""),
        "nama_tender": scraped.get("nama_tender", ""),
    }


def preview_undangan(paket_id: str) -> dict:
    """Ambil info penerima dan nama tender tanpa submit."""
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung"}
    try:
        scraped = scrap_token(paket_id, cookie_str)
        return {"sukses": True, **scraped}
    except RuntimeError as e:
        return {"sukses": False, "pesan": str(e)}


def fetch_paket_draft() -> dict:
    """
    Ambil daftar paket berstatus Draft dari SPSE via dt/paketpanitia.
    Return: {"sukses": bool, "paket": [{"kode", "nama", "id_lelang", "pokja"}], "pesan": str}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung", "paket": []}

    url = f"{SPSE_BASE_URL}dt/paketpanitia"
    params = {
        "draw": 1,
        "start": 0,
        "length": 500,
        "order[0][column]": 3,
        "order[0][dir]": "desc",
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{SPSE_BASE_URL}paket",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return {"sukses": False, "pesan": f"HTTP {resp.status_code}", "paket": []}

        data = resp.json()
        rows = data.get("data", [])

        from datetime import datetime as _dt2
        tahun = str(_dt2.now().year)
        paket = []
        for r in rows:
            status = r[_COL_STATUS] if len(r) > _COL_STATUS else ""
            if "draft" not in status.lower():
                continue
            tgl = str(r[3]) if len(r) > 3 else ""
            if tahun not in tgl:
                continue
            paket.append({
                "kode": str(r[_COL_ID_LELANG]),
                "nama": str(r[_COL_NAMA]),
                "id_lelang": str(r[_COL_ID_LELANG]),
                "pokja": str(r[_COL_POKJA]) if len(r) > _COL_POKJA else "",
            })

        return {"sukses": True, "paket": paket, "pesan": f"{len(paket)} paket Draft ditemukan"}
    except Exception as e:
        return {"sukses": False, "pesan": str(e), "paket": []}


def fetch_paket_semua() -> dict:
    """
    Ambil SEMUA paket dari SPSE (termasuk yang sudah selesai).
    Return: {"sukses": bool, "paket": [{...}], "pesan": str}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung", "paket": []}

    url = f"{SPSE_BASE_URL}dt/paketpanitia"
    params = {
        "draw": 1,
        "start": 0,
        "length": 500,
        "order[0][column]": 3,
        "order[0][dir]": "desc",
        "search[value]": "",
        "search[regex]": "false",
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{SPSE_BASE_URL}paket",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return {"sukses": False, "pesan": f"HTTP {resp.status_code}", "paket": []}

        data = resp.json()
        rows = data.get("data", [])

        paket = []
        seen = set()
        for r in rows:
            kode = str(r[_COL_KODE])
            if kode in seen:
                continue
            seen.add(kode)
            status = str(r[_COL_STATUS]) if len(r) > _COL_STATUS else ""
            paket.append({
                "kode": str(r[_COL_ID_LELANG]),
                "nama": str(r[_COL_NAMA]),
                "id_lelang": str(r[_COL_ID_LELANG]),
                "pokja": str(r[_COL_POKJA]) if len(r) > _COL_POKJA else "",
                "status": status,
            })

        return {"sukses": True, "paket": paket, "pesan": f"{len(paket)} paket ditemukan (semua status)"}
    except Exception as e:
        return {"sukses": False, "pesan": str(e), "paket": []}


def fetch_tahap_tender(paket_list: list[dict]) -> dict:
    """
    Scrape tahap aktif Tender dari badge di /lelang/{kode} per paket.
    Tiru pola _fetch_tahap_spse di pl_engine — return {id_lelang: tahap_str}.
    Pakai ThreadPoolExecutor supaya N paket tidak lambat.
    Non-fatal: kode yang gagal di-skip (return empty string).
    """
    import re as _re
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str or not paket_list:
        return {}

    base = SPSE_BASE_URL.rstrip("/")
    hdr = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0", "Referer": f"{base}/paket"}

    _TAHAP_PAT = _re.compile(
        r'Tahap Tender Saat Ini.*?<td[^>]*>\s*<a[^>]*>([^<]+)',
        _re.IGNORECASE | _re.DOTALL,
    )
    _BADGE_PAT = _re.compile(
        r'badge[^>]*>([^<]*(?:Hasil Evaluasi|Masa Sanggah|Surat Penunjukan|'
        r'Penunjukan Penyedia|Penandatanganan Kontrak|Penandatanganan|Klarifikasi|Negosiasi|Selesai)[^<]*)',
        _re.IGNORECASE,
    )

    def _scrape_one(id_lelang: str) -> tuple[str, str]:
        try:
            r = requests.get(f"{base}/lelang/{id_lelang}", headers=hdr, timeout=10)
            if r.status_code != 200:
                return id_lelang, ""
            # Prioritas: ambil dari "Tahap Tender Saat Ini" (lebih akurat)
            m = _TAHAP_PAT.search(r.text)
            if m:
                return id_lelang, m.group(1).strip()
            # Fallback: badge
            m2 = _BADGE_PAT.search(r.text)
            return id_lelang, m2.group(1).strip() if m2 else ""
        except Exception:
            return id_lelang, ""

    result = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_scrape_one, p["id_lelang"]): p["id_lelang"] for p in paket_list}
        for fut in as_completed(futs):
            id_lelang, tahap = fut.result()
            if tahap:
                result[id_lelang] = tahap
    return result


def fetch_paket_aktif() -> dict:
    """
    Ambil daftar paket yang sedang berjalan (bukan Draft, bukan Selesai) dari dt/paketpanitia.
    Return: {"sukses": bool, "paket": [{"kode", "nama", "id_lelang", "pokja", "status"}], "pesan": str}
    """
    cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        return {"sukses": False, "pesan": "Browser belum terhubung", "paket": []}

    url = f"{SPSE_BASE_URL}dt/paketpanitia"
    params = {
        "draw": 1,
        "start": 0,
        "length": 500,
        "order[0][column]": 3,
        "order[0][dir]": "desc",
        "search[value]": "",
        "search[regex]": "false",
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{SPSE_BASE_URL}paket",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return {"sukses": False, "pesan": f"HTTP {resp.status_code}", "paket": []}

        data = resp.json()
        rows = data.get("data", [])

        # Skip hanya paket yang benar-benar tidak aktif sama sekali
        # Masa Sanggah / Penunjukan / Penandatanganan = masih relevan, filter di UI saja
        _SKIP_STATUS = ("draft", "tender sudah selesai")
        paket = []
        for r in rows:
            status = str(r[_COL_STATUS]) if len(r) > _COL_STATUS else ""
            if any(s in status.lower() for s in _SKIP_STATUS):
                continue
            paket.append({
                "kode": str(r[_COL_ID_LELANG]),
                "nama": str(r[_COL_NAMA]),
                "id_lelang": str(r[_COL_ID_LELANG]),
                "pokja": str(r[_COL_POKJA]) if len(r) > _COL_POKJA else "",
                "status": status,
            })

        return {"sukses": True, "paket": paket, "pesan": f"{len(paket)} paket aktif ditemukan"}
    except Exception as e:
        return {"sukses": False, "pesan": str(e), "paket": []}


def enrich_paket_supabase(paket_list: list[dict], tahap_map: dict | None = None) -> list[dict]:
    """
    Enrich daftar paket dengan kode_unik + kode_pokja dari Supabase draft_paket.
    Sekaligus upsert status_tahap (dari tahap_map scrape /lelang/{kode}) ke Supabase
    agar filter UI bisa berjalan independent dari session state.
    tahap_map: {id_lelang: tahap_str} — dari fetch_tahap_tender(). None = skip upsert.
    Query bulk 1x — match by kode_tender (= id_lelang).
    Return: paket_list yang sama, tiap dict ditambah field kode_unik + kode_pokja.
    """
    if not paket_list:
        return paket_list
    try:
        from config import sb as _sb
        kode_list = [p["id_lelang"] for p in paket_list]
        rows = _sb().table("draft_paket").select("kode_tender,kode_unik,kode_pokja").in_("kode_tender", kode_list).execute().data or []
        lookup = {r["kode_tender"]: r for r in rows}
        for p in paket_list:
            sb_row = lookup.get(p["id_lelang"], {})
            p["kode_unik"] = sb_row.get("kode_unik") or ""
            p["kode_pokja"] = sb_row.get("kode_pokja") or ""
            # Upsert status_tahap ke Supabase — hanya kalau paket ada di DB dan tahap_map tersedia
            if tahap_map is not None and p["id_lelang"] in lookup:
                tahap = tahap_map.get(p["id_lelang"]) or p.get("status") or ""
                if tahap:
                    try:
                        _sb().table("draft_paket").update(
                            {"status_tahap": tahap}
                        ).eq("kode_tender", p["id_lelang"]).execute()
                    except Exception:
                        pass
    except Exception:
        pass
    return paket_list


def kirim_undangan_batch(
    paket_list: list[dict],
    waktu: str,
    sampai: str,
    tempat: str,
    dibawa: str,
    hadir: str,
    is_online: bool = False,
    link_pembuktian: str = "",
) -> list[dict]:
    """
    Kirim undangan ke banyak paket sekaligus.
    paket_list: [{"id_lelang": str, "nama": str, ...}]
    Return: list hasil per paket [{"kode", "nama", "sukses", "pesan"}]
    """
    hasil = []
    for paket in paket_list:
        res = kirim_undangan(
            paket_id=paket["id_lelang"],
            waktu=waktu,
            sampai=sampai,
            tempat=tempat,
            dibawa=dibawa,
            hadir=hadir,
            is_online=is_online,
            link_pembuktian=link_pembuktian,
        )
        hasil.append({
            "kode": paket.get("kode", paket["id_lelang"]),
            "nama": paket.get("nama", ""),
            "sukses": res["sukses"],
            "pesan": res["pesan"],
            "status_code": res.get("status_code"),
        })
    return hasil
