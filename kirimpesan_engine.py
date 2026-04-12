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
_COL_KODE = 0       # kode paket / ID lelang
_COL_NAMA = 1       # nama paket
_COL_STATUS = 2     # status: "Draft" / "Tender Sudah Selesai" / dll
_COL_ID_LELANG = 5  # ID lelang (untuk endpoint /lelang/[ID]/...)
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


def kirim_undangan(
    paket_id: str,
    waktu: str,
    sampai: str,
    tempat: str,
    dibawa: str,
    hadir: str,
    is_online: bool = False,
    link_pembuktian: str = "",
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

    payload = {
        "authenticityToken": scraped["authenticityToken"],
        "waktu": waktu,
        "sampai": sampai,
        "tempat": tempat,
        "is_online": "true" if is_online else "false",
        "link_pembuktian": link_pembuktian if is_online else "",
        "dibawa": dibawa,
        "hadir": hadir,
        "path": "",
        "fileId": "",
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
            paket.append({
                "kode": str(r[_COL_KODE]),
                "nama": str(r[_COL_NAMA]),
                "id_lelang": str(r[_COL_ID_LELANG]),
                "pokja": str(r[_COL_POKJA]) if len(r) > _COL_POKJA else "",
            })

        return {"sukses": True, "paket": paket, "pesan": f"{len(paket)} paket Draft ditemukan"}
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
