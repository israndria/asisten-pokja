"""Loader/cache data PL untuk UI Streamlit.

Memisahkan I/O read-only dari renderer mode agar rerun widget tidak mengulang
query SPSE/Supabase dan supaya JKK/PK memiliki cache key yang eksplisit.
"""

from __future__ import annotations

import os
import time

import streamlit as st

_LOCAL_DRAFT_CACHE_VERSION = "folder-identity-v3-family-gate"
_PL_UMUMKAN_STATUS_KEY = "pl_umumkan_status"
_PUBLISH_DONE_MARKERS = (
    "sudah diumumkan",
    "diumumkan",
    "pengumuman",
    "berjalan",
    "aktif",
    "published",
)
_PUBLISH_NEGATIVE_MARKERS = (
    "belum",
    "draft",
    "gagal",
    "ditolak",
    "batal",
    "ditarik",
    "tidak aktif",
    "nonaktif",
)
_PUBLISH_PRESTART_STAGE = "paket belum dilaksanakan"


def _publish_status_text_is_done(value) -> bool:
    """True jika teks status menunjukkan paket sudah melewati tahap draft."""
    text = str(value or "").strip().lower()
    if not text or any(marker in text for marker in _PUBLISH_NEGATIVE_MARKERS):
        return False
    return any(marker in text for marker in _PUBLISH_DONE_MARKERS)


def get_paket_umumkan_status() -> dict:
    """Ambil status pengumuman lokal tanpa memicu I/O."""
    status = st.session_state.get(_PL_UMUMKAN_STATUS_KEY, {})
    return status if isinstance(status, dict) else {}


def mark_paket_sudah_diumumkan(kode_paket: str, result: dict | None = None) -> None:
    """Simpan bukti POST pengumuman sukses untuk rerun Streamlit saat ini."""
    kode = str(kode_paket or "").strip()
    if not kode:
        return
    status = dict(get_paket_umumkan_status())
    entry = {"status": "sudah diumumkan"}
    if isinstance(result, dict):
        for key in ("status_code", "location"):
            if result.get(key) not in (None, ""):
                entry[key] = result[key]
    status[kode] = entry
    st.session_state[_PL_UMUMKAN_STATUS_KEY] = status


def mark_tahap_spse_sudah_diumumkan(tahap_map: dict) -> int:
    """Salin batch tahap aktif SPSE ke session sebagai status sudah diumumkan."""
    status = dict(get_paket_umumkan_status())
    jumlah = 0
    for kode_paket, tahap in (tahap_map or {}).items():
        kode = str(kode_paket or "").strip()
        tahap_text = str(tahap or "").strip()
        if not kode or not tahap_text:
            continue
        status[kode] = {
            "status": "sudah diumumkan",
            "tahap_spse": tahap_text,
        }
        jumlah += 1
    if jumlah:
        st.session_state[_PL_UMUMKAN_STATUS_KEY] = status
    return jumlah


def is_paket_sudah_diumumkan(row: dict, session_status: dict | None = None) -> bool:
    """Deteksi paket yang sudah diumumkan dari session atau field SPSE."""
    row = row or {}
    kode = str(row.get("kode_paket") or "").strip()
    session_status = session_status if isinstance(session_status, dict) else get_paket_umumkan_status()
    if kode and kode in session_status:
        marker = session_status[kode]
        if marker is True:
            return True
        if isinstance(marker, dict):
            if marker.get("ok") is True:
                return True
            marker = marker.get("status") or marker.get("tahap_spse") or marker.get("pesan")
        if _publish_status_text_is_done(marker):
            return True

    tahap = str(row.get("tahap_spse") or "").strip().lower()
    if tahap == _PUBLISH_PRESTART_STAGE:
        # SPSE memakai label ini untuk paket yang sudah diumumkan/disetujui,
        # tetapi jadwal mulai belum tercapai.
        return True
    if tahap and not any(marker in tahap for marker in _PUBLISH_NEGATIVE_MARKERS):
        # Tahap berikutnya (mis. Upload Dokumen Penawaran) berarti Draft sudah
        # dilewati walau label tahap tidak memuat kata "Pengumuman".
        return True
    return _publish_status_text_is_done(row.get("status"))


