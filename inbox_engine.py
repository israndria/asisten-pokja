"""
Tab 0 — Persiapan Draft Paket
Scrape inbox SPSE /admin/pegawai/inbox, parse HTML + PDF in-memory,
upsert ke Supabase tabel draft_paket.
"""

import io
import os
import re
import requests
import pdfplumber
from bs4 import BeautifulSoup
from datetime import datetime, timezone

import spse_browser
from config import sb as _sb

BASE_URL = "https://spse.inaproc.id/tapinkab"
SUBJEK_DELEGASI = "(LPSE) Pengumuman Delegasi Pokja"


def _headers(referer: str = "") -> dict:
    cookie = spse_browser.get_spse_cookies()
    return {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer or f"{BASE_URL}/admin/pegawai/inbox",
    }


def _get(url: str, referer: str = "", timeout: int = 10) -> requests.Response:
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
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        raise RuntimeError("Cookie SPSE kosong — buka Chrome SPSE dan login ulang dulu.")
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
    """Filter pesan Delegasi Pokja tahun berjalan saja.
    Cek di tanggal pesan DAN kode_paket_raw (format SPSE mengandung tahun di keduanya).
    """
    def _strip(s):
        return re.sub(r"<[^>]+>", "", s)
    tahun = str(datetime.now().year)
    return [
        p for p in list_inbox
        if SUBJEK_DELEGASI in _strip(p["subjek"])
        and (tahun in p.get("tanggal", "") or tahun in p.get("kode_paket_raw", ""))
    ]


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

_NAMA_DINAS_MAP = {
    "DPUPR": "Dinas Pekerjaan Umum Dan Penataan Ruang",
    "PUPR": "Dinas Pekerjaan Umum Dan Penataan Ruang",
    "DISDIK": "Dinas Pendidikan",
    "DIPERTA": "Dinas Pertanian",
    "DISPORA": "Dinas Pemuda Dan Olahraga",
    "DISDAG": "Dinas Perdagangan",
    "DISKAN": "Dinas Perikanan",
}

def _resolve_nama_dinas(nomor_surat: str, nama_dinas_raw: str) -> str:
    """Resolve nama dinas lengkap dari nomor surat atau nama singkatan."""
    # Coba match singkatan dari nomor surat dulu (lebih akurat)
    # contoh: 40-L1/DPUPR-BM/KAB-TAPIN/XI/2025
    m = re.search(r"/([A-Z]+)(?:-[A-Z]+)?/KAB", nomor_surat, re.IGNORECASE)
    if m:
        kode = m.group(1).upper()
        if kode in _NAMA_DINAS_MAP:
            return _NAMA_DINAS_MAP[kode]
    # Fallback: match dari nama_dinas_raw
    for singkatan, nama_lengkap in _NAMA_DINAS_MAP.items():
        if nama_dinas_raw.upper().startswith(singkatan):
            return nama_lengkap
    return nama_dinas_raw  # kembalikan apa adanya jika tidak match


