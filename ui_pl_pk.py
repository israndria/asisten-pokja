"""Konfigurasi domain UI Pengadaan Langsung Pekerjaan Konstruksi."""

import re

PLPK_TAB_LABELS = [
    "1️⃣ Draft Paket PL",
    "2️⃣ Monitor Dokumen PPK",
    "3️⃣ Kirim Undangan DPP",
    "4️⃣ Setup Paket",
    "5️⃣ Buat & Monitor Jadwal",
    "6️⃣ Pilih Penyedia & Umumkan",
    "7️⃣ Download Kualifikasi",
    "8️⃣ Evaluasi & Teknis/Biaya",
    "9️⃣ Kirim Verifikasi",
    "🔟 Upload BA PL",
    "1️⃣1️⃣ Penetapan Pemenang",
    "📄 Import DPA",
]


def get_engine():
    """Kembalikan engine PK tanpa mengubah alias engine JKK global."""
    import pl_engine_plpk
    return pl_engine_plpk


def active_rows(load_fn, engine) -> tuple[list[dict], int]:
    """Ambil row PK aktif/berjalan dan jumlah duplikat yang disembunyikan UI."""
    from pl_engine import is_paket_operasional_eligible
    from pl_data_ui import overlay_live_tahap_spse

    rows = load_fn("PK")
    rows = overlay_live_tahap_spse(rows)
    rows, duplicate_count = engine.buang_duplikat_paket_lama(rows)
    return [row for row in rows if is_paket_operasional_eligible(row)], duplicate_count


def _provider_check_signature(rows: list[dict]) -> tuple:
    return tuple(sorted(
        (
            str(row.get("kode_paket") or ""),
            str(row.get("nama_penyedia") or ""),
            str(row.get("npwp_penyedia") or ""),
        )
        for row in rows
    ))


def provider_identity_available(row: dict) -> bool:
    """True bila provider dapat dicari via NPWP atau fallback nama."""
    return bool(
        str((row or {}).get("npwp_penyedia") or "").strip()
        or str((row or {}).get("nama_penyedia") or "").strip()
    )


def provider_status_caption(
    st,
    row: dict,
    selected_rows: list[dict],
    *,
    result_key: str,
    signature_key: str,
    formal_skp: bool,
) -> str:
    """Status ringkas untuk ditempel di bawah paket pada kolom kiri."""
    import cek_penyedia_engine as engine

    if st.session_state.get(signature_key) != _provider_check_signature(selected_rows):
        return "⏳ Status belum dicek"
    result = st.session_state.get(result_key) or {}
    target_npwp = engine._normalize_npwp(row.get("npwp_penyedia"))
    target_name = re.sub(r"[^a-z0-9]+", " ", str(row.get("nama_penyedia") or "").lower()).strip()
    provider = None
    for candidate in result.get("providers") or []:
        candidate_npwp = engine._normalize_npwp(candidate.get("npwp"))
        candidate_name = re.sub(
            r"[^a-z0-9]+", " ", str(candidate.get("nama_penyedia") or "").lower()
        ).strip()
        if (target_npwp and candidate_npwp and target_npwp == candidate_npwp) or (
            target_name and target_name == candidate_name
        ):
            provider = candidate
            break
    if provider is None:
        return "⚠️ Histori penyedia tidak ditemukan"

    active = int(provider.get("skp_berjalan", 0))
    review = int(provider.get("skp_perlu_verifikasi", 0))
    limit = engine.SKP_LIMIT
    if formal_skp:
        if review:
            return f"🟡 SKP {active}/{limit} aktif · {review} perlu verifikasi"
        return f"✅ SKP {active}/{limit} aktif · proyeksi {int(provider.get('skp_proyeksi', active))}/{limit}"
    if review:
        return f"🟡 Beban aktif {active} · {review} perlu verifikasi"
    return f"✅ Beban aktif {active} kontrak"


def provider_selection_status_caption(row: dict, selection_status: dict) -> str:
    """Caption read-only status pilihan penyedia di SPSE.

    Status gagal sengaja tidak diterjemahkan menjadi ``belum terpilih``;
    session/CDP yang gagal tidak boleh menghasilkan kesimpulan operasional.
    """
    kode = str((row or {}).get("kode_paket") or "").strip()
    if not kode or not isinstance(selection_status, dict):
        return "⏳ Status pilihan SPSE belum disinkronkan"
    result = selection_status.get(kode)
    if not isinstance(result, dict):
        return "⏳ Status pilihan SPSE belum disinkronkan"

    status = result.get("status")
    if status in {"sudah_terpilih", "sudah_terpilih_lain"}:
        nama = str(result.get("nama") or "").strip()
        return f"✅ Penyedia sudah dipilih{': ' + nama if nama else ''}"
    if status == "belum_terpilih":
        return "⬜ Belum ada penyedia terpilih di SPSE"
    pesan = str(result.get("pesan") or "status tidak dapat diverifikasi").strip()
    return f"❔ Status pilihan SPSE tidak dapat diverifikasi: {pesan}"


