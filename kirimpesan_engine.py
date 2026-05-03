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

import requests
from bs4 import BeautifulSoup
from config import SPSE_BASE_URL
import spse_browser

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
_COL_TANGGAL = 20   # tanggal format "YYYY-MM-DD HH:MM:SS" — untuk filter tahun
_COL_POKJA = 21     # nama pokja

_FILTER_TAHUN = "2025"  # hanya tampilkan paket tahun ini


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
        "length": 200,
        "order[0][column]": 3,
        "order[0][dir]": "desc",
        "search[value]": "Draft",
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
        for r in rows:
            status = r[_COL_STATUS] if len(r) > _COL_STATUS else ""
            if "draft" not in status.lower():
                continue
            tgl = str(r[_COL_TANGGAL]) if len(r) > _COL_TANGGAL else ""
            if not tgl.startswith(_FILTER_TAHUN):
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
            tgl = str(r[_COL_TANGGAL]) if len(r) > _COL_TANGGAL else ""
            if not tgl.startswith(_FILTER_TAHUN):
                continue
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
        "length": 200,
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

        _SKIP_STATUS = ("draft", "tender sudah selesai", "selesai")
        paket = []
        for r in rows:
            status = str(r[_COL_STATUS]) if len(r) > _COL_STATUS else ""
            if any(s in status.lower() for s in _SKIP_STATUS):
                continue
            tgl = str(r[_COL_TANGGAL]) if len(r) > _COL_TANGGAL else ""
            if not tgl.startswith(_FILTER_TAHUN):
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