def parse_anggota_pokja(kode_tender: str) -> dict:
    """
    GET /lelang/{kode_tender}/edit, parse tabel "Anggota Pokja Pemilihan".
    GET /lelang/{kode_tender}, parse nama PPK dari baris "PPK | nama".
    Return: {anggota_1, anggota_2, anggota_3, nama_ppk}
    """
    hasil = {"anggota_1": "", "anggota_2": "", "anggota_3": "", "nama_ppk": ""}
    if not kode_tender:
        return hasil

    # ── Ambil nama PPK dari halaman lelang utama ──
    try:
        r_main = _get(f"{BASE_URL}/lelang/{kode_tender}", referer=f"{BASE_URL}/admin/pegawai/inbox")
        if r_main.status_code == 200:
            soup_main = BeautifulSoup(r_main.text, "html.parser")
            for tr in soup_main.find_all("tr"):
                # Struktur: <th>PPK</th><td>Nama PPK</td>
                th = tr.find("th")
                td = tr.find("td")
                if th and td and th.text.strip() == "PPK":
                    nama_ppk = td.text.strip()
                    nama_ppk = re.sub(r"\s*Ganti PPK.*", "", nama_ppk, flags=re.IGNORECASE).strip()
                    hasil["nama_ppk"] = nama_ppk
                    break
    except Exception:
        pass

    # ── Ambil anggota pokja dari halaman edit ──
    url = f"{BASE_URL}/lelang/{kode_tender}/edit"
    try:
        r = _get(url, referer=f"{BASE_URL}/admin/pegawai/inbox")
        if r.status_code != 200:
            return hasil
    except Exception:
        return hasil

    soup = BeautifulSoup(r.text, "html.parser")
    anggota = []
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if "Anggota Pokja" in txt or "Status Persetujuan" in txt:
            for row in tbl.find_all("tr"):
                tds = row.find_all("td")
                if not tds:
                    continue
                nama = tds[0].text.strip()
                if nama and len(nama) > 3 and not nama.isdigit():
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
        "bidang": "",
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

                # Nama Dinas: ambil dari PDF, bisa multiline (misal "RUMAH SAKIT UMUM DAERAH DATU\nSANGGUL")
                # Tabel 2 kolom — pdfplumber extract per baris horizontal, konten kolom kanan ikut dalam baris yang sama.
                # Strategi: per baris → buang konten setelah 2+ spasi + keyword kolom kanan → kumpulkan nilai "Surat Dari"
                _STOP_LABEL = r"(?:Nomor Surat|Tanggal Surat|Nomor Agenda|Kode Pokja|Diteruskan)"
                # Keyword kolom kanan — bisa붙어 langsung (1 spasi) atau 2+ spasi
                _RIGHT_COL  = r"\s+(?:Diterima\b|No Agenda\b|Sifat\b|Paraf\b|Catatan\b)"
                nama_parts = []
                capturing_dinas = False
                for _line in txt1.split("\n"):
                    # Strip konten kolom kanan
                    _line_l = re.split(_RIGHT_COL, _line, flags=re.IGNORECASE)[0]
                    if re.search(r"Surat Dari\s*:?\s*", _line_l, re.IGNORECASE):
                        val = re.sub(r"^.*?Surat Dari\s*:?\s*", "", _line_l, flags=re.IGNORECASE).strip()
                        if val:
                            nama_parts.append(val)
                        capturing_dinas = True
                    elif capturing_dinas:
                        if re.search(r"^\s*" + _STOP_LABEL, _line_l, re.IGNORECASE):
                            break
                        val = _line_l.strip()
                        # Abaikan baris yang hanya tanda baca/simbol (sisa format tabel)
                        if val and re.search(r"[A-Za-z0-9]", val):
                            nama_parts.append(val)
                nama_dinas_raw = " ".join(nama_parts)
                hasil["nama_dinas"] = _resolve_nama_dinas(hasil["nomor_surat_dinas"], nama_dinas_raw)

                # Bidang: hanya untuk PUPR — ambil dari kode surat (DPUPR-BM, PUPR-SDA, dst)
                _BIDANG_MAP = {"BM": "Bidang Bina Marga", "SDA": "Bidang Sumber Daya Air", "CK": "Bidang Cipta Karya"}
                _m_bidang = re.search(r"(?:DPUPR|PUPR)-([A-Z]+)", hasil["nomor_surat_dinas"], re.IGNORECASE)
                if _m_bidang:
                    hasil["bidang"] = _BIDANG_MAP.get(_m_bidang.group(1).upper(), "")

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

_KOLOM_DRAFT_PAKET = {
    "kode_tender", "id_pesan", "mak", "nama_tender", "kode_rup",
    "nilai_pagu", "nilai_hps", "link_pdf", "kode_pokja", "nomor_pp", "nomor_surat_dinas",
    "nama_dinas", "bidang", "nama_ppk", "jangka_waktu", "sumber_anggaran",
    "anggota_1", "anggota_2", "anggota_3",
    "diambil_pada", "nomor_urut", "folder_dibuat", "folder_dibuat_pada", "kode_unik",
    "sbu_baru", "sbu_lama",
}

