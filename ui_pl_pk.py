"""Konfigurasi domain UI Pengadaan Langsung Pekerjaan Konstruksi."""

PLPK_TAB_LABELS = [
    "1️⃣ Draft Paket PL",
    "2️⃣ Kirim Undangan DPP",
    "3️⃣ Setup Paket",
    "4️⃣ Pilih Penyedia & Umumkan",
    "5️⃣ Buat Jadwal",
    "6️⃣ Download Kualifikasi",
    "7️⃣ Evaluasi & Teknis/Biaya",
    "8️⃣ Kirim Verifikasi",
    "9️⃣ Upload BA PL",
    "🔟 Penetapan Pemenang",
    "📄 Import DPA",
]


def get_engine():
    """Kembalikan engine PK tanpa mengubah alias engine JKK global."""
    import pl_engine_plpk
    return pl_engine_plpk


def active_rows(load_fn, engine) -> tuple[list[dict], int]:
    """Ambil row PK aktif/berjalan dan jumlah duplikat yang disembunyikan UI."""
    from pl_engine import is_paket_berjalan

    rows = load_fn("PK")
    rows, duplicate_count = engine.buang_duplikat_paket_lama(rows)
    return [row for row in rows if is_paket_berjalan(row)], duplicate_count


def render_skp_gate(st, selected_rows: list[dict], key_prefix: str = "plpk_skp") -> bool:
    """Cek SKP provider terpilih sebelum tombol pilih penyedia diaktifkan."""
    if not selected_rows:
        return False

    import cek_penyedia_engine as engine

    signature = tuple(sorted(
        (
            str(row.get("kode_paket") or ""),
            str(row.get("nama_penyedia") or ""),
            str(row.get("npwp_penyedia") or ""),
        )
        for row in selected_rows
    ))
    result_key = f"{key_prefix}_result"
    signature_key = f"{key_prefix}_signature"

    with st.container(border=True):
        st.markdown("#### 🔍 Cek Penyedia — Gate SKP Pekerjaan Berjalan")
        st.caption(
            "Cek sumber Tender + Non-Tender Pekerjaan Konstruksi. "
            "Peserta bukan pemenang tidak dihitung; hanya pemenang yang masih berjalan. "
            "Batas maksimal = 5 paket."
        )
        if st.button(
            "🔍 Cek SKP Penyedia dari Excel",
            key=f"{key_prefix}_run",
            type="secondary",
            use_container_width=True,
        ):
            with st.spinner("Memeriksa riwayat penyedia di database SPSE Scraper..."):
                st.session_state[result_key] = engine.check_selected_providers(selected_rows)
                st.session_state[signature_key] = signature

        result = st.session_state.get(result_key)
        checked_signature = st.session_state.get(signature_key)
        if checked_signature != signature:
            st.info("Klik **Cek SKP Penyedia dari Excel** sebelum memilih penyedia ke SPSE.")
            return False
        if not result:
            st.info("Cek SKP belum dijalankan.")
            return False
        if result.get("errors"):
            for error in result["errors"]:
                st.error(error)
        if not result.get("ok"):
            return False

        allowed = True
        for provider in result.get("providers", []):
            projected = int(provider.get("skp_proyeksi", 0))
            current = int(provider.get("skp_berjalan", 0))
            candidate_count = int(provider.get("paket_baru_dicek", 0))
            label = provider.get("nama_penyedia") or "Penyedia"
            if not provider.get("boleh_submit"):
                allowed = False
                st.error(
                    f"❌ **{label}**: saat ini {current}/{engine.SKP_LIMIT} paket berjalan; "
                    f"batch ini menambah {candidate_count}, proyeksi {projected}/{engine.SKP_LIMIT}. "
                    "Pilih penyedia lain atau jangan kirim paket ini."
                )
            elif projected == engine.SKP_LIMIT:
                st.warning(f"⚠️ **{label}** tepat di batas: proyeksi {projected}/{engine.SKP_LIMIT}.")
            else:
                st.success(f"✅ **{label}** masih tersedia: proyeksi {projected}/{engine.SKP_LIMIT}.")

        detail_rows = result.get("rows") or []
        if detail_rows:
            st.dataframe(
                [
                    {
                        "Sumber": row.get("source"),
                        "Penyedia": row.get("nama_peserta"),
                        "NPWP": row.get("npwp"),
                        "Paket": row.get("nama_paket"),
                        "Tahap": row.get("tahapan"),
                        "Peran": row.get("status_peran"),
                        "SKP dihitung": "Ya" if row.get("is_pemenang_berjalan") else "Tidak",
                        "Link": row.get("link_detail"),
                    }
                    for row in detail_rows
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Belum ada riwayat paket konstruksi yang cocok di database scraper; proyeksi dimulai dari 0.")
        return allowed


def render_provider_search(st, key_prefix: str = "plpk_provider_search") -> None:
    """Pencarian manual ala V20 untuk audit provider di luar paket terpilih."""
    import cek_penyedia_engine as engine

    with st.expander("🔎 Cari penyedia lain (nama / NPWP)", expanded=False):
        query = st.text_input(
            "Nama penyedia atau NPWP",
            key=f"{key_prefix}_query",
            placeholder="contoh: CV. Harapan Group atau 1234567890123456",
        )
        if st.button("🔍 Cari", key=f"{key_prefix}_run", use_container_width=True):
            if len((query or "").strip()) < 3:
                st.warning("Masukkan minimal 3 karakter.")
            else:
                with st.spinner("Mencari riwayat penyedia..."):
                    st.session_state[f"{key_prefix}_result"] = engine.search_provider(query)

        result = st.session_state.get(f"{key_prefix}_result")
        if not result:
            return
        if not result.get("ok"):
            st.error(result.get("error", "Pencarian gagal."))
            return
        summaries = engine.summarize_provider_rows(result.get("rows") or [])
        if not summaries:
            st.info("Tidak ada data Pekerjaan Konstruksi yang cocok.")
            return
        for summary in summaries:
            st.write(
                f"**{summary['nama_penyedia']}** — {summary['status']} | "
                f"Menang: {summary['paket_dimenangkan']} | "
                f"Peserta bukan pemenang: {summary['peserta_bukan_pemenang']}"
            )


def render_download_actions(st, selected_rows: list[dict], kualifikasi_engine, hasil_engine, label_fn) -> None:
    """Render aksi download kualifikasi + populate evaluasi untuk paket PL."""
    jumlah = len(selected_rows)
    if not selected_rows:
        st.info("Centang minimal 1 paket di kiri.")
        return

    st.markdown(f"**{jumlah} paket** dipilih")
    st.caption("Peserta akan di-fetch via CDP saat tombol Jalankan diklik.")
    do_download = st.checkbox("⬇️ Download dokumen kualifikasi", value=True, key="pl7_do_dl")
    do_parse = st.checkbox("📋 Parse & populate sheet Hasil Evaluasi", value=True, key="pl7_do_parse")
    run = st.button(
        f"▶ Jalankan — {jumlah} paket",
        type="primary", key="pl7_run", use_container_width=True,
    )
    if not run:
        return

    progress = st.progress(0.0, text="Memulai...")
    logs: list[str] = []
    summary: list[dict] = []

    for index, row in enumerate(selected_rows):
        kode = row["kode_paket"]
        nama = label_fn(row)
        status = st.status(f"Paket {index + 1}/{jumlah} — {nama}", expanded=True)
        with status:
            logs.clear()
            log_box = st.empty()

            def log_cb(message, box=log_box, lines=logs):
                lines.append(str(message))
                box.code("\n".join(lines[-40:]))

            log_cb(f"[{index + 1}/{jumlah}] Fetch peserta SPSE...")
            progress.progress(index / jumlah, text=f"{nama} — fetch peserta")
            fetched = kualifikasi_engine.fetch_peserta_pl(kode)
            if not fetched.get("ok"):
                detail = fetched.get("pesan", "peserta tidak ditemukan")
                log_cb(f"[SKIP] Peserta: {detail}")
                status.update(label=f"SKIP {nama} — {detail}", state="error", expanded=False)
                summary.append({"nama": nama, "status": "skip", "detail": detail})
                continue

            peserta = fetched["peserta"]
            log_cb(f"Peserta ({len(peserta)}): {', '.join(p['nama'] for p in peserta)}")
            folder = kualifikasi_engine.resolve_folder_paket_pl(kode)
            if not folder.get("ok"):
                detail = folder.get("pesan", "folder tidak ditemukan")
                log_cb(f"[SKIP] Folder: {detail}")
                status.update(label=f"SKIP {nama} — folder tidak ditemukan", state="error", expanded=False)
                summary.append({"nama": nama, "status": "skip", "detail": detail})
                continue

            folder_kualifikasi = folder["path"]
            if do_download:
                progress.progress((index + 0.3) / jumlah, text=f"{nama} — download kualifikasi")
                for urutan, peserta_row in enumerate(peserta, 1):
                    log_cb(f"--- Download [{urutan}/{len(peserta)}] {peserta_row['nama']} ---")
                    kualifikasi_engine.download_kualifikasi_peserta_pl(
                        peserta_row, folder_kualifikasi, urutan, len(peserta), log_cb,
                    )

                log_cb("--- Serap penyedia (nama/NPWP/personil) ---")
                try:
                    import parse_kak_pl
                    scraped = parse_kak_pl.serap_penyedia_pl(kode_paket_filter=kode)
                    log_cb(
                        f"👤 Penyedia: {scraped.get('updated', 0)} diperbarui"
                        if scraped.get("updated", 0) > 0 else "👤 Penyedia: tidak ada data baru"
                    )
                except Exception as exc:
                    log_cb(f"⚠ Serap penyedia: {exc}")

            if do_parse:
                progress.progress((index + 0.7) / jumlah, text=f"{nama} — parse evaluasi")
                log_cb("--- Populate sheet Hasil Evaluasi ---")
                result = hasil_engine.populate_hasil_evaluasi_pl(kode, peserta, log_cb)
                log_cb(f"{'[OK]' if result.get('ok') else '[GAGAL]'} {result['pesan']}")
                if result.get("ok"):
                    log_cb("--- Refresh @ Master Data ---")
                    try:
                        import isi_master_data_pl
                        workbook = hasil_engine._find_xlsm(kode)
                        if workbook:
                            refreshed = isi_master_data_pl.isi_master_data_pl(
                                kode, workbook, progress_cb=log_cb
                            )
                            log_cb(f"{'[OK]' if refreshed.get('ok') else '[WARN]'} {refreshed['pesan']}")
                        else:
                            log_cb("[WARN] File .xlsm tidak ditemukan untuk refresh @ Master Data")
                    except Exception as exc:
                        log_cb(f"[WARN] Refresh @ Master Data gagal: {exc}")
                summary.append({
                    "nama": nama,
                    "status": "ok" if result.get("ok") else "gagal",
                    "detail": result.get("pesan", ""),
                })
            else:
                summary.append({"nama": nama, "status": "ok", "detail": "download saja"})

            status.update(label=f"Selesai — {nama}", state="complete", expanded=False)
        progress.progress((index + 1) / jumlah, text=f"Selesai {index + 1}/{jumlah} paket")

    progress.progress(1.0, text="Semua paket selesai.")
    from batch_summary import render_ringkasan_batch
    render_ringkasan_batch(st, summary)
