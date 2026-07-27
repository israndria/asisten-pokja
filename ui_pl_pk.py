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
    """Ambil row PK aktif dan jumlah duplikat yang disembunyikan UI."""
    rows = load_fn("PK")
    rows, duplicate_count = engine.buang_duplikat_paket_lama(rows)
    return [row for row in rows if not engine.is_paket_selesai(row)], duplicate_count


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