# ── SBU Detection Engine ────────────────────────────────────────────────────────
# Format: (sbu_baru_lengkap, sbu_lama_lengkap, [include_keywords], [exclude_keywords_opsional])
# Urutan prioritas: lebih spesifik di atas, lebih umum di bawah
_SBU_RULES = [
    # BS016 SI012 — fasilitas olahraga INDOOR (GOR, gedung olahraga, kolam renang dalam gedung)
    (
        "Subklasifikasi BS016 (KBLI 2020) Konstruksi Bangunan Sipil Fasilitas Olah Raga",
        "Subklasifikasi SI012 (KBLI 2015) Jasa Pelaksana Konstruksi Bangunan Fasilitas Olah Raga Indoor dan Fasilitas",
        ["gedung olahraga", "gor ", "velodrome", "skatepark"],
    ),
    # BS016 SI011 — fasilitas olahraga OUTDOOR (stadion, lapangan, tribun, kolam renang terbuka)
    (
        "Subklasifikasi BS016 (KBLI 2020) Konstruksi Bangunan Sipil Fasilitas Olah Raga",
        "Subklasifikasi SI011 (KBLI 2015) Jasa Pelaksana Konstruksi Bangunan Stadion Untuk Olahraga Outdoor",
        ["stadion", "lapangan sepakbola", "lapangan bola", "lapangan olahraga",
         "lapangan olah raga", "kolam renang", "kolam karang taruna", "gelanggang", "tribun"],
    ),
    (
        "Subklasifikasi BS016 (KBLI 2020) Konstruksi Bangunan Sipil Fasilitas Olah Raga",
        "Subklasifikasi SI011 (KBLI 2015) Jasa Pelaksana Konstruksi Bangunan Stadion Untuk Olahraga Outdoor",
        ["kolam"],
        ["tambak", "ikan", "perikanan", "udang", "lele", "nila", "bandeng"],
    ),
    # BG006 BG007 — gedung pendidikan
    (
        "Subklasifikasi BG006 (KBLI 2020) Konstruksi Gedung Pendidikan",
        "Subklasifikasi BG007 (KBLI 2015) Jasa Pelaksana Konstruksi Bangunan Pendidikan",
        ["ruang kelas", "sekolah", "sdn ", "smpn ", "smkn ", "sman ",
         "madrasah", "perpustakaan", "universitas"],
    ),
    # BG005 BG008 — gedung kesehatan
    (
        "Subklasifikasi BG005 (KBLI 2020) Konstruksi Gedung Kesehatan",
        "Subklasifikasi BG008 (KBLI 2015) Jasa Pelaksana Konstruksi Bangunan Kesehatan",
        ["rumah sakit", "puskesmas", "polindes", "posyandu", "klinik",
         "bangunan kesehatan", "cytotoxic", "laboratorium kesehatan",
         "instalasi farmasi", "apotek", "rsud", "rsu ", "rsup", "rskd"],
    ),
    # BG002 BG004 — gedung perkantoran/komersial
    (
        "Subklasifikasi BG002 (KBLI 2020) Konstruksi Gedung Perkantoran",
        "Subklasifikasi BG004 (KBLI 2015) Jasa Pelaksana Konstruksi Bangunan Komersial",
        ["kantor", "perkantoran", "pengadilan", "polsek", "polres",
         "koramil", "kodim", "pos pengaman", "pos jaga",
         "balai desa", "balai kecamatan", "aula"],
    ),
    # BS002 SI004 — jembatan & jalan layang
    (
        "Subklasifikasi BS002 (KBLI 2020) Bangunan Sipil Jembatan, Jalan Layang, Fly Over, dan Underpass",
        "Subklasifikasi SI004 (KBLI 2015) Jasa Pelaksana Konstruksi Jembatan, Jalan Layang, Terowongan, dan Subways",
        ["jembatan", "fly over", "flyover", "underpass", "jalan layang", "titian", "gorong-gorong"],
    ),
    # BS004 SI001 — drainase & irigasi
    (
        "Subklasifikasi BS004 (KBLI 2020) Konstruksi Jaringan Irigasi dan Drainase",
        "Subklasifikasi SI001 (KBLI 2015) Jasa Pelaksana Konstruksi Saluran Air, Pelabuhan, Dam, dan Prasarana Sumber Daya Air Lainnya",
        ["drainase", "irigasi", "tersier", "tabat", "siring jalan", "siring pengaman",
         "saluran drainase", "saluran irigasi", "saluran pembuangan"],
    ),
    # BS010 SI001 — sumber daya air, sungai, bendung
    (
        "Subklasifikasi BS010 (KBLI 2020) Konstruksi Bangunan Prasarana Sumber Daya Air",
        "Subklasifikasi SI001 (KBLI 2015) Jasa Pelaksana Konstruksi Saluran Air, Pelabuhan, Dam, dan Prasarana Sumber Daya Air Lainnya",
        ["normalisasi", "pengerukan", "tebing sungai", "siring sungai",
         "rehab sungai", "rehabilitasi sungai", "tanggul", "bendung",
         "embung", "check dam", "waduk", "pintu air", "sei.", "sumber daya air", "sungai"],
    ),
    # BS001 SI003 — jalan
    (
        "Subklasifikasi BS001 (KBLI 2020) Konstruksi Bangunan Sipil Jalan",
        "Subklasifikasi SI003 (KBLI 2015) Jasa Pelaksana Konstruksi Jalan Raya (kecuali Jalan Layang), Jalan, Rel Kereta Api, dan Landas Pacu Bandara",
        ["jalan", "pengaspalan", "aspal", "hotmix", "hot mix",
         "perkerasan", "pelebaran", "rabat beton", "rigid pavement"],
    ),
    # BG009 BG009 — gedung lainnya (paling umum, selalu di bawah)
    (
        "Subklasifikasi BG009 (KBLI 2020) Konstruksi Gedung Lainnya",
        "Subklasifikasi BG009 (KBLI 2015) Jasa Pelaksana Konstruksi Bangunan Gedung Lainnya",
        ["gedung", "serbaguna", "paud", "rumah ibadah", "masjid", "musholla", "gereja", "lapas"],
    ),
]

