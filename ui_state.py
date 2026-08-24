"""State lifecycle Streamlit per mode.

State widget lama tetap dipertahankan agar kompatibel, tetapi transient state
dibersihkan saat user berpindah mode. Data hasil baca/cache tidak disentuh.
"""

from __future__ import annotations

import re
import time
from typing import Any

import streamlit as st


_MODE_SLUG = {
    "Tender": "tender",
    "PL - Konsultansi": "pl_jkk",
    "PL - Konstruksi": "pl_pk",
    "PPK - Upload Dokumen": "ppk",
    "PPK - Konsultan": "ppk_jkk",
    "PPK - Pekerjaan Konstruksi": "ppk_pk",
    "E-Katalog - Survei Pasar": "ekatalog",
}

# Widget/action state yang aman dibuang ketika mode berubah. Data loader/cache
# sengaja tidak masuk daftar ini karena dapat dipakai ulang pada mode berikut.
_TRANSIENT_PREFIXES = (
    "pl7_", "pl8_", "pl_dpa_", "pl_ubah_", "pl_btn_", "pl_excel_",
    "pl_dl_", "pl_hps_", "plf_", "pljd_", "plsp_", "pp_chk_", "kd_chk_",
    "tender_", "ba_", "kl_", "dp_", "ppk_",
)
_TRANSIENT_EXACT = {
    "pl_show_done", "pl_filter_jenis", "pl7_rows", "pl7_checked",
    "pl8_rows", "pl8_checked",
}


def mode_slug(mode: str | None) -> str:
    return _MODE_SLUG.get(str(mode or ""), re.sub(r"[^a-z0-9]+", "_", str(mode or "unknown").lower()).strip("_"))


def _is_transient(key: str) -> bool:
    # Detail metadata SPSE dapat dipakai ulang saat berpindah submode PPK;
    # logout/refresh eksplisit tetap membersihkannya dari app.py.
    if key.startswith("ppk_detail_"):
        return False
    return key in _TRANSIENT_EXACT or key.startswith(_TRANSIENT_PREFIXES)


def activate_mode(mode: str) -> bool:
    """Aktifkan mode dan bersihkan state UI transient dari mode sebelumnya.

    Return True bila terjadi perpindahan mode. Fungsi idempotent pada rerun.
    """
    previous = st.session_state.get("_workflow_active_mode")
    changed = previous is not None and previous != mode
    if changed:
        for key in list(st.session_state.keys()):
            if _is_transient(str(key)):
                st.session_state.pop(key, None)
    st.session_state["_workflow_active_mode"] = mode
    st.session_state["_workflow_mode_slug"] = mode_slug(mode)
    return changed


def restore_selection_from_query(state_key: str, options: list[str], query_key: str) -> None:
    """Restore one select/radio value after browser refresh, if still valid."""
    if state_key in st.session_state:
        return
    try:
        raw = st.query_params.get(query_key, "")
    except Exception:
        return
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    raw = str(raw or "")
    if raw in options:
        st.session_state[state_key] = raw
        return
    try:
        index = int(raw)
    except (TypeError, ValueError):
        return
    if 0 <= index < len(options):
        st.session_state[state_key] = options[index]


def persist_selection_to_query(value: str, options: list[str], query_key: str) -> None:
    """Persist a valid select/radio value in URL query params."""
    try:
        index = options.index(value)
        if str(st.query_params.get(query_key, "")) != str(index):
            st.query_params[query_key] = str(index)
    except (AttributeError, TypeError, ValueError):
        # Older Streamlit/test doubles may not expose query params.
        pass


def invalidate_ppk_session_state(clear_navigation: bool = True) -> None:
    """Bersihkan state PPK; navigasi boleh dipertahankan saat cookie berotasi."""
    st.session_state["_spse_session_epoch"] = time.time_ns()
    for key in list(st.session_state.keys()):
        if str(key).startswith("ppk_"):
            st.session_state.pop(key, None)
    if clear_navigation:
        st.session_state.pop("active_ppk_upload_package", None)


def package_key(mode: str, kode: Any, name: str) -> str:
    """Buat key stabil untuk state per paket/per aksi."""
    safe_mode = mode_slug(mode)
    safe_kode = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(kode or "unknown"))
    return f"{safe_mode}:{safe_kode}:{name}"


def ppk_upload_expander_label(label: str, active: bool) -> str:
    """Beri identitas render berbeda agar expander aktif terbuka setelah rerun."""
    return f"{'🔽' if active else '▶️'} {label}"
