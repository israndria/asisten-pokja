"""
Mode Pengadaan Langsung — Tab 0: Draft Paket PL
Input manual paket PL (JKK atau PK), simpan ke Supabase tabel draft_paket_pl.
Juga berisi fungsi scrape otomatis dari SPSE /dt/paketpp.
"""

import os
import re
from datetime import datetime, timezone
from config import sb as _sb
from pl_engine import (
    is_paket_ditarik,
    _safe_download_name_for_folder,
    _spse_retry_call,
    _is_paket_ulang_serap,
    filter_rows_for_serap,
    XML_DATA_SUBFOLDER,
)

BASE_URL = "https://spse.inaproc.id/tapinkab"

SATKER_LIST = [
    "Dinas Perdagangan",
    "Dinas Pekerjaan Umum Dan Penataan Ruang (Bina Marga)",
    "Dinas Pekerjaan Umum Dan Penataan Ruang (PUPR)",
    "Kecamatan CLU",
    "Dinas Perizinan Terpadu Satu Pintu",
    "Lainnya",
]

STATUS_LIST = ["draft", "undangan", "evaluasi", "negosiasi", "selesai"]


def load_draft_pl() -> list[dict]:
    """Ambil semua paket pekerjaan konstruksi (jenis_pl=PK), urut terbaru dulu."""
    try:
        rows = (
            _sb()
            .table("draft_paket_pl")
            .select("*")
            .eq("jenis_pl", "PK")
            .order("diambil_pada", desc=True)
            .execute()
            .data or []
        )
        return [row for row in rows if not is_paket_ditarik(row)]
    except Exception as e:
        return []


def _kode_live_dan_stale(
    existing_rows: list[dict],
    live_codes: set[str],
    *,
    snapshot_valid: bool,
) -> tuple[list[str], bool]:
    """Hitung kode PK yang hilang dari snapshot SPSE.

    Snapshot invalid tidak boleh mengubah state database. Ini mencegah outage,
    halaman login, atau payload rusak membuat seluruh paket tampak ditarik.
    """
    if not snapshot_valid:
        return [], False
    live = {str(code).strip() for code in (live_codes or set()) if str(code).strip()}
    stale = sorted({
        str(row.get("kode_paket") or "").strip()
        for row in (existing_rows or [])
        if str(row.get("kode_paket") or "").strip()
        and str(row.get("kode_paket")).strip() not in live
    })
    return stale, True


def reconcile_paket_pl_dengan_spse(
    live_codes: set[str],
    *,
    snapshot_valid: bool = False,
    log_fn=None,
) -> dict:
    """Tandai row PK yang hilang dari `/dt/paketpp` tanpa menghapusnya."""
    if not snapshot_valid:
        return {"ok": False, "withdrawn": 0, "error": "Snapshot SPSE tidak tervalidasi."}

    def log(message: str) -> None:
        if log_fn:
            log_fn(message)

    try:
        existing = (
            _sb()
            .table("draft_paket_pl")
            .select("kode_paket,status")
            .eq("jenis_pl", "PK")
            .execute()
            .data or []
        )
    except Exception as exc:
        return {"ok": False, "withdrawn": 0, "error": f"Gagal baca snapshot DB: {exc}"}

    stale_codes, _ = _kode_live_dan_stale(existing, live_codes, snapshot_valid=True)
    withdrawn = 0
    errors = []
    for kode in stale_codes:
        try:
            (
                _sb()
                .table("draft_paket_pl")
                .update({"status": "ditarik_spse"})
                .eq("kode_paket", kode)
                .execute()
            )
            withdrawn += 1
            log(f"  Tandai ditarik SPSE: {kode}")
        except Exception as exc:
            errors.append(f"{kode}: {exc}")
    return {"ok": not errors, "withdrawn": withdrawn, "errors": errors}


_TAHAP_SELESAI_KEYWORDS = ("penandatanganan kontrak", "paket sudah selesai", "sudah selesai")

def is_paket_selesai(r: dict) -> bool:
    """True jika paket sudah Penandatanganan Kontrak / selesai.
    Identik dengan pl_engine.is_paket_selesai — tabel dan kolom sama (draft_paket_pl, tahap_spse).
    """
    tahap = (r.get("tahap_spse") or "").lower()
    if tahap:
        return any(k in tahap for k in _TAHAP_SELESAI_KEYWORDS)
    return any(k in (r.get("status") or "").lower() for k in _TAHAP_SELESAI_KEYWORDS)


