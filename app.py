"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import sys
import threading
import time
from datetime import datetime, timedelta
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SPSE_BASE_URL
import spse_browser
import ldk_engine
import ldk_config
import checklist_engine
import masa_berlaku_engine
import penjelasan_engine
import penjelasan_config
import jadwal_engine
import jadwal_config
import kirimpesan_engine
import bareviu_engine
import ba_engine
import ba_config

st.set_page_config(
    page_title="Asisten Pokja",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 Asisten Pokja")
st.caption("Otomasi SPSE — spse.tapinkab.go.id")

# ============================================================
# Sidebar — Browser Control
# ============================================================

with st.sidebar:
    st.header("Browser SPSE")

    # Auto-reconnect Playwright hanya saat dibutuhkan (lazy) — sidebar info pakai CDP HTTP saja
    # buka_browser() dipanggil oleh engine saat submit, bukan di sini setiap refresh

    url_aktif = spse_browser.get_url()
    if url_aktif:
        st.success("Browser terhubung")
        st.caption(url_aktif[:60] + "..." if len(url_aktif) > 60 else url_aktif)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Refresh", use_container_width=True):
                spse_browser._cdp_tabs(force=True)  # invalidate cache
                page = spse_browser.halaman_aktif()
                if page:
                    try:
                        page.reload()
                    except Exception:
                        pass
                st.rerun()
        with col2:
            if st.button("❌ Tutup", use_container_width=True):
                spse_browser.tutup_browser()
                st.rerun()
    else:
        st.info("Chrome SPSE belum terhubung")

        if st.button("🌐 Hubungkan ke Chrome SPSE", type="primary", use_container_width=True):
            try:
                with st.spinner("Menghubungkan..."):
                    spse_browser.buka_browser(SPSE_BASE_URL)
                st.success("Terhubung!")
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))

        st.divider()
        st.caption("💡 **Opsi otomatis:** Chrome akan diluncurkan langsung dari sini")

        if st.button("🚀 Launch Chrome Otomatis", type="secondary", use_container_width=True):
            try:
                with st.spinner("Meluncurkan Chrome SPSE..."):
                    spse_browser.launch_chrome_dengan_cdp()
                    # Tunggu Chrome siap
                    time.sleep(3)
                # Auto-connect setelah Chrome launch
                with st.spinner("Menghubungkan ke Chrome..."):
                    spse_browser.buka_browser(SPSE_BASE_URL)
                st.success("Chrome SPSE berhasil diluncurkan & terhubung!")
                st.rerun()
            except Exception as e:
                st.error(f"Gagal launch Chrome: {e}")

# ============================================================
# Tabs
# ============================================================

_HARI_NAMA  = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_BULAN_NAMA = ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
               "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

tab9, tab8, tab_setup, tab7, tab_ba = st.tabs([
    "1️⃣ Kirim Undangan DPP", "2️⃣ Buat Jadwal",
    "3️⃣ Setup Paket", "4️⃣ Pemberian Penjelasan",
    "5️⃣ Upload 5 BA",
])

# Auto-start scheduler saat app dibuka (daemon thread, jalan terus)
penjelasan_engine.start_scheduler()

# ============================================================
# Tab Setup Paket: LDK Auto-fill + Checklist + Masa Berlaku
# ============================================================