def detect_sbu(nama_tender: str) -> tuple[str, str]:
    """Deteksi SBU dari judul paket. Return (sbu_baru_lengkap, sbu_lama_lengkap)."""
    nama_lower = nama_tender.lower()
    for rule in _SBU_RULES:
        sbu_baru, sbu_lama, keywords = rule[0], rule[1], rule[2]
        excludes = rule[3] if len(rule) > 3 else []
        for kw in keywords:
            if kw in nama_lower:
                if any(ex in nama_lower for ex in excludes):
                    break  # keyword cocok tapi ada exclude → skip rule ini
                return sbu_baru, sbu_lama
    return "", ""

def upsert_draft_paket(data: dict) -> dict:
    """Upsert satu record ke tabel draft_paket. Return response Supabase."""
    sb = _sb()
    data["diambil_pada"] = datetime.now(timezone.utc).isoformat()
    data.pop("_error_pdf", None)
    # Hanya kirim kolom yang dikenal agar tidak error jika schema belum ada kolom baru
    filtered = {k: v for k, v in data.items() if k in _KOLOM_DRAFT_PAKET}
    r = sb.table("draft_paket").upsert(filtered).execute()
    return r


# ── Fungsi utama (dipanggil dari app.py Tab 0) ─────────────────────────────────

def _proses_satu_pesan(pesan: dict, existing_kode: set) -> dict:
    """Proses satu pesan: fetch detail HTML + PDF + anggota + HPS. Return record atau error."""
    try:
        detail_html = parse_detail_pesan(pesan["id_pesan"])
        if not detail_html.get("kode_tender"):
            return {"_error": f"ID {pesan['id_pesan']}: kode_tender tidak ditemukan"}

        detail_pdf = {}
        if detail_html.get("link_pdf"):
            detail_pdf = parse_pdf_inmemory(detail_html["link_pdf"])

        kode_tender = detail_html["kode_tender"]
        detail_anggota = parse_anggota_pokja(kode_tender)

        record = {**detail_html, **detail_pdf, **detail_anggota}
        record.pop("_error_pdf", None)
        record.pop("_kode_tender_for_anggota", None)
        record["id_pesan"] = pesan["id_pesan"]
        record["_is_baru"] = kode_tender not in existing_kode
        record["_tanggal_pesan"] = pesan["tanggal"]

        # Deteksi SBU dari judul paket
        sbu_baru, sbu_lama = detect_sbu(record.get("nama_tender", ""))
        record["sbu_baru"] = sbu_baru
        record["sbu_lama"] = sbu_lama

        # Scrape HPS via Playwright (halaman di-render JS)
        try:
            from hps_engine import scrape_dan_upsert_hps
            scrape_dan_upsert_hps(kode_tender)
        except Exception:
            pass  # HPS gagal tidak menggagalkan proses utama

        return record
    except Exception as e:
        return {"_error": f"ID {pesan['id_pesan']}: {e}"}