def simpan_paket_pl(data: dict) -> dict:
    """
    Upsert satu paket PL ke draft_paket_pl.
    Return: {"ok": True} atau {"ok": False, "error": str}
    """
    if not data.get("kode_paket"):
        return {"ok": False, "error": "kode_paket wajib diisi"}
    data = dict(data)
    # Kompatibilitas schema jadwal lama/baru; Excel membaca tanggal pembukaan
    # dari data ini dan tidak boleh mewarisi nilai paket donor.
    tgl_buka = data.get("tgl_buka_penawaran") or data.get("tgl_pembukaan")
    if tgl_buka:
        data["tgl_buka_penawaran"] = tgl_buka
        data["tgl_pembukaan"] = tgl_buka
    data.setdefault("diambil_pada", datetime.now(timezone.utc).isoformat())
    try:
        _sb().table("draft_paket_pl").upsert(data).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def hapus_paket_pl(kode_paket: str) -> dict:
    """Hapus satu baris dari draft_paket_pl berdasarkan kode_paket."""
    try:
        _sb().table("draft_paket_pl").delete().eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def buang_duplikat_paket_lama(rows: list[dict]) -> tuple[list[dict], int]:
    """Simpan hanya row kode_paket terbaru per nama_paket (paket ulang → kode baru)."""
    by_nama: dict[str, dict] = {}
    for r in rows:
        nama = (r.get("nama_paket") or "").strip()
        if not nama:
            by_nama[r.get("kode_paket") or id(r)] = r
            continue
        prev = by_nama.get(nama)
        if prev is None or str(r.get("kode_paket") or "") > str(prev.get("kode_paket") or ""):
            by_nama[nama] = r
    hasil = list(by_nama.values())
    return hasil, len(rows) - len(hasil)


_SUFFIX_ULANG = " (PL - Ulang)"


def nama_folder_dengan_suffix_ulang(
    output_base: str,
    nama_folder: str,
    paksa_suffix: bool = False,
) -> str:
    """Auto-tambah ' (PL - Ulang)' bila folder sama sudah ada di disk."""
    import os as _os
    nama = (nama_folder or "").strip()
    if not nama:
        return nama
    sudah_bersuffix = nama.endswith(_SUFFIX_ULANG.strip()) or _SUFFIX_ULANG.strip() in nama
    target_polos = _os.path.join(output_base, nama)
    perlu_suffix = paksa_suffix or _os.path.exists(target_polos)
    if not perlu_suffix or sudah_bersuffix:
        return nama
    kandidat = f"{nama}{_SUFFIX_ULANG}"
    if not _os.path.exists(_os.path.join(output_base, kandidat)):
        return kandidat
    n = 2
    while _os.path.exists(_os.path.join(output_base, f"{nama}{_SUFFIX_ULANG.rstrip(')')}{n})")):
        n += 1
    return f"{nama}{_SUFFIX_ULANG.rstrip(')')}{n})"


def update_status(kode_paket: str, status: str) -> dict:
    """Update kolom status paket PL."""
    try:
        _sb().table("draft_paket_pl").update({"status": status}).eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tandai_folder_dibuat(kode_paket: str) -> dict:
    """Set folder_dibuat=True dan folder_dibuat_pada=now."""
    try:
        query = _sb().table("draft_paket_pl").update({
            "folder_dibuat": True,
            "folder_dibuat_pada": datetime.now(timezone.utc).isoformat(),
        }).eq("kode_paket", kode_paket)
        # Minta row hasil update. Mock lama mungkin belum punya select().
        try:
            query = query.select("kode_paket")
        except (AttributeError, TypeError):
            pass
        response = query.execute()
        data = getattr(response, "data", None)
        if data is None and isinstance(response, dict):
            data = response.get("data")
        if isinstance(data, (list, tuple, dict)) and not data:
            return {"ok": False, "error": f"Paket {kode_paket} tidak ditemukan saat menandai folder_dibuat."}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# Scrape otomatis dari SPSE
# ============================================================

def _parse_hps_dari_edit(html: str) -> str:
    """Ekstrak nilai HPS dari halaman nontender/{kode}/edit."""
    import re
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    teks = soup.get_text(" ", strip=True)
    m = re.search(r"Nilai HPS\s*Rp\.\s*([\d.,]+)", teks)
    return f"Rp. {m.group(1)}" if m else ""


def _parse_jenis_kontrak_dari_edit(html: str) -> str:
    """Ekstrak Jenis Kontrak dari halaman nontender/{kode}/edit."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    teks = soup.get_text(" ", strip=True)
    m = re.search(r"Jenis Kontrak\s+([\w\s]+?)(?:Dokumen|Jadwal|Survey|\Z)", teks)
    if m:
        return m.group(1).strip()
    return ""


def _parse_metode_pengadaan_dari_edit(html: str) -> str:
    """Ekstrak Metode Pengadaan dari halaman nontender/{kode}/edit."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    teks = soup.get_text(" ", strip=True)
    m = re.search(r"Metode Pengadaan\s+(.+?)(?:Kualifikasi Usaha|Jenis Kontrak|Dokumen|Jadwal|\Z)", teks)
    if m:
        return m.group(1).strip()
    return ""


def _derive_jenis_pl_dari_metode(metode: str, nama_paket: str) -> str:
    """Derive jenis_pl dari metode_pengadaan (lebih akurat dari nama saja)."""
    if metode:
        m_lower = metode.lower()
        if "barang" in m_lower:
            return "PK"
        # "Non Konstruksi" maupun "Konstruksi" → JKK (LDK/checklist identik)
        if "konsultan" in m_lower:
            return "JKK"
    # Fallback ke keyword nama
    nama_lower = nama_paket.lower()
    if any(k in nama_lower for k in ["konsultan", "perencanaan", "pengawasan", "supervisi", "manajemen konstruksi"]):
        return "JKK"
    return "PK"