with tab_setup:
    # ── Layout 2 kolom: kiri = pilih paket + konfigurasi, kanan = upload dokpil ─
    _sp_col_kiri, _sp_col_kanan = st.columns([2, 3])

    with _sp_col_kiri:
        st.markdown("### 1. Pilih Paket")
        st.caption("💡 Pastikan browser sudah membuka halaman **/paket** di SPSE sebelum fetch.")
        col_spfetch, col_spall, col_spnone = st.columns([3, 1, 1])
        with col_spfetch:
            if st.button("🔍 Ambil Paket Draft", key="sp_fetch_draft", use_container_width=True):
                with st.spinner("Mengambil daftar paket..."):
                    result = kirimpesan_engine.fetch_paket_draft()
                st.session_state["sp_paket_draft"] = result
                for key in list(st.session_state.keys()):
                    if key.startswith("sp_chk_"):
                        del st.session_state[key]

        sp_selected = []
        if "sp_paket_draft" in st.session_state:
            r = st.session_state["sp_paket_draft"]
            if not r["sukses"]:
                st.error(f"❌ {r['pesan']}")
            else:
                paket_list_sp = r.get("paket", [])
                if not paket_list_sp:
                    st.warning("⚠️ Tidak ada paket berstatus Draft.")
                else:
                    with col_spall:
                        if st.button("✅ Semua", key="sp_sel_all", use_container_width=True):
                            for p in paket_list_sp:
                                st.session_state[f"sp_chk_{p['id_lelang']}"] = True
                            st.rerun()
                    with col_spnone:
                        if st.button("⬜ Kosong", key="sp_sel_none", use_container_width=True):
                            for p in paket_list_sp:
                                st.session_state[f"sp_chk_{p['id_lelang']}"] = False
                            st.rerun()

                    for p in paket_list_sp:
                        key_chk  = f"sp_chk_{p['id_lelang']}"
                        key_dokpil = f"sp_dokpil_{p['id_lelang']}"
                        col_chk, col_dokpil = st.columns([3, 2])
                        with col_chk:
                            checked = st.checkbox(
                                f"**{p['kode']}** — {p['nama']}",
                                value=st.session_state.get(key_chk, True),
                                key=key_chk,
                            )
                        with col_dokpil:
                            up_dokpil = st.file_uploader(
                                "DOKPIL",
                                type=["pdf"],
                                key=key_dokpil,
                                label_visibility="collapsed",
                            )
                            if up_dokpil:
                                st.caption(f"📄 {up_dokpil.name}")
                        if checked:
                            sp_selected.append({**p, "_dokpil": up_dokpil})

                    st.caption(f"**{len(sp_selected)}** dari **{len(paket_list_sp)}** paket dipilih")
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket Draft.")

        # ── Section 3: Upload Dokumen Pemilihan (di bawah checklist) ─────────
        st.divider()
        st.markdown("### 3. Upload Dokumen Pemilihan")
        st.caption("Menggunakan file DOKPIL yang sudah diupload di atas. Isi nomor BA dan tanggal, lalu klik Upload.")

        _dp_dengan_file = [p for p in sp_selected if p.get("_dokpil")]
        _dp_tanpa_file  = [p for p in sp_selected if not p.get("_dokpil")]
        dp_selected     = _dp_dengan_file

        if not sp_selected:
            st.info("Pilih paket dan upload DOKPIL di atas terlebih dahulu.")
        else:
            if _dp_dengan_file:
                st.caption(f"✅ **{len(_dp_dengan_file)} paket** siap diupload:")
                for _p in _dp_dengan_file:
                    st.markdown(f"- **{_p['kode']}** — {_p['nama'][:60]}  \n  📄 `{_p['_dokpil'].name}`")
            if _dp_tanpa_file:
                st.caption(f"⚠️ **{len(_dp_tanpa_file)} paket** tanpa DOKPIL (dilewati):")
                for _p in _dp_tanpa_file:
                    st.markdown(f"- **{_p['kode']}** — {_p['nama'][:60]}")

        dp_nomor_ba = st.text_input(
            "Nomor BA",
            placeholder="Contoh: 001/BA-DPP/POKJA/2026",
            key="dp_nomor_ba",
        )
        _dp_col_tgl, _dp_col_btn = st.columns([2, 3])
        with _dp_col_tgl:
            dp_tgl = st.date_input(
                "Tanggal Dokumen",
                value=datetime.now().date(),
                key="dp_tgl",
                format="DD/MM/YYYY",
                label_visibility="collapsed",
            )
            st.caption(f"{_HARI_NAMA[dp_tgl.weekday()]}, {dp_tgl.day} {_BULAN_NAMA[dp_tgl.month-1]} {dp_tgl.year}")
        with _dp_col_btn:
            _dp_n_file = len(dp_selected)
            if st.button(
                f"📤 Upload Dokumen Pemilihan ({_dp_n_file} file)",
                key="dp_upload",
                type="primary",
                disabled=_dp_n_file == 0,
                use_container_width=True,
            ):
                st.warning(
                    "⚠️ **Fitur ini belum aktif.** Endpoint upload Dokumen Pemilihan di SPSE "
                    "baru bisa dibedah setelah ada paket yang sudah upload BA Reviu dan semua syarat terpenuhi."
                )
                st.info(
                    f"**Siap diupload:** {_dp_n_file} file  \n"
                    f"**Nomor BA:** {dp_nomor_ba or '(belum diisi)'}  \n"
                    f"**Tanggal:** {dp_tgl.strftime('%d-%m-%Y')}"
                )

    with _sp_col_kanan:
        st.markdown("### 2. Konfigurasi")
        st.caption("Upload DOKPIL per paket di sebelah kiri — akan di-extract saat Push.")

        st.divider()

        # ── Izin Usaha rows (fallback jika DOKPIL tidak diupload) ────────────
        st.markdown("**Izin Usaha** *(default — ditimpa oleh DOKPIL jika diupload)*")
        if "ijin_rows" not in st.session_state:
            st.session_state["ijin_rows"] = [dict(r) for r in ldk_config.IJIN_USAHA_DEFAULT["rows"]]

        # ── Load/save SBU terakhir ke file ───────────────────────────────────
        import json as _json
        _SBU_LAST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sbu_last.json")

        def _load_sbu_last():
            try:
                with open(_SBU_LAST_FILE, "r", encoding="utf-8") as f:
                    return _json.load(f)
            except Exception:
                return {"sbu_2020": "", "sbu_2015": ""}

        def _save_sbu_last(sbu_2020, sbu_2015):
            try:
                with open(_SBU_LAST_FILE, "w", encoding="utf-8") as f:
                    _json.dump({"sbu_2020": sbu_2020, "sbu_2015": sbu_2015}, f)
            except Exception:
                pass

        # Inisialisasi default SBU dari file — hanya sekali per session, SEBELUM widget dirender
        if "sbu_last_loaded" not in st.session_state:
            _last = _load_sbu_last()
            # Hanya set jika key belum ada (jangan overwrite pilihan user saat ini)
            if "sbu_2020_1" not in st.session_state:
                st.session_state["sbu_2020_1"] = _last["sbu_2020"]
            if "sbu_2015_1" not in st.session_state:
                st.session_state["sbu_2015_1"] = _last["sbu_2015"]
            st.session_state["sbu_last_loaded"] = True

        # Opsi SBU dropdown — tambah kosong di awal
        _sbu_opts_2020 = [""] + ldk_config.SBU_KBLI_2020
        _sbu_opts_2015 = [""] + ldk_config.SBU_KBLI_2015

        for i, row in enumerate(st.session_state["ijin_rows"]):
            st.caption(f"Row {i+1}")

            # Row 2 = SBU → tampilkan 2 dropdown
            if i == 1:
                col_jn, col_del = st.columns([6, 1])
                with col_jn:
                    st.session_state["ijin_rows"][i]["jenis_izin"] = st.text_input(
                        "Jenis Izin", value=row["jenis_izin"],
                        key=f"ijin_nama_{i}", label_visibility="collapsed",
                    )
                with col_del:
                    if len(st.session_state["ijin_rows"]) > 1:
                        if st.button("🗑️", key=f"hapus_row_{i}", use_container_width=True):
                            st.session_state["ijin_rows"].pop(i)
                            st.rerun()

                col_2020, col_2015 = st.columns(2)
                with col_2020:
                    sbu_2020 = st.selectbox(
                        "SBU KBLI 2020",
                        options=_sbu_opts_2020,
                        key="sbu_2020_1",
                        label_visibility="collapsed",
                    )
                with col_2015:
                    sbu_2015 = st.selectbox(
                        "SBU KBLI 2015",
                        options=_sbu_opts_2015,
                        key="sbu_2015_1",
                        label_visibility="collapsed",
                    )

                # Auto-generate teks klasifikasi dari pilihan dropdown
                _gen = ldk_config.build_sbu_klasifikasi(sbu_2020, sbu_2015)
                if _gen:
                    st.session_state["ijin_rows"][i]["klasifikasi"] = _gen
                    st.text_area(
                        "Preview teks SBU",
                        value=_gen,
                        key=f"ijin_klas_{i}_preview",
                        label_visibility="collapsed",
                        height=100,
                        disabled=True,
                    )
                else:
                    # Fallback: edit manual jika belum pilih SBU
                    st.session_state["ijin_rows"][i]["klasifikasi"] = st.text_area(
                        "Klasifikasi manual",
                        value=row["klasifikasi"],
                        key=f"ijin_klas_{i}",
                        label_visibility="collapsed",
                        height=80,
                    )
            else:
                col_r1, col_r2, col_r3 = st.columns([2, 5, 1])
                with col_r1:
                    st.session_state["ijin_rows"][i]["jenis_izin"] = st.text_input(
                        "Jenis Izin", value=row["jenis_izin"],
                        key=f"ijin_nama_{i}", label_visibility="collapsed",
                    )
                with col_r2:
                    st.session_state["ijin_rows"][i]["klasifikasi"] = st.text_area(
                        "Klasifikasi", value=row["klasifikasi"],
                        key=f"ijin_klas_{i}", label_visibility="collapsed", height=80,
                    )
                with col_r3:
                    if len(st.session_state["ijin_rows"]) > 1:
                        if st.button("🗑️", key=f"hapus_row_{i}", use_container_width=True):
                            st.session_state["ijin_rows"].pop(i)
                            st.rerun()

        if st.button("➕ Tambah Row Izin", key="tambah_row_ijin"):
            st.session_state["ijin_rows"].append({"jenis_izin": "", "klasifikasi": ""})
            st.rerun()

        st.divider()

        # ── Syarat Teknis (Kinerja Penyedia + rows tambahan) ─────────────────
        st.markdown("**Syarat Teknis**")
        if "sp_syarat_teknis_rows" not in st.session_state:
            st.session_state["sp_syarat_teknis_rows"] = [
                {"label": "Kinerja Penyedia", "teks": ldk_config.KINERJA_PENYEDIA_DEFAULT}
            ]

        _st_rows = st.session_state["sp_syarat_teknis_rows"]
        for i, st_row in enumerate(_st_rows):
            col_lbl, col_del = st.columns([5, 1])
            with col_lbl:
                chk = st.checkbox(
                    st_row["label"],
                    value=st.session_state.get(f"sp_st_chk_{i}", True),
                    key=f"sp_st_chk_{i}",
                )
            with col_del:
                if len(_st_rows) > 1 and st.button("🗑️", key=f"sp_st_del_{i}", use_container_width=True):
                    _st_rows.pop(i)
                    st.rerun()
            if chk:
                _st_rows[i]["teks"] = st.text_area(
                    "Teks",
                    value=st_row["teks"],
                    key=f"sp_st_teks_{i}",
                    height=80,
                    label_visibility="collapsed",
                )

        if st.button("➕ Tambah Syarat Teknis", key="sp_tambah_syarat"):
            _st_rows.append({"label": "Syarat Teknis Baru", "teks": ""})
            st.rerun()

        st.divider()

        # ── Masa Berlaku ──────────────────────────────────────────────────────
        st.markdown("**Masa Berlaku Penawaran**")
        mb_nilai_hari = st.number_input(
            "Hari",
            min_value=1, max_value=365, value=40, step=1,
            help="Default 40 hari — standar konstruksi usaha kecil",
            label_visibility="collapsed",
        )
        st.caption(f"{int(mb_nilai_hari)} hari")

        st.divider()

        sp_push = st.button(
            f"🚀 Push Setup ke SPSE ({len(sp_selected)} paket)",
            type="primary",
            use_container_width=True,
            disabled=len(sp_selected) == 0,
            key="sp_push_all",
        )

        if sp_push:
            import tempfile, ldk_pdf_extractor as _ldk_ext

            # Simpan pilihan SBU terakhir (persisten lintas restart Streamlit)
            _save_sbu_last(
                st.session_state.get("sbu_2020_1", ""),
                st.session_state.get("sbu_2015_1", ""),
            )

            # Default dari form (dipakai jika paket tidak punya DOKPIL)
            _default_ijin = st.session_state.get("ijin_rows", ldk_config.IJIN_USAHA_DEFAULT["rows"])
            _default_kinerja = "\n".join(
                r["teks"] for i, r in enumerate(st.session_state.get("sp_syarat_teknis_rows", []))
                if st.session_state.get(f"sp_st_chk_{i}", True) and r["teks"].strip()
            )
            mb_hari = int(mb_nilai_hari)

            progress = st.progress(0, text="Memulai...")
            hasil_sp = []

            for i, p in enumerate(sp_selected):
                pid = p["id_lelang"]
                progress.progress((i + 1) / len(sp_selected), text=f"Setup {p['kode']} ({i+1}/{len(sp_selected)})...")

                row_result = {"kode": p["kode"], "nama": p["nama"][:50], "ldk": "—", "checklist": "—", "masa_berlaku": "—"}

                # Extract DOKPIL per paket jika diupload
                ijin_rows   = _default_ijin
                kinerja_txt = _default_kinerja
                dokpil_file = p.get("_dokpil")
                if dokpil_file:
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(dokpil_file.getvalue())
                            tmp_path = tmp.name
                        ldk_data = _ldk_ext.extract_ldk_from_pdf(tmp_path)
                        try:
                            os.unlink(tmp_path)
                        except:
                            pass
                        if ldk_data.extracted:
                            if ldk_data.izin_usaha_rows:
                                ijin_rows = [
                                    {"jenis_izin": r.jenis_izin, "klasifikasi": r.klasifikasi}
                                    for r in ldk_data.izin_usaha_rows
                                ]
                            if ldk_data.kinerja_required and ldk_data.kinerja_penyedia:
                                kinerja_txt = ldk_data.kinerja_penyedia
                        row_result["ldk"] = row_result["ldk"]  # akan diisi di bawah
                    except Exception as e:
                        row_result["ldk"] = f"❌ Extract DOKPIL gagal: {e}"
                        hasil_sp.append(row_result)
                        continue

                try:
                    r_ldk = ldk_engine.submit_ldk(pid, ijin_usaha_rows=ijin_rows, kinerja_text=kinerja_txt)
                    row_result["ldk"] = "✅" if r_ldk["ok"] else f"❌ {r_ldk['status']}"
                except Exception as e:
                    row_result["ldk"] = f"❌ {e}"

                try:
                    r_ck = checklist_engine.submit_checklist(pid)
                    row_result["checklist"] = "✅" if r_ck["sukses"] else f"❌ {r_ck['pesan']}"
                except Exception as e:
                    row_result["checklist"] = f"❌ {e}"

                try:
                    r_mb = masa_berlaku_engine.submit_masa_berlaku(pid, mb_hari)
                    row_result["masa_berlaku"] = "✅" if r_mb["sukses"] else f"❌ {r_mb['pesan']}"
                except Exception as e:
                    row_result["masa_berlaku"] = f"❌ {e}"

                hasil_sp.append(row_result)

            progress.empty()

            sukses_n = sum(1 for h in hasil_sp if all(v == "✅" for k, v in h.items() if k not in ("kode", "nama")))
            st.success(f"✅ Selesai! {sukses_n}/{len(hasil_sp)} paket berhasil.")
            st.dataframe(
                hasil_sp,
                use_container_width=True,
                column_config={
                    "kode":         st.column_config.TextColumn("Kode", width="small"),
                    "nama":         st.column_config.TextColumn("Nama Paket", width="large"),
                    "ldk":          st.column_config.TextColumn("LDK", width="small"),
                    "checklist":    st.column_config.TextColumn("Checklist", width="small"),
                    "masa_berlaku": st.column_config.TextColumn("Masa Berlaku", width="small"),
                },
                hide_index=True,
            )

