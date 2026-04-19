"""
Tab 0 — Persiapan Draft Paket
Scrape inbox SPSE /admin/pegawai/inbox, parse HTML + PDF in-memory,
upsert ke Supabase tabel draft_paket.
"""

import io
import re
import requests
import pdfplumber
from bs4 import BeautifulSoup
from datetime import datetime, timezone

import spse_browser

BASE_URL = "https://spse.inaproc.id/tapinkab"
SUBJEK_DELEGASI = "(LPSE) Pengumuman Delegasi Pokja"


def _headers(referer: str = "") -> dict:
    cookie = spse_browser.get_spse_cookies()
    return {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer or f"{BASE_URL}/admin/pegawai/inbox",
    }


def _get(url: str, referer: str = "", timeout: int = 20) -> requests.Response:
    return requests.get(url, headers=_headers(referer), timeout=timeout)


# ── Scrape list inbox ──────────────────────────────────────────────────────────

def _ambil_authenticity_token() -> str:
    """Ambil authenticityToken dari halaman inbox untuk DataTables POST."""
    r = _get(f"{BASE_URL}/admin/pegawai/inbox")
    r.raise_for_status()
    m = re.search(r"authenticityToken\s*=\s*['\"]([a-f0-9]+)['\"]", r.text)
    return m.group(1) if m else ""


def ambil_list_inbox() -> list[dict]:
    """
    Fetch semua pesan inbox via DataTables AJAX endpoint (POST).
    Return list of dict: {id_pesan, tanggal, kode_paket, metode, subjek, link_detail}
    """
    token = _ambil_authenticity_token()
    if not token:
        raise RuntimeError("authenticityToken tidak ditemukan — pastikan sudah login")

    cookie = spse_browser.get_spse_cookies()
    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"{BASE_URL}/admin/pegawai/inbox",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # DataTables POST — ambil semua data (length=-1 atau besar)
    payload = {
        "draw": "1",
        "start": "0",
        "length": "1000",
        "authenticityToken": token,
    }

    r = requests.post(
        f"{BASE_URL}/dt/inbox-nonpenyedia",
        headers=headers,
        data=payload,
        timeout=30,
    )
    r.raise_for_status()

    try:
        json_data = r.json()
    except Exception:
        raise RuntimeError(f"Response bukan JSON: {r.text[:200]}")

    rows = json_data.get("data", [])
    if not rows and json_data.get("recordsTotal", 0) == 0:
        return []

    # Struktur kolom: [0]=id_pesan, [1]=tanggal, [2]=subjek, [3]=id_paket, [4]=metode, [5]=nama_paket
    hasil = []
    for row in rows:
        if len(row) < 3:
            continue
        id_pesan = str(row[0])
        tanggal  = str(row[1])
        subjek   = re.sub(r"<[^>]+>", "", str(row[2]))
        metode   = str(row[4]) if len(row) > 4 else ""
        nama_raw = str(row[5]) if len(row) > 5 else ""
        hasil.append({
            "id_pesan": id_pesan,
            "tanggal": tanggal,
            "kode_paket_raw": nama_raw,
            "metode": metode,
            "subjek": subjek,
            "link_detail": f"/tapinkab/non-rekanan/inbox/{id_pesan}",
        })
    return hasil


def filter_delegasi(list_inbox: list[dict]) -> list[dict]:
    """Filter hanya pesan Pengumuman Delegasi Pokja (strip HTML tags dulu)."""
    def _strip(s):
        return re.sub(r"<[^>]+>", "", s)
    return [p for p in list_inbox if SUBJEK_DELEGASI in _strip(p["subjek"])]


# ── Parse detail pesan (HTML) ──────────────────────────────────────────────────

def _extract_td_value(tabel, label: str) -> str:
    """Cari baris tabel dengan label tertentu, kembalikan nilai kolom terakhir."""
    for row in tabel.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and label.lower() in tds[0].text.strip().lower():
            return tds[-1].text.strip()
    return ""


