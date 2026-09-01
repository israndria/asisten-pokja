"""Komponen UI yang dipakai bersama mode PLJKK dan PLPK."""

import json
import re
from pathlib import Path


_PL7_ACTION_KEYS = ("download", "parse", "parse_eval", "hps")
_PL7_ACTION_LABELS = {
    "download": "Download Kualifikasi",
    "parse": "Parse & Populate",
    "parse_eval": "Parse @ Evaluasi",
    "hps": "Update HPS",
}
_PL7_BACKFILL_PATH = Path(__file__).resolve().parent / "data" / "pl7_action_status_backfill.json"


def _load_pl7_action_backfill(path: Path = _PL7_BACKFILL_PATH) -> dict:
    """Baca daftar backfill historis yang sengaja dibatasi pada kode terverifikasi."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def apply_pl7_historical_backfill(state, family: str, rows: list[dict]) -> int:
    """Pulihkan status aksi historis tanpa menandai paket baru otomatis.

    Backfill hanya berlaku jika kode paket ada di daftar versioned dan sedang
    tampil pada keluarga yang sama. Idempoten; status sukses yang sudah ada
    tidak diturunkan atau ditimpa.
    """
    family_key = str(family or "PL").strip().upper()
    row_codes = {
        str(row.get("kode_paket") or "").strip()
        for row in (rows or [])
        if isinstance(row, dict)
    }
    records = _load_pl7_action_backfill().get(family_key) or {}
    if not row_codes or not isinstance(records, dict):
        return 0

    status_by_code = state.setdefault(f"pl7_action_status_{family_key}", {})
    changed = 0
    for kode, record in records.items():
        kode = str(kode or "").strip()
        if not kode or kode not in row_codes or not isinstance(record, dict):
            continue
        entry = dict(status_by_code.get(kode) or {})
        entry_changed = False
        for action in _PL7_ACTION_KEYS:
            if record.get(action) is True and entry.get(action) is not True:
                entry[action] = True
                entry_changed = True
        if entry_changed:
            status_by_code[kode] = entry
            changed += 1
    return changed


def mark_pl7_action_success(
    state, family: str, kode_paket: str, action: str, detail: str = ""
) -> None:
    """Catat aksi Tab 7 hanya setelah engine mengembalikan ``ok``."""
    action = str(action or "").strip().lower()
    kode = str(kode_paket or "").strip()
    if not kode or action not in _PL7_ACTION_KEYS:
        return

    family_key = str(family or "PL").strip().upper()
    status_key = f"pl7_action_status_{family_key}"
    status_by_code = state.setdefault(status_key, {})
    entry = dict(status_by_code.get(kode) or {})
    entry[action] = True
    if detail:
        entry[f"{action}_detail"] = str(detail)
    status_by_code[kode] = entry


def summarize_pl7_action_status(
    rows: list[dict], state, family: str, label_fn
) -> list[dict]:
    """Bangun status per paket tanpa menebak sukses dari file/folder."""
    family_key = str(family or "PL").strip().upper()
    status_by_code = state.get(f"pl7_action_status_{family_key}") or {}
    result = []
    for row in rows or []:
        kode = str(row.get("kode_paket") or "").strip()
        entry = status_by_code.get(kode) or {}
        completed = [
            _PL7_ACTION_LABELS[action]
            for action in _PL7_ACTION_KEYS
            if entry.get(action) is True
        ]
        result.append(
            {
                "Paket": label_fn(row),
                "Download Kualifikasi": "✅" if entry.get("download") else "—",
                "Parse & Populate": "✅" if entry.get("parse") else "—",
                "Parse @ Evaluasi": "✅" if entry.get("parse_eval") else "—",
                "Update HPS": "✅" if entry.get("hps") else "—",
                "Status Paket": "Sudah ada aksi sukses" if completed else "Belum diproses",
                "_aksi_sukses": tuple(completed),
                "_kode_paket": kode,
            }
        )
    return result


def render_pl7_action_summary(st, rows: list[dict], state, family: str, label_fn) -> None:
    """Tampilkan paket terproses dan belum diproses di bawah aksi Tab 7."""
    apply_pl7_historical_backfill(state, family, rows)
    summary = summarize_pl7_action_status(rows, state, family, label_fn)
    if not summary:
        return

    processed = [row for row in summary if row["_aksi_sukses"]]
    untouched = [row for row in summary if not row["_aksi_sukses"]]
    st.divider()
    st.markdown("### Status Aksi Paket")
    st.caption(
        "Status berasal dari aksi sukses atau backfill historis terverifikasi. "
        "Tanda ✅ menunjukkan aksi yang sudah sukses."
    )
    metric_done, metric_todo = st.columns(2)
    metric_done.metric("Sudah ada aksi sukses", len(processed))
    metric_todo.metric("Belum ada aksi sukses", len(untouched))

    def _table(rows_to_render):
        return [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in rows_to_render
        ]

    if processed:
        st.markdown("#### ✅ Paket sudah diproses")
        st.dataframe(_table(processed), use_container_width=True, hide_index=True)
    if untouched:
        st.markdown("#### ⏳ Paket belum diproses")
        st.dataframe(_table(untouched), use_container_width=True, hide_index=True)


def render_package_selection(st, rows: list[dict], label_fn, prefix: str = "pl7") -> list[dict]:
    """Render checklist paket dan return row terpilih."""
    checked_key = f"{prefix}_checked"
    if checked_key not in st.session_state:
        st.session_state[checked_key] = {}

    codes = [row["kode_paket"] for row in rows]
    for code in codes:
        widget_key = f"{prefix}_chk_{code}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = True

    select_col, clear_col = st.columns(2)
    if select_col.button("✅ Pilih Semua", key=f"{prefix}_select_all", use_container_width=True):
        for code in codes:
            st.session_state[f"{prefix}_chk_{code}"] = True
            st.session_state[checked_key][code] = True
    if clear_col.button("❌ Batal Semua", key=f"{prefix}_deselect_all", use_container_width=True):
        for code in codes:
            st.session_state[f"{prefix}_chk_{code}"] = False
            st.session_state[checked_key][code] = False

    for row in rows:
        code = row["kode_paket"]
        # Streamlit merender ``80. Nama Paket`` sebagai ordered-list Markdown.
        # Escape titik hanya pada label checkbox; nilai/key tetap asli.
        label = re.sub(r"^(\d+)\.(\s+)", r"\1\\.\2", str(label_fn(row)), count=1)
        checked = st.checkbox(label, key=f"{prefix}_chk_{code}")
        st.session_state[checked_key][code] = checked
    return [row for row in rows if st.session_state[checked_key].get(row["kode_paket"])]
