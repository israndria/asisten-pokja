"""Loader/cache data PL untuk UI Streamlit.

Memisahkan I/O read-only dari renderer mode agar rerun widget tidak mengulang
query SPSE/Supabase dan supaya JKK/PK memiliki cache key yang eksplisit.
"""

from __future__ import annotations

import os

import streamlit as st


@st.cache_data(ttl=300, show_spinner=False)
def fetch_status_semua_paket_cached(kode_tuple: tuple) -> dict:
    """Ambil status peserta PL secara batch; cache 5 menit."""
    try:
        import peserta_monitor_pl
        return peserta_monitor_pl.fetch_status_semua_paket(list(kode_tuple))
    except Exception:
        return {}


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
    """Gunakan C51:C52 Excel sebagai fallback identitas authoritative lokal."""
    from pl_ui_helpers import _baca_identitas_penyedia_pl

    result = []
    for row in rows or []:
        current = dict(row)
        if not current.get("nama_penyedia") or not current.get("npwp_penyedia"):
            identity = _baca_identitas_penyedia_pl(current)
            for key in ("nama_penyedia", "npwp_penyedia"):
                if identity.get(key) and not current.get(key):
                    current[key] = identity[key]
        result.append(current)
    return result


def _hydrate_dokpil_from_excel(rows: list[dict]) -> list[dict]:
    """Timpa metadata Dokpil dari workbook lokal tiap paket.

    Ini menutup cache Supabase lama yang pernah menyimpan nomor hasil parser
    PDF, termasuk nomor dengan tanda ?. Jika C20 kosong/invalid, nomor
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
def load_draft_pl_cached(engine_kind: str = "JKK", only_local: bool = True) -> list:
    """Load draft PL; cache terpisah dan gate disk untuk tab operasional."""
    if str(engine_kind).upper() == "PK":
        import pl_engine_plpk as engine
    else:
        import pl_engine as engine
    rows = engine.load_draft_pl()
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
        rows = filter_local_pl_rows(rows)
        return _hydrate_provider_from_excel(rows), ""
    except Exception as exc:
        return [], str(exc)