def _render_provider_detail(
    st, rows: list[dict], status_header: str = "SKP dihitung"
) -> None:
    """Render tabel keterlibatan provider seperti pencarian V20."""
    if not rows:
        st.caption("Belum ada detail keterlibatan yang cocok.")
        return

    ordered = sorted(
        rows,
        key=lambda row: (
            not bool(row.get("is_pemenang")),
            not bool(row.get("is_pemenang_berjalan")),
            not bool(row.get("skp_perlu_verifikasi")),
            str(row.get("nama_paket") or "").lower(),
        ),
    )
    table_rows = [
        {
            "Penyedia": row.get("nama_peserta"),
            "Paket": row.get("nama_paket"),
            "Instansi": row.get("instansi"),
            "Jenis Pengadaan": row.get("jenis_pengadaan"),
            "Tahapan": row.get("tahapan"),
            "Status Peran": row.get("status_peran"),
            status_header: row.get("skp_status") or (
                "Ya — terindikasi berjalan"
                if row.get("is_pemenang_berjalan")
                else (
                    "Tidak — belum berkontrak"
                    if row.get("is_pemenang") and not row.get("is_berkontrak")
                    else "Tidak — peserta"
                )
            ),
            "Jadwal TTD Kontrak Mulai": row.get("kontrak_mulai"),
            "Jadwal TTD Kontrak Akhir": row.get("kontrak_selesai"),
        }
        for row in ordered
    ]
    st.dataframe(table_rows, use_container_width=True, hide_index=True)