def sync_live_paket_umumkan_status(state_key: str, ttl_seconds: float = 60.0) -> dict:
    """Sinkronkan tahap tayang live SPSE secara read-only dengan TTL singkat."""
    now = time.monotonic()
    last_sync = st.session_state.get(state_key)
    if isinstance(last_sync, (int, float)) and now - last_sync < ttl_seconds:
        return {"ok": True, "cached": True, "count": 0}

    st.session_state[state_key] = now
    try:
        import spse_browser
        from config import SPSE_BASE_URL
        import pl_engine as _live_pl_engine

        cookie = spse_browser.get_spse_cookies()
        if not cookie:
            return {"ok": False, "cached": False, "count": 0, "error": "Cookie SPSE kosong"}
        tahap_map = _live_pl_engine._fetch_tahap_spse(cookie, SPSE_BASE_URL)
        count = mark_tahap_spse_sudah_diumumkan(tahap_map)
        return {"ok": True, "cached": False, "count": count}
    except Exception as exc:
        return {"ok": False, "cached": False, "count": 0, "error": str(exc)}


def _filter_pl_family(rows: list[dict], engine_kind: str) -> list[dict]:
    """Batasi row ke family yang diminta; family tidak dikenal ditolak.

    Query Supabase tetap menjadi filter pertama di masing-masing engine, tetapi
    boundary ini wajib ada di loader UI juga. Dengan begitu row JKK yang
    terselip akibat cache/query lama tidak pernah masuk ke mode PK, dan row
    tanpa klasifikasi tidak diasumsikan sebagai salah satu family.
    """
    kind = str(engine_kind or "JKK").strip().upper()
    if kind in {"PK", "PLPK", "KONSTRUKSI", "PL - KONSTRUKSI"}:
        expected = "PK"
    elif kind in {"JKK", "PLJKK", "KONSULTANSI", "PL - KONSULTANSI"}:
        expected = "JKK"
    else:
        return []

    return [
        row for row in (rows or [])
        if str(row.get("jenis_pl") or "").strip().upper() == expected
    ]


@st.cache_data(ttl=300, show_spinner=False)
def fetch_status_semua_paket_cached(kode_tuple: tuple) -> dict:
    """Ambil status peserta PL secara batch; cache 5 menit."""
    try:
        import peserta_monitor_pl
        return peserta_monitor_pl.fetch_status_semua_paket(list(kode_tuple))
    except Exception:
        return {}


def load_status_peserta_on_demand(
    kode_tuple: tuple,
    state_key: str,
    button_key: str,
) -> dict:
    """Muat badge peserta hanya setelah diminta user.

    Tab 1 tidak boleh memblokir perpindahan mode dengan puluhan request SPSE.
    Hasil disimpan di session state agar rerun widget berikutnya tetap ringan;
    tombol sengaja mengosongkan cache supaya refresh benar-benar mengambil data
    terbaru.
    """
    kode = tuple(str(k) for k in kode_tuple if k)
    if not kode:
        return {}

    status = st.session_state.get(state_key)
    if not isinstance(status, dict):
        status = {}

    if st.button("🔄 Muat status peserta", key=button_key, help="Ambil jumlah peserta dari SPSE"):
        fetch_status_semua_paket_cached.clear()
        status = fetch_status_semua_paket_cached(kode)
        st.session_state[state_key] = status
    return status


def filter_local_pl_rows(rows: list[dict]) -> list[dict]:
    """Kembalikan hanya paket yang benar-benar siap di disk lokal.

    ``folder_dibuat`` di Supabase adalah status workflow, bukan bukti bahwa
    folder masih ada di komputer aktif. Tab operasi tidak boleh menampilkan
    row yang statusnya stale, foldernya hilang, atau workbook utama belum ada.
    Bukti lokal (folder + workbook) menjadi sumber gate; status Supabase boleh
    stale atau belum tersimpan tanpa membuat paket fisik yang valid menghilang.
    Tab 1 sengaja dapat memanggil loader dengan ``only_local=False`` agar paket
    baru tetap bisa dipilih untuk proses Create Folder.
    """
    from parse_kak_pl import _resolve_folder_pl
    from pl_ui_helpers import _cari_xlsm_pl

    result = []
    for row in rows or []:
        if not row.get("kode_paket"):
            continue
        try:
            folder, _ = _resolve_folder_pl(
                row.get("nomor_urut"),
                row.get("nama_paket") or "",
                row.get("jenis_pl") or "JKK",
                is_ulang=bool(row.get("is_ulang")),
                strict_name=True,
            )
            xlsm = _cari_xlsm_pl(folder) if folder and os.path.isdir(folder) else None
            if not xlsm or not os.path.isfile(xlsm):
                continue
            enriched = dict(row)
            enriched["_folder_lokal"] = folder
            enriched["_xlsm_lokal"] = xlsm
            result.append(enriched)
        except (OSError, TypeError, ValueError):
            continue
    return result