def serap_inbox(progress_cb=None, max_workers: int = 10) -> dict:
    """
    Serap pesan Delegasi Pokja dari inbox, simpan ke Supabase.
    Incremental: skip id_pesan yang sudah ada. Paralel: max_workers thread.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def log(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    log(0.05, "Mengambil list inbox...")
    semua = ambil_list_inbox()
    delegasi = filter_delegasi(semua)

    if not delegasi:
        log(1.0, "Tidak ada pesan Delegasi Pokja ditemukan di inbox.")
        return {"baru": 0, "diperbarui": 0, "skip": 0, "error": [], "data": []}

    # Snapshot DB
    log(0.08, "Mengambil snapshot database...")
    sb = _sb()
    existing_raw = sb.table("draft_paket").select("kode_tender,id_pesan,nama_tender").execute()
    existing_id_pesan = {str(r["id_pesan"]) for r in (existing_raw.data or []) if r.get("id_pesan")}
    existing_kode = {r["kode_tender"] for r in (existing_raw.data or [])}

    # Snapshot nama paket yang sudah ada di DB (untuk skip duplikat pesan inbox)
    existing_nama = {str(r.get("nama_tender") or "").strip().lower()
                     for r in (existing_raw.data or []) if r.get("nama_tender")}

    # Filter: skip jika id_pesan sudah ada ATAU nama paket sudah ada di DB
    to_process = [
        p for p in delegasi
        if p["id_pesan"] not in existing_id_pesan
        and p["kode_paket_raw"].strip().lower() not in existing_nama
    ]
    skip = len(delegasi) - len(to_process)
    total = len(to_process)

    log(0.10, f"⏭️ {skip} dilewati, memproses {total} pesan baru...")

    if total == 0:
        log(1.0, f"Selesai — semua sudah tersimpan, ⏭️ {skip} dilewati")
        return {"baru": 0, "diperbarui": 0, "skip": skip, "error": [], "data": []}

    hasil_data = []
    errors = []
    baru = 0
    diperbarui = 0
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_proses_satu_pesan, p, existing_kode): p for p in to_process}
        for future in as_completed(futures):
            done += 1
            pct = 0.10 + (done / total) * 0.85
            record = future.result()

            if "_error" in record:
                errors.append(record["_error"])
                log(pct, f"[{done}/{total}] ❌ {record['_error'][:60]}")
                # Simpan ke DB dengan kode_tender = id_pesan agar skip di run berikutnya
                id_p = futures[future]["id_pesan"]
                try:
                    sb.table("draft_paket").upsert({
                        "kode_tender": f"_err_{id_p}",
                        "id_pesan": id_p,
                        "nama_tender": f"[ERROR] {record['_error'][:80]}",
                    }).execute()
                except Exception:
                    pass
                continue

            is_baru = record.pop("_is_baru")
            tgl = record.pop("_tanggal_pesan", "")
            try:
                upsert_draft_paket(record)
                if is_baru:
                    baru += 1
                else:
                    diperbarui += 1
                hasil_data.append({**record, "tanggal_pesan": tgl,
                                   "status": "baru" if is_baru else "diperbarui"})
                log(pct, f"[{done}/{total}] ✅ {record.get('nama_tender','')[:45]}")
            except Exception as e:
                errors.append(f"Upsert {record.get('kode_tender')}: {e}")

    log(1.0, f"Selesai — {baru} baru, {diperbarui} diperbarui, ⏭️ {skip} dilewati, {len(errors)} error")
    return {"baru": baru, "diperbarui": diperbarui, "skip": skip, "error": errors, "data": hasil_data}


# ── Download Dokumen Paket (Lampiran Inbox + Dokumen SPSE) ────────────────────

def _unique_dst(folder: str, fname: str) -> str:
    """Jika fname sudah ada di folder, tambahkan suffix _2, _3, dst."""
    dst = os.path.join(folder, fname)
    if not os.path.exists(dst):
        return dst
    base, ext = os.path.splitext(fname)
    n = 2
    while True:
        candidate = os.path.join(folder, f"{base}_{n}{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def download_dokumen_paket(
    kode_tender: str,
    id_pesan: str,
    folder_tujuan: str,
    kode_pokja: str = "",
    progress_cb=None,
    st_ctx=None,
) -> dict:
    """
    Download semua dokumen paket langsung ke folder_tujuan (tanpa subfolder):
      - Lampiran dari inbox (klik via Playwright)
      - Dokumen SPSE: spek, docsskk, uploaduraian, lainnya

    Setelah download, buat 1 PDF gabungan: Draft_Pokja_{kode_pokja}.pdf
    Butuh Chrome yang sudah login SPSE (CDP port 9222).
    Return: {"ok": [...], "skip": [...], "error": [...], "draft_pdf": str}
    """
    import asyncio
    import shutil
    import urllib.parse
    import threading
    from playwright.async_api import async_playwright
    from bs4 import BeautifulSoup

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    hasil = {"ok": [], "skip": [], "error": [], "draft_pdf": ""}
    os.makedirs(folder_tujuan, exist_ok=True)

    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
            ctx = browser.contexts[0]

            cookies = await ctx.cookies(["https://spse.inaproc.id"])
            cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)
            hdrs = {
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{BASE_URL}/admin/pegawai/inbox",
            }

            # Worker page untuk download (reuse agar tidak bolak-balik buka tab baru)
            worker_page = await ctx.new_page()
            try:
                await worker_page.set_viewport_size({"width": 100, "height": 100})
            except: pass

            async def _playwright_download(url: str, dst: str, pg) -> bool:
                """Download satu file via Playwright goto + expect_download."""
                try:
                    async with pg.expect_download(timeout=30000) as dl_info:
                        try:
                            await pg.goto(url, wait_until="commit")
                        except Exception:
                            pass
                    dl = await dl_info.value
                    server_fname = urllib.parse.unquote_plus(dl.suggested_filename or "")
                    if server_fname:
                        clean = re.sub(r'[<>:"/\\|?*]', "_", server_fname).strip()
                        dst = os.path.join(os.path.dirname(dst), clean)
                    tmp = await dl.path()
                    if tmp:
                        shutil.copy2(tmp, dst)
                        return dst
                    return False
                except Exception as e:
                    raise e

            # ════════════════════════════════
            # 1. Lampiran Inbox
            # ════════════════════════════════
            log(f"📨 Lampiran inbox pesan {id_pesan}...")
            try:
                await worker_page.goto(
                    f"{BASE_URL}/non-rekanan/inbox/{id_pesan}",
                    wait_until="networkidle", timeout=20000,
                )
                lamp_links = await worker_page.query_selector_all('a[href*="/dl/"]')
                total_lamp = len(lamp_links)
                log(f"  {total_lamp} lampiran ditemukan")
                for i, link in enumerate(lamp_links, 1):
                    fname_raw = re.sub(r"\s*-\s*\d+\s*[KkMm][Bb]\s*$", "",
                                       (await link.text_content() or ""), flags=re.IGNORECASE).strip()
                    fname = re.sub(r'[<>:"/\\|?*]', "_", fname_raw).strip() or "lampiran"
                    dst = _unique_dst(folder_tujuan, fname)
                    try:
                        async with worker_page.expect_download(timeout=30000) as dl_info:
                            await link.evaluate("el => el.click()")
                        dl = await dl_info.value
                        tmp = await dl.path()
                        if tmp:
                            shutil.copy2(tmp, dst)
                            log(f"  ({i}/{total_lamp}) ✅ {os.path.basename(dst)}")
                            hasil["ok"].append(dst)
                    except Exception as e:
                        log(f"  ({i}/{total_lamp}) ❌ {fname}: {e}")
                        hasil["error"].append(f"{fname}: {e}")
            except Exception as e:
                log(f"  ❌ Gagal buka inbox: {e}")
                hasil["error"].append(f"Inbox: {e}")

            # ════════════════════════════════
            # 1b. Parse jangka_waktu
            # ════════════════════════════════
            jangka_waktu_found = ""
            for fpath in hasil["ok"]:
                if not fpath.lower().endswith(".pdf"): continue
                try:
                    import pdfplumber
                    with pdfplumber.open(fpath) as _pdf:
                        for _page in _pdf.pages:
                            _txt = _page.extract_text() or ""
                            _m = re.search(r"(\d+)\s*(?:\([^)]+\)\s*)?(Hari\s+Kalender|Hari\s+Kerja|H\.K\.?)", _txt, re.IGNORECASE)
                            if _m:
                                jangka_waktu_found = f"{_m.group(1)} {_m.group(2).strip()}"
                                log(f"  📅 Jangka waktu: {jangka_waktu_found} (dari {os.path.basename(fpath)})")
                                break
                except Exception: pass
                if jangka_waktu_found: break

            # ════════════════════════════════
            # 2. Dokumen SPSE
            # ════════════════════════════════
            log(f"📄 Mencari link dokumen di halaman persiapan...")
            try:
                await worker_page.goto(f"{BASE_URL}/lelang/{kode_tender}/edit", wait_until="networkidle", timeout=20000)
                edit_html = await worker_page.content()
                soup_edit = BeautifulSoup(edit_html, "html.parser")
            except Exception as e:
                log(f"  ❌ Gagal buka halaman edit: {e}")
                soup_edit = None

            if soup_edit:
                links_dok = soup_edit.select("a.list-group-item")
                targets = []
                for a in links_dok:
                    txt = a.get_text().lower()
                    href = a.get("href", "")
                    if not href or "/dl/" in href: continue
                    keywords = ["spek", "rancangan kontrak", "uraian singkat", "lainnya", "kak", "spesifikasi"]
                    if any(kw in txt for kw in keywords):
                        label_clean = re.sub(r"\s*\*.*$", "", a.get_text(strip=True)).strip()
                        targets.append({"label": label_clean, "href": href})
                
                total_bagisan = len(targets)
                log(f"  Ditemukan {total_bagisan} bagian dokumen")

                for idx, target in enumerate(targets, 1):
                    url_sec = f"https://spse.inaproc.id{target['href']}" if target['href'].startswith("/") else target['href']
                    log(f"[{idx}/{total_bagisan}] 📂 Membuka {target['label']}...")
                    try:
                        r = requests.get(url_sec, headers=hdrs, timeout=15)
                        if r.status_code == 403: continue
                        r.raise_for_status()
                        soup = BeautifulSoup(r.text, "html.parser")
                        # Navigasi ke halaman section via Playwright agar link /dl/ punya session aktif
                        await worker_page.goto(url_sec, wait_until="networkidle", timeout=20000)
                        pw_links = await worker_page.query_selector_all(
                            "table#files a[href*='/dl/'], table.table a[href*='/dl/']"
                        )
                        num_f = len(pw_links)
                        for fi, link in enumerate(pw_links, 1):
                            fname_raw = re.sub(r"\s*-\s*\d+\s*[KkMm][Bb]\s*$", "",
                                               (await link.text_content() or ""), flags=re.IGNORECASE).strip()
                            fname = re.sub(r'[<>:"/\\|?*]', "_", fname_raw).strip() or f"file_{fi}"
                            dst = _unique_dst(folder_tujuan, fname)
                            try:
                                async with worker_page.expect_download(timeout=30000) as dl_info:
                                    await link.evaluate("el => el.click()")
                                dl = await dl_info.value
                                server_fname = urllib.parse.unquote_plus(dl.suggested_filename or "")
                                if server_fname:
                                    dst = _unique_dst(folder_tujuan, re.sub(r'[<>:"/\\|?*]', "_", server_fname).strip())
                                tmp = await dl.path()
                                if tmp:
                                    shutil.copy2(tmp, dst)
                                    log(f"  ({fi}/{num_f}) ✅ {os.path.basename(dst)}")
                                    hasil["ok"].append(dst)
                                else:
                                    hasil["error"].append(f"{fname}: gagal")
                            except Exception as e:
                                log(f"  ({fi}/{num_f}) ❌ {fname}: {e}")
                                hasil["error"].append(f"{fname}: {e}")
                    except Exception as e:
                        log(f"  ❌ Error: {e}")
                        hasil["error"].append(f"{target['label']}: {e}")
            else:
                log("  ❌ Lewati scan dokumen")

            # ════════════════════════════════
            # 2b. Parse jangka_waktu dari dokumen SPSE jika belum ketemu
            # ════════════════════════════════
            if not jangka_waktu_found:
                for fpath in hasil["ok"]:
                    if not fpath.lower().endswith(".pdf"):
                        continue
                    try:
                        import pdfplumber
                        with pdfplumber.open(fpath) as _pdf:
                            for _page in _pdf.pages:
                                _txt = _page.extract_text() or ""
                                _m = re.search(
                                    r"(\d+)\s*(?:\([^)]+\)\s*)?(Hari\s+Kalender|Hari\s+Kerja|H\.K\.?)",
                                    _txt, re.IGNORECASE
                                )
                                if _m:
                                    jangka_waktu_found = f"{_m.group(1)} {_m.group(2).strip()}"
                                    log(f"  📅 Jangka waktu: {jangka_waktu_found} (dari {os.path.basename(fpath)})")
                                    break
                    except Exception:
                        pass
                    if jangka_waktu_found:
                        break

                if jangka_waktu_found and kode_tender:
                    try:
                        _sb().table("draft_paket").update(
                            {"jangka_waktu": jangka_waktu_found}
                        ).eq("kode_tender", kode_tender).execute()
                        log(f"  ✅ Supabase jangka_waktu diupdate: {jangka_waktu_found}")
                    except Exception as _e:
                        log(f"  ⚠ Gagal update jangka_waktu Supabase: {_e}")

            await worker_page.close()
            log("🏁 Proses download dokumen selesai.")

    import concurrent.futures

    def _run_in_thread():
        if st_ctx:
            from streamlit.runtime.scriptrunner import add_script_run_ctx
            add_script_run_ctx(threading.current_thread(), st_ctx)
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(_run_in_thread).result()

    # ════════════════════════════════
    # 2c. Parse jangka_waktu dari PDF di folder jika belum ketemu dari download
    # ════════════════════════════════
    if not jangka_waktu_found:
        import glob as _glob
        import pdfplumber as _pdfplumber
        for fpath in _glob.glob(os.path.join(folder_tujuan, "*.pdf")):
            if os.path.basename(fpath).startswith("Draft_"):
                continue
            try:
                with _pdfplumber.open(fpath) as _pdf:
                    for _page in _pdf.pages:
                        _txt = _page.extract_text() or ""
                        _m = re.search(
                            r"(\d+)\s*(?:\([^)]+\))?\s*(hari\s+kalender|hari\s+kerja|H\.K\.?)",
                            _txt, re.IGNORECASE
                        )
                        if _m:
                            jangka_waktu_found = f"{_m.group(1)} {_m.group(2).strip()}"
                            log(f"  📅 Jangka waktu: {jangka_waktu_found} (dari {os.path.basename(fpath)})")
                            break
            except Exception:
                pass
            if jangka_waktu_found:
                break
        if jangka_waktu_found and kode_tender:
            try:
                _sb().table("draft_paket").update(
                    {"jangka_waktu": jangka_waktu_found}
                ).eq("kode_tender", kode_tender).execute()
                log(f"  ✅ Supabase jangka_waktu diupdate: {jangka_waktu_found}")
            except Exception as _e:
                log(f"  ⚠ Gagal update jangka_waktu Supabase: {_e}")

    # ════════════════════════════════
    # 3. Gabung semua jadi 1 PDF Draft
    # ════════════════════════════════
    label = f"Pokja_{kode_pokja}" if kode_pokja else "Draft"
    draft_path = os.path.join(folder_tujuan, f"Draft_{label}.pdf")
    # Urutan sudah benar: lampiran inbox (bagian 1) masuk duluan ke hasil["ok"],
    # lalu dokumen SPSE (bagian 2). File pertama = lampiran inbox, dikecualikan dari limit size.
    files_didownload = hasil["ok"][:]

    try:
        merged = _gabung_pdf_draft(draft_path, files_didownload, progress_cb)
        hasil["draft_pdf"] = merged
        log(f"📎 Draft PDF: {os.path.basename(merged)}")
    except Exception as e:
        log(f"❌ Gagal buat draft PDF: {e}")
        hasil["error"].append(f"Draft PDF: {e}")

    return hasil


def _gabung_pdf_draft(output_path: str, file_list: list, progress_cb=None) -> str:
    """
    Gabung file_list (path absolut hasil download SPSE) jadi 1 PDF.
    PDF  : langsung merge via PyMuPDF (maks 50 hal)
    Docx/xlsx : konversi ke PDF via Word/Excel COM dulu
    Gambar : embed via PyMuPDF
    File > 5MB dilewati agar proses cepat.
    """
    import fitz  # PyMuPDF

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    exts_office = {".docx", ".doc", ".xlsx", ".xls"}
    exts_img    = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
    exts_pdf    = {".pdf"}

    MAX_FILE_MB  = 5
    MAX_PDF_PAGES = 50

    # File pertama dalam list = lampiran inbox — wajib masuk, bebas dari limit size
    _lampiran_wajib = {file_list[0]} if file_list else set()

    # Filter: hanya file yang ada, didukung, dan tidak terlalu besar
    files = []
    for fpath in file_list:
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fpath)[1].lower()
        if ext not in exts_pdf | exts_office | exts_img:
            continue
        size_mb = os.path.getsize(fpath) / 1024 / 1024
        if size_mb > MAX_FILE_MB and fpath not in _lampiran_wajib:
            log(f"  ⏭ {os.path.basename(fpath)} ({size_mb:.1f}MB, skip)")
            continue
        files.append(fpath)

    if not files:
        raise ValueError("Tidak ada file yang bisa digabung")

    log(f"📎 Menggabung {len(files)} file ke PDF draft...")

    merged_doc = fitz.open()
    tmp_pdfs = []  # temp files Office→PDF untuk cleanup

    for fpath in files:
        ext = os.path.splitext(fpath)[1].lower()
        fname = os.path.basename(fpath)
        try:
            if ext == ".pdf":
                src = fitz.open(fpath)
                n = src.page_count
                # Ambil maks MAX_PDF_PAGES halaman pertama
                end = min(n, MAX_PDF_PAGES)
                merged_doc.insert_pdf(src, from_page=0, to_page=end - 1)
                src.close()
                note = f"{end}/{n} hal" if n > MAX_PDF_PAGES else f"{n} hal"
                log(f"  + {fname} ({note})")

            elif ext in exts_office:
                # Konversi via COM (Word/Excel)
                tmp_pdf = fpath + "_tmp.pdf"
                _office_to_pdf_com(fpath, tmp_pdf)
                if os.path.exists(tmp_pdf):
                    src = fitz.open(tmp_pdf)
                    n = src.page_count
                    end = min(n, MAX_PDF_PAGES)
                    merged_doc.insert_pdf(src, from_page=0, to_page=end - 1)
                    src.close()
                    tmp_pdfs.append(tmp_pdf)
                    note = f"{end}/{n} hal" if n > MAX_PDF_PAGES else ""
                    log(f"  + {fname} (via COM{', ' + note if note else ''})")
                else:
                    log(f"  ⏭ {fname}: konversi COM gagal, skip")

            elif ext in exts_img:
                # Buat halaman PDF dari gambar
                img_doc = fitz.open(fpath)
                rect = fitz.Rect(0, 0, 595, 842)  # A4
                page = merged_doc.new_page(width=595, height=842)
                page.insert_image(rect, filename=fpath)
                log(f"  + {fname} (gambar)")

        except Exception as e:
            log(f"  ⏭ {fname}: {e}")

    merged_doc.save(output_path, garbage=4, deflate=True)
    merged_doc.close()

    # Cleanup temp PDF
    for tmp in tmp_pdfs:
        try:
            os.remove(tmp)
        except Exception:
            pass

    return output_path


def gabung_pdf(output_path: str, file_list: list, progress_cb=None) -> str:
    """Wrapper publik untuk _gabung_pdf_draft — bisa diimport modul lain."""
    return _gabung_pdf_draft(output_path, file_list, progress_cb)


def _office_to_pdf_com(src_path: str, dst_pdf: str):
    """Konversi file Office ke PDF via COM (Word atau Excel)."""
    import pythoncom
    import win32com.client
    ext = os.path.splitext(src_path)[1].lower()
    src_abs = os.path.abspath(src_path)
    dst_abs = os.path.abspath(dst_pdf)

    pythoncom.CoInitialize()
    try:
        if ext in (".docx", ".doc"):
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            app.DisplayAlerts = False
            try:
                doc = app.Documents.Open(src_abs)
                doc.SaveAs(dst_abs, FileFormat=17)  # wdFormatPDF=17
                doc.Close(False)
            finally:
                app.Quit()
        elif ext in (".xlsx", ".xls"):
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible = False
            app.DisplayAlerts = False
            app.AskToUpdateLinks = False
            app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable — nonaktifkan macro
            try:
                wb = app.Workbooks.Open(
                    src_abs,
                    UpdateLinks=0,
                    ReadOnly=True,
                    IgnoreReadOnlyRecommended=True,
                )
                wb.ExportAsFixedFormat(0, dst_abs)  # xlTypePDF=0
                wb.Close(False)
            finally:
                app.Quit()
    finally:
        pythoncom.CoUninitialize()