def serap_paket_pl_dari_spse(cookie_str: str, base_url: str, log_fn=None) -> dict:
    """
    Scrape daftar paket non-tender dari SPSE /dt/paketpp,
    fetch detail tiap paket dari /nontender/{kode}/edit,
    upsert ke Supabase draft_paket_pl.

    cookie_str : hasil get_spse_cookies()
    base_url   : SPSE_BASE_URL (diakhiri /)
    log_fn     : callable(str) untuk log progres, opsional
    Returns    : {"ok": True, "scraped": N, "errors": [...]}
    """
    import requests

    def log(msg):
        if log_fn:
            log_fn(msg)

    headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"}

    # 1. Fetch daftar paket
    try:
        resp = requests.get(f"{base_url}dt/paketpp", headers=headers, timeout=15)
        payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("payload dt/paketpp tidak memiliki data list")
        live_codes = {
            str(row[5]).strip()
            for row in rows
            if isinstance(row, (list, tuple)) and len(row) > 5 and str(row[5]).strip()
        }
        if rows and not live_codes:
            raise ValueError("payload dt/paketpp berisi row tanpa kode paket")
    except Exception as e:
        return {"ok": False, "scraped": 0, "withdrawn": 0, "errors": [f"Gagal fetch dt/paketpp: {e}"]}

    reconciliation = reconcile_paket_pl_dengan_spse(
        live_codes,
        snapshot_valid=True,
        log_fn=log_fn,
    )
    if not reconciliation.get("ok"):
        errors = reconciliation.get("errors") or [reconciliation.get("error", "Rekonsiliasi gagal")]
    else:
        errors = []

    log(f"Ditemukan {len(rows)} paket di SPSE")
    scraped = 0

    # Tahap real di SPSE dipakai untuk mencegah POST setup ke paket selesai.
    # Reuse parser JKK karena endpoint/status PP memang shared.
    try:
        from pl_engine import _fetch_tahap_spse
        tahap_map = _fetch_tahap_spse(cookie_str, base_url, log_fn=log_fn)
    except Exception as exc:
        tahap_map = {}
        log(f"  [WARN] Tahap real SPSE tidak terbaca: {exc}")

    # Snapshot lokal dipakai sebagai pre-filter agar paket yang sudah dibuatkan
    # folder/ditangani tidak membuka rangkaian endpoint detail yang mahal.
    try:
        _existing_rows = _sb().table("draft_paket_pl").select(
            "kode_paket,status,tahap_spse,is_ulang,folder_dibuat"
        ).eq("jenis_pl", "PK").execute().data or []
    except Exception as _existing_error:
        errors.append(f"Gagal baca snapshot paket lokal: {_existing_error}")
        return {
            "ok": False,
            "scraped": 0,
            "withdrawn": reconciliation.get("withdrawn", 0),
            "skipped": 0,
            "errors": errors,
        }

    _existing_by_code = {
        str(item.get("kode_paket") or "").strip(): item
        for item in _existing_rows
        if isinstance(item, dict) and str(item.get("kode_paket") or "").strip()
    }
    rows, _skipped_rows = filter_rows_for_serap(rows, _existing_rows, tahap_map)
    for _skip in _skipped_rows:
        log(f"  Skip {_skip['kode_paket']} — {_skip['reason']}")

    if not rows:
        log(f"Tidak ada paket yang perlu diserap; {len(_skipped_rows)} paket dilewati.")
        return {
            "ok": not errors,
            "scraped": 0,
            "withdrawn": reconciliation.get("withdrawn", 0),
            "skipped": len(_skipped_rows),
            "errors": errors,
        }

    for row in rows:
        id_paket_internal = str(row[0])  # ID paket-level (kolom 0), bukan untuk kirim verifikasi
        nama_paket   = row[1]
        status_spse  = row[2]
        satker       = row[4]
        kode_paket   = str(row[5])   # kode resmi non-tender

        log(f"  Scraping {kode_paket} — {nama_paket[:40]}...")

        # Ambil ID peserta dari halaman evaluasi (untuk kirimundanganverifikasi)
        id_nontender = id_paket_internal  # fallback jika belum ada peserta
        is_ulang = _is_paket_ulang_serap(
            {"nama_paket": nama_paket}, _existing_by_code.get(kode_paket)
        )
        try:
            import re as _re
            r_eval = requests.get(
                f"{base_url}evaluasinontender/{kode_paket}",
                headers=headers, timeout=15
            )
            ids_peserta = _re.findall(
                r'/evaluasinontender/(\d+)/kirimundanganverifikasi', r_eval.text
            )
            if ids_peserta:
                id_nontender = ids_peserta[0]
            is_ulang = is_ulang or _is_paket_ulang_serap(
                {"nama_paket": nama_paket, "status": r_eval.text}
            )
        except Exception:
            pass

        # 2. Fetch detail dari halaman edit
        jenis_kontrak = ""
        hps_str = ""
        _hps_live = {}
        metode_pengadaan = ""
        viewdraft = {}
        edit_html = ""
        try:
            r_edit = requests.get(
                f"{base_url}nontender/{kode_paket}/edit",
                headers=headers, timeout=15
            )
            edit_html = r_edit.text
            jenis_kontrak = _parse_jenis_kontrak_dari_edit(edit_html)
            metode_pengadaan = _parse_metode_pengadaan_dari_edit(edit_html)
        except Exception as e:
            errors.append(f"{kode_paket}: gagal fetch edit — {e}")

        try:
            from pl_engine import _scrape_viewdraftpl
            viewdraft = _scrape_viewdraftpl(kode_paket, headers, base_url)
        except Exception as e:
            errors.append(f"{kode_paket}: gagal fetch viewdraft — {e}")

        # Nama PPK di halaman detail SPSE adalah sumber paket. Jangan biarkan
        # jalur PK mengosongkan field ini sementara jalur JKK mengisinya.
        nama_ppk = ""
        try:
            from pl_engine import _lookup_nama_ppk_lengkap, _parse_nama_ppk_dari_view
            r_view = requests.get(
                f"{base_url}nontender/{kode_paket}",
                headers=headers, timeout=15,
            )
            nama_ppk = _parse_nama_ppk_dari_view(r_view.text)
            if nama_ppk:
                nama_ppk = _lookup_nama_ppk_lengkap(nama_ppk)
        except Exception as e:
            errors.append(f"{kode_paket}: gagal fetch PPK — {e}")

        # HPS/Pagu wajib berasal dari halaman HPS live, bukan nilai stale di edit.
        try:
            from hps_engine import scrape_hps_pl
            _hps_live = scrape_hps_pl(kode_paket)
            hps_str = _hps_live.get("nilai_hps", "")
        except Exception as e:
            errors.append(f"{kode_paket}: gagal scrape HPS live — {e}")

        # 3. Deteksi jenis PL (dari metode, fallback nama)
        jenis_pl = _derive_jenis_pl_dari_metode(metode_pengadaan, nama_paket)

        data = {
            "kode_paket":        kode_paket,
            "id_nontender":      id_nontender,
            "nama_paket":        nama_paket,
            "satker":            satker,
            "nilai_hps":         hps_str,
            "jenis_pl":          jenis_pl,
            "jenis_kontrak":     jenis_kontrak,
            "metode_pengadaan":  metode_pengadaan,
            "status":            status_spse.lower() if status_spse else "draft",
            "is_ulang":          is_ulang,
            "tahap_spse":        tahap_map.get(kode_paket),
            "diambil_pada":      datetime.now(timezone.utc).isoformat(),
        }

        # Boundary refresh paket: field hasil parsing harus diganti penuh.
        # Upsert parsial tanpa reset akan membawa SBU/personil/provider dari
        # donor atau paket sebelumnya saat parser baru belum menemukan data.
        for _field in (
            "nama_ppk", "nip_ppk", "no_sk_ppk", "sbu_baru", "sbu_lama",
            "jabatan_teknis", "skk_teknis", "jabatan_k3", "skk_k3",
            "dpa_nomor", "sub_kegiatan", "nama_file_uraian", "mak",
            "nama_penyedia", "npwp_penyedia", "personil_json",
            "nomor_nota_dinas", "nomor_rekomendasi", "tgl_rekomendasi",
            "uraian_singkat", "masa_berlaku",
        ):
            data[_field] = None

        if viewdraft.get("sumber_anggaran"):
            data["sumber_anggaran"] = viewdraft["sumber_anggaran"]
        if viewdraft.get("lokasi"):
            data["lokasi"] = viewdraft["lokasi"]
        if nama_ppk:
            data["nama_ppk"] = nama_ppk

        if _hps_live.get("nilai_pagu"):
            data["nilai_pagu"] = _hps_live["nilai_pagu"]

        try:
            _sb().table("draft_paket_pl").upsert(data, on_conflict="kode_paket").execute()
            scraped += 1
        except Exception as e:
            errors.append(f"{kode_paket}: gagal upsert — {e}")

    log(f"Selesai: {scraped} paket disimpan, {len(errors)} error")

    # 4. Auto set Usaha Kecil (kualifikasiId=21) untuk semua paket
    log("Set Usaha Kecil hanya untuk paket berstatus Draft...")
    for row in rows:
        kode = str(row[5])
        status = str(row[2] or "").lower()
        tahap = str(tahap_map.get(kode) or "").lower()
        if "draft" not in status or any(k in tahap for k in _TAHAP_SELESAI_KEYWORDS):
            log(f"  Skip kualifikasi {kode}: status={status or '-'}, tahap={tahap or '-'}")
            continue
        ok_kual = set_kualifikasi_usaha_pl(kode, headers, base_url)
        log(f"  Set Usaha Kecil {kode}: {'OK' if ok_kual else 'GAGAL'}")

    return {
        "ok": not errors,
        "scraped": scraped,
        "withdrawn": reconciliation.get("withdrawn", 0),
        "skipped": len(_skipped_rows),
        "errors": errors,
    }