def _hydrate_provider_from_excel(rows: list[dict]) -> list[dict]:
    """Gunakan cell identitas Excel sebagai nilai authoritative lokal.

    Nilai Excel sengaja menimpa cache Supabase bila tersedia. Ini mencegah
    hasil parser PDF yang keliru (contoh: ``1 Unit``) tampil atau dikirim
    kembali ke SPSE pada Tab 4.
    """
    from pl_ui_helpers import _baca_identitas_penyedia_pl

    result = []
    for row in rows or []:
        current = dict(row)
        identity = _baca_identitas_penyedia_pl(current)
        for key in ("nama_penyedia", "npwp_penyedia"):
            if identity.get(key):
                current[key] = identity[key]
        result.append(current)
    return result


def _hydrate_dokpil_from_excel(rows: list[dict]) -> list[dict]:
    """Timpa metadata Dokpil dari workbook lokal tiap paket.

    Ini menutup cache Supabase lama yang pernah menyimpan nomor hasil parser
    PDF, termasuk nomor dengan tanda ``?``. Jika C20 kosong/invalid, nomor
    dikosongkan dan error disimpan untuk ditampilkan/menahan upload.
    """
    from pl_ui_helpers import _resolve_nomor_dokpil_excel_pl

    result = []
    for row in rows or []:
        current = dict(row)
        resolved = _resolve_nomor_dokpil_excel_pl(current)
        master = resolved.get("master_data") or {}
        if master:
            current["kode_unik"] = str(master.get("kode_unik") or "").strip()
            current["nomor_dokpil"] = resolved.get("nomor_dokpil", "")
            current["tgl_dokpil"] = master.get("tgl_dokpil") or ""
        current["_nomor_dokpil_excel_ok"] = bool(resolved.get("ok"))
        current["_nomor_dokpil_excel_error"] = resolved.get("error", "")
        result.append(current)
    return result


@st.cache_data(ttl=60, show_spinner=False)
def load_draft_pl_cached(
    engine_kind: str = "JKK",
    only_local: bool = True,
    cache_version: str = _LOCAL_DRAFT_CACHE_VERSION,
) -> list:
    """Load draft PL; cache terpisah dan gate disk untuk tab operasional.

    ``cache_version`` dinaikkan saat aturan identitas folder berubah agar hasil
    lama tidak menahan paket yang baru berhasil di-resolve.
    """
    _ = cache_version
    if str(engine_kind).upper() == "PK":
        import pl_engine_plpk as engine
    else:
        import pl_engine as engine
    rows = engine.load_draft_pl()
    # Defense-in-depth: jangan percaya query engine/cache sebagai satu-satunya
    # boundary family. Ini mencegah paket konsultan bocor ke mode konstruksi.
    rows = _filter_pl_family(rows, engine_kind)
    # PK engine tidak mendefinisikan helper display ini; gunakan helper shared
    # agar label/nomor folder tetap identik dengan workflow JKK.
    from pl_engine import _hydrate_nomor_urut_folder
    hydrate = _hydrate_nomor_urut_folder
    rows = hydrate(rows) if hydrate and any(not r.get("nomor_urut") for r in rows) else rows
    if only_local:
        rows = filter_local_pl_rows(rows)
    rows = _hydrate_dokpil_from_excel(rows)
    if only_local:
        rows = _hydrate_provider_from_excel(rows)
    return rows


def clear_draft_pl_cache() -> None:
    """Invalidasi daftar PL setelah serap/update data."""
    load_draft_pl_cached.clear()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_peserta_pl_cached(kode_nontender: str) -> int:
    try:
        import peserta_monitor_pl
        return (peserta_monitor_pl.fetch_jumlah_peserta_pl(kode_nontender) or {}).get("jumlah", 0)
    except Exception:
        return -1


@st.cache_data(ttl=300, show_spinner=False)
def parse_jadwal_pl_cached(kode_paket: str) -> list:
    try:
        import gcal_pl_helper
        return gcal_pl_helper.parse_jadwal_pl_dari_spse(kode_paket) or []
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def load_verifikasi_pl_rows_cached(engine_kind: str = "JKK") -> tuple[list[dict], str]:
    try:
        engine = __import__("pl_engine_plpk" if str(engine_kind).upper() == "PK" else "pl_engine")
        rows = engine._sb().table("draft_paket_pl").select(
            "kode_paket, id_nontender, nama_paket, kode_unik, nama_penyedia, "
            "npwp_penyedia, tgl_negosiasi, tgl_undangan_verifikasi, "
            "status_undangan_verifikasi, is_ulang, jenis_pl, tahap_spse, "
            "folder_dibuat, nomor_urut"
        ).order("kode_paket").execute().data or []
        rows = _filter_pl_family(rows, engine_kind)
        rows = filter_local_pl_rows(rows)
        return _hydrate_provider_from_excel(rows), ""
    except Exception as exc:
        return [], str(exc)
