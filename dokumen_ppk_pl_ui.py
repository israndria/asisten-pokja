"""Renderer Tab 2 monitor dokumen PPK PL JKK/PK."""

from __future__ import annotations


def _package_name(row: dict, label_fn) -> str:
    try:
        return str(label_fn(row) or row.get("nama_paket") or row.get("kode_paket") or "-")
    except Exception:
        return str(row.get("nama_paket") or row.get("kode_paket") or "-")


def _filter_unannounced_rows(rows: list[dict], session_status: dict, is_announced) -> list[dict]:
    """Sembunyikan paket yang sudah tayang dari checklist monitoring."""
    return [row for row in rows if not is_announced(row, session_status)]


def _render_snapshot_summary(st, engine, snapshot: dict) -> None:
    total = 0
    for kind, label in engine.DOCUMENT_TYPES.items():
        files = snapshot.get(kind) or []
        total += len(files)
        st.markdown(f"- **{label}:** {len(files)} file")
        for item in files:
            name = item.get("nama") or "-"
            tanggal = item.get("tanggal") or "tanggal tidak terbaca"
            st.caption(f"  `{name}` — {tanggal}")
    if total == 0:
        st.caption("Belum ada file yang terdeteksi pada kategori dokumen PPK.")


def _snapshot_file_count(engine, snapshot: dict) -> int:
    return sum(len(snapshot.get(kind) or []) for kind in engine.DOCUMENT_TYPES)


def _render_download_result(st, result: dict) -> None:
    folder = result.get("folder") or "-"
    ok = result.get("ok") or []
    errors = result.get("error") or []
    if result.get("archive"):
        st.caption(f"Batch sebelumnya diarsipkan ke: `{result['archive']}`")
    st.caption(f"Folder tujuan: `{folder}`")
    if ok:
        st.success(f"✅ {len(ok)} file berhasil diunduh.")
    if errors:
        st.warning(f"⚠️ {len(errors)} file gagal diunduh.")
        for error in errors:
            st.error(str(error))
    if not ok and not errors:
        st.info("Tidak ada file yang perlu diunduh.")


def _render_diff(st, result: dict) -> None:
    for item in result.get("berubah", []):
        st.markdown(
            f"- **Berubah** [{item.get('jenis', '-')}]: "
            f"`{item.get('nama_lama', '-')}` → `{item.get('nama_baru', '-')}` "
            f"({item.get('tanggal_lama', '-')} → {item.get('tanggal_baru', '-')})"
        )
    for item in result.get("baru", []):
        st.markdown(
            f"- **File baru** [{item.get('jenis', '-')}]: "
            f"`{item.get('nama', '-')}` — {item.get('tanggal') or 'tanggal tidak terbaca'}"
        )
    for item in result.get("perlu_verifikasi", []):
        st.warning(
            f"Perlu verifikasi [{item.get('jenis', '-')}]: "
            f"`{item.get('nama_lama', '-')}` → `{item.get('nama_baru', '-')}`. "
            f"{item.get('alasan', '')}"
        )
    for item in result.get("hilang", []):
        st.markdown(
            f"- **File hilang dari live SPSE** [{item.get('jenis', '-')}]: "
            f"`{item.get('nama', '-')}` — mungkin diganti"
        )