def parse_detail_pesan(id_pesan: str) -> dict:
    """
    GET /non-rekanan/inbox/{id_pesan}, extract field dari tabel class="list-content".
    """
    url = f"{BASE_URL}/non-rekanan/inbox/{id_pesan}"
    r = _get(url, referer=f"{BASE_URL}/admin/pegawai/inbox")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Tabel data ada di class="list-content"
    tabel = soup.find("table", class_="list-content")
    if not tabel:
        # Fallback: tabel pertama yang punya baris "Kode Tender"
        for t in soup.find_all("table"):
            if "Kode Tender" in t.get_text():
                tabel = t
                break
    if not tabel:
        return {"kode_tender": "", "link_pdf": "", "_kode_tender_for_anggota": ""}

    # Ambil link PDF
    pdf_tag = soup.find("a", href=lambda h: h and "/dl/" in h)
    link_pdf = ""
    if pdf_tag:
        href = pdf_tag.get("href", "")
        href = re.sub(r"^/(spse4|eproc4)/", "/tapinkab/", href)
        link_pdf = f"https://spse.inaproc.id{href}" if href.startswith("/") else href

    kode_tender = _extract_td_value(tabel, "Kode Tender")

    return {
        "mak": _extract_td_value(tabel, "MAK"),
        "kode_tender": kode_tender,
        "nama_tender": _extract_td_value(tabel, "Nama Tender"),
        "kode_rup": _extract_td_value(tabel, "Kode RUP"),
        "nilai_pagu": _extract_td_value(tabel, "Nilai Pagu"),
        "nilai_hps": _extract_td_value(tabel, "Nilai HPS"),
        "link_pdf": link_pdf,
        "_kode_tender_for_anggota": kode_tender,
    }


# ── Scrape anggota pokja dari halaman /lelang/{kode_tender}/edit ───────────────

def parse_anggota_pokja(kode_tender: str) -> dict:
    """
    GET /lelang/{kode_tender}/edit, parse tabel "Anggota Pokja Pemilihan".
    Return: {anggota_1, anggota_2, anggota_3}
    """
    hasil = {"anggota_1": "", "anggota_2": "", "anggota_3": ""}
    if not kode_tender:
        return hasil

    url = f"{BASE_URL}/lelang/{kode_tender}/edit"
    try:
        r = _get(url, referer=f"{BASE_URL}/admin/pegawai/inbox")
        if r.status_code != 200:
            return hasil
    except Exception:
        return hasil

    soup = BeautifulSoup(r.text, "html.parser")

    # Cari tabel yang mengandung "Anggota Pokja Pemilihan"
    anggota = []
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if "Anggota Pokja" in txt or "Status Persetujuan" in txt:
            for row in tbl.find_all("tr"):
                tds = row.find_all("td")
                if not tds:
                    continue
                nama = tds[0].text.strip()
                # Filter: bukan header, ada isi, bukan tanggal saja
                if nama and len(nama) > 3 and not nama.isdigit():
                    # Skip baris header
                    if nama in ("Status", "Tanggal", "Alasan Tidak Setuju", "Anggota Pokja Pemilihan"):
                        continue
                    anggota.append(nama)

    for idx, nama in enumerate(anggota[:3]):
        hasil[f"anggota_{idx+1}"] = nama

    return hasil


# ── Parse PDF in-memory ────────────────────────────────────────────────────────

def _re_extract(pattern: str, text: str, flags=re.IGNORECASE) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""


def parse_pdf_inmemory(pdf_url: str) -> dict:
    """
    Download PDF ke memory (tidak disimpan ke disk), extract field via pdfplumber.
    Halaman 1: Lembar Disposisi  → kode_pokja, nomor_pp, nomor_surat_dinas, nama_dinas
    Halaman 2: Surat PPK→UKPBJ  → nama_ppk, jangka_waktu, sumber_anggaran
    """
    hasil = {
        "kode_pokja": "",
        "nomor_pp": "",
        "nomor_surat_dinas": "",
        "nama_dinas": "",
        "nama_ppk": "",
        "jangka_waktu": "",
        "sumber_anggaran": "",
    }

    try:
        r = requests.get(pdf_url, headers=_headers(pdf_url), timeout=30)
        r.raise_for_status()
    except Exception as e:
        return {**hasil, "_error_pdf": str(e)}

    try:
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            # ── Halaman 1: Lembar Disposisi ──
            if len(pdf.pages) >= 1:
                txt1 = pdf.pages[0].extract_text() or ""

                # Nomor PP: "Nomor : 000.3.3/486/PP-335/BPBJ/2024"
                hasil["nomor_pp"] = _re_extract(
                    r"Nomor\s*:\s*([\d\./\-A-Za-z]+(?:/BPBJ/\d{4}))", txt1
                )

                # Kode Pokja: "Diteruskan Kepada Pokja Pemilihan : 335"
                hasil["kode_pokja"] = _re_extract(
                    r"Pokja Pemilihan\s*:\s*(\d+)", txt1
                )

                # Nomor Surat Dinas: "Nomor Surat : 72-L4/KAB-TAPIN/DPUPR-BM/IX/2024"
                hasil["nomor_surat_dinas"] = _re_extract(
                    r"Nomor Surat\s*:\s*([^\n]+)", txt1
                )

                # Nama Dinas: "Surat Dari : DPUPR" atau "Surat Dari DINAS PEKERJAAN UMUM..."
                nama_dinas = _re_extract(r"Surat Dari\s*[:\s]+([^\n]+)", txt1)
                # Ambil singkatan di akhir jika ada, atau 50 char pertama
                if "DINAS" in nama_dinas.upper() or len(nama_dinas) > 30:
                    hasil["nama_dinas"] = nama_dinas[:60].strip()
                else:
                    hasil["nama_dinas"] = nama_dinas

            # ── Halaman 2: Surat PPK ke UKPBJ ──
            if len(pdf.pages) >= 2:
                txt2 = pdf.pages[1].extract_text() or ""

                hasil["nama_ppk"] = _re_extract(
                    r"Nama PPK\s*:\s*([^\n]+)", txt2
                )
                hasil["jangka_waktu"] = _re_extract(
                    r"Jangka Waktu\s*:\s*([^\n]+)", txt2
                )
                hasil["sumber_anggaran"] = _re_extract(
                    r"Sumber Anggaran\s*:\s*([^\n]+)", txt2
                )
    except Exception as e:
        hasil["_error_pdf"] = str(e)

    return hasil