def set_kualifikasi_usaha_pl(kode_paket: str, headers: dict, base_url: str) -> bool:
    """
    Set kualifikasi usaha ke Kecil (kualifikasiId=21) via POST /nontender/{kode}/simpan.
    headers: dict Cookie+User-Agent (sudah siap dari serap).
    Return True jika 302 redirect (sukses), False jika gagal.
    """
    import requests
    from bs4 import BeautifulSoup

    try:
        # Ambil authenticityToken dari halaman edit
        r_edit = requests.get(
            f"{base_url}nontender/{kode_paket}/edit",
            headers=headers, timeout=15,
        )
        soup = BeautifulSoup(r_edit.text, "html.parser")
        token_input = soup.find("input", {"name": "authenticityToken"})
        if not token_input:
            return False
        token = token_input.get("value", "")

        # POST simpan
        post_headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "authenticityToken": token,
            "kualifikasiId": "21",   # 21 = Kecil
            "pl.oap": "1",
        }
        r_post = requests.post(
            f"{base_url}nontender/{kode_paket}/simpan",
            headers=post_headers,
            data=payload,
            timeout=15,
            allow_redirects=False,
        )
        return r_post.status_code in (301, 302)
    except Exception:
        return False


# Mapping metode pengadaan → (kategoriId, pilih)
METODE_PL_MAP = {
    "Pengadaan Barang — PL":              (0, 0),
    "Pekerjaan Konstruksi — PL":          (2, 3),
    "JKK Non-Konstruksi — PL":           (1, 9),
    "JKK Konstruksi — PL":               (5, 17),
    "JKK Perorangan Non-Konstruksi — PL": (4, 13),
    "JKK Perorangan Konstruksi — PL":    (6, 21),
    "Jasa Lainnya — PL":                 (3, 6),
    "PK Terintegrasi — PL":              (7, 25),
}


