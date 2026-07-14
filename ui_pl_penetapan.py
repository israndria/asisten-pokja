"""Renderer negosiasi, penetapan, dan pengumuman PL."""

import streamlit as st

import spse_browser


def _render_pl_negosiasi_penetapan_legacy(selected_rows: list[dict], key_prefix: str) -> None:
    """UI Tab 7 untuk input negosiasi dan penetapan pemenang PL."""
    import pl_negosiasi_engine as _neg

    st.markdown("---")
    st.markdown("### 💬 Hasil Negosiasi & Penetapan Pemenang")
    st.caption("Pilih satu paket. Data hanya dikirim setelah checkbox konfirmasi dicentang.")
    paket_options = [str(r.get("kode_paket")) for r in selected_rows]
    if len(paket_options) == 1:
        kode = paket_options[0]
        st.session_state[f"{key_prefix}_neg_package"] = kode
    else:
        kode = st.selectbox("Paket", paket_options, key=f"{key_prefix}_neg_package")
    row = next((r for r in selected_rows if str(r.get("kode_paket")) == kode), {})
    st.caption(row.get("nama_paket", ""))
    cookie = spse_browser.get_spse_cookies()

    participant_key = f"{key_prefix}_neg_participants"
    participant_for_key = f"{key_prefix}_neg_participants_for"
    if st.session_state.get(participant_for_key) != kode:
        with st.spinner("Membaca peserta dari SPSE..."):
            result = _neg.scrape_peserta(kode, cookie)
        if result["ok"]:
            st.session_state[participant_key] = result["peserta"]
            st.session_state[participant_for_key] = kode
            st.session_state.pop(f"{key_prefix}_neg_loaded", None)
        else:
            st.error(result["pesan"])

    participants = st.session_state.get(participant_key, [])
    if not participants:
        st.info("Peserta belum tersedia. Pilih paket lain atau cek koneksi SPSE.")
        return
    pmap = {p["id_nontender"]: p for p in participants}
    pid = st.selectbox(
        "Peserta untuk negosiasi",
        list(pmap),
        format_func=lambda x: pmap[x]["nama"],
        key=f"{key_prefix}_neg_participant",
    )
    c1, c2 = st.columns(2)
    if c1.button("📥 Muat Rincian Negosiasi", key=f"{key_prefix}_neg_load"):
        with st.spinner("Membaca rincian negosiasi..."):
            result = _neg.scrape_negosiasi(pid, cookie)
        if result["ok"]:
            st.session_state[f"{key_prefix}_neg_loaded"] = {"id": pid, **result}
            st.success("Rincian negosiasi siap diedit.")
        else:
            st.error(result["pesan"])

    loaded = st.session_state.get(f"{key_prefix}_neg_loaded")
    if loaded and loaded.get("id") == pid:
        raw = loaded.get("data") or []
        headers = ["item", "unit", "volume", "harga", "harga_nego", "pajak", "total_harga_nego", "keterangan", "kunci"]
        rows = []
        for values in raw:
            vals = list(values) if isinstance(values, (list, tuple)) else [values]
            vals += [""] * (len(headers) - len(vals))
            rows.append({h: vals[i] for i, h in enumerate(headers)})
        edited = st.data_editor(
            rows, key=f"{key_prefix}_neg_editor_{pid}", hide_index=True,
            use_container_width=True, num_rows="fixed",
            column_config={
                "harga_nego": st.column_config.NumberColumn("Harga Nego", min_value=0, step=1),
                "keterangan": st.column_config.TextColumn("Keterangan"),
                "kunci": st.column_config.CheckboxColumn("Kunci"),
            },
        )
        confirm_neg = st.checkbox("Saya sudah memeriksa rincian dan siap menyimpan hasil negosiasi.", key=f"{key_prefix}_neg_confirm")
        if st.button("💾 Simpan Hasil Negosiasi", type="primary", disabled=not confirm_neg, key=f"{key_prefix}_neg_submit"):
            payload = [[item.get(h, "") for h in headers] for item in edited]
            result = _neg.submit_negosiasi(pid, loaded["token"], payload, cookie)
            (st.success if result["ok"] else st.error)(result["pesan"])

    st.markdown("#### Penetapan Pemenang")
    if st.button("📋 Muat Form Penetapan", key=f"{key_prefix}_pen_load"):
        with st.spinner("Membaca form penetapan..."):
            result = _neg.scrape_penetapan(kode, cookie)
        if result["ok"]:
            st.session_state[f"{key_prefix}_pen_loaded"] = result
            st.success("Form penetapan siap.")
        else:
            st.error(result["pesan"])
    pen = st.session_state.get(f"{key_prefix}_pen_loaded")
    if pen:
        st.dataframe(pen.get("peserta", []), hide_index=True, use_container_width=True)
        confirm_pen = st.checkbox("Saya menetapkan peserta pada daftar di atas sebagai pemenang.", key=f"{key_prefix}_pen_confirm")
        if st.button("🏆 Simpan Penetapan Pemenang", type="primary", disabled=not confirm_pen, key=f"{key_prefix}_pen_submit"):
            result = _neg.submit_penetapan(kode, pen, cookie)
            (st.success if result["ok"] else st.error)(result["pesan"])

