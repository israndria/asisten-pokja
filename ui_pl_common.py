"""Komponen UI yang dipakai bersama mode PLJKK dan PLPK."""


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
        checked = st.checkbox(label_fn(row), key=f"{prefix}_chk_{code}")
        st.session_state[checked_key][code] = checked
    return [row for row in rows if st.session_state[checked_key].get(row["kode_paket"])]