def umumkan_paket_pl(kode_paket: str, cookie_str: str) -> dict:
    """Umumkan paket PK memakai endpoint shared non-tender yang sudah teruji."""
    from pl_engine import umumkan_paket_pl as _umumkan
    return _umumkan(kode_paket, cookie_str)


def ubah_metode_pl(
    kode_paket: str,
    kategori_id: int,
    pilih: int,
    cookie_str: str,
    base_url: str,
    debug: bool = False,
) -> bool:
    """
    Ubah metode pengadaan via POST /nontender/{kode}/metodesubmit.
    Return True jika 302/200, False jika gagal.
    debug=True: print status + body + semua form fields untuk investigasi.
    """
    import requests
    from bs4 import BeautifulSoup

    _UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15"
    headers = {"Cookie": cookie_str, "User-Agent": _UA}
    try:
        r_form = requests.get(
            f"{base_url}nontender/{kode_paket}/metode",
            headers=headers, timeout=15,
        )
        soup = BeautifulSoup(r_form.text, "html.parser")

        if debug:
            # Dump semua input fields dari form /metode
            print(f"\n=== DEBUG ubah_metode_pl({kode_paket}) ===")
            print(f"GET /metode status: {r_form.status_code}")
            for inp in soup.find_all(["input", "select", "textarea"]):
                print(f"  field: name={inp.get('name')} type={inp.get('type')} value={inp.get('value','')}")
            # Dump radio/option pilih
            for opt in soup.find_all("option"):
                print(f"  option: value={opt.get('value')} text={opt.get_text(strip=True)}")
            # Dump form action
            for frm in soup.find_all("form"):
                print(f"  form: action={frm.get('action')} method={frm.get('method')}")
            # Dump title + tombol submit (cek onsubmit/onclick)
            title = soup.find("title")
            print(f"  page title: {title.get_text() if title else '(none)'}")
            for btn in soup.find_all(["button", "input"], type=lambda t: t in (None, "submit")):
                print(f"  btn: name={btn.get('name')} onclick={btn.get('onclick','')[:100]} onsubmit={btn.get('onsubmit','')}")
            for frm2 in soup.find_all("form"):
                print(f"  form onsubmit: {frm2.get('onsubmit','')[:100]}")
            # Dump raw HTML di sekitar select kategoriId (800 char)
            import re as _re
            m_sel = _re.search(r'(?s)(kategoriId.{0,800})', r_form.text)
            if m_sel:
                print(f"  HTML snippet kategoriId:\n{m_sel.group(1)[:800]}")
            # Dump POST response body (ikuti redirect)
            print(f"  === IKUTI REDIRECT ===")
            r_follow = requests.get(
                f"{base_url}nontender/{kode_paket}/edit",
                headers=headers, timeout=15,
            )
            soup2 = BeautifulSoup(r_follow.text, "html.parser")
            m2 = _re.search(r"Metode Pengadaan\s+(.+?)(?:Kualifikasi|$)", soup2.get_text(" ", strip=True))
            print(f"  Metode setelah POST: {m2.group(1)[:80] if m2 else '(tidak ketemu)'}")

        token_input = soup.find("input", {"name": "authenticityToken"})
        if not token_input:
            if debug:
                print("  ERROR: authenticityToken tidak ditemukan!")
                print(r_form.text[:500])
            return False
        token = token_input.get("value", "")

        post_headers = {
            **headers,
            "Referer": f"{base_url}nontender/{kode_paket}/edit",
            "Origin": "https://spse.inaproc.id",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "cache-control": "max-age=0",
            "priority": "u=0, i",
        }
        # Wajib multipart/form-data + field simpan=simpan (browser behavior)
        payload = {
            "authenticityToken": token,
            "kategoriId": str(kategori_id),
            "pilih": str(pilih),
            "simpan": "simpan",
        }

        if debug:
            print(f"  POST payload (multipart): {payload}")

        r_post = requests.post(
            f"{base_url}nontender/{kode_paket}/metodesubmit",
            headers=post_headers,
            files={k: (None, v) for k, v in payload.items()},  # multipart/form-data
            timeout=15,
            allow_redirects=False,
        )

        if debug:
            print(f"  POST status: {r_post.status_code}")
            print(f"  POST Location: {r_post.headers.get('Location','')}")
            print(f"  POST body (500 char): {r_post.text[:500]}")

        return r_post.status_code in (200, 301, 302)
    except Exception as e:
        if debug:
            print(f"  EXCEPTION: {e}")
        return False