def _render_pl_negosiasi_penetapan(selected_rows: list[dict], key_prefix: str) -> None:
    """Submit negosiasi lalu penetapan untuk paket PL satu peserta."""
    import pl_negosiasi_engine as _neg

    st.markdown("---")
    st.markdown("### 💬 Submit Negosiasi & Penetapan Pemenang")
    st.caption("Otomatis memproses paket terpilih; setiap paket wajib memiliki tepat satu peserta.")
    confirm = st.checkbox(
        f"Saya yakin memproses {len(selected_rows)} paket terpilih.",
        key=f"{key_prefix}_neg_pen_confirm",
    )
    if st.button(
        f"✅ Submit Negosiasi & Penetapan Pemenang — {len(selected_rows)} paket",
        type="primary", use_container_width=True,
        disabled=not confirm, key=f"{key_prefix}_neg_pen_submit",
    ):
        cookie = spse_browser.get_spse_cookies()
        with st.status("Memproses negosiasi dan penetapan...", expanded=True) as status:
            ok_count = 0
            for row in selected_rows:
                kode = str(row.get("kode_paket"))
                result = _neg.submit_negosiasi_dan_penetapan_pl(kode, cookie)
                if result["ok"]:
                    ok_count += 1
                    status.write(f"✅ {kode}: {result['pesan']}")
                else:
                    status.write(f"❌ {kode}: {result['pesan']}")
            status.update(
                label=f"Selesai — {ok_count}/{len(selected_rows)} paket berhasil",
                state="complete" if ok_count == len(selected_rows) else "error",
                expanded=False,
            )

def _render_tab10_pl(rows: list[dict], key_prefix: str) -> None:
    """Tab 10: penetapan, pengumuman, dan Summary Non Tender per paket."""
    import pl_negosiasi_engine as _neg
    import summary_nontender_engine as _summary

    st.markdown("## Penetapan Pemenang — Pengadaan Langsung")
    st.caption("Kelola negosiasi, penetapan, pengumuman, dan Summary Non Tender dalam satu tab.")
    if not rows:
        st.info("Tidak ada paket PL aktif.")
        return

    left, right = st.columns([2, 3])
    with left:
        st.markdown("### 1. Pilih Paket")
        check_key = f"{key_prefix}_checked"
        if check_key not in st.session_state:
            st.session_state[check_key] = {str(r.get("kode_paket")): True for r in rows}
        all_col, none_col = st.columns(2)
        if all_col.button("✅ Semua", key=f"{key_prefix}_select_all", use_container_width=True):
            st.session_state[check_key] = {str(r.get("kode_paket")): True for r in rows}
            st.rerun()
        if none_col.button("⬜ Kosong", key=f"{key_prefix}_select_none", use_container_width=True):
            st.session_state[check_key] = {str(r.get("kode_paket")): False for r in rows}
            st.rerun()
        for item in rows:
            item_code = str(item.get("kode_paket"))
            label = f"{item.get('nomor_urut') or ''}. {item.get('nama_paket', '?')}".strip()
            st.session_state[check_key][item_code] = st.checkbox(
                label, value=st.session_state[check_key].get(item_code, True),
                key=f"{key_prefix}_check_{item_code}",
            )

    selected_rows = [r for r in rows if st.session_state[check_key].get(str(r.get("kode_paket")))]
    with right:
        if not selected_rows:
            st.info("Centang minimal 1 paket di kiri.")
            return
        st.markdown(f"### 2. Aksi — {len(selected_rows)} paket dipilih")
        _render_pl_negosiasi_penetapan(selected_rows, key_prefix)

        st.markdown("### 📣 Pengumuman Pemenang")
        st.caption("Kirim pengumuman untuk paket-paket yang tercentang.")
        confirm = st.checkbox("Saya sudah memastikan semua penetapan paket terpilih benar.", key=f"{key_prefix}_announce_confirm")
        if st.button(f"📣 Kirim Pengumuman — {len(selected_rows)} paket", type="primary", disabled=not confirm, key=f"{key_prefix}_announce"):
            cookie = spse_browser.get_spse_cookies()
            with st.status("Mengirim pengumuman pemenang...", expanded=True) as status:
                for row in selected_rows:
                    kode = str(row.get("kode_paket"))
                    result = _neg.umumkan_pemenang_pl(kode, cookie)
                    status.write(f"{'✅' if result['ok'] else '❌'} {kode}: {result['pesan']}")
                status.update(label="Pengumuman selesai", state="complete", expanded=False)

        st.markdown("### 📄 Summary Non Tender")
        st.caption("Download Summary Non Tender untuk paket-paket yang tercentang.")
        if st.button(f"⬇️ Download Summary — {len(selected_rows)} paket", key=f"{key_prefix}_summary_download"):
            cookie = spse_browser.get_spse_cookies()
            with st.status("Download Summary Non Tender...", expanded=True) as status:
                for row in selected_rows:
                    try:
                        kode = str(row.get("kode_paket"))
                        import kualifikasi_engine_pl as _folder_engine
                        if (row.get("jenis_pl") or "JKK").upper() == "PK":
                            import kualifikasi_engine_plpk as _folder_engine
                        folder_result = _folder_engine.resolve_folder_paket_pl(kode, buat_subfolder=False)
                        if not folder_result.get("ok"):
                            status.write(f"❌ {kode}: {folder_result.get('pesan', 'folder tidak ditemukan')}")
                            continue
                        result = _summary.download_summary_nontender(kode, folder_result["path"], cookie)
                        status.write(f"{'✅' if result['ok'] else '❌'} {kode}: {result['pesan']}")
                    except Exception as e:
                        status.write(f"❌ {row.get('kode_paket')}: {e}")
                status.update(label="Download Summary selesai", state="complete", expanded=False)