# ============================================================
# Tab 4: Pemberian Penjelasan (v2 — auto-post sapaan via GCal)
# ============================================================

with tab7:
    # ── Layout 2 kolom: kiri = pilih paket, kanan = isi pembukaan ───────
    _pj_col_kiri, _pj_col_kanan = st.columns([2, 3])

    with _pj_col_kiri:
        st.markdown("### 1. Pilih Paket")
        st.caption("💡 Pastikan browser sudah membuka halaman **/paket** di SPSE sebelum fetch.")
        col_pjfetch, col_pjall, col_pjnone = st.columns([3, 1, 1])
        with col_pjfetch:
            if st.button("🔍 Ambil Paket Draft", key="pj_fetch_draft", use_container_width=True):
                with st.spinner("Mengambil daftar paket..."):
                    result = kirimpesan_engine.fetch_paket_draft()
                st.session_state["pj_paket_draft"] = result
                for key in list(st.session_state.keys()):
                    if key.startswith("pj_chk_"):
                        del st.session_state[key]

        pj_selected = []
        if "pj_paket_draft" in st.session_state:
            r = st.session_state["pj_paket_draft"]
            if not r["sukses"]:
                st.error(f"❌ {r['pesan']}")
            else:
                paket_list_pj = r.get("paket", [])
                if not paket_list_pj:
                    st.warning("⚠️ Tidak ada paket berstatus Draft.")
                else:
                    with col_pjall:
                        if st.button("✅ Semua", key="pj_sel_all", use_container_width=True):
                            for p in paket_list_pj:
                                st.session_state[f"pj_chk_{p['id_lelang']}"] = True
                            st.rerun()
                    with col_pjnone:
                        if st.button("⬜ Kosong", key="pj_sel_none", use_container_width=True):
                            for p in paket_list_pj:
                                st.session_state[f"pj_chk_{p['id_lelang']}"] = False
                            st.rerun()

                    for p in paket_list_pj:
                        key_chk = f"pj_chk_{p['id_lelang']}"
                        checked = st.checkbox(
                            f"**{p['kode']}** — {p['nama']}",
                            value=st.session_state.get(key_chk, True),
                            key=key_chk,
                        )
                        if checked:
                            pj_selected.append(p)

                    st.caption(f"**{len(pj_selected)}** dari **{len(paket_list_pj)}** paket dipilih")
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket Draft.")

    with _pj_col_kanan:
        st.markdown("### 2. Isi Pembukaan")
        st.caption("Template sapaan akan otomatis di-post saat masa penjelasan tiba.")

        pj_jenis = st.selectbox(
            "Jenis Penjelasan",
            options=list(penjelasan_config.JENIS_PAKET.keys()),
            format_func=lambda k: penjelasan_config.JENIS_PAKET[k],
            key="pj_jenis",
        )

        with st.expander("✏️ Override teks pembukaan (opsional)"):
            pj_teks_override = st.text_area(
                "Teks custom", value="", height=120,
                placeholder="Kosongkan untuk pakai template bawaan",
            )

        # ── Countdown timer per paket terpilih ─────────────────────────────
        if pj_selected:
            st.markdown("### ⏰ Countdown Penjelasan")
            st.caption("Waktu mundur dari Google Calendar.")

            with st.spinner("Baca jadwal dari Google Calendar..."):
                jadwal_gcal = penjelasan_engine.get_jadwal_dari_gcalendar()

            from penjelasan_engine import TZ_WIB
            now = datetime.now(TZ_WIB)

            for p in pj_selected:
                pid = p["id_lelang"]
                tgl_mulai = jadwal_gcal.get(pid)

                if tgl_mulai:
                    delta = tgl_mulai - now
                    total_secs = int(delta.total_seconds())

                    if total_secs > 0:
                        hari = total_secs // 86400
                        jam  = (total_secs % 86400) // 3600
                        menit = (total_secs % 3600) // 60
                        detik = total_secs % 60
                        status_icon = "⏳"
                        status_teks = f"{hari}h {jam}j {menit}m {detik}d"
                    elif total_secs > -10800:  # masih dalam window 3 jam setelah mulai
                        status_icon = "🔴"
                        status_teks = "MASA PENJELASAN AKTIF"
                    else:
                        status_icon = "✅"
                        status_teks = "Sudah lewat"

                    st.markdown(
                        f"**{status_icon} {p['kode']}** — {p['nama'][:50]}  \n"
                        f"Mulai: `{tgl_mulai.strftime('%d/%m/%Y %H:%M')}` | {status_teks}"
                    )
                else:
                    st.markdown(f"⚠️ **{p['kode']}** — Tidak ada event penjelasan di GCal")

        st.divider()

        # ── Tombol Post Manual ─────────────────────────────────────────────
        pj_n = len(pj_selected)
        if st.button(
            f"🚀 Post Pembukaan ke {pj_n} Paket",
            key="pj_post",
            type="primary",
            disabled=pj_n == 0,
            use_container_width=True,
        ):
            progress = st.progress(0, text="Memulai...")
            hasil_pj = []
            for i, p in enumerate(pj_selected):
                progress.progress((i + 1) / len(pj_selected), text=f"Post ke {p['kode']} ({i+1}/{len(pj_selected)})...")
                try:
                    teks_ov = pj_teks_override.strip() or None
                    result = penjelasan_engine.auto_post_sapaan(p["id_lelang"], pj_jenis, teks_ov)
                    hasil_pj.append({
                        "kode": p["kode"],
                        "nama": p["nama"][:50],
                        "total": result["total"],
                        "sukses": result["sukses"],
                        "gagal": result["gagal"],
                        "pesan": result.get("pesan", ""),
                    })
                except Exception as e:
                    hasil_pj.append({
                        "kode": p["kode"],
                        "nama": p["nama"][:50],
                        "total": 0,
                        "sukses": 0,
                        "gagal": 1,
                        "pesan": str(e),
                    })
            progress.empty()

            sukses_n = sum(1 for h in hasil_pj if h["gagal"] == 0 and h["total"] > 0)
            if sukses_n == len(hasil_pj):
                st.success(f"✅ {sukses_n}/{len(hasil_pj)} paket berhasil.")
            else:
                st.warning(f"⚠️ {sukses_n}/{len(hasil_pj)} paket berhasil.")
            st.dataframe(
                hasil_pj,
                use_container_width=True,
                column_config={
                    "kode":  st.column_config.TextColumn("Kode", width="small"),
                    "nama":  st.column_config.TextColumn("Nama Paket", width="large"),
                    "total": st.column_config.NumberColumn("Total", width="small"),
                    "sukses": st.column_config.NumberColumn("Sukses", width="small"),
                    "gagal": st.column_config.NumberColumn("Gagal", width="small"),
                    "pesan": st.column_config.TextColumn("Pesan"),
                },
                hide_index=True,
            )

