"""Renderer UI ubah jadwal Pengadaan Langsung."""

from datetime import datetime, timedelta

import streamlit as st

import pl_engine
from pl_ui_helpers import _pl_label


def _validasi_perubahan_jadwal(current: list[dict], proposed: list[dict]) -> list[str]:
    """Validasi perubahan tanpa memblokir overlap lama yang tidak diperparah.

    Beberapa jadwal PL yang sudah tersimpan di SPSE memang memiliki tahap
    evaluasi dan klarifikasi yang berjalan tumpang tindih. Ubah jadwal existing
    harus tetap bisa mengubah satu field (misalnya selesai T4) tanpa dipaksa
    membetulkan seluruh histori jadwal sekaligus. Overlap baru atau overlap yang
    makin besar tetap ditolak sebelum POST.
    """
    errors = []
    for i, row in enumerate(proposed):
        if row["mulai"] >= row["selesai"]:
            errors.append(f"T{i + 1}: waktu mulai harus sebelum selesai")

    for i in range(min(len(current), len(proposed)) - 1):
        current_overlap = current[i]["selesai"] - current[i + 1]["mulai"]
        proposed_overlap = proposed[i]["selesai"] - proposed[i + 1]["mulai"]
        if proposed_overlap <= timedelta(0):
            continue
        # Jadwal lama valid tetapi usulan membuat overlap baru.
        if current_overlap <= timedelta(0):
            errors.append(f"T{i + 1}–T{i + 2}: overlap baru")
        # Jadwal lama sudah overlap; hanya izinkan jika tidak makin besar.
        elif proposed_overlap > current_overlap:
            errors.append(f"T{i + 1}–T{i + 2}: overlap makin besar")
    return errors