def ubah_metode_pl_playwright(
    kode_paket: str,
    kategori_id: int,
    pilih: int,
    base_url: str,
) -> bool:
    """Ubah metode via Playwright CDP (handle JS confirm). Preferred over requests."""
    import spse_browser
    hasil = spse_browser.ubah_metode_via_playwright(kode_paket, kategori_id, pilih, base_url)
    return hasil == "OK"


def debug_ubah_metode_pl(kode_paket: str, cookie_str: str, base_url: str) -> str:
    """
    Helper debug: jalankan ubah_metode JKK Konstruksi dengan debug=True.
    Return string log untuk ditampilkan di UI.
    """
    import io, sys
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    ubah_metode_pl(kode_paket, 5, 9, cookie_str, base_url, debug=True)
    sys.stdout = old_stdout
    return buf.getvalue()


def ubah_ke_jkk_konstruksi_pl(kode_paket: str, cookie_str: str, base_url: str) -> bool:
    """Shortcut: ubah metode ke JKK Konstruksi PL (kategoriId=5, pilih=17) via CDP Playwright."""
    return ubah_metode_pl_playwright(kode_paket, 5, 17, base_url)


# ============================================================
# Download Dokumen Paket PL dari SPSE
# ============================================================

# Map label endpoint → subfolder rapi (dibuat on-demand saat ada file)
SUBFOLDER_DOK_PPK = {
    "KAK & Personil":            "1. KAK & Spesifikasi Teknis",
    "Rancangan Kontrak":         "2. Rancangan Kontrak",
    "Uraian Singkat Pekerjaan":  "3. Uraian Singkat Pekerjaan",
    "Informasi Lainnya":         "4. Informasi Lainnya",
    "Nota Dinas PPK":            "4. Informasi Lainnya",
}


def buat_subfolder_dokumen(folder_paket: str) -> list:
    """Buat semua subfolder dokumen di folder_paket. Return list subfolder yang baru dibuat."""
    dibuat = []
    subfolder_unik = list(dict.fromkeys(SUBFOLDER_DOK_PPK.values()))
    for sub in subfolder_unik:
        p = os.path.join(folder_paket, sub)
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            dibuat.append(sub)
    for extra in [
        "5. Evaluator Kualifikasi & Teknis",
        "10. Revisi Uploadan PPK",
        XML_DATA_SUBFOLDER,
    ]:
        p = os.path.join(folder_paket, extra)
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            dibuat.append(extra)
    return dibuat