# ============================================================
# Tab 8: Auto-Fill Jadwal
# ============================================================

with tab8:

    _hari_nama  = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
    _bulan_nama = ["Januari","Februari","Maret","April","Mei","Juni",
                   "Juli","Agustus","September","Oktober","November","Desember"]
    LIBUR_2026 = {
        "2026-01-01": "Tahun Baru 2026 Masehi",
        "2026-01-16": "Isra Mikraj Nabi Muhammad S.A.W.",
        "2026-02-16": "Cuti Bersama Tahun Baru Imlek",
        "2026-02-17": "Tahun Baru Imlek 2577 Kongzili",
        "2026-03-18": "Cuti Bersama Hari Suci Nyepi",
        "2026-03-19": "Hari Suci Nyepi (Tahun Baru Saka 1948)",
        "2026-03-20": "Cuti Bersama Idul Fitri 1447 Hijriah",
        "2026-03-21": "Idul Fitri 1447 Hijriah",
        "2026-03-22": "Idul Fitri 1447 Hijriah",
        "2026-03-23": "Cuti Bersama Idul Fitri 1447 Hijriah",
        "2026-03-24": "Cuti Bersama Idul Fitri 1447 Hijriah",
        "2026-04-03": "Wafat Yesus Kristus",
        "2026-04-05": "Kebangkitan Yesus Kristus (Paskah)",
        "2026-05-01": "Hari Buruh Internasional",
        "2026-05-14": "Kenaikan Yesus Kristus",
        "2026-05-15": "Cuti Bersama Kenaikan Yesus Kristus",
        "2026-05-27": "Idul Adha 1447 Hijriah",
        "2026-05-28": "Cuti Bersama Idul Adha 1447 Hijriah",
        "2026-05-31": "Hari Raya Waisak 2570 BE",
        "2026-06-01": "Hari Lahir Pancasila",
        "2026-06-16": "1 Muharam Tahun Baru Islam 1448 Hijriah",
        "2026-08-17": "Proklamasi Kemerdekaan",
        "2026-08-25": "Maulid Nabi Muhammad S.A.W.",
        "2026-12-24": "Cuti Bersama Kelahiran Yesus Kristus",
        "2026-12-25": "Kelahiran Yesus Kristus",
    }
    _libur_map = {datetime.strptime(k, "%Y-%m-%d").date(): v for k, v in LIBUR_2026.items()}

    _jd_col_list, _jd_col_detail = st.columns([3, 2])

    with _jd_col_list:
        st.markdown("### 1. Pilih Paket")
        st.caption("💡 Pastikan browser sudah membuka halaman **/paket** di SPSE sebelum fetch.")
        col_fetch, col_all, col_none = st.columns([3, 1, 1])
        with col_fetch:
            if st.button("🔍 Ambil Paket Draft", key="jd_fetch_draft", use_container_width=True):
                with st.spinner("Mengambil daftar paket..."):
                    result_draft = kirimpesan_engine.fetch_paket_draft()
                st.session_state["jd_paket_draft"] = result_draft
                for key in list(st.session_state.keys()):
                    if key.startswith("jd_chk_") or key.startswith("jd_tgl_"):
                        del st.session_state[key]

        jd_selected = []
        if "jd_paket_draft" in st.session_state:
            r = st.session_state["jd_paket_draft"]
            if not r["sukses"]:
                st.error(f"❌ {r['pesan']}")
            else:
                paket_list = r.get("paket", [])
                if not paket_list:
                    st.warning("⚠️ Tidak ada paket berstatus Draft.")
                else:
                    with col_all:
                        if st.button("✅ Semua", key="jd_sel_all", use_container_width=True):
                            for p in paket_list:
                                st.session_state[f"jd_chk_{p['id_lelang']}"] = True
                            st.rerun()
                    with col_none:
                        if st.button("⬜ Kosong", key="jd_sel_none", use_container_width=True):
                            for p in paket_list:
                                st.session_state[f"jd_chk_{p['id_lelang']}"] = False
                            st.rerun()

                    for p in paket_list:
                        key_chk = f"jd_chk_{p['id_lelang']}"
                        checked = st.checkbox(
                            f"**{p['kode']}** — {p['nama']}",
                            value=st.session_state.get(key_chk, True),
                            key=key_chk,
                        )
                        if checked:
                            jd_selected.append(p)

                    st.caption(f"**{len(jd_selected)}** dari **{len(paket_list)}** paket dipilih")
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket Draft.")

    with _jd_col_detail:
        st.markdown("### 2. Tanggal Mulai")

        jd_beda_jadwal = st.checkbox(
            "Jadwal berbeda per paket",
            value=False,
            key="jd_beda_jadwal",
        )

        if not jd_beda_jadwal:
            col_date, col_time = st.columns(2)
            with col_date:
                jd_tgl_global = st.date_input(
                    "Tanggal",
                    value=datetime.now().date(),
                    format="DD/MM/YYYY",
                    key="jd_tgl_global",
                )
                st.markdown(f"**{_hari_nama[jd_tgl_global.weekday()]}, {jd_tgl_global.day} {_bulan_nama[jd_tgl_global.month-1]} {jd_tgl_global.year}**")
            with col_time:
                jd_jam_global = st.time_input(
                    "Jam",
                    value=datetime.strptime("08:00", "%H:%M").time(),
                    key="jd_jam_global",
                )
            if jd_tgl_global in _libur_map:
                st.warning(f"⚠️ **{_libur_map[jd_tgl_global]}**")
        else:
            if not jd_selected:
                st.info("Pilih paket di sebelah kiri terlebih dahulu.")
            else:
                for p in jd_selected:
                    key_tgl = f"jd_tgl_{p['id_lelang']}"
                    key_jam = f"jd_jam_{p['id_lelang']}"
                    col_nama, col_tgl, col_jam = st.columns([3, 2, 1])
                    with col_nama:
                        st.markdown(f"**{p['kode']}**")
                    with col_tgl:
                        tgl_p = st.date_input(
                            "Tgl",
                            value=st.session_state.get(key_tgl, datetime.now().date()),
                            format="DD/MM/YYYY",
                            key=key_tgl,
                            label_visibility="collapsed",
                        )
                        if tgl_p in _libur_map:
                            st.caption(f"⚠️ {_libur_map[tgl_p]}")
                        else:
                            st.caption(f"{_hari_nama[tgl_p.weekday()]}, {tgl_p.day} {_bulan_nama[tgl_p.month-1]} {tgl_p.year}")
                    with col_jam:
                        st.time_input(
                            "Jam",
                            value=st.session_state.get(key_jam, datetime.strptime("08:00", "%H:%M").time()),
                            key=key_jam,
                            label_visibility="collapsed",
                        )

        with st.expander("ℹ️ Libur Nasional Tersisa"):
            hari_ini = datetime.now().date()
            sisa = sorted(d for d in _libur_map if d >= hari_ini)
            for d in sisa:
                st.write(f"• {_hari_nama[d.weekday()]}, {d.day} {_bulan_nama[d.month-1]} {d.year} — {_libur_map[d]}")

        st.divider()
        st.caption("⚠️ Akan menimpa jadwal yang sudah ada di SPSE.")

        jd_submit = st.button(
            f"🚀 Set Jadwal ke SPSE ({len(jd_selected)} paket)",
            type="primary",
            use_container_width=True,
            disabled=len(jd_selected) == 0,
            key="jd_submit",
        )

        if jd_submit:
            hasil_list = []
            progress = st.progress(0, text="Memulai...")

            for i, p in enumerate(jd_selected):
                progress.progress((i + 1) / len(jd_selected), text=f"Submit {p['kode']} ({i+1}/{len(jd_selected)})...")

                if jd_beda_jadwal:
                    tgl_p = st.session_state.get(f"jd_tgl_{p['id_lelang']}", datetime.now().date())
                    jam_p = st.session_state.get(f"jd_jam_{p['id_lelang']}", datetime.strptime("08:00", "%H:%M").time())
                else:
                    tgl_p = jd_tgl_global
                    jam_p = jd_jam_global

                tgl_mulai = datetime.combine(tgl_p, jam_p)

                try:
                    result = jadwal_engine.auto_fill_jadwal(p["id_lelang"], tgl_mulai)
                    scraped = result["scraped"]
                    payload = result["payload"]

                    if not scraped.get("csrf"):
                        hasil_list.append({"kode": p["kode"], "nama": p["nama"][:50], "sukses": False, "pesan": "CSRF tidak ditemukan", "mulai": ""})
                        continue
                    if not scraped.get("cookie"):
                        hasil_list.append({"kode": p["kode"], "nama": p["nama"][:50], "sukses": False, "pesan": "Cookie tidak ditemukan", "mulai": ""})
                        continue

                    submit_result = jadwal_engine.submit_jadwal(p["id_lelang"], payload, cookie_str=scraped.get("cookie"))
                    hasil_list.append({
                        "kode": p["kode"],
                        "nama": p["nama"][:50],
                        "sukses": submit_result.get("ok", False),
                        "pesan": f"HTTP {submit_result['status']}",
                        "mulai": tgl_mulai.strftime("%d/%m/%Y %H:%M"),
                    })
                except Exception as e:
                    hasil_list.append({"kode": p["kode"], "nama": p["nama"][:50], "sukses": False, "pesan": str(e), "mulai": ""})

            progress.empty()

            sukses_n = sum(1 for h in hasil_list if h["sukses"])
            gagal_n  = len(hasil_list) - sukses_n
            if gagal_n == 0:
                st.success(f"✅ Semua {sukses_n} paket berhasil dijadwalkan!")
            else:
                st.warning(f"⚠️ {sukses_n} berhasil, {gagal_n} gagal.")

            st.dataframe(
                hasil_list,
                use_container_width=True,
                column_config={
                    "kode":   st.column_config.TextColumn("Kode", width="small"),
                    "nama":   st.column_config.TextColumn("Nama Paket", width="large"),
                    "mulai":  st.column_config.TextColumn("Tgl Mulai"),
                    "sukses": st.column_config.CheckboxColumn("Sukses", width="small"),
                    "pesan":  st.column_config.TextColumn("Pesan"),
                },
                hide_index=True,
            )