def _render_result(st, engine, row: dict, result: dict, state_key: str, results: dict) -> None:
    if result.get("error"):
        if result.get("error_kind") == "session":
            st.error(f"⚠️ Cookie SPSE invalid/expired — login ulang di Brave. {result['error']}")
        else:
            st.error(result["error"])
        return

    if result.get("baseline_created"):
        st.info(
            "Baseline dokumen berhasil disimpan. Cek ulang nanti untuk mendeteksi "
            "file baru, perubahan tanggal upload, rename, atau file yang hilang."
        )
    elif result.get("ada_update"):
        st.warning("Ada perubahan dokumen PPK pada paket ini.")
        _render_diff(st, result)
        if st.button(
            "✅ Tandai snapshot terbaru sudah diperiksa",
            key=f"pldoc_ack_{state_key}_{row['kode_paket']}",
            use_container_width=True,
            help="Simpan daftar live terbaru sebagai baseline berikutnya.",
        ):
            engine.save_snapshot(
                row["kode_paket"],
                row.get("jenis_pl") or state_key,
                result.get("snapshot_baru") or {},
            )
            results.pop(str(row["kode_paket"]), None)
            st.session_state[state_key] = results
            st.success("✅ Snapshot terbaru disimpan sebagai baseline.")
            st.rerun()
    else:
        st.success("✅ Tidak ada perubahan dokumen PPK sejak baseline terakhir.")

    # Kartu paket di caller sudah berupa expander. Streamlit melarang expander
    # bersarang, jadi daftar live dirender sebagai section biasa di dalam kartu.
    st.markdown("**📄 Daftar dokumen live**")
    snapshot = result.get("snapshot_baru") or {}
    _render_snapshot_summary(st, engine, snapshot)
    total_files = _snapshot_file_count(engine, snapshot)
    if st.button(
        "⬇️ Download semua dokumen PPK",
        key=f"pldoc_download_{state_key}_{row['kode_paket']}",
        use_container_width=True,
        disabled=total_files == 0,
        help="Refresh folder 10 dengan batch terbaru; batch sebelumnya diarsipkan bertimestamp.",
    ):
        with st.spinner("Mengunduh semua dokumen PPK..."):
            try:
                download_result = engine.download_all_dokumen_ppk(row, snapshot)
            except Exception as exc:
                download_result = {
                    "folder": "",
                    "ok": [],
                    "error": [str(exc)],
                }
        result["download"] = download_result
        results[str(row["kode_paket"])] = result
        st.session_state[state_key] = results

    if result.get("download"):
        st.markdown("**📥 Hasil download dokumen PPK**")
        _render_download_result(st, result["download"])