def download_dokumen_paket_pl(
    kode_paket: str,
    folder_tujuan: str,
    progress_cb=None,
    cookie_str: str = "",
    skip_merge: bool = False,
    force_clean: bool = False,
    per_file_workers: int = 1,
    download_timeout: int = 60,
) -> dict:
    """
    Download dokumen dari endpoint non-tender PP ke folder_tujuan:
      - /dokumennontender/{kode}/spek  → KAK, Daftar Personil, RAB
      - /dokumennontender/{kode}/docsskk → Rancangan SPK/SPMK/SSUK/SSKK

    Pakai cookie PP via spse_browser.get_spse_cookies() — bisa juga di-pass
    eksplisit lewat parameter cookie_str (untuk paralel: hindari race init Playwright).

    skip_merge=True: lewati gabung PDF (Excel COM tidak thread-safe untuk paralel).
                     Merge dilakukan sequential setelah pool selesai via gabung_draft_pl().

    force_clean=True: hapus file lama hanya di subfolder dokumen pada
                      SUBFOLDER_DOK_PPK sebelum download ulang. Root folder,
                      template, dan 0. Draft Dokumen PPK tidak disentuh.

    Return: {"ok": [...], "error": [...]}
    """
    import requests
    import urllib.parse
    import time
    from bs4 import BeautifulSoup
    import spse_browser

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    os.makedirs(folder_tujuan, exist_ok=True)
    hasil = {"ok": [], "error": []}

    if force_clean:
        for sub_name in SUBFOLDER_DOK_PPK.values():
            sub_path = os.path.join(folder_tujuan, sub_name)
            if not os.path.isdir(sub_path):
                continue
            for name in os.listdir(sub_path):
                path = os.path.join(sub_path, name)
                if os.path.isfile(path):
                    os.remove(path)

    if not cookie_str:
        cookie_str = spse_browser.get_spse_cookies()
    if not cookie_str:
        hasil["error"].append("Cookie SPSE kosong — buka Brave SPSE dan login ulang.")
        return hasil

    hdrs = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{BASE_URL}/admin/pegawai",
    }

    def _unique_dst(folder, fname):
        fname = _safe_download_name_for_folder(folder, fname)
        dst = os.path.join(folder, fname)
        if not os.path.exists(dst):
            return dst
        base, ext = os.path.splitext(fname)
        n = 2
        while True:
            candidate_name = _safe_download_name_for_folder(folder, f"{base}_{n}{ext}")
            candidate = os.path.join(folder, candidate_name)
            if not os.path.exists(candidate):
                return candidate
            n += 1

    def _fix_customhostname_url(url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname != "customhostname":
            return url, hdrs
        path = parsed.path if parsed.path.startswith("/lpse-prod-data/") else "/lpse-prod-data" + parsed.path
        fixed = urllib.parse.urlunsplit((parsed.scheme, "storage.googleapis.com", path, parsed.query, parsed.fragment))
        fixed_hdrs = {k: v for k, v in hdrs.items() if k.lower() not in ("cookie", "host")}
        log("    ↪ customhostname → storage.googleapis.com/lpse-prod-data")
        return fixed, fixed_hdrs

    def _get_download_response(url):
        current = url
        for _ in range(5):
            current, req_hdrs = _fix_customhostname_url(current)
            resp = requests.get(current, headers=req_hdrs, timeout=download_timeout, stream=True, allow_redirects=False)
            if resp.status_code not in (301, 302, 303, 307, 308):
                return resp
            loc = resp.headers.get("Location")
            if not loc:
                return resp
            current = urllib.parse.urljoin(current, loc)
        current, req_hdrs = _fix_customhostname_url(current)
        return requests.get(current, headers=req_hdrs, timeout=download_timeout, stream=True, allow_redirects=False)

    def _get_download_response_retry(url):
        for i, delay in enumerate((0, 0.7, 1.5), start=1):
            if delay:
                time.sleep(delay)
            resp = _spse_retry_call(
                lambda: _get_download_response(url),
                requests,
                log=log,
                label="file",
            )
            if resp.status_code not in (404, 429, 500, 502, 503, 504):
                return resp
            if i < 3:
                resp.close()
                log(f"    ↻ retry download {i}/2 (HTTP {resp.status_code})")
        return resp

    def _download_links_dari_endpoint(endpoint_url, label):
        """Scrape link /dl/ dari endpoint, download semua file ke subfolder rapi."""
        r = None
        try:
            r = _spse_retry_call(
                lambda: requests.get(endpoint_url, headers=hdrs, timeout=30),
                requests,
                log=log,
                label=label,
            )
            if r.status_code in (401, 403) or r.status_code >= 500:
                err = f"HTTP {r.status_code} — sesi SPSE tidak valid atau server gagal"
                hasil["error"].append(f"{label}: {err}")
                log(f"  ❌ {label}: {err}")
                return
            r.raise_for_status()
            response_text = r.text
            soup = BeautifulSoup(response_text, "html.parser")
            lowered = response_text.lower()
            response_path = urllib.parse.urlsplit(getattr(r, "url", endpoint_url)).path.lower().rstrip("/")
            login_page = response_path.endswith("/login") or any(
                marker in lowered
                for marker in ("name=\"username\"", "id=\"username\"", "silakan login")
            )
            if login_page:
                err = "Sesi SPSE tidak valid — server mengembalikan halaman login"
                hasil["error"].append(f"{label}: {err}")
                log(f"  ❌ {label}: {err}")
                return
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/dl/" not in href:
                    continue
                fname_raw = a.get_text(strip=True)
                fname_raw = re.sub(r"\s*-\s*\d+\s*[KkMm][Bb]\s*$", "", fname_raw, re.IGNORECASE).strip()
                fname = re.sub(r'[<>:"/\\|?*]', "_", fname_raw).strip() or "dokumen"
                url_dl = f"https://spse.inaproc.id{href}" if href.startswith("/") else href
                links.append((url_dl, fname))

            # Subfolder tujuan (on-demand: dibuat hanya jika ada file)
            sub = SUBFOLDER_DOK_PPK.get(label, "4. Informasi Lainnya")
            folder_dl = os.path.join(folder_tujuan, sub)
            if links:
                os.makedirs(folder_dl, exist_ok=True)

            log(f"  📂 {label}: {len(links)} file")
            def _download_satu(link):
                url_dl, initial_fname = link

                def _download_once():
                    r_dl = None
                    partial = None
                    fname = initial_fname
                    try:
                        r_dl = _get_download_response_retry(url_dl)
                        r_dl.raise_for_status()
                        cd = r_dl.headers.get("Content-Disposition", "")
                        m_cd = re.search(r'filename[^;=\n]*=["\']?([^"\';\n]+)', cd)
                        if m_cd:
                            clean = re.sub(r'[<>:"/\\|?*]', "_", urllib.parse.unquote_plus(m_cd.group(1).strip())).strip()
                            if clean:
                                fname = clean
                        original_fname = fname
                        fname = _safe_download_name_for_folder(folder_dl, fname)
                        if fname != original_fname:
                            log(f"    ⚠️ nama file dipendekkan ({len(original_fname)}→{len(fname)} karakter): {fname}")
                        with open(_unique_dst(folder_dl, fname) + ".part", "wb") as f:
                            partial = f.name
                            for chunk in r_dl.iter_content(65536):
                                f.write(chunk)
                        dst = partial[:-5]
                        os.replace(partial, dst)
                        partial = None
                        return dst, fname
                    finally:
                        if partial and os.path.exists(partial):
                            os.remove(partial)
                        if r_dl is not None:
                            close = getattr(r_dl, "close", None)
                            if callable(close):
                                close()

                return _spse_retry_call(
                    _download_once,
                    requests,
                    log=log,
                    label=initial_fname,
                )

            for url_dl, fname in links:
                try:
                    dst, final_fname = _download_satu((url_dl, fname))
                    hasil["ok"].append(dst)
                    log(f"    ✅ {os.path.basename(dst)}")
                except Exception as e:
                    hasil["error"].append(f"{fname}: {e}")
                    log(f"    ❌ {fname}: {e}")
        except Exception as e:
            hasil["error"].append(f"{label}: {e}")
            log(f"  ❌ {label}: {e}")
        finally:
            if r is not None:
                close = getattr(r, "close", None)
                if callable(close):
                    close()

    ENDPOINTS = [
        (f"{BASE_URL}/dokumennontender/{kode_paket}/spek",      "KAK & Personil"),
        (f"{BASE_URL}/dokumennontender/{kode_paket}/docsskk",   "Rancangan Kontrak"),
        (f"{BASE_URL}/dokumennontender/{kode_paket}/docuraian", "Uraian Singkat Pekerjaan"),
        (f"{BASE_URL}/dokumennontender/{kode_paket}/lainnya",   "Informasi Lainnya"),
        (f"{BASE_URL}/nontender/{kode_paket}/edit",             "Nota Dinas PPK"),
    ]

    for url_ep, label_ep in ENDPOINTS:
        _download_links_dari_endpoint(url_ep, label_ep)

    log(f"🏁 Download selesai: {len(hasil['ok'])} file OK, {len(hasil['error'])} error")

    # ── Catat basename PDF uraian singkat ke Supabase
    try:
        for fpath in hasil["ok"]:
            bn = os.path.basename(fpath).lower()
            if "uraian" in bn and bn.endswith(".pdf"):
                _sb().table("draft_paket_pl").update(
                    {"nama_file_uraian": os.path.basename(fpath)}
                ).eq("kode_paket", kode_paket).execute()
                log(f"  📝 nama_file_uraian: {os.path.basename(fpath)}")
                break
    except Exception as e:
        log(f"  ⚠ gagal simpan nama_file_uraian: {e}")

    # ── Gabung semua PDF jadi 1 draft (tiru flow tender)
    if not skip_merge:
        try:
            merged = gabung_draft_pl(kode_paket, folder_tujuan, hasil["ok"], progress_cb)
            if merged:
                hasil["draft_pdf"] = merged
                log(f"📎 Draft PDF gabungan: {os.path.basename(merged)}")
        except Exception as e:
            import traceback as _tb
            log(f"❌ Gagal gabung PDF: {e}")
            log(f"   {_tb.format_exc()[-300:]}")
            hasil["error"].append(f"Gabung PDF: {e}")

    return hasil


def gabung_draft_pl(kode_paket: str, folder_tujuan: str, files_ok: list, progress_cb=None) -> str:
    """Standalone gabung PDF — dipanggil sequential setelah bulk parallel download.

    Excel/Word COM tidak thread-safe → harus serial.
    Return: path Draft_PL_*.pdf atau "" jika gagal.
    """
    from inbox_engine import _gabung_pdf_draft

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    nama_paket_row = _sb().table("draft_paket_pl").select("nama_paket").eq(
        "kode_paket", kode_paket
    ).maybe_single().execute()
    nama_paket = (nama_paket_row.data or {}).get("nama_paket", kode_paket) if nama_paket_row else kode_paket
    nama_clean = re.sub(r'[<>:"/\\|?*]', "_", nama_paket)[:60].strip()
    # Draft gabungan adalah artefak PPK; simpan bersama draft dokumen lain.
    # Jangan taruh di root paket karena root dipakai untuk template/metadata.
    draft_dir = os.path.join(folder_tujuan, "0. Draft Dokumen PPK")
    os.makedirs(draft_dir, exist_ok=True)
    draft_path = os.path.join(draft_dir, f"Draft_PL_{nama_clean}.pdf")
    ordered = sorted(files_ok, key=lambda p: _pl_pdf_sort_key(os.path.basename(p)))
    return _gabung_pdf_draft(draft_path, ordered, progress_cb)


def _pl_pdf_sort_key(fname: str) -> tuple:
    """Urutan gabung draft PL: KAK → RAB/Personil → Rancangan → Uraian → Lainnya → Nota."""
    f = fname.lower()
    if "kak" in f: return (0, f)
    if "rab" in f: return (1, f)
    if "personil" in f or "personel" in f: return (2, f)
    if "rincian" in f or "prn" in f: return (3, f)
    if "rancangan" in f or "sskk" in f or "ssuk" in f or "spk" in f or "spmk" in f: return (4, f)
    if "uraian" in f: return (5, f)
    if "rekomendasi" in f or "lainnya" in f: return (6, f)
    if "permohonan" in f or "nota" in f: return (7, f)
    return (9, f)