# ============================================================
# Tab 9: Kirim Undangan
# ============================================================

with tab9:
    # ── Layout 2 kolom: kiri = pilih paket, kanan = detail undangan ─────────
    _kp_col_list, _kp_col_detail = st.columns([3, 2])

    with _kp_col_list:
        st.markdown("### 1. Pilih Paket")
        st.caption("💡 Pastikan browser sudah membuka halaman **/paket** di SPSE sebelum fetch.")
        col_fetch, col_all, col_none = st.columns([3, 1, 1])
        with col_fetch:
            if st.button("🔍 Ambil Paket Draft", key="kp_fetch_draft", use_container_width=True):
                with st.spinner("Mengambil daftar paket..."):
                    result = kirimpesan_engine.fetch_paket_draft()
                st.session_state["kp_paket_draft"] = result
                for key in list(st.session_state.keys()):
                    if key.startswith("kp_chk_"):
                        del st.session_state[key]

        kp_selected = []
        if "kp_paket_draft" in st.session_state:
            r = st.session_state["kp_paket_draft"]
            if not r["sukses"]:
                st.error(f"❌ {r['pesan']}")
            else:
                paket_list = r.get("paket", [])
                if not paket_list:
                    st.warning("⚠️ Tidak ada paket berstatus Draft.")
                else:
                    with col_all:
                        if st.button("✅ Semua", key="kp_sel_all", use_container_width=True):
                            for p in paket_list:
                                st.session_state[f"kp_chk_{p['id_lelang']}"] = True
                            st.rerun()
                    with col_none:
                        if st.button("⬜ Kosong", key="kp_sel_none", use_container_width=True):
                            for p in paket_list:
                                st.session_state[f"kp_chk_{p['id_lelang']}"] = False
                            st.rerun()

                    for p in paket_list:
                        key_chk = f"kp_chk_{p['id_lelang']}"
                        col_chk, col_lamp = st.columns([3, 2])
                        with col_chk:
                            checked = st.checkbox(
                                f"**{p['kode']}** — {p['nama']}",
                                value=st.session_state.get(key_chk, True),
                                key=key_chk,
                            )
                        with col_lamp:
                            uploaded_lamp = st.file_uploader(
                                "Lampiran",
                                type=["pdf"],
                                key=f"kp_lamp_{p['id_lelang']}",
                                label_visibility="collapsed",
                            )
                            if uploaded_lamp:
                                st.caption(f"📎 {uploaded_lamp.name}")
                        if checked:
                            kp_selected.append({**p, "_lampiran": uploaded_lamp})

                    st.caption(f"**{len(kp_selected)}** dari **{len(paket_list)}** paket dipilih")
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket Draft.")

        # ── 2. Detail Undangan ────────────────────────────────────────────────
        st.divider()
        st.markdown("### 2. Detail Undangan")

        _kp_hari_nama  = _HARI_NAMA
        _kp_bulan_nama = _BULAN_NAMA
        _kp_libur_map = {datetime.strptime(k, "%Y-%m-%d").date(): v for k, v in {
            "2026-01-01": "Tahun Baru 2026 Masehi",
            "2026-01-16": "Isra Mikraj Nabi Muhammad S.A.W.",
            "2026-02-16": "Cuti Bersama Tahun Baru Imlek",
            "2026-02-17": "Tahun Baru Imlek 2577 Kongzili",
            "2026-03-18": "Cuti Bersama Hari Suci Nyepi",
            "2026-03-19": "Hari Suci Nyepi (Tahun Baru Saka 1948)",
            "2026-03-20": "Cuti Bersama Idul Fitri 1447 Hijriah",
            "2026-03-21": "Idul Fitri 1447 Hijriah",
            "2026-03-22": "Idul Fitri 1447 Hijriah",
            "2026-03-23": "Cuti Bersama Idul Fitri 1447 Hijriah",
            "2026-03-24": "Cuti Bersama Idul Fitri 1447 Hijriah",
            "2026-04-03": "Wafat Yesus Kristus",
            "2026-04-05": "Kebangkitan Yesus Kristus (Paskah)",
            "2026-05-01": "Hari Buruh Internasional",
            "2026-05-14": "Kenaikan Yesus Kristus",
            "2026-05-15": "Cuti Bersama Kenaikan Yesus Kristus",
            "2026-05-27": "Idul Adha 1447 Hijriah",
            "2026-05-28": "Cuti Bersama Idul Adha 1447 Hijriah",
            "2026-05-31": "Hari Raya Waisak 2570 BE",
            "2026-06-01": "Hari Lahir Pancasila",
            "2026-06-16": "1 Muharam Tahun Baru Islam 1448 Hijriah",
            "2026-08-17": "Proklamasi Kemerdekaan",
            "2026-08-25": "Maulid Nabi Muhammad S.A.W.",
            "2026-12-24": "Cuti Bersama Kelahiran Yesus Kristus",
            "2026-12-25": "Kelahiran Yesus Kristus",
        }.items()}

        col_tgl, col_mulai, col_selesai = st.columns(3)
        with col_tgl:
            kp_tgl = st.date_input(
                "Tanggal",
                value=datetime.now().date(),
                format="DD/MM/YYYY",
                key="kp_tgl",
            )
            st.markdown(f"**{_kp_hari_nama[kp_tgl.weekday()]}, {kp_tgl.day} {_kp_bulan_nama[kp_tgl.month-1]} {kp_tgl.year}**")
        with col_mulai:
            kp_jam_mulai = st.time_input(
                "Mulai",
                value=datetime.strptime("09:00", "%H:%M").time(),
                key="kp_jam_mulai",
                step=1800,
            )
        with col_selesai:
            kp_jam_selesai = st.time_input(
                "Selesai",
                value=datetime.strptime("11:00", "%H:%M").time(),
                key="kp_jam_selesai",
                step=1800,
            )

        if kp_tgl in _kp_libur_map:
            st.warning(f"⚠️ **{_kp_libur_map[kp_tgl]}**")

        with st.expander("ℹ️ Libur Nasional Tersisa"):
            _kp_hari_ini = datetime.now().date()
            _kp_sisa = sorted(d for d in _kp_libur_map if d >= _kp_hari_ini)
            for d in _kp_sisa:
                st.write(f"• {_kp_hari_nama[d.weekday()]}, {d.day} {_kp_bulan_nama[d.month-1]} {d.year} — {_kp_libur_map[d]}")

        kp_tempat = st.text_area(
            "Tempat",
            value=kirimpesan_engine.DEFAULT_TEMPAT,
            key="kp_tempat",
            height=100,
        )

        # Hardcode: Mekanisme = Offline, Dibawa & Hadir pakai default
        kp_is_online = False
        kp_link = ""
        kp_dibawa = kirimpesan_engine.DEFAULT_DIBAWA
        kp_hadir = kirimpesan_engine.DEFAULT_HADIR

        st.divider()
        st.caption("⚠️ Undangan yang sudah terkirim **tidak bisa dihapus** dari sistem SPSE.")

        kirim_disabled = len(kp_selected) == 0

        if not st.session_state.get("kp_konfirmasi"):
            if st.button(
                f"📨 Kirim Undangan ke {len(kp_selected)} Paket",
                key="kp_kirim",
                type="primary",
                disabled=kirim_disabled,
                use_container_width=True,
            ):
                if not kp_tempat.strip():
                    st.error("❌ Tempat wajib diisi.")
                else:
                    st.session_state["kp_konfirmasi"] = True
                    st.rerun()
        else:
            waktu_str  = datetime.combine(kp_tgl, kp_jam_mulai).strftime("%d-%m-%Y %H:%M")
            sampai_str = datetime.combine(kp_tgl, kp_jam_selesai).strftime("%d-%m-%Y %H:%M")

            st.warning(
                f"Kirim ke **{len(kp_selected)} paket**\n\n"
                f"- Waktu: {waktu_str} s.d. {sampai_str}\n"
                f"- Tempat: {kp_tempat.strip()[:60]}...\n\n"
                f"**Tidak bisa dibatalkan setelah dikirim.**"
            )

            col_ya, col_batal = st.columns(2)
            with col_ya:
                if st.button("✅ Ya, Kirim", key="kp_ya", type="primary", use_container_width=True):
                    st.session_state["kp_konfirmasi"] = False

                    progress = st.progress(0, text="Memulai pengiriman...")
                    hasil_list = []

                    for i, paket in enumerate(kp_selected):
                        progress.progress(
                            (i + 1) / len(kp_selected),
                            text=f"Mengirim ke {paket['kode']} ({i+1}/{len(kp_selected)})..."
                        )
                        lamp = paket.get("_lampiran")
                        res = kirimpesan_engine.kirim_undangan(
                            paket_id=paket["id_lelang"],
                            waktu=waktu_str,
                            sampai=sampai_str,
                            tempat=kp_tempat.strip(),
                            dibawa=kp_dibawa.strip(),
                            hadir=kp_hadir.strip(),
                            is_online=False,
                            link_pembuktian="",
                            lampiran_bytes=lamp.getvalue() if lamp else None,
                            lampiran_nama=lamp.name if lamp else "",
                        )

                        hasil_list.append({
                            "kode": paket["kode"],
                            "nama": paket["nama"][:50],
                            "sukses": res["sukses"],
                            "pesan": res["pesan"],
                        })

                    progress.empty()

                    sukses_n = sum(1 for h in hasil_list if h["sukses"])
                    gagal_n  = len(hasil_list) - sukses_n
                    if gagal_n == 0:
                        st.success(f"✅ Semua {sukses_n} undangan berhasil dikirim!")
                    else:
                        st.warning(f"⚠️ {sukses_n} berhasil, {gagal_n} gagal.")

                    st.dataframe(
                        hasil_list,
                        use_container_width=True,
                        column_config={
                            "kode":   st.column_config.TextColumn("Kode", width="small"),
                            "nama":   st.column_config.TextColumn("Nama Paket", width="large"),
                            "sukses": st.column_config.CheckboxColumn("Sukses", width="small"),
                            "pesan":  st.column_config.TextColumn("Pesan"),
                        },
                        hide_index=True,
                    )

            with col_batal:
                if st.button("❌ Batal", key="kp_batal", use_container_width=True):
                    st.session_state["kp_konfirmasi"] = False
                    st.rerun()

    with _kp_col_detail:
        st.markdown("### 3. Upload BA Reviu DPP")
        st.caption("Upload BA Hasil Reviu setelah PPK menandatangani.")
        st.caption("💡 Pastikan browser sudah membuka halaman **/paket** di SPSE sebelum fetch.")
        if st.button("🔍 Ambil Paket Draft", key="ba_fetch_draft", use_container_width=True):
            with st.spinner("Mengambil daftar paket..."):
                _ba_result = kirimpesan_engine.fetch_paket_draft()
            st.session_state["ba_paket_draft"] = _ba_result
            for _k in list(st.session_state.keys()):
                if _k.startswith("ba_chk_"):
                    del st.session_state[_k]

        ba_selected = []
        if "ba_paket_draft" in st.session_state:
            _ba_r = st.session_state["ba_paket_draft"]
            if not _ba_r["sukses"]:
                st.error(f"❌ {_ba_r['pesan']}")
            else:
                _ba_paket_list = _ba_r.get("paket", [])
                if not _ba_paket_list:
                    st.warning("⚠️ Tidak ada paket berstatus Draft.")
                else:
                    for _p in _ba_paket_list:
                        _key_chk = f"ba_chk_{_p['id_lelang']}"
                        _col_chk, _col_file = st.columns([3, 2])
                        with _col_chk:
                            _checked = st.checkbox(
                                f"**{_p['kode']}** — {_p['nama']}",
                                value=st.session_state.get(_key_chk, False),
                                key=_key_chk,
                            )
                        with _col_file:
                            _ba_up = st.file_uploader(
                                "BA Reviu",
                                type=["pdf"],
                                key=f"ba_file_{_p['id_lelang']}",
                                label_visibility="collapsed",
                            )
                            if _ba_up:
                                st.caption(f"📋 {_ba_up.name}")
                        if _checked:
                            ba_selected.append({**_p, "_ba_file": _ba_up})
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket Draft.")

        st.divider()
        ba_tgl = st.date_input(
            "Tanggal BA Reviu",
            value=datetime.now().date(),
            key="ba_tgl",
            format="DD/MM/YYYY",
        )
        st.caption(f"{_HARI_NAMA[ba_tgl.weekday()]}, {ba_tgl.day} {_BULAN_NAMA[ba_tgl.month-1]} {ba_tgl.year}")

        _ba_upload_disabled = len(ba_selected) == 0 or all(p.get("_ba_file") is None for p in ba_selected)
        _ba_n_file = len([p for p in ba_selected if p.get("_ba_file")])
        if st.button(
            f"📤 Upload BA Reviu ({_ba_n_file} file)",
            key="ba_upload",
            type="primary",
            disabled=_ba_upload_disabled,
            use_container_width=True,
        ):
            _ba_progress = st.progress(0, text="Memulai upload...")
            _ba_hasil = []
            _ba_valid = [p for p in ba_selected if p.get("_ba_file")]
            for _i, _p in enumerate(_ba_valid):
                _ba_progress.progress(
                    (_i + 1) / len(_ba_valid),
                    text=f"Upload {_p['kode']} ({_i+1}/{len(_ba_valid)})..."
                )
                _res = bareviu_engine.upload_ba_reviu(
                    paket_id=_p["id_lelang"],
                    file_bytes=_p["_ba_file"].getvalue(),
                    file_name=_p["_ba_file"].name,
                    tgl_dok_ba=ba_tgl.strftime("%d-%m-%Y"),
                )
                _ba_hasil.append({
                    "kode": _p["kode"],
                    "nama": _p["nama"][:50],
                    "sukses": _res["sukses"],
                    "pesan": _res["pesan"],
                })
            _ba_progress.empty()

            _ba_ok = sum(1 for h in _ba_hasil if h["sukses"])
            _ba_fail = len(_ba_hasil) - _ba_ok
            if _ba_fail == 0:
                st.success(f"✅ {_ba_ok} BA Reviu berhasil diupload!")
            else:
                st.warning(f"⚠️ {_ba_ok} berhasil, {_ba_fail} gagal.")

            st.dataframe(
                _ba_hasil,
                use_container_width=True,
                column_config={
                    "kode":   st.column_config.TextColumn("Kode", width="small"),
                    "nama":   st.column_config.TextColumn("Nama Paket", width="large"),
                    "sukses": st.column_config.CheckboxColumn("Sukses", width="small"),
                    "pesan":  st.column_config.TextColumn("Pesan"),
                },
                hide_index=True,
            )

