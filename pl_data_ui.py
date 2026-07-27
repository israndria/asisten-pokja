"""Loader/cache data PL untuk UI Streamlit.

Memisahkan I/O read-only dari renderer mode agar rerun widget tidak mengulang
query SPSE/Supabase dan supaya JKK/PK memiliki cache key yang eksplisit.
"""

from __future__ import annotations

import streamlit as st


@st.cache_data(ttl=300, show_spinner=False)
def fetch_status_semua_paket_cached(kode_tuple: tuple) -> dict:
    """Ambil status peserta PL secara batch; cache 5 menit."""
    try:
        import peserta_monitor_pl
        return peserta_monitor_pl.fetch_status_semua_paket(list(kode_tuple))
    except Exception:
        return {}


@st.cache_data(ttl=60, show_spinner=False)
def load_draft_pl_cached(engine_kind: str = "JKK") -> list:
    """Load draft PL dengan cache terpisah untuk JKK dan PK."""
    if str(engine_kind).upper() == "PK":
        import pl_engine_plpk as engine
    else:
        import pl_engine as engine
    rows = engine.load_draft_pl()
    # PK engine tidak mendefinisikan helper display ini; gunakan helper shared
    # agar label/nomor folder tetap identik dengan workflow JKK.
    from pl_engine import _hydrate_nomor_urut_folder
    hydrate = _hydrate_nomor_urut_folder
    return hydrate(rows) if hydrate and any(not r.get("nomor_urut") for r in rows) else rows


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
            "status_undangan_verifikasi, is_ulang, jenis_pl, tahap_spse"
        ).order("kode_paket").execute().data or []
        return rows, ""
    except Exception as exc:
        return [], str(exc)