# ── Upsert ke Supabase ─────────────────────────────────────────────────────────

def _sb():
    import os
    from supabase import create_client
    from dotenv import load_dotenv
    import pathlib
    env_path = pathlib.Path(__file__).parent.parent / "V19_Scheduler/WPy64-313110/secret_supabase.env"
    if not env_path.exists():
        # Fallback: cari di folder yang sama
        env_path = pathlib.Path(__file__).parent / "secret_supabase.env"
    load_dotenv(env_path)
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def upsert_draft_paket(data: dict) -> dict:
    """Upsert satu record ke tabel draft_paket. Return response Supabase."""
    sb = _sb()
    data["diambil_pada"] = datetime.now(timezone.utc).isoformat()
    # Hapus key internal
    data.pop("_error_pdf", None)
    r = sb.table("draft_paket").upsert(data).execute()
    return r


# ── Fungsi utama (dipanggil dari app.py Tab 0) ─────────────────────────────────

def serap_inbox(progress_cb=None) -> dict:
    """
    Serap seluruh pesan Delegasi Pokja dari inbox, simpan ke Supabase.

    progress_cb(pct: float, msg: str) — callback opsional untuk Streamlit progress bar.

    Return: {"baru": int, "diperbarui": int, "error": list, "data": list}
    """
    def log(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    log(0.05, "Mengambil list inbox...")
    semua = ambil_list_inbox()
    delegasi = filter_delegasi(semua)

    if not delegasi:
        log(1.0, "Tidak ada pesan Delegasi Pokja baru.")
        return {"baru": 0, "diperbarui": 0, "error": [], "data": []}

    # Cek existing di Supabase
    sb = _sb()
    existing_raw = sb.table("draft_paket").select("kode_tender").execute()
    existing_ids = {r["kode_tender"] for r in (existing_raw.data or [])}

    hasil_data = []
    errors = []
    baru = 0
    diperbarui = 0
    total = len(delegasi)

    for i, pesan in enumerate(delegasi):
        pct = 0.1 + (i / total) * 0.85
        log(pct, f"[{i+1}/{total}] Memproses: {pesan['subjek']} — {pesan['id_pesan']}")

        try:
            # 1. Parse HTML detail pesan
            detail_html = parse_detail_pesan(pesan["id_pesan"])

            if not detail_html.get("kode_tender"):
                errors.append(f"ID {pesan['id_pesan']}: kode_tender tidak ditemukan")
                continue

            # 2. Parse PDF in-memory (jika ada link)
            detail_pdf = {}
            if detail_html.get("link_pdf"):
                log(pct, f"[{i+1}/{total}] Download & parse PDF...")
                detail_pdf = parse_pdf_inmemory(detail_html["link_pdf"])

            # 3. Scrape anggota pokja dari halaman /edit
            kode_tender = detail_html.get("kode_tender", "")
            log(pct, f"[{i+1}/{total}] Mengambil anggota pokja...")
            detail_anggota = parse_anggota_pokja(kode_tender)

            # 4. Gabungkan data
            record = {**detail_html, **detail_pdf, **detail_anggota}
            record.pop("_error_pdf", None)
            record.pop("_kode_tender_for_anggota", None)

            # 4. Upsert
            is_baru = record["kode_tender"] not in existing_ids
            upsert_draft_paket(record)

            if is_baru:
                baru += 1
            else:
                diperbarui += 1

            hasil_data.append({
                **record,
                "tanggal_pesan": pesan["tanggal"],
                "status": "baru" if is_baru else "diperbarui",
            })

        except Exception as e:
            errors.append(f"ID {pesan['id_pesan']}: {e}")

    log(1.0, f"Selesai — {baru} baru, {diperbarui} diperbarui, {len(errors)} error")
    return {"baru": baru, "diperbarui": diperbarui, "error": errors, "data": hasil_data}