def _render_ubah_jadwal_pl(rows: list[dict], engine, prefix: str):
    """Bulk edit jadwal existing; POST hanya setelah konfirmasi."""
    st.markdown("### ✏️ Ubah Jadwal Existing (Bulk)")
    st.caption("Pilih banyak paket. Tahap yang tidak dipilih tetap memakai jadwal live masing-masing paket.")
    if not rows:
        st.info("Belum ada paket PL.")
        return

    by_code = {str(p.get("kode_paket")): p for p in rows}
    codes = st.multiselect(
        "Paket yang diubah",
        list(by_code),
        format_func=lambda k: f"{k} — {_pl_label(by_code[k])[:70]}",
        key=f"{prefix}_codes",
    )
    if not codes:
        st.info("Pilih satu atau beberapa paket.")
        return

    if st.button(f"🔄 Ambil Jadwal Live ({len(codes)} paket)", key=f"{prefix}_fetch", use_container_width=True):
        _loaded = {}
        with st.spinner("Mengambil jadwal live..."):
            for code in codes:
                try:
                    scraped = engine.scrap_hidden_fields_pl(code)
                    _loaded[code] = {"scraped": scraped, "jadwal": engine.parse_jadwal_aktual_pl(scraped)}
                except Exception as e:
                    st.error(f"{code}: gagal ambil jadwal — {e}")
        st.session_state[f"{prefix}_loaded"] = _loaded
        st.rerun()

    loaded = st.session_state.get(f"{prefix}_loaded", {})
    if any(c not in loaded for c in codes):
        st.info("Klik **Ambil Jadwal Live** setelah memilih paket.")
        return

    tahap = ["T1 Upload", "T2 Pembukaan", "T3 Evaluasi", "T4 Klarifikasi+Nego", "T5 Kontrak"]
    selected_tahap = st.multiselect("Tahap yang diubah", tahap, key=f"{prefix}_stages")
    idx_tahap = {x: i for i, x in enumerate(tahap)}
    if not selected_tahap:
        st.info("Pilih minimal satu tahap yang diubah.")
        return

    mode = st.radio("Metode perubahan", ["Geser relatif", "Set waktu absolut sama"], horizontal=True, key=f"{prefix}_mode")
    perubahan = {}
    if mode == "Geser relatif":
        c1, c2 = st.columns(2)
        with c1:
            hari = st.number_input("Geser hari", min_value=-365, max_value=365, value=0, step=1, key=f"{prefix}_days")
        with c2:
            jam = st.number_input("Geser jam", min_value=-23, max_value=23, value=0, step=1, key=f"{prefix}_hours")
        delta = timedelta(days=hari, hours=jam)
    else:
        for label in selected_tahap:
            i = idx_tahap[label]
            c1, c2, c3, c4 = st.columns([2, 1, 2, 1])
            sample = next(iter(loaded.values()))["jadwal"][i]
            with c1:
                d1 = st.date_input(f"{label} mulai", value=sample["mulai"].date(), format="DD/MM/YYYY", key=f"{prefix}_abs_sd_{i}")
            with c2:
                t1 = st.time_input("Jam", value=sample["mulai"].time(), key=f"{prefix}_abs_td_{i}")
            with c3:
                d2 = st.date_input(f"{label} selesai", value=sample["selesai"].date(), format="DD/MM/YYYY", key=f"{prefix}_abs_ss_{i}")
            with c4:
                t2 = st.time_input("Jam", value=sample["selesai"].time(), key=f"{prefix}_abs_ts_{i}")
            perubahan[i] = (datetime.combine(d1, t1), datetime.combine(d2, t2))

    semua_usulan = {}
    preview = []
    for code in codes:
        usulan = []
        for i, current in enumerate(loaded[code]["jadwal"]):
            mulai, selesai = current["mulai"], current["selesai"]
            if tahap[i] in selected_tahap:
                if mode == "Geser relatif":
                    mulai, selesai = mulai + delta, selesai + delta
                else:
                    mulai, selesai = perubahan[i]
            usulan.append({"nama": i + 1, "mulai": mulai, "selesai": selesai})
            preview.append({"Paket": _pl_label(by_code[code]), "Tahap": tahap[i], "Mulai": mulai.strftime("%d-%m-%Y %H:%M"), "Selesai": selesai.strftime("%d-%m-%Y %H:%M")})
        semua_usulan[code] = usulan

    import pandas as _pd_edit
    st.dataframe(_pd_edit.DataFrame(preview), use_container_width=True, hide_index=True)
    for code in codes:
        existing_schedule = loaded[code]["jadwal"]
        if any(
            existing_schedule[i]["selesai"] > existing_schedule[i + 1]["mulai"]
            for i in range(len(existing_schedule) - 1)
        ):
            st.warning(
                f"{code}: terdapat overlap jadwal lama di SPSE. "
                "Overlap ini dipertahankan selama perubahan tidak memperbesarnya."
            )
    alasan = st.text_area("Alasan Perubahan (minimal 30 karakter)", key=f"{prefix}_alasan")
    konfirmasi = st.checkbox("Saya sudah memeriksa preview dan menyetujui perubahan semua paket.", key=f"{prefix}_confirm")

    if st.button(f"🚀 Simpan Perubahan ({len(codes)} paket)", type="primary", key=f"{prefix}_submit", use_container_width=True):
        if not konfirmasi:
            st.error("Centang konfirmasi terlebih dahulu.")
            return
        if len(alasan.strip()) < 30:
            st.error("Alasan perubahan minimal 30 karakter.")
            return
        hasil = []
        for code in codes:
            usulan = semua_usulan[code]
            validasi = _validasi_perubahan_jadwal(
                loaded[code]["jadwal"], usulan
            )
            if validasi:
                hasil.append((
                    code,
                    False,
                    "Urutan waktu antar tahap tidak valid: " + "; ".join(validasi),
                ))
                continue
            try:
                result = engine.submit_perubahan_jadwal_pl(code, usulan, alasan)
                sub = result["submit_result"]
                if sub["ok"]:
                    try:
                        pl_engine.simpan_paket_pl({
                            "kode_paket": code,
                            "tgl_batas_penawaran": usulan[0]["selesai"].strftime("%Y-%m-%d"),
                            "tgl_buka_penawaran": usulan[1]["mulai"].strftime("%Y-%m-%d"),
                            "tgl_evaluasi": usulan[2]["selesai"].strftime("%Y-%m-%d"),
                            "tgl_negosiasi": usulan[3]["mulai"].strftime("%Y-%m-%d"),
                            "tgl_penetapan": usulan[4]["mulai"].strftime("%Y-%m-%d"),
                        })
                    except Exception:
                        pass
                    try:
                        import gcal_pl_helper as _gcal_edit
                        _gcal_edit.push_jadwal_pl_ke_gcal(code, by_code[code].get("nama_paket", ""), usulan)
                    except Exception:
                        pass
                    hasil.append((code, True, f"HTTP {sub['status']}"))
                else:
                    hasil.append((code, False, f"HTTP {sub['status']}: {sub['body'][:180]}"))
            except Exception as e:
                hasil.append((code, False, str(e)[:180]))
        for code, ok, msg in hasil:
            st.success(f"✅ {code} — {msg}") if ok else st.error(f"❌ {code} — {msg}")