def render_tab_dokumen_ppk_pl(st, jenis_pl: str, label_fn) -> None:
    """Render checklist paket Draft + cek dokumen PPK secara on-demand."""
    import pl_engine
    from pl_data_ui import (
        get_paket_umumkan_status,
        is_paket_sudah_diumumkan,
        load_draft_pl_cached,
        mark_tahap_spse_sudah_diumumkan,
    )
    from ui_pl_common import render_package_selection
    import dokumen_ppk_pl as engine

    family = str(jenis_pl or "JKK").upper()
    state_key = f"pl_dokumen_ppk_results_{family.lower()}"
    prefix = f"pldoc_{family.lower()}"

    st.markdown(f"## Monitor Dokumen PPK — PL {family}")
    st.caption(
        "Hanya paket berstatus Draft yang ditampilkan. Pemeriksaan SPSE berjalan "
        "saat tombol ditekan, tidak otomatis ketika tab dibuka."
    )

    if st.button(
        "🔄 Sinkronkan status tayang dari SPSE",
        key=f"{prefix}_sync_status",
        use_container_width=True,
        help="Read-only: paket yang sudah diumumkan/disetujui tidak dimonitor lagi.",
    ):
        try:
            import spse_browser

            cookie = spse_browser.get_spse_cookies()
            if not cookie:
                st.error("Browser SPSE tidak terhubung atau session kosong.")
            else:
                with st.spinner("Membaca status tayang dari SPSE..."):
                    tahap_map = pl_engine._fetch_tahap_spse(cookie, pl_engine.BASE_URL)
                count = mark_tahap_spse_sudah_diumumkan(tahap_map)
                load_draft_pl_cached.clear()
                if count:
                    st.session_state[f"{prefix}_status_flash"] = (
                        f"✅ {count} status paket berhasil disinkronkan dari SPSE."
                    )
                    st.rerun()
                st.warning("Tidak ada tahap paket aktif yang terbaca dari SPSE.")
        except Exception as exc:
            st.error(f"Sinkronisasi status SPSE gagal: {exc}")

    status_flash = st.session_state.pop(f"{prefix}_status_flash", "")
    if status_flash:
        st.success(status_flash)

    try:
        rows = load_draft_pl_cached(family, only_local=False)
        kind_engine = __import__("pl_engine_plpk" if family == "PK" else "pl_engine")
        rows, duplicate_count = kind_engine.buang_duplikat_paket_lama(rows)
        rows = [row for row in rows if pl_engine.is_paket_draft(row)]
        sebelum_filter = len(rows)
        rows = _filter_unannounced_rows(
            rows,
            get_paket_umumkan_status(),
            is_paket_sudah_diumumkan,
        )
    except Exception as exc:
        st.error(f"Gagal memuat paket Draft PL {family}: {exc}")
        return

    if duplicate_count:
        st.caption(f"↻ {duplicate_count} row paket ulang lama disembunyikan otomatis.")
    if sebelum_filter != len(rows):
        st.caption(
            f"✅ {sebelum_filter - len(rows)} paket yang sudah tayang disembunyikan dari monitoring."
        )

    if st.button("🔄 Muat ulang daftar paket Draft", key=f"{prefix}_reload", use_container_width=True):
        load_draft_pl_cached.clear()
        st.session_state.pop(state_key, None)
        st.rerun()

    if not rows:
        st.info(f"Tidak ada paket PL {family} berstatus Draft.")
        return

    st.caption(f"📋 {len(rows)} paket Draft — centang paket yang ingin diperiksa:")
    selected = render_package_selection(st, rows, label_fn, prefix=prefix)
    results = st.session_state.setdefault(state_key, {})

    if not selected:
        st.info("Centang minimal satu paket.")
        return

    st.divider()
    st.markdown(f"#### Aksi — {len(selected)} paket terpilih")
    check_col, download_col = st.columns(2)
    with check_col:
        check_all_clicked = st.button(
            "🔍 Cek semua paket terpilih",
            key=f"{prefix}_check_all",
            type="primary",
            use_container_width=True,
        )
    with download_col:
        download_all_clicked = st.button(
            "⬇️ Download semua dokumen PPK",
            key=f"{prefix}_download_all",
            use_container_width=True,
            help="Cek snapshot live tiap paket lalu refresh folder 10; batch sebelumnya diarsipkan.",
        )

    if check_all_clicked:
        progress = st.progress(0.0, text="Memulai pemeriksaan...")
        for index, row in enumerate(selected, start=1):
            name = _package_name(row, label_fn)
            progress.progress((index - 1) / len(selected), text=f"Memeriksa {name[:55]}...")
            try:
                results[str(row["kode_paket"])] = engine.check_dokumen_ppk_pl(
                    row["kode_paket"], family
                )
            except Exception as exc:
                results[str(row["kode_paket"])] = {
                    "error": str(exc),
                    "error_kind": getattr(exc, "kind", "request"),
                }
        st.session_state[state_key] = results
        progress.progress(1.0, text="Pemeriksaan selesai.")

    if download_all_clicked:
        progress = st.progress(0.0, text="Menyiapkan download...")
        for index, row in enumerate(selected, start=1):
            code = str(row.get("kode_paket") or "")
            name = _package_name(row, label_fn)
            progress.progress(
                (index - 1) / len(selected),
                text=f"Cek dan download {name[:48]}...",
            )
            try:
                result = engine.check_dokumen_ppk_pl(code, family)
                if not result.get("error"):
                    result["download"] = engine.download_all_dokumen_ppk(
                        row, result.get("snapshot_baru") or {}
                    )
                results[code] = result
            except Exception as exc:
                results[code] = {
                    "error": str(exc),
                    "error_kind": getattr(exc, "kind", "request"),
                }
        st.session_state[state_key] = results
        progress.progress(1.0, text="Download paket terpilih selesai.")

    st.caption("Atau periksa satu paket dari kartu masing-masing:")
    for row in selected:
        code = str(row.get("kode_paket") or "")
        name = _package_name(row, label_fn)
        result = results.get(code)
        with st.expander(f"📄 {name}", expanded=bool(result)):
            st.caption(f"Kode paket: `{code}` · Status SPSE: **Draft**")
            if st.button(
                "🔍 Cek ulang Dokumen PPK" if result else "🔍 Cek Dokumen PPK",
                key=f"{prefix}_check_{code}",
                use_container_width=True,
            ):
                with st.spinner(f"Memeriksa dokumen PPK {name[:45]}..."):
                    try:
                        result = engine.check_dokumen_ppk_pl(code, family)
                    except Exception as exc:
                        result = {
                            "error": str(exc),
                            "error_kind": getattr(exc, "kind", "request"),
                        }
                    results[code] = result
                    st.session_state[state_key] = results

            result = results.get(code)
            if result:
                _render_result(st, engine, row, result, state_key, results)
            else:
                st.caption("Belum diperiksa pada sesi ini.")