# Tab 5: Upload 5 BA

# ============================================================

with tab_ba:

    _ba_col_kiri, _ba_col_kanan = st.columns([2, 3])

    with _ba_col_kiri:

        st.markdown("### 1. Pilih Paket")

        st.caption("💡 Pastikan browser sudah membuka halaman **/paket** di SPSE sebelum fetch.")

        col_bafetch, col_baall, col_banone = st.columns([3, 1, 1])

        with col_bafetch:

            if st.button("🔍 Ambil Paket Draft", key="ba_fetch_draft", use_container_width=True):

                with st.spinner("Mengambil daftar paket..."):

                    result = kirimpesan_engine.fetch_paket_draft()

                st.session_state["ba_paket_draft"] = result

                for key in list(st.session_state.keys()):

                    if key.startswith("ba_chk_"):

                        del st.session_state[key]

        ba_selected = []

        if "ba_paket_draft" in st.session_state:

            r = st.session_state["ba_paket_draft"]

            if not r["sukses"]:

                st.error(f"❌ {r['pesan']}")

            else:

                paket_list_ba = r.get("paket", [])

                if not paket_list_ba:

                    st.warning("⚠️ Tidak ada paket berstatus Draft.")

                else:

                    with col_baall:

                        if st.button("✅ Semua", key="ba_sel_all", use_container_width=True):

                            for p in paket_list_ba:

                                st.session_state[f"ba_chk_{p['id_lelang']}"] = True

                            st.rerun()

                    with col_banone:

                        if st.button("⬜ Kosong", key="ba_sel_none", use_container_width=True):

                            for p in paket_list_ba:

                                st.session_state[f"ba_chk_{p['id_lelang']}"] = False

                            st.rerun()

                    for p in paket_list_ba:

                        key_chk = f"ba_chk_{p['id_lelang']}"

                        checked = st.checkbox(

                            f"**{p['kode']}** —  {p['nama']}",

                            value=st.session_state.get(key_chk, True), key=key_chk,

                        )

                        if checked:

                            ba_selected.append(p)

                    st.caption(f"**{len(ba_selected)}** dari **{len(paket_list_ba)}** paket dipilih")

        else:

            st.info("Klik tombol di atas untuk mengambil daftar paket Draft.")

    with _ba_col_kanan:

        st.markdown("### 2. Konfigurasi 5 BA")

        st.caption("Isi nomor, tanggal, dan upload file PDF untuk setiap BA.")

        for jenis_key in ba_config.JENIS_KEYS:

            if f"ba_no_{jenis_key}" not in st.session_state:

                st.session_state[f"ba_no_{jenis_key}"] = ""

            if f"ba_tgl_{jenis_key}" not in st.session_state:

                st.session_state[f"ba_tgl_{jenis_key}"] = date.today().strftime("%d-%m-%Y")

            if f"ba_info_{jenis_key}" not in st.session_state:

                st.session_state[f"ba_info_{jenis_key}"] = ba_config.DEFAULT_INFO.get(jenis_key, "")

        for jenis_key in ba_config.JENIS_KEYS:

            st.markdown(f"#### 📋“„ {ba_config.JENIS_BA[jenis_key]}")

            col_no, col_tgl = st.columns(2)

            with col_no:

                st.text_input("Nomor BA", key=f"ba_no_{jenis_key}", placeholder="000/BA/POKJA/2026", label_visibility="collapsed")

            with col_tgl:

                st.date_input("Tanggal", value=date.today(), key=f"ba_tgl_date_{jenis_key}", format="DD/MM/YYYY", label_visibility="collapsed")

                _dt = st.session_state.get(f"ba_tgl_date_{jenis_key}", date.today())

                if isinstance(_dt, date):

                    st.session_state[f"ba_tgl_{jenis_key}"] = _dt.strftime("%d-%m-%Y")

            st.file_uploader("File PDF", type=["pdf"], key=f"ba_file_{jenis_key}", label_visibility="collapsed")

            st.text_area("Keterangan tambahan (opsional)", key=f"ba_info_{jenis_key}", height=68, label_visibility="collapsed")

            st.divider()

        st.divider()

        ba_n = len(ba_selected)

        if st.button(f"🚀 Upload {ba_n} Paket × 5 BA", key="ba_upload", type="primary", disabled=ba_n == 0, use_container_width=True):

            progress = st.progress(0, text="Memulai...")

            hasil_ba = []

            for i, p in enumerate(ba_selected):

                pid = p["id_lelang"]

                progress.progress((i + 0.5) / len(ba_selected), text=f"Upload BA untuk {p['kode']} ({i+1}/{len(ba_selected)})...")

                paket_hasil = {"kode": p["kode"], "nama": p["nama"][:50], "ba": []}

                for jenis_key in ba_config.JENIS_KEYS:

                    file_up = st.session_state.get(f"ba_file_{jenis_key}")

                    nomor = st.session_state.get(f"ba_no_{jenis_key}", "").strip()

                    tanggal = st.session_state.get(f"ba_tgl_{jenis_key}", "").strip()

                    info = st.session_state.get(f"ba_info_{jenis_key}", "").strip()

                    ba_result = {"jenis": ba_config.JENIS_BA[jenis_key], "status": "⏭️ Lewati"}

                    if file_up and nomor and tanggal:

                        try:

                            r = ba_engine.upload_ba(paket_id=pid, jenis_key=jenis_key, nomor_ba=nomor, tanggal_ba=tanggal, file_bytes=file_up.getvalue(), file_name=file_up.name, info=info)

                            ba_result["status"] = "✅" if r["ok"] else f"❌ HTTP {r['status']}"

                            ba_result["detail"] = r

                        except Exception as e:

                            ba_result["status"] = f"❌ {e}"

                    elif file_up:

                        ba_result["status"] = "⚠️ Nomor/tanggal belum diisi"

                    paket_hasil["ba"].append(ba_result)

                hasil_ba.append(paket_hasil)

            progress.empty()

            sukses_n = sum(1 for h in hasil_ba for b in h["ba"] if b["status"] == "✅")

            st.success(f"✅ Selesai! {sukses_n} BA berhasil di-upload.")

            for h in hasil_ba:

                st.markdown(f"**{h['kode']}** —  {h['nama']}")

                for b in h["ba"]:

                    st.caption(f"{b['status']} {b['jenis']}")

                st.divider()