def render_skp_gate(st, selected_rows: list[dict], key_prefix: str = "plpk_skp") -> bool:
    """Tampilkan SKP sebagai informasi; tidak pernah memblokir submit batch."""
    if not selected_rows:
        return True

    import cek_penyedia_engine as engine

    signature = _provider_check_signature(selected_rows)
    result_key = f"{key_prefix}_result"
    signature_key = f"{key_prefix}_signature"

    with st.container(border=True):
        st.markdown("#### 🔍 Informasi SKP — Pekerjaan Berjalan")
        st.caption(
            "Cek sumber Tender + Non-Tender Pekerjaan Konstruksi. "
            "Akhir jadwal Penandatanganan Kontrak SPSE sampai 30 hari lalu "
            "dihitung aktif; lebih dari 30 hari diasumsikan selesai secara heuristik. "
            "Tanggal kosong/invalid tetap perlu verifikasi. Paket tanpa NPWP tetap dicari "
            "berdasarkan nama; hanya paket tanpa NPWP dan nama yang tidak ikut cek. "
            "Jika nama Excel berbeda tetapi NPWP cocok, nama SPSE ditampilkan sebagai "
            "identitas canonical dan perbedaannya diberi catatan audit. "
            "Hasil ini hanya filter/informasi dan tidak menghapus atau menahan checklist. "
            "Batas pembanding = 5 paket."
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
                for state_key in list(st.session_state):
                    if state_key.startswith(f"{key_prefix}_verify_"):
                        del st.session_state[state_key]

        result = st.session_state.get(result_key)
        checked_signature = st.session_state.get(signature_key)
        if checked_signature != signature:
            st.info("Klik **Cek SKP Penyedia dari Excel** jika ingin melihat histori SKP.")
            return True
        if not result:
            st.info("Histori SKP belum dimuat; batch tetap dapat diproses.")
            return True
        if result.get("errors"):
            for error in result["errors"]:
                st.warning(f"Status SKP tidak lengkap: {error}")
        if not result.get("ok"):
            st.warning("Pemeriksaan SKP gagal/parsial; hasil ini tidak memblokir pilihan penyedia.")

        for provider in result.get("providers", []):
            projected = int(provider.get("skp_proyeksi", 0))
            current = int(provider.get("skp_berjalan", 0))
            candidate_count = int(provider.get("paket_baru_dicek", 0))
            needs_verification = int(provider.get("skp_perlu_verifikasi", 0))
            conservative = int(provider.get("skp_proyeksi_konservatif", projected))
            label = provider.get("nama_penyedia") or "Penyedia"
            identity_note = ""
            input_name = str(provider.get("nama_penyedia_excel") or "").strip()
            if provider.get("nama_penyedia_mismatch") and input_name:
                identity_note = (
                    f" Nama Excel: {input_name}; NPWP cocok dengan identitas SPSE."
                )
            if projected > engine.SKP_LIMIT:
                st.warning(
                    f"⚠️ **{label}**: {current}/{engine.SKP_LIMIT} paket aktif terverifikasi; "
                    f"batch ini menambah {candidate_count}, proyeksi {projected}/{engine.SKP_LIMIT}. "
                    "Catatan kapasitas saja; checklist tetap dipertahankan."
                    + identity_note
                )
            elif needs_verification:
                st.warning(
                    f"⚠️ **{label}**: {needs_verification} kontrak perlu verifikasi status selesai. "
                    f"Beban konservatif {conservative}/{engine.SKP_LIMIT}. Verifikasi manual tetap disarankan."
                    + identity_note
                )
            elif projected == engine.SKP_LIMIT:
                st.warning(
                    f"⚠️ **{label}** tepat di batas: proyeksi {projected}/{engine.SKP_LIMIT}."
                    + identity_note
                )
            else:
                st.success(
                    f"✅ **{label}** masih tersedia: proyeksi {projected}/{engine.SKP_LIMIT}."
                    + identity_note
                )

        detail_rows = result.get("rows") or []
        if detail_rows:
            st.markdown(f"**📋 Detail Semua Keterlibatan ({len(detail_rows)} baris)**")
            st.caption(
                "🏆 Pemenang berkontrak dihitung memakai heuristik tanggal akhir jadwal SPSE. "
                "👤 Peserta bukan pemenang hanya konteks. Ini bukan bukti PHO/selesai fisik; "
                "tanggal tabel adalah jendela Penandatanganan Kontrak."
            )
            _render_provider_detail(st, detail_rows)
        else:
            st.caption("Belum ada riwayat paket konstruksi yang cocok di database scraper; proyeksi dimulai dari 0.")
        return True


def render_provider_workload(
    st,
    selected_rows: list[dict],
    key_prefix: str = "pljkk_workload",
) -> None:
    """Tampilkan beban kontrak historis tanpa menjadi gate SKP konstruksi."""
    if not selected_rows:
        return

    import cek_penyedia_engine as engine

    signature = _provider_check_signature(selected_rows)
    result_key = f"{key_prefix}_result"
    signature_key = f"{key_prefix}_signature"

    with st.container(border=True):
        st.markdown("#### 🔍 Status beban kontrak penyedia")
        st.caption(
            "Memakai histori V20 Scraper dari Tender + Non-Tender. "
            "Kontrak dengan akhir jadwal SPSE lebih dari 30 hari lalu "
            "diasumsikan selesai; tanggal kosong/invalid ditandai perlu verifikasi. "
            "Panel ini informatif dan tidak mengunci submit PLJKK."
        )
        if st.button(
            "🔍 Cek beban kontrak dari V20",
            key=f"{key_prefix}_run",
            type="secondary",
            use_container_width=True,
        ):
            with st.spinner("Memeriksa histori penyedia di database V20 Scraper..."):
                st.session_state[result_key] = engine.check_selected_providers(
                    selected_rows,
                    include_non_construction=True,
                )
                st.session_state[signature_key] = signature

        result = st.session_state.get(result_key)
        if st.session_state.get(signature_key) != signature:
            st.info("Klik **Cek beban kontrak dari V20** untuk memuat status penyedia.")
            return
        if not result:
            return
        for error in result.get("errors") or []:
            st.warning(error)
        for provider in result.get("providers") or []:
            label = provider.get("nama_penyedia") or "Penyedia"
            active = int(provider.get("skp_berjalan", 0))
            review = int(provider.get("skp_perlu_verifikasi", 0))
            if review:
                st.warning(
                    f"⚠️ **{label}**: {active} kontrak aktif terindikasi; "
                    f"{review} perlu verifikasi tanggal akhir."
                )
            else:
                st.success(f"✅ **{label}**: {active} kontrak aktif terindikasi.")

        detail_rows = result.get("rows") or []
        if detail_rows:
            st.markdown(f"**📋 Detail histori kontrak ({len(detail_rows)} baris)**")
            _render_provider_detail(st, detail_rows, "Status kontrak")


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
            with st.container(border=True):
                left, right = st.columns([2, 1])
                with left:
                    st.markdown(f"**{summary['nama_penyedia']}**")
                    st.caption(f"NPWP: {summary.get('npwp') or '-'}")
                with right:
                    if summary.get("skp_perlu_verifikasi"):
                        badge = "🟡 Perlu verifikasi"
                    elif summary["skp_berjalan"] <= engine.SKP_LIMIT:
                        badge = "🟢 Aman"
                    else:
                        badge = "🔴 Melebihi batas"
                    st.markdown(f"**{badge}**")
                    st.caption(f"Paket dimenangkan: {summary['paket_dimenangkan']}")
                    st.caption(
                        f"SKP aktif terverifikasi: {summary['skp_berjalan']} "
                        f"dari batas {engine.SKP_LIMIT}"
                    )
                    if summary.get("skp_perlu_verifikasi"):
                        st.caption(f"Kontrak perlu verifikasi: {summary['skp_perlu_verifikasi']}")
                metrics = st.columns(6)
                metrics[0].metric("📦 Total keterlibatan", summary["total_keterlibatan"])
                metrics[1].metric("🏆 Paket dimenangkan", summary["paket_dimenangkan"])
                metrics[2].metric("👤 Peserta bukan pemenang", summary["peserta_bukan_pemenang"])
                metrics[3].metric("⚙️ Tahap SPSE aktif", summary["paket_berjalan"])
                metrics[4].metric("✅ SKP aktif terverifikasi", summary["skp_berjalan"])
                metrics[5].metric("🟡 Perlu verifikasi", summary.get("skp_perlu_verifikasi", 0))

        detail_rows = result.get("rows") or []
        st.divider()
        st.markdown(f"**📋 Detail Semua Keterlibatan ({len(detail_rows)} baris)**")
        st.caption(
            "🏆 Pemenang dihitung sebagai kemenangan. "
            "👤 Peserta bukan pemenang hanya menunjukkan ikut tender dan tidak dihitung sebagai kemenangan/SKP. "
            "Kontrak ada tetapi tahap SPSE selesai ditandai Perlu verifikasi; scraper belum memiliki PHO. "
            "Tanggal kontrak adalah jendela penandatanganan, bukan akhir masa pelaksanaan pekerjaan."
        )
        _render_provider_detail(st, detail_rows)


def render_download_actions(
    st,
    selected_rows: list[dict],
    kualifikasi_engine,
    hasil_engine,
    label_fn,
    family: str = "PK",
) -> None:
    """Render aksi download kualifikasi + populate evaluasi untuk paket PL."""
    from ui_pl_common import mark_pl7_action_success

    jumlah = len(selected_rows)
    if not selected_rows:
        st.info("Centang minimal 1 paket di kiri.")
        return

    st.markdown(f"**{jumlah} paket** dipilih")
    st.caption("Peserta akan di-fetch via CDP saat tombol Jalankan diklik.")
    do_download = st.checkbox("⬇️ Download dokumen kualifikasi", value=True, key="pl7_do_dl")
    do_parse = st.checkbox("📋 Parse & populate sheet Hasil Evaluasi", value=True, key="pl7_do_parse")
    do_hps = st.checkbox("💰 Update HPS (sheet 5. HPS)", value=True, key="pl7_do_hps_pk")
    run = st.button(
        f"▶ Jalankan — {jumlah} paket",
        type="primary", key="pl7_run", use_container_width=True,
    )
    if not run:
        return

    progress = st.progress(0.0, text="Memulai...")
    logs: list[str] = []
    summary: list[dict] = []
    detail_logs: list[tuple[str, list[str]]] = []

    for index, row in enumerate(selected_rows):
        kode = row["kode_paket"]
        nama = label_fn(row)
        status = st.status(f"Paket {index + 1}/{jumlah} — {nama}", expanded=False)
        with status:
            logs.clear()
            log_box = st.empty()

            def log_cb(message, box=log_box, lines=logs):
                lines.append(str(message))
                box.caption(str(message).replace("\n", " ")[:120])

            hps_result = None
            if do_hps:
                progress.progress(index / jumlah, text=f"{nama} — update HPS")
                log_cb("--- Update HPS ke sheet 5. HPS ---")
                from pl_ui_helpers import update_hps_paket_pl
                hps_result = update_hps_paket_pl(kode, hasil_engine, log_cb)
                if hps_result.get("ok"):
                    mark_pl7_action_success(
                        st.session_state, family, kode, "hps",
                        f"{hps_result.get('count', 0)} item",
                    )
                    log_cb(f"[OK] HPS: {hps_result.get('count', 0)} item ditulis")
                else:
                    log_cb(f"[GAGAL] HPS: {hps_result.get('pesan', '-')}")
            result = None

            hps_summary = ""
            if hps_result is not None:
                hps_summary = (
                    f"Update HPS berhasil ({hps_result.get('count', 0)} item)"
                    if hps_result.get("ok") else
                    f"Update HPS gagal: {hps_result.get('pesan', '-')}"
                )
            if not do_download and not do_parse:
                hps_ok = bool(hps_result and hps_result.get("ok"))
                detail = hps_summary or "tidak ada operasi"
                status.update(
                    label=f"Selesai — {nama}",
                    state="complete" if hps_ok else "error",
                    expanded=False,
                )
                summary.append({
                    "nama": nama,
                    "status": "ok" if hps_ok else "gagal",
                    "detail": detail,
                })
                detail_logs.append((nama, list(logs)))
                progress.progress((index + 1) / jumlah, text=f"Selesai {index + 1}/{jumlah} paket")
                continue

            download_ok = None
            log_cb(f"[{index + 1}/{jumlah}] Fetch peserta SPSE...")
            progress.progress(index / jumlah, text=f"{nama} — fetch peserta")
            fetched = kualifikasi_engine.fetch_peserta_pl(kode)
            if not fetched.get("ok"):
                detail = fetched.get("pesan", "peserta tidak ditemukan")
                if hps_summary:
                    detail = f"{detail}; {hps_summary}"
                log_cb(f"[SKIP] Peserta: {detail}")
                status.update(label=f"SKIP {nama} — {detail}", state="error", expanded=False)
                summary.append({"nama": nama, "status": "skip", "detail": detail})
                detail_logs.append((nama, list(logs)))
                continue

            peserta = fetched["peserta"]
            log_cb(f"Peserta ({len(peserta)}): {', '.join(p['nama'] for p in peserta)}")
            folder = kualifikasi_engine.resolve_folder_paket_pl(kode)
            if not folder.get("ok"):
                detail = folder.get("pesan", "folder tidak ditemukan")
                if hps_summary:
                    detail = f"{detail}; {hps_summary}"
                log_cb(f"[SKIP] Folder: {detail}")
                status.update(label=f"SKIP {nama} — {detail}", state="error", expanded=False)
                summary.append({"nama": nama, "status": "skip", "detail": detail})
                detail_logs.append((nama, list(logs)))
                continue

            folder_kualifikasi = folder["path"]
            if do_download:
                progress.progress((index + 0.3) / jumlah, text=f"{nama} — download kualifikasi")
                download_results = []
                for urutan, peserta_row in enumerate(peserta, 1):
                    log_cb(f"--- Download [{urutan}/{len(peserta)}] {peserta_row['nama']} ---")
                    download_results.append(kualifikasi_engine.download_kualifikasi_peserta_pl(
                        peserta_row, folder_kualifikasi, urutan, len(peserta), log_cb,
                    ))
                download_ok = bool(peserta) and all(
                    bool(download_result.get("ok"))
                    for download_result in download_results
                )
                if download_ok:
                    mark_pl7_action_success(
                        st.session_state, family, kode, "download",
                        f"{len(peserta)} peserta",
                    )
                else:
                    log_cb("[GAGAL] Download kualifikasi tidak selesai untuk semua peserta")

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
                    mark_pl7_action_success(
                        st.session_state, family, kode, "parse",
                        result.get("pesan", ""),
                    )
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
                    "status": "ok" if (
                        (not do_download or bool(download_ok))
                        and result.get("ok")
                        and (not do_hps or bool(hps_result and hps_result.get("ok")))
                    ) else "gagal",
                    "detail": "; ".join(
                        part for part in (result.get("pesan", ""), hps_summary) if part
                    ),
                })
            else:
                summary.append({
                    "nama": nama,
                    "status": "ok" if (
                        (not do_download or bool(download_ok))
                        and (not do_hps or bool(hps_result and hps_result.get("ok")))
                    ) else "gagal",
                    "detail": "; ".join(part for part in ("download saja", hps_summary) if part),
                })

            _package_ok = (not do_download or bool(download_ok)) and (
                not do_parse or bool(result and result.get("ok"))
            ) and (
                not do_hps or bool(hps_result and hps_result.get("ok"))
            )
            status.update(
                label=f"Selesai — {nama}",
                state="complete" if _package_ok else "error",
                expanded=False,
            )
            detail_logs.append((nama, list(logs)))
        progress.progress((index + 1) / jumlah, text=f"Selesai {index + 1}/{jumlah} paket")

    progress.progress(1.0, text="Semua paket selesai.")
    if detail_logs:
        with st.expander("📋 Log detail proses", expanded=False):
            for nama_log, lines_log in detail_logs:
                st.caption(nama_log)
                st.code("\n".join(lines_log))
    from batch_summary import render_ringkasan_batch
    render_ringkasan_batch(st, summary)
