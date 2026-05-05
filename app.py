"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, date
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _pokja_label(p: dict) -> str:
    """Buat label ringkas paket: 'Pokja 086 · 10096884000 — Nama Paket'."""
    pokja_raw = p.get("pokja") or ""
    m = re.search(r"\d+", pokja_raw)
    pokja_no = m.group() if m else p.get("kode", "")
    return f"Pokja {pokja_no} · {p['kode']} — {p['nama']}"

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
import merge_engine
import bareviu_engine
import ba_engine
import ba_config
import kualifikasi_engine
import kualifikasi_parser
import kk_evaluasi_engine
import pl_engine

st.set_page_config(
    page_title="Asisten Pokja",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 Asisten Pokja")
st.caption("Otomasi SPSE — spse.tapinkab.go.id")

# ── Mode Switcher ──────────────────────────────────────────────────────────────
_MODE_OPTIONS = ["Tender", "Pengadaan Langsung"]
if "app_mode" not in st.session_state:
    st.session_state["app_mode"] = "Tender"

_mode_col, _ = st.columns([2, 5])
with _mode_col:
    _selected_mode = st.radio(
        "Mode:",
        _MODE_OPTIONS,
        index=_MODE_OPTIONS.index(st.session_state["app_mode"]),
        horizontal=True,
        key="radio_app_mode",
    )
    st.session_state["app_mode"] = _selected_mode

st.divider()

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
        if st.button("🔌 Diskonek", use_container_width=True, help="Reset status tanpa menutup browser (pakai jika CDP sudah ditutup manual)"):
            spse_browser.diskonek()
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

_LIBUR_2026 = {
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
_LIBUR_MAP = {datetime.strptime(k, "%Y-%m-%d").date(): v for k, v in _LIBUR_2026.items()}

# Auto-start scheduler saat app dibuka (daemon thread, jalan terus)
penjelasan_engine.start_scheduler()

if st.session_state["app_mode"] == "Pengadaan Langsung":
    # ============================================================
    # MODE: PENGADAAN LANGSUNG (PL JKK & PL PK)
    # ============================================================
    _pl_tab0, _pl_tab1, _pl_tab2, _pl_tab3, _pl_tab4 = st.tabs([
        "0️⃣ Draft Paket PL",
        "1️⃣ Undangan",
        "2️⃣ Evaluasi",
        "3️⃣ Negosiasi",
        "4️⃣ BA & Laporan",
    ])

    # ── Tab 0: Draft Paket PL ──────────────────────────────────────────────────
    with _pl_tab0:
        import os as _pl_os, subprocess as _pl_sp
        from config import POKJA_ROOT as _PL_POKJA_ROOT

        _PL_PY     = "D:/Dokumen/@ POKJA 2026/V19_Scheduler/WPy64-313110/python/python.exe"
        _PL_SCRIPT = "D:/Dokumen/@ POKJA 2026/V19_Scheduler/WPy64-313110/setup_paket_baru.py"
        _PL_NO_WIN = 0x08000000

        st.markdown("### Draft Paket Pengadaan Langsung")
        st.caption("Input manual paket PL (JKK atau PK), simpan ke database, dan buat folder paket.")

        # Load data
        _pl_rows = pl_engine.load_draft_pl()

        _pl_col_kiri, _pl_col_kanan = st.columns(2)

        # ── Kolom Kiri: Form Input Paket Baru ──
        with _pl_col_kiri:
            st.markdown("#### 1. Tambah / Edit Paket PL")

            with st.form("form_paket_pl", clear_on_submit=True):
                _f_jenis = st.selectbox("Jenis PL:", ["JKK", "PK"], key="f_jenis_pl")
                _f_kode  = st.text_input("Kode Paket *", placeholder="Contoh: PL-JKK-001-2026")
                _f_nama  = st.text_input("Nama Paket *", placeholder="Perencanaan Pembangunan ...")
                _f_hps   = st.text_input("Nilai HPS", placeholder="85.000.000")
                _f_pagu  = st.text_input("Nilai Pagu", placeholder="90.000.000")
                _f_rup   = st.text_input("Kode RUP", placeholder="12345678")
                _f_mak   = st.text_input("MAK / Kode Akun", placeholder="5.2.02.01.01")
                _f_satker = st.selectbox("Satker:", pl_engine.SATKER_LIST)
                _f_satker_manual = ""
                if _f_satker == "Lainnya":
                    _f_satker_manual = st.text_input("Nama satker (manual):")
                _f_ppk   = st.text_input("Nama PPK", placeholder="...")
                _f_bidang = st.text_input("Bidang Pekerjaan", placeholder="Bina Marga / Cipta Karya / ...")
                _f_jangka = st.text_input("Jangka Waktu", placeholder="30 hari kalender")
                _f_sumber = st.text_input("Sumber Anggaran", placeholder="APBD 2026")
                _f_catatan = st.text_area("Catatan", height=80)

                _f_submit = st.form_submit_button("💾 Simpan Paket", type="primary", use_container_width=True)

            if _f_submit:
                if not _f_kode or not _f_nama:
                    st.error("Kode Paket dan Nama Paket wajib diisi.")
                else:
                    _satker_val = _f_satker_manual if _f_satker == "Lainnya" else _f_satker
                    _hasil_simpan = pl_engine.simpan_paket_pl({
                        "kode_paket": _f_kode.strip(),
                        "jenis_pl": _f_jenis,
                        "nama_paket": _f_nama.strip(),
                        "nilai_hps": _f_hps.strip(),
                        "nilai_pagu": _f_pagu.strip(),
                        "kode_rup": _f_rup.strip(),
                        "mak": _f_mak.strip(),
                        "satker": _satker_val.strip(),
                        "nama_ppk": _f_ppk.strip(),
                        "bidang": _f_bidang.strip(),
                        "jangka_waktu": _f_jangka.strip(),
                        "sumber_anggaran": _f_sumber.strip(),
                        "catatan": _f_catatan.strip(),
                    })
                    if _hasil_simpan["ok"]:
                        st.success(f"Paket `{_f_kode}` berhasil disimpan.")
                        st.rerun()
                    else:
                        st.error(f"Gagal simpan: {_hasil_simpan['error']}")

        # ── Kolom Kanan: Daftar Paket + Buat Folder ──
        with _pl_col_kanan:
            st.markdown("#### 2. Daftar Paket PL")

            _pl_filter = st.selectbox(
                "Filter:",
                ["Semua", "JKK", "PK", "Belum Folder", "Sudah Folder"],
                key="pl_filter_jenis",
            )

            def _pl_match(r):
                if _pl_filter == "JKK":
                    return r.get("jenis_pl") == "JKK"
                if _pl_filter == "PK":
                    return r.get("jenis_pl") == "PK"
                if _pl_filter == "Belum Folder":
                    return not bool(r.get("folder_dibuat"))
                if _pl_filter == "Sudah Folder":
                    return bool(r.get("folder_dibuat"))
                return True

            _pl_filtered = [r for r in _pl_rows if _pl_match(r)]

            if not _pl_filtered:
                st.info("Belum ada paket PL. Tambah via form di sebelah kiri.")
            else:
                for _pr in _pl_filtered:
                    _pr_kode  = _pr.get("kode_paket", "")
                    _pr_nama  = _pr.get("nama_paket", "-")
                    _pr_jenis = _pr.get("jenis_pl", "")
                    _pr_hps   = _pr.get("nilai_hps", "-")
                    _pr_status = _pr.get("status", "draft")
                    _pr_folder = _pr.get("folder_dibuat", False)

                    _pr_label = f"{'✅' if _pr_folder else '📋'} [{_pr_jenis}] {_pr_nama}"
                    with st.expander(_pr_label):
                        st.caption(f"Kode: `{_pr_kode}` | HPS: {_pr_hps} | Status: **{_pr_status}**")
                        st.caption(f"Satker: {_pr.get('satker','-')} | PPK: {_pr.get('nama_ppk','-')}")

                        _pr_c1, _pr_c2, _pr_c3 = st.columns(3)

                        # Tombol buat folder
                        if not _pr_folder:
                            _pr_no = _pr.get("nomor_urut") or (len(_pl_rows) + 1)
                            _pr_nama_folder_default = f"{_pr_no}. PL {_pr_jenis} - {_pr_nama}"
                            _pr_nama_folder = st.text_input(
                                "Nama folder:",
                                value=_pr_nama_folder_default,
                                key=f"pl_nama_folder_{_pr_kode}",
                            )
                            if _pr_c1.button("📁 Buat Folder", key=f"pl_buat_{_pr_kode}", use_container_width=True):
                                _pr_nama_clean = re.sub(r'[/<>:"\|?*]', "-", _pr_nama_folder).strip()
                                _pr_target = _pl_os.path.join(_PL_POKJA_ROOT, _pr_nama_clean)
                                if _pl_os.path.exists(_pr_target):
                                    st.warning(f"Folder sudah ada: `{_pr_target}`")
                                else:
                                    try:
                                        _pl_sp.run(
                                            [_PL_PY, _PL_SCRIPT, _pr_nama_clean],
                                            creationflags=_PL_NO_WIN,
                                            check=True,
                                        )
                                        pl_engine.tandai_folder_dibuat(_pr_kode)
                                        st.success(f"Folder `{_pr_nama_clean}` berhasil dibuat.")
                                        st.rerun()
                                    except Exception as _pe:
                                        st.error(f"Gagal buat folder: {_pe}")
                        else:
                            _pr_c1.success("Folder sudah dibuat ✅")

                        # Update status
                        _pr_status_baru = _pr_c2.selectbox(
                            "Status:",
                            pl_engine.STATUS_LIST,
                            index=pl_engine.STATUS_LIST.index(_pr_status) if _pr_status in pl_engine.STATUS_LIST else 0,
                            key=f"pl_status_{_pr_kode}",
                        )
                        if _pr_c2.button("💾 Update", key=f"pl_upd_status_{_pr_kode}", use_container_width=True):
                            pl_engine.update_status(_pr_kode, _pr_status_baru)
                            st.rerun()

                        # Hapus
                        if _pr_c3.button("🗑️ Hapus", key=f"pl_hapus_{_pr_kode}", use_container_width=True):
                            pl_engine.hapus_paket_pl(_pr_kode)
                            st.rerun()

    # ── Tab 1–4: Placeholder ──────────────────────────────────────────────────
    with _pl_tab1:
        st.info("🚧 Tab Undangan belum tersedia — akan dikembangkan.")

    with _pl_tab2:
        st.info("🚧 Tab Evaluasi belum tersedia — akan dikembangkan.")

    with _pl_tab3:
        st.info("🚧 Tab Negosiasi belum tersedia — akan dikembangkan.")

    with _pl_tab4:
        st.info("🚧 Tab BA & Laporan belum tersedia — akan dikembangkan.")

    st.stop()  # Jangan render tab Tender jika mode PL

# ============================================================
# MODE: TENDER
# ============================================================
tab0, tab9, tab8, tab_setup, tab7, tab_ba, tab_kual, tab_apendo = st.tabs([
    "0️⃣ Persiapan Draft Paket",
    "1️⃣ Kirim Undangan DPP", "2️⃣ Buat Jadwal",
    "3️⃣ Setup Paket", "4️⃣ Pemberian Penjelasan",
    "5️⃣ Upload & Cetak 5 BA", "6️⃣ Download Kualifikasi",
    "7️⃣ Dokumen Penawaran",
])

# ============================================================
# Tab 0: Persiapan Draft Paket
# ============================================================

with tab0:
    import inbox_engine
    import os as _os, subprocess as _sp
    from config import POKJA_ROOT as _POKJA_ROOT

    _PY     = "D:/Dokumen/@ POKJA 2026/V19_Scheduler/WPy64-313110/python/python.exe"
    _SCRIPT = "D:/Dokumen/@ POKJA 2026/V19_Scheduler/WPy64-313110/setup_paket_baru.py"
    _NO_WIN = 0x08000000  # CREATE_NO_WINDOW — cegah jendela hitam ngeblink di Windows

    # ── Load data draft_paket ──
    _draft_rows = []
    try:
        _draft_rows = inbox_engine._sb().table("draft_paket").select("*").order("diambil_pada", desc=True).execute().data or []
    except Exception as _e:
        st.warning(f"Gagal load data: {_e}")

    # ── Layout: kolom kiri (1) dan kanan (2) ──
    _col_kiri, _col_kanan = st.columns(2)

    # ══════════════════════════════════════════
    # KOLOM KIRI — 1. Scrap Inbox SPSE
    # ══════════════════════════════════════════
    with _col_kiri:
        st.markdown("#### 1. Scrap Inbox SPSE")
        st.caption("Baca pesan Delegasi Pokja → parse HTML + PDF → simpan ke Supabase.")
        serap_btn = st.button("📥 Update Inbox", type="primary", use_container_width=True)

        if serap_btn:
            _pb = st.progress(0.0)
            _st = st.empty()
            def cb(pct, msg):
                _pb.progress(min(pct, 1.0))
                _st.info(msg)
            try:
                hasil = inbox_engine.serap_inbox(progress_cb=cb)
                _pb.progress(1.0)
                _c1, _c2, _c3, _c4 = st.columns(4)
                _c1.metric("✅ Baru", hasil["baru"])
                _c2.metric("🔄 Diperbarui", hasil["diperbarui"])
                _c3.metric("⏭️ Dilewati", hasil.get("skip", 0))
                _c4.metric("❌ Error", len(hasil["error"]))
                if hasil["error"]:
                    with st.expander("Detail Error"):
                        for e in hasil["error"]:
                            st.error(e)
                if hasil["data"]:
                    st.success(f"{len(hasil['data'])} paket diproses.")
                else:
                    _st.warning("Tidak ada pesan Delegasi Pokja baru.")
            except Exception as e:
                st.error(f"Gagal: {e}")

        st.divider()
        st.markdown("#### 🔄 Sinkronkan Paket SPSE")
        st.caption("Fetch daftar paket dari SPSE — dipakai oleh semua tab. Auto-dimuat saat pertama buka.")

        # Auto-load: session baru → baca cache dulu (instan), baru fetch SPSE kalau cache expired
        if "global_paket_draft" not in st.session_state:
            _cache = kirimpesan_engine.load_paket_cache()
            if _cache:
                st.session_state["global_paket_draft"] = _cache["draft"]
                st.session_state["global_paket_aktif"] = _cache["aktif"]
            else:
                with st.spinner("Memuat daftar paket dari SPSE..."):
                    _gd0 = kirimpesan_engine.fetch_paket_draft()
                    _ga0 = kirimpesan_engine.fetch_paket_aktif()
                    st.session_state["global_paket_draft"] = _gd0
                    st.session_state["global_paket_aktif"] = _ga0
                    kirimpesan_engine.save_paket_cache(_gd0, _ga0)

        _sync_col1, _sync_col2 = st.columns(2)
        with _sync_col1:
            if st.button("🔄 Refresh dari SPSE", type="secondary", use_container_width=True, key="btn_sync_spse"):
                kirimpesan_engine.clear_paket_cache()
                with st.spinner("Mengambil daftar paket dari SPSE..."):
                    _gd_r = kirimpesan_engine.fetch_paket_draft()
                    _ga_r = kirimpesan_engine.fetch_paket_aktif()
                    st.session_state["global_paket_draft"] = _gd_r
                    st.session_state["global_paket_aktif"] = _ga_r
                    kirimpesan_engine.save_paket_cache(_gd_r, _ga_r)
                st.toast("✅ Data paket SPSE tersinkronkan!", icon="🔄")
                st.success(f"Draft: {len(_gd_r.get('paket',[]))} paket | Aktif: {len(_ga_r.get('paket',[]))} paket")
        with _sync_col2:
            import os as _os_sync
            _gd2 = st.session_state.get("global_paket_draft", {})
            _ga2 = st.session_state.get("global_paket_aktif", {})
            _cache_info = ""
            if _os_sync.path.exists(kirimpesan_engine._CACHE_FILE):
                import time as _t_sync
                _age = int((_t_sync.time() - _os_sync.path.getmtime(kirimpesan_engine._CACHE_FILE)) / 60)
                _cache_info = f" (cache {_age}m lalu)"
            st.caption(f"✅ Draft: {len(_gd2.get('paket',[]))} | Aktif: {len(_ga2.get('paket',[]))}{_cache_info}")

    # ══════════════════════════════════════════
    # KOLOM KANAN — 2. Buat Folder Paket
    # ══════════════════════════════════════════
    with _col_kanan:
        st.markdown("#### 2. Buat Folder Paket")

        # ── Notif folder baru dibuat (persist across rerun) ──
        if "_folder_just_created" in st.session_state:
            _just = st.session_state.pop("_folder_just_created")
            st.toast(f"✅ Folder berhasil dibuat: {_just}", icon="📁")
            st.success(f"✅ Folder **{_just}** berhasil dibuat!")
            st.balloons()
        if "_folder_bulk_created" in st.session_state:
            _bulk_msg = st.session_state.pop("_folder_bulk_created")
            st.toast(_bulk_msg, icon="📁")
            st.success(f"✅ {_bulk_msg}")
            st.balloons()
        st.caption("Buat satu folder atau semua sekaligus.")

        _tahun_skrg = str(datetime.now().year)
        _rows_tahun_ini = [_r for _r in _draft_rows if _tahun_skrg in str(_r.get("nomor_pp") or "")]
        _nomor_terakhir = max((int(_r.get("nomor_urut") or 0) for _r in _rows_tahun_ini), default=0)
        _nomor_berikutnya = _nomor_terakhir + 1

        # Dropdown pilih paket — hanya tahun berjalan
        _opsi_map = {"(input manual)": None}
        for _r in _draft_rows:
            if str(_r.get("kode_tender", "")).startswith("_err_") or not _r.get("nama_tender"):
                continue
            if _tahun_skrg not in str(_r.get("nomor_pp") or ""):
                continue
            _pk = str(_r.get("kode_pokja") or "").strip()
            _nm = str(_r.get("nama_tender") or "").strip()
            if _pk and _nm:
                _lbl = f"Pokja {_pk} - {_nm}"
                if _r.get("folder_dibuat"):
                    _lbl += " ✅"
                _opsi_map[_lbl] = _r

        _pilihan = st.selectbox("Pilih paket:", list(_opsi_map.keys()), key="selectbox_paket_baru")
        _row_terpilih = _opsi_map.get(_pilihan)

        # Nama folder default (penuh)
        _default_nama = ""
        if _row_terpilih:
            _pk = str(_row_terpilih.get("kode_pokja") or "").strip()
            _nm = str(_row_terpilih.get("nama_tender") or "").strip()
            _no = int(_row_terpilih.get("nomor_urut") or _nomor_berikutnya)
            if _nm and _pk:
                _default_nama = f"{_no}. Pokja {_pk} - {_nm}"

        _nama_folder = st.text_input(
            "Nama folder:",
            value=_default_nama,
            placeholder=f'{_nomor_berikutnya}. Nama Paket - Pokja 086',
            key="input_nama_folder"
        )

        _nama_folder_clean = re.sub(r'[/<>:"\|?*]', "-", _nama_folder).strip() if _nama_folder else ""
        _target_path = _os.path.join(_POKJA_ROOT, _nama_folder_clean) if _nama_folder_clean else ""
        _folder_ada  = bool(_target_path and _os.path.exists(_target_path))
        if _folder_ada:
            st.warning(f"Folder sudah ada: `{_target_path}`")

        _cb1, _cb2 = st.columns(2)
        _buat_btn = _cb1.button("📁 Buat Folder", type="primary",
                                disabled=not bool(_nama_folder),
                                use_container_width=True, key="btn_buat_folder")
        if _folder_ada:
            if _cb2.button("📂 Buka Explorer", use_container_width=True, key="btn_buka_folder"):
                _sp.Popen(f'explorer "{_target_path.replace("/", chr(92))}"')

        # Tombol scrape HPS mandiri (untuk folder yang sudah ada)
        if _folder_ada and _row_terpilih and _row_terpilih.get("kode_tender"):
            if st.button("📊 Scrape HPS dari SPSE", use_container_width=True, key="btn_scrape_hps_saja"):
                import hps_engine as _hps_eng3
                with st.spinner("Scraping HPS... (scroll virtual, mungkin 30-60 detik)"):
                    _hps_r = _hps_eng3.scrape_dan_upsert_hps(_row_terpilih["kode_tender"])
                if _hps_r.get("error") is None and _hps_r.get("count", 0) > 0:
                    st.success(f"✅ HPS tersimpan: {_hps_r['count']} item")
                    if _hps_r.get("warning"):
                        st.warning(f"⚠️ {len(_hps_r['warning'])} item ada selisih hitung")
                else:
                    st.warning(f"HPS gagal/kosong: {_hps_r.get('error', '-')}")

        # Tombol download dokumen mandiri (untuk folder yang sudah ada)
        if _folder_ada and _row_terpilih:
            _kt2 = _row_terpilih.get("kode_tender", "")
            _ip2 = str(_row_terpilih.get("id_pesan", ""))
            if _kt2 and _ip2:
                if st.button("📦 Download Dokumen SPSE + Lampiran", use_container_width=True, key="btn_dl_dokumen_saja"):
                    _dl_msgs2 = []
                    _st_log = st.empty() # Placeholder untuk log real-time
                    def _dl_cb2(msg):
                        _dl_msgs2.append(msg)
                        # Render log terbaru ke placeholder
                        with _st_log.container():
                            with st.status("🔽 Sedang mengunduh dokumen...", expanded=True) as _status:
                                st.code("\n".join(_dl_msgs2[-10:])) # Tampilkan 10 log terakhir
                                _status.update(label=f"🔽 Mengunduh... ({msg[:30]}...)", state="running")

                    from streamlit.runtime.scriptrunner import get_script_run_ctx
                    _ctx = get_script_run_ctx()

                    _dl2 = inbox_engine.download_dokumen_paket(
                        _kt2, _ip2, _target_path, 
                        kode_pokja=_row_terpilih.get("kode_pokja",""), 
                        progress_cb=_dl_cb2,
                        st_ctx=_ctx
                    )
                    _st_log.empty() # Bersihkan placeholder setelah selesai
                    st.success(
                        f"✅ {len(_dl2['ok'])} file, ⏭ {len(_dl2['skip'])} sudah ada, ❌ {len(_dl2['error'])} gagal"
                        + (f" | 📎 {_os.path.basename(_dl2['draft_pdf'])}" if _dl2.get('draft_pdf') else "")
                    )
                    if _dl_msgs2:
                        with st.expander("Log download lengkap"):
                            st.text("\n".join(_dl_msgs2))
                    if _dl2["error"]:
                        with st.expander("Detail error"):
                            for _e4 in _dl2["error"]:
                                st.error(_e4)

        _dl_dokumen = st.checkbox("📦 Download dokumen SPSE + lampiran surat", value=True, key="cb_dl_dokumen")

        if _buat_btn and _nama_folder:
            with st.spinner(f"Membuat '{_nama_folder}'..."):
                try:
                    _res = _sp.run([_PY, _SCRIPT, _nama_folder],
                                   capture_output=True, text=True, timeout=60,
                                   creationflags=_NO_WIN)
                    if _res.returncode == 0:
                        st.success(f"Folder dibuat: `{_target_path}`")
                        if _row_terpilih:
                            from datetime import timezone as _tz
                            try:
                                inbox_engine._sb().table("draft_paket").update({
                                    "nomor_urut": int(_row_terpilih.get("nomor_urut") or _nomor_berikutnya),
                                    "folder_dibuat": _nama_folder_clean,
                                    "folder_dibuat_pada": datetime.now(_tz.utc).isoformat(),
                                }).eq("kode_tender", _row_terpilih["kode_tender"]).execute()
                            except Exception as _e2:
                                st.warning(f"Gagal update riwayat: {_e2}")
                        # Download dokumen jika checkbox aktif
                        if _dl_dokumen and _row_terpilih and _target_path:
                            _kt = _row_terpilih.get("kode_tender", "")
                            _ip = str(_row_terpilih.get("id_pesan", ""))
                            if _kt and _ip:
                                _dl_msgs = []
                                _st_log_f = st.empty()
                                def _dl_cb(msg):
                                    _dl_msgs.append(msg)
                                    with _st_log_f.container():
                                        with st.status("🔽 Mengunduh dokumen persiapan...", expanded=True) as _status:
                                            st.code("\n".join(_dl_msgs[-10:]))
                                            _status.update(label=f"🔽 Progress: {msg[:30]}...", state="running")

                                from streamlit.runtime.scriptrunner import get_script_run_ctx
                                _ctx_f = get_script_run_ctx()

                                _dl_hasil = inbox_engine.download_dokumen_paket(
                                    _kt, _ip, _target_path,
                                    kode_pokja=_row_terpilih.get("kode_pokja",""),
                                    progress_cb=_dl_cb,
                                    st_ctx=_ctx_f
                                )
                                _st_log_f.empty()
                                st.success(
                                    f"Download selesai — ✅ {len(_dl_hasil['ok'])} file, "
                                    f"⏭ {len(_dl_hasil['skip'])} sudah ada, "
                                    f"❌ {len(_dl_hasil['error'])} gagal"
                                    + (f" | 📎 {_os.path.basename(_dl_hasil['draft_pdf'])}" if _dl_hasil.get('draft_pdf') else "")
                                )
                                if _dl_msgs:
                                    with st.expander("Log download lengkap"):
                                        st.text("\n".join(_dl_msgs))
                                if _dl_hasil["error"]:
                                    with st.expander("Detail error download"):
                                        for _e3 in _dl_hasil["error"]:
                                            st.error(_e3)
                        # Scrape HPS ke Supabase
                        if _row_terpilih and _row_terpilih.get("kode_tender"):
                            try:
                                import hps_engine as _hps_eng
                                with st.spinner("Scraping HPS dari SPSE..."):
                                    _hps_res = _hps_eng.scrape_dan_upsert_hps(_row_terpilih["kode_tender"])
                                if _hps_res.get("error") is None and _hps_res.get("count", 0) > 0:
                                    st.success(f"✅ HPS tersimpan: {_hps_res['count']} item")
                                else:
                                    st.warning(f"HPS gagal/kosong: {_hps_res.get('error', '-')}")
                            except Exception as _hps_e:
                                st.warning(f"Scrape HPS error: {_hps_e}")
                        st.session_state["_folder_just_created"] = _nama_folder_clean
                        st.rerun()
                    else:
                        st.error("Setup gagal.")
                        st.code(_res.stdout + "\n" + _res.stderr)
                except _sp.TimeoutExpired:
                    st.error("Timeout.")

        # Bulk Create
        st.divider()
        _bulk_kandidat = [_r for _r in _draft_rows if not _r.get("folder_dibuat") and _r.get("nama_tender")
                          and not str(_r.get("kode_tender","")).startswith("_err_")
                          and _tahun_skrg in str(_r.get("nomor_pp") or "")]
        if _bulk_kandidat:
            _max_urut = max((int(_r.get("nomor_urut") or 0) for _r in _rows_tahun_ini), default=0)
            _bulk_plan, _ctr = [], _max_urut
            for _r in sorted(_bulk_kandidat, key=lambda x: x.get("diambil_pada") or ""):
                _n = int(_r["nomor_urut"]) if _r.get("nomor_urut") else (_ctr := _ctr + 1) and _ctr
                _bulk_plan.append({
                    "kode_tender": _r["kode_tender"],
                    "nomor_urut": _n,
                    "nama_folder": re.sub(r'[/<>:"\|?*\\]', "-", f"{_n}. {str(_r.get('nama_tender','')).strip()} - Pokja {str(_r.get('kode_pokja','')).strip()}").strip(),
                    "id_pesan": _r.get("id_pesan", ""),
                    "kode_pokja": _r.get("kode_pokja", ""),
                })
            with st.expander(f"📋 Preview {len(_bulk_plan)} folder yang akan dibuat"):
                for _bp in _bulk_plan:
                    st.caption(_bp["nama_folder"])
            _bulk_dl = st.checkbox("📦 Download dokumen SPSE + lampiran per paket", value=True, key="cb_bulk_dl")
            if st.button(f"📁 Buat Semua ({len(_bulk_plan)} folder)", type="secondary",
                         use_container_width=True, key="btn_bulk_buat"):
                from datetime import timezone as _tz2
                from streamlit.runtime.scriptrunner import get_script_run_ctx as _get_ctx
                _ctx_bulk = _get_ctx()
                _bp2 = st.progress(0.0)
                _bs  = st.empty()
                _ok, _fail = 0, 0
                for _i, _bp in enumerate(_bulk_plan):
                    _bp2.progress((_i+1)/len(_bulk_plan))
                    _bs.info(f"[{_i+1}/{len(_bulk_plan)}] Membuat folder: {_bp['nama_folder'][:50]}")
                    try:
                        _r2 = _sp.run([_PY, _SCRIPT, _bp["nama_folder"]],
                                      capture_output=True, text=True, timeout=60,
                                      creationflags=_NO_WIN)
                        if _r2.returncode == 0:
                            _ok += 1
                            _bp_target = os.path.join(_POKJA_ROOT, _bp["nama_folder"])
                            try:
                                inbox_engine._sb().table("draft_paket").update({
                                    "nomor_urut": _bp["nomor_urut"],
                                    "folder_dibuat": _bp["nama_folder"],
                                    "folder_dibuat_pada": datetime.now(_tz2.utc).isoformat(),
                                }).eq("kode_tender", _bp["kode_tender"]).execute()
                            except Exception:
                                pass
                            # Download dokumen SPSE per paket
                            if _bulk_dl and _bp.get("id_pesan") and _bp.get("kode_tender"):
                                _bs.info(f"[{_i+1}/{len(_bulk_plan)}] Mengunduh dokumen: {_bp['nama_folder'][:40]}")
                                _dl_log = []
                                def _bulk_cb(msg, _log=_dl_log):
                                    _log.append(msg)
                                try:
                                    inbox_engine.download_dokumen_paket(
                                        _bp["kode_tender"], str(_bp["id_pesan"]),
                                        _bp_target,
                                        kode_pokja=_bp.get("kode_pokja", ""),
                                        progress_cb=_bulk_cb,
                                        st_ctx=_ctx_bulk,
                                    )
                                except Exception as _dl_e:
                                    _dl_log.append(f"ERROR download: {_dl_e}")
                            # Scrape HPS ke Supabase
                            if _bp.get("kode_tender"):
                                _bs.info(f"[{_i+1}/{len(_bulk_plan)}] Scraping HPS: {_bp['nama_folder'][:40]}")
                                try:
                                    import hps_engine as _hps_eng2
                                    _hps_eng2.scrape_dan_upsert_hps(_bp["kode_tender"])
                                except Exception:
                                    pass
                        else:
                            _fail += 1
                    except _sp.TimeoutExpired:
                        _fail += 1
                _bs.success(f"Selesai — {_ok} berhasil, {_fail} gagal.")
                st.session_state["_folder_bulk_created"] = f"{_ok} folder berhasil dibuat"
                st.rerun()
        else:
            st.info("Semua paket sudah punya folder.")

    # ══════════════════════════════════════════
    # BAWAH — 3. Data Draft Paket
    # ══════════════════════════════════════════
    st.divider()
    st.markdown("#### 3. Data Draft Paket")

    _t_filter, _t_info, _t_refresh = st.columns([2, 3, 1])

    _hari_ini = datetime.now().strftime("%Y-%m-%d")
    _tahun_ini = datetime.now().year
    _tahun_data = sorted({
        int(str(r.get("nomor_pp") or "")[-4:])
        for r in _draft_rows
        if str(r.get("nomor_pp") or "")[-4:].isdigit()
    }, reverse=True)
    _tahun_options = ["Semua"] + [str(t) for t in range(_tahun_ini, min(_tahun_data or [_tahun_ini]) - 1, -1)] + ["Baru (hari ini)", "Sudah Folder", "Belum Folder"]
    _default_idx = next((i for i, o in enumerate(_tahun_options) if o == str(_tahun_ini)), 1)
    _filter_status = _t_filter.selectbox("Filter:", _tahun_options, index=_default_idx,
                                         key="filter_draft_status", label_visibility="collapsed")
    if _t_refresh.button("🔄", key="refresh_draft"):
        st.rerun()

    def _filter_row(r):
        if _filter_status.isdigit():
            return str(r.get("nomor_pp") or "").endswith(_filter_status)
        if _filter_status == "Baru (hari ini)":
            return str(r.get("diambil_pada") or "").startswith(_hari_ini)
        if _filter_status == "Sudah Folder":
            return bool(r.get("folder_dibuat"))
        if _filter_status == "Belum Folder":
            return not bool(r.get("folder_dibuat"))
        return True

    _rows_tampil = [r for r in _draft_rows
                    if _filter_row(r) and not str(r.get("kode_tender","")).startswith("_err_")]
    _t_info.caption(f"Menampilkan {len(_rows_tampil)} dari {len(_draft_rows)} paket")

    if _rows_tampil:
        import pandas as pd
        _df_tampil = pd.DataFrame([{
            "No": i + 1,
            "Pokja": str(r.get("kode_pokja") or "").strip(),
            "Kode Tender": str(r.get("kode_tender") or ""),
            "Nama Tender": str(r.get("nama_tender") or ""),
            "Status": ("🆕 " if str(r.get("diambil_pada","")).startswith(_hari_ini) else "") +
                      ("✅ Folder" if r.get("folder_dibuat") else ""),
        } for i, r in enumerate(_rows_tampil)])
        st.dataframe(_df_tampil, use_container_width=True, hide_index=True,
                     height=min(400, 35 + len(_rows_tampil) * 35))

        # ── Reset folder_dibuat ──
        with st.expander("↩️ Reset Status Folder"):
            st.caption("Kosongkan `folder_dibuat` agar paket muncul kembali di Bulk Create (folder fisik tidak dihapus).")
            _opsi_reset = {
                f"Pokja {str(r.get('kode_pokja') or '').strip()} — {str(r.get('nama_tender') or '')[:60]}": r.get("kode_tender")
                for r in _rows_tampil if r.get("folder_dibuat") and r.get("kode_tender")
            }
            if _opsi_reset:
                _pilih_reset = st.multiselect("Pilih paket:", list(_opsi_reset.keys()), key="ms_reset_folder")
                if _pilih_reset:
                    if st.button("↩️ Reset Sekarang", type="secondary", key="btn_reset_folder_confirm"):
                        _reset_ok = 0
                        for _kr in [_opsi_reset[k] for k in _pilih_reset]:
                            try:
                                inbox_engine._sb().table("draft_paket").update(
                                    {"folder_dibuat": None, "folder_dibuat_pada": None}
                                ).eq("kode_tender", _kr).execute()
                                _reset_ok += 1
                            except Exception as _er:
                                st.error(f"{_kr}: {_er}")
                        if _reset_ok:
                            st.success(f"✅ {_reset_ok} paket berhasil direset.")
                        st.rerun()
            else:
                st.info("Tidak ada paket dengan status folder yang bisa direset.")

        # ── Hapus paket dari Supabase ──
        with st.expander("🗑️ Hapus Paket dari Database"):
            st.caption("Pilih paket yang ingin dihapus dari tabel `draft_paket` Supabase.")
            _opsi_hapus = {
                f"Pokja {str(r.get('kode_pokja') or '').strip()} — {str(r.get('nama_tender') or '')[:60]}": r.get("kode_tender")
                for r in _rows_tampil if r.get("kode_tender")
            }
            _pilih_hapus = st.multiselect("Pilih paket yang akan dihapus:", list(_opsi_hapus.keys()), key="ms_hapus_draft")
            if _pilih_hapus:
                st.warning(f"⚠️ {len(_pilih_hapus)} paket akan dihapus permanen dari Supabase.")
                if st.button("🗑️ Hapus Sekarang", type="primary", key="btn_hapus_draft_confirm"):
                    _kode_hapus = [_opsi_hapus[k] for k in _pilih_hapus]
                    _hapus_ok, _hapus_err = 0, []
                    for _kh in _kode_hapus:
                        try:
                            inbox_engine._sb().table("draft_paket").delete().eq("kode_tender", _kh).execute()
                            _hapus_ok += 1
                        except Exception as _eh:
                            _hapus_err.append(f"{_kh}: {_eh}")
                    if _hapus_ok:
                        st.success(f"✅ {_hapus_ok} paket berhasil dihapus.")
                    if _hapus_err:
                        for _em in _hapus_err:
                            st.error(_em)
                    st.rerun()
    else:
        st.info("Belum ada data. Klik 'Update Inbox' untuk mulai.")


# ============================================================
# Tab Setup Paket: LDK Auto-fill + Checklist + Masa Berlaku
# ============================================================

with tab_setup:
    # ── Layout 2 kolom: kiri = pilih paket + upload dokpil, kanan = konfigurasi ─
    _sp_col_kiri, _sp_col_kanan = st.columns([2, 3])

    with _sp_col_kiri:
        st.markdown("### 1. Pilih Paket")
        col_spfetch, col_spall, col_spnone = st.columns([3, 1, 1])
        with col_spfetch:
            if "global_paket_draft" not in st.session_state:
                st.info("⚠️ Klik **🔄 Sinkronkan Paket** di **Tab 0** dulu.")
            else:
                st.caption(f"📋 {len(st.session_state['global_paket_draft'].get('paket',[]))} paket draft tersedia")

        sp_selected = []
        if "global_paket_draft" in st.session_state:
            r = st.session_state["global_paket_draft"]
            if not r["sukses"]:
                st.error(f"❌ {r['pesan']}")
            else:
                paket_list_sp = r.get("paket", [])
                if not paket_list_sp:
                    st.warning("⚠️ Tidak ada paket ditemukan.")
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
                                _pokja_label(p),
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
            st.info("Klik tombol di atas untuk mengambil daftar paket.")

    with _sp_col_kiri:
        st.markdown("### 2. Upload Dokumen Pemilihan")
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
                    st.markdown(f"- {_pokja_label(_p)[:80]}  \n  📄 `{_p['_dokpil'].name}`")
            if _dp_tanpa_file:
                st.caption(f"⚠️ **{len(_dp_tanpa_file)} paket** tanpa DOKPIL (dilewati):")
                for _p in _dp_tanpa_file:
                    st.markdown(f"- {_pokja_label(_p)[:80]}")

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
        st.markdown("### 3. Konfigurasi")
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
        col_pjfetch, col_pjall, col_pjnone = st.columns([3, 1, 1])
        with col_pjfetch:
            if "global_paket_draft" not in st.session_state:
                st.info("⚠️ Klik **🔄 Sinkronkan Paket** di **Tab 0** dulu.")
            else:
                st.caption(f"📋 {len(st.session_state['global_paket_draft'].get('paket',[]))} paket draft tersedia")

        pj_selected = []
        if "global_paket_draft" in st.session_state:
            r = st.session_state["global_paket_draft"]
            if not r["sukses"]:
                st.error(f"❌ {r['pesan']}")
            else:
                paket_list_pj = r.get("paket", [])
                if not paket_list_pj:
                    st.warning("⚠️ Tidak ada paket ditemukan.")
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
                            _pokja_label(p),
                            value=st.session_state.get(key_chk, True),
                            key=key_chk,
                        )
                        if checked:
                            pj_selected.append(p)

                    st.caption(f"**{len(pj_selected)}** dari **{len(paket_list_pj)}** paket dipilih")
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket.")

        # ── Status Antrian ─────────────────────────────────────────────────
        st.divider()
        st.markdown("### 2. Status Antrian")
        col_refresh_pj, col_hapus_fired = st.columns(2)
        with col_refresh_pj:
            if st.button("🔄 Refresh", key="pj_refresh_queue", use_container_width=True):
                st.rerun()
        with col_hapus_fired:
            if st.button("🗑️ Hapus yang Selesai", key="pj_hapus_fired", use_container_width=True):
                jobs = penjelasan_engine.get_jobs()
                for j in jobs:
                    if j["status"] in ("fired", "gagal"):
                        penjelasan_engine.hapus_job(j["paket_id"], j["jenis"])
                st.rerun()

        jobs_all = penjelasan_engine.get_jobs()
        if not jobs_all:
            st.info("Antrian kosong. Pilih paket dan klik Jadwalkan.")
        else:
            from penjelasan_engine import TZ_WIB as _TZ_WIB
            now_q = datetime.now(_TZ_WIB)
            rows_q = []
            for j in jobs_all:
                try:
                    wf = datetime.fromisoformat(j["waktu_fire"])
                    secs = int((wf - now_q).total_seconds())
                    if j["status"] == "fired":
                        countdown_q = "✅ Selesai"
                    elif j["status"] == "gagal":
                        countdown_q = "❌ Gagal"
                    elif secs > 0:
                        h, rem = divmod(secs, 3600)
                        m = rem // 60
                        countdown_q = f"⏳ {h//24}h {h%24}j {m}m"
                    else:
                        countdown_q = "🔴 Menunggu scheduler..."
                    waktu_str = wf.strftime("%d/%m %H:%M")
                except Exception:
                    waktu_str = j.get("waktu_fire", "-")
                    countdown_q = "-"
                rows_q.append({
                    "Paket": j.get("nama_paket", j["paket_id"])[:45],
                    "Jenis": j.get("jenis", "-"),
                    "Waktu": waktu_str,
                    "Countdown": countdown_q,
                })
            st.dataframe(rows_q, use_container_width=True, hide_index=True)

    with _pj_col_kanan:
        from penjelasan_engine import TZ_WIB

        st.markdown("### 3. Jadwalkan Auto-Post")
        st.caption("Engine cari jadwal penjelasan dari Google Calendar lalu auto-post saat waktunya tiba.")

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
                key="pj_teks_override",
            )

        # ── Preview jadwal GCal per paket terpilih ─────────────────────────
        if pj_selected:
            with st.spinner("Baca jadwal dari Google Calendar..."):
                jadwal_gcal = penjelasan_engine.get_jadwal_dari_gcalendar()
            now_pj = datetime.now(TZ_WIB)

            for p in pj_selected:
                tgl_mulai = jadwal_gcal.get(p["id_lelang"])
                if tgl_mulai:
                    secs = int((tgl_mulai - now_pj).total_seconds())
                    if secs > 0:
                        h, rem = divmod(secs, 3600)
                        m = rem // 60
                        countdown = f"⏳ {h//24}h {h%24}j {m}m lagi"
                    elif secs > -10800:
                        countdown = "🔴 AKTIF SEKARANG"
                    else:
                        countdown = "✅ Sudah lewat"
                    st.caption(f"**{p['kode']}** — {tgl_mulai.strftime('%d/%m/%Y %H:%M')} WIB | {countdown}")
                else:
                    st.caption(f"**{p['kode']}** — ⚠️ Tidak ditemukan di GCal")

        st.divider()

        # ── Tombol Jadwalkan ───────────────────────────────────────────────
        pj_n = len(pj_selected)
        if st.button(
            f"📅 Jadwalkan {pj_n} Paket ke Antrian",
            key="pj_jadwalkan",
            type="primary",
            disabled=pj_n == 0,
            use_container_width=True,
        ):
            teks_ov = st.session_state.get("pj_teks_override", "").strip() or None
            hasil_jadwal = []
            for p in pj_selected:
                r = penjelasan_engine.jadwalkan_dari_gcal(
                    paket_id=p["id_lelang"],
                    nama_paket=p["nama"],
                    jenis=pj_jenis,
                    teks_override=teks_ov,
                )
                hasil_jadwal.append({
                    "kode": p["kode"],
                    "nama": p["nama"][:50],
                    "status": "✅ Dijadwalkan" if r["ok"] else "❌ Gagal",
                    "waktu": r["waktu_fire"].strftime("%d/%m/%Y %H:%M") if r["waktu_fire"] else "-",
                    "pesan": r["pesan"],
                })
            ok_n = sum(1 for h in hasil_jadwal if h["status"].startswith("✅"))
            if ok_n == pj_n:
                st.success(f"✅ {ok_n} paket berhasil dijadwalkan.")
            else:
                st.warning(f"⚠️ {ok_n}/{pj_n} paket dijadwalkan. Cek paket yang gagal.")
            st.dataframe(hasil_jadwal, use_container_width=True, hide_index=True)

        # ── Log Scheduler ──────────────────────────────────────────────────
        with st.expander("📋 Log Scheduler"):
            log_lines = penjelasan_engine.get_log()
            if log_lines:
                st.code("\n".join(reversed(log_lines[-30:])), language=None)
            else:
                st.caption("Belum ada log.")

        # ── Post Manual (darurat) ──────────────────────────────────────────
        with st.expander("⚡ Post Manual Sekarang (darurat)"):
            st.caption("Post langsung tanpa menunggu scheduler. Gunakan jika scheduler tidak jalan.")
            if st.button(
                f"🚀 Post ke {pj_n} Paket Sekarang",
                key="pj_post_manual",
                disabled=pj_n == 0,
                use_container_width=True,
            ):
                teks_ov = st.session_state.get("pj_teks_override", "").strip() or None
                progress = st.progress(0, text="Memulai...")
                hasil_pj = []
                for i, p in enumerate(pj_selected):
                    progress.progress((i + 1) / len(pj_selected), text=f"Post ke {p['kode']}...")
                    try:
                        result = penjelasan_engine.auto_post_sapaan(p["id_lelang"], pj_jenis, teks_ov)
                        hasil_pj.append({
                            "kode": p["kode"], "nama": p["nama"][:45],
                            "total": result["total"], "sukses": result["sukses"],
                            "gagal": result["gagal"], "pesan": result.get("pesan", ""),
                        })
                    except Exception as e:
                        hasil_pj.append({
                            "kode": p["kode"], "nama": p["nama"][:45],
                            "total": 0, "sukses": 0, "gagal": 1, "pesan": str(e),
                        })
                progress.empty()
                ok_m = sum(1 for h in hasil_pj if h["gagal"] == 0 and h["total"] > 0)
                if ok_m == len(hasil_pj):
                    st.success(f"✅ {ok_m}/{len(hasil_pj)} paket berhasil.")
                else:
                    st.warning(f"⚠️ {ok_m}/{len(hasil_pj)} paket berhasil.")
                st.dataframe(hasil_pj, use_container_width=True, hide_index=True)

# ============================================================
# Tab 8: Auto-Fill Jadwal
# ============================================================

with tab8:

    _libur_map = _LIBUR_MAP

    _jd_col_list, _jd_col_detail = st.columns([3, 2])

    with _jd_col_list:
        st.markdown("### 1. Pilih Paket")
        col_fetch, col_all, col_none = st.columns([3, 1, 1])
        with col_fetch:
            if "global_paket_draft" not in st.session_state:
                st.info("⚠️ Klik **🔄 Sinkronkan Paket** di **Tab 0** dulu.")
            else:
                st.caption(f"📋 {len(st.session_state['global_paket_draft'].get('paket',[]))} paket draft tersedia")

        jd_selected = []
        if "global_paket_draft" in st.session_state:
            r = st.session_state["global_paket_draft"]
            if not r["sukses"]:
                st.error(f"❌ {r['pesan']}")
            else:
                paket_list = r.get("paket", [])
                if not paket_list:
                    st.warning("⚠️ Tidak ada paket ditemukan.")
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
                            _pokja_label(p),
                            value=st.session_state.get(key_chk, True),
                            key=key_chk,
                        )
                        if checked:
                            jd_selected.append(p)

                    st.caption(f"**{len(jd_selected)}** dari **{len(paket_list)}** paket dipilih")
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket.")

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
                st.markdown(f"**{_HARI_NAMA[jd_tgl_global.weekday()]}, {jd_tgl_global.day} {_BULAN_NAMA[jd_tgl_global.month-1]} {jd_tgl_global.year}**")
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
                            st.caption(f"{_HARI_NAMA[tgl_p.weekday()]}, {tgl_p.day} {_BULAN_NAMA[tgl_p.month-1]} {tgl_p.year}")
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
                st.write(f"• {_HARI_NAMA[d.weekday()]}, {d.day} {_BULAN_NAMA[d.month-1]} {d.year} — {_libur_map[d]}")

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
        
        kp_selected = []
        
        # Menggunakan data paket yang sudah disinkronkan di Tab 0
        if "global_paket_draft" not in st.session_state:
            st.info("⚠️ Data paket belum disinkronkan. Silakan ke **Tab 0** dan klik **🔄 Sinkronkan Paket**.")
        else:
            r = st.session_state["global_paket_draft"]
            if not r.get("sukses"):
                st.error(f"❌ {r.get('pesan', 'Gagal memuat data paket')}")
            else:
                paket_list = r.get("paket", [])
                if not paket_list:
                    st.warning("⚠️ Tidak ada paket draft ditemukan.")
                else:
                    st.caption(f"📋 {len(paket_list)} paket draft tersedia — pilih target:")
                    
                    _kp_sel_col1, _kp_sel_col2 = st.columns(2)
                    with _kp_sel_col1:
                        if st.button("✅ Semua", key="kp_sel_all", use_container_width=True):
                            for p in paket_list:
                                st.session_state[f"kp_chk_{p['id_lelang']}"] = True
                            st.rerun()
                    with _kp_sel_col2:
                        if st.button("⬜ Kosong", key="kp_sel_none", use_container_width=True):
                            for p in paket_list:
                                st.session_state[f"kp_chk_{p['id_lelang']}"] = False
                            st.rerun()

                    for p in paket_list:
                        key_chk = f"kp_chk_{p['id_lelang']}"
                        key_lamp_bytes = f"kp_lamp_bytes_{p['id_lelang']}"
                        key_lamp_nama  = f"kp_lamp_nama_{p['id_lelang']}"

                        col_chk, col_lamp = st.columns([3, 2])
                        with col_chk:
                            checked = st.checkbox(
                                _pokja_label(p),
                                value=st.session_state.get(key_chk, True),
                                key=key_chk,
                            )
                        with col_lamp:
                            # Tampilkan info lampiran yang sudah di-generate / diupload
                            lamp_bytes = st.session_state.get(key_lamp_bytes)
                            lamp_nama  = st.session_state.get(key_lamp_nama, "")
                            if lamp_bytes:
                                st.caption(f"📎 {lamp_nama}")
                                if st.button("✖ Hapus", key=f"kp_hapus_{p['id_lelang']}", use_container_width=True):
                                    del st.session_state[key_lamp_bytes]
                                    st.session_state[key_lamp_nama] = ""
                                    st.rerun()
                            else:
                                if st.button(
                                    "⚙️ Generate",
                                    key=f"kp_gen_{p['id_lelang']}",
                                    use_container_width=True,
                                    help="Generate lampiran PDF dari Excel+Word (butuh folder paket sudah dibuat di Tab 0)",
                                ):
                                    with st.spinner(f"Generate PDF {p['kode']}..."):
                                        res_gen = merge_engine.generate_undangan_pdf(p["kode"])
                                    if res_gen["sukses"]:
                                        st.session_state[key_lamp_bytes] = res_gen["pdf_bytes"]
                                        st.session_state[key_lamp_nama]  = f"Undangan_{p['kode'].replace('/', '-')}.pdf"
                                        st.success(res_gen["pesan"])
                                        st.rerun()
                                    else:
                                        st.error(res_gen["pesan"])
                                uploaded_lamp = st.file_uploader(
                                    "Upload",
                                    type=["pdf"],
                                    key=f"kp_lamp_{p['id_lelang']}",
                                    label_visibility="collapsed",
                                )
                                if uploaded_lamp:
                                    st.session_state[key_lamp_bytes] = uploaded_lamp.read()
                                    st.session_state[key_lamp_nama]  = uploaded_lamp.name
                                    st.rerun()

                        if checked:
                            lamp_bytes_final = st.session_state.get(key_lamp_bytes)
                            lamp_nama_final  = st.session_state.get(key_lamp_nama, "")
                            # Bungkus bytes ke objek file-like agar kompatibel dgn code lama
                            kp_selected.append({
                                **p,
                                "_lampiran_bytes": lamp_bytes_final,
                                "_lampiran_nama":  lamp_nama_final,
                                "_lampiran": None,  # legacy field (tidak dipakai lagi)
                            })

                    st.caption(f"**{len(kp_selected)}** dari **{len(paket_list)}** paket dipilih")

        # ── Auto Pre-fill dari Excel (jika ada 1 paket terpilih & folder ada) ──
        if len(kp_selected) == 1:
            pkode = kp_selected[0]["kode"]
            if st.button(
                f"📋 Pre-fill Tanggal & Tempat dari Excel ({pkode})",
                key="kp_prefill",
                use_container_width=True,
                help="Baca E26 (tanggal DPP) dan E31 (tempat) dari file Excel paket",
            ):
                with st.spinner("Membaca Excel..."):
                    info = merge_engine.get_draft_info_from_excel(pkode)
                if info["tanggal"]:
                    st.session_state["kp_tgl"] = info["tanggal"]
                if info["tempat"]:
                    st.session_state["kp_tempat"] = info["tempat"]
                if info["pesan"] != "OK":
                    st.warning(f"Pre-fill: {info['pesan']}")
                else:
                    st.success("Tanggal & tempat berhasil diisi dari Excel.")
                st.rerun()

        # ── 2. Detail Undangan ────────────────────────────────────────────────
        st.divider()
        st.markdown("### 2. Detail Undangan")

        _kp_HARI_NAMA  = _HARI_NAMA
        _kp_BULAN_NAMA = _BULAN_NAMA
        _kp_libur_map = _LIBUR_MAP

        col_tgl, col_mulai, col_selesai = st.columns(3)
        with col_tgl:
            kp_tgl = st.date_input(
                "Tanggal",
                value=datetime.now().date(),
                format="DD/MM/YYYY",
                key="kp_tgl",
            )
            st.markdown(f"**{_kp_HARI_NAMA[kp_tgl.weekday()]}, {kp_tgl.day} {_kp_BULAN_NAMA[kp_tgl.month-1]} {kp_tgl.year}**")
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
                st.write(f"• {_kp_HARI_NAMA[d.weekday()]}, {d.day} {_kp_BULAN_NAMA[d.month-1]} {d.year} — {_kp_libur_map[d]}")

        kp_tempat = st.text_area(
            "Tempat",
            value=kirimpesan_engine.DEFAULT_TEMPAT,
            key="kp_tempat",
            height=100,
        )

        # ── Kode Unik ──────────────────────────────────────────────────────────
        kp_kode_unik = st.text_input(
            "Kode Unik Surat",
            placeholder="mis. 001, 002, 003",
            key="kp_kode_unik",
            help="Nomor urut surat undangan reviu — digunakan di nomor surat (opsional, bisa diisi nanti)",
        )
        if kp_selected and kp_kode_unik:
            # Simpan kode_unik ke Supabase untuk tiap paket terpilih
            for _kp in kp_selected:
                _kp["_kode_unik"] = kp_kode_unik

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
                        lamp_bytes = paket.get("_lampiran_bytes")
                        lamp_nama  = paket.get("_lampiran_nama", "")
                        # Legacy fallback: file_uploader object
                        if lamp_bytes is None:
                            lamp_legacy = paket.get("_lampiran")
                            if lamp_legacy:
                                lamp_bytes = lamp_legacy.getvalue()
                                lamp_nama  = lamp_legacy.name
                        res = kirimpesan_engine.kirim_undangan(
                            paket_id=paket["id_lelang"],
                            waktu=waktu_str,
                            sampai=sampai_str,
                            tempat=kp_tempat.strip(),
                            dibawa=kp_dibawa.strip(),
                            hadir=kp_hadir.strip(),
                            is_online=False,
                            link_pembuktian="",
                            lampiran_bytes=lamp_bytes,
                            lampiran_nama=lamp_nama,
                        )

                        hasil_list.append({
                            "kode": paket["kode"],
                            "nama": paket["nama"][:50],
                            "sukses": res["sukses"],
                            "pesan": res["pesan"],
                        })
                        # Simpan kode_unik ke Supabase jika ada
                        _ku = paket.get("_kode_unik") or kp_kode_unik
                        if res["sukses"] and _ku:
                            try:
                                inbox_engine._sb().table("draft_paket").update({
                                    "kode_unik": _ku,
                                }).eq("kode_tender", paket["kode"]).execute()
                            except Exception:
                                pass

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
        if "global_paket_draft" not in st.session_state:
            st.info("⚠️ Klik **🔄 Sinkronkan Paket** di **Tab 0** dulu.")

        ba_selected = []
        if "global_paket_draft" in st.session_state:
            _ba_r = st.session_state["global_paket_draft"]
            if not _ba_r["sukses"]:
                st.error(f"❌ {_ba_r['pesan']}")
            else:
                _ba_paket_list = _ba_r.get("paket", [])
                if not _ba_paket_list:
                    st.warning("⚠️ Tidak ada paket ditemukan.")
                else:
                    for _p in _ba_paket_list:
                        _key_chk = f"r1_ba_chk_{_p['id_lelang']}"
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
                                key=f"r1_ba_file_{_p['id_lelang']}",
                                label_visibility="collapsed",
                            )
                            if _ba_up:
                                st.caption(f"📋 {_ba_up.name}")
                        if _checked:
                            ba_selected.append({**_p, "_ba_file": _ba_up})
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket.")

        st.divider()
        ba_tgl = st.date_input(
            "Tanggal BA Reviu",
            value=datetime.now().date(),
            key="r1_ba_tgl",
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

# Tab 5: Upload & Cetak 5 BA

# ============================================================

with tab_ba:

    _ba_col1, _ba_col2, _ba_col3, _ba_col4, _ba_col5 = st.columns([2.2, 1.7, 1.7, 1.7, 1.7])


    with _ba_col1:
        st.markdown("### 1. Pilih Paket")

        ba_selected = []

        # Menggunakan data paket yang sudah disinkronkan di Tab 0
        if "global_paket_draft" not in st.session_state:
            st.info("⚠️ Data paket belum disinkronkan. Silakan ke **Tab 0** dan klik **🔄 Sinkronkan Paket**.")
        else:
            r = st.session_state["global_paket_draft"]
            if not r.get("sukses"):
                st.error(f"❌ {r.get('pesan', 'Gagal memuat data paket')}")
            else:
                paket_list_ba = r.get("paket", [])
                if not paket_list_ba:
                    st.warning("⚠️ Tidak ada paket draft ditemukan.")
                else:
                    st.caption(f"📋 {len(paket_list_ba)} paket draft tersedia — pilih:")
                    
                    _ba_sel_col1, _ba_sel_col2 = st.columns(2)
                    with _ba_sel_col1:
                        if st.button("✅ Semua", key="ba_sel_all", use_container_width=True):
                            for p in paket_list_ba:
                                st.session_state[f"ba_chk_{p['id_lelang']}"] = True
                            st.rerun()
                    with _ba_sel_col2:
                        if st.button("⬜ Kosong", key="ba_sel_none", use_container_width=True):
                            for p in paket_list_ba:
                                st.session_state[f"ba_chk_{p['id_lelang']}"] = False
                            st.rerun()


                    for p in paket_list_ba:
                        key_chk = f'ba_chk_{p["id_lelang"]}'
                        _chk_col, _super_col = st.columns([3, 1])
                        with _chk_col:
                            checked = st.checkbox(
                                _pokja_label(p),
                                value=st.session_state.get(key_chk, True), key=key_chk,
                            )
                        with _super_col:
                            if st.button('🚀', key=f'btn_super_{p["id_lelang"]}', use_container_width=True, help='Cetak & Upload SEMUA BA untuk paket ini'):
                                st.session_state["ba_auto_target"] = "SEMUA"
                                st.session_state["ba_super_paket"] = [p]
                        if checked:
                            ba_selected.append(p)

                    st.caption(f"**{len(ba_selected)}** dari **{len(paket_list_ba)}** paket dipilih")


        # ── Inisialisasi session state BA ─────────────────────────────────
        for jenis_key in ba_config.JENIS_KEYS:
            if f"ba_tgl_{jenis_key}" not in st.session_state:
                st.session_state[f"ba_tgl_{jenis_key}"] = datetime.today().strftime("%d-%m-%Y")
            if f"ba_info_{jenis_key}" not in st.session_state:
                st.session_state[f"ba_info_{jenis_key}"] = ba_config.DEFAULT_INFO.get(jenis_key, "")

        # ── Auto-populate nomor BA dari dokpil paket pertama yang dipilih ──
        if ba_selected and st.button("🔄 Auto Nomor dari Dokpil", key="ba_auto_nomor", use_container_width=True):
            with st.spinner("Mengambil nomor dokpil..."):
                _nomor_dokpil = ba_engine.get_nomor_dokpil(ba_selected[0]["id_lelang"])
            if _nomor_dokpil:
                for jenis_key in ba_config.JENIS_KEYS:
                    _urut = ba_config.NOMOR_URUT[jenis_key]
                    st.session_state[f"ba_no_{jenis_key}"] = ba_engine.derive_nomor_ba(_nomor_dokpil, _urut)
                st.success(f"✅ Nomor BA berhasil di-generate dari: `{_nomor_dokpil}`")
            else:
                st.warning("⚠️ Nomor dokpil tidak ditemukan di halaman SPSE.")
            st.rerun()

        # ── Auto-detect tanggal BA dari Google Calendar ───────────────────
        if ba_selected and st.button("📅 Auto Tanggal dari GCal", key="ba_auto_tgl_gcal", use_container_width=True):
            with st.spinner("Mencari tanggal di Google Calendar..."):
                try:
                    import gcal_helper
                    _nama_paket = ba_selected[0]["nama"]
                    _tgl_map = gcal_helper.get_tanggal_ba_dari_gcal(_nama_paket)
                    _found = []
                    for _jk, _d in _tgl_map.items():
                        if _d is not None:
                            st.session_state[f"ba_tgl_date_{_jk}"] = _d
                            st.session_state[f"ba_tgl_{_jk}"] = _d.strftime("%d-%m-%Y")
                            _found.append(ba_config.JENIS_LABEL.get(_jk, _jk))
                    if _found:
                        st.success(f"✅ Tanggal ditemukan: {', '.join(_found)}")
                    else:
                        st.warning(f"⚠️ Tidak ada event GCal yang cocok dengan paket:\n**{_nama_paket}**")
                except Exception as _e:
                    st.error(f"❌ GCal error: {_e}")
            st.rerun()

    with _ba_col2:

        st.markdown("### 2. Konfigurasi BA")
        st.markdown(f"#### 📋 {ba_config.JENIS_LABEL['penjelasan']}")
        _nd = st.session_state.get("ba_no_penjelasan", "")
        if _nd:
            st.code(_nd, language=None)
        else:
            st.caption("Nomor: klik 🔄 _Auto Nomor_ di kolom kiri")
        st.date_input("Tanggal", value=date.today(), key="ba_tgl_date_penjelasan", format="DD/MM/YYYY", label_visibility="collapsed")
        _dt = st.session_state.get("ba_tgl_date_penjelasan", date.today())
        if isinstance(_dt, date):
            st.session_state["ba_tgl_penjelasan"] = _dt.strftime("%d-%m-%Y")
        st.text_area("Keterangan (opsional)", key="ba_info_penjelasan", height=100, label_visibility="collapsed")
        if st.button("⚡ Cetak & Upload", key="btn_cetak_penjelasan", use_container_width=True, disabled=len(ba_selected) == 0):
            st.session_state["ba_auto_target"] = "penjelasan"

    with _ba_col3:

        st.markdown("### &nbsp;")
        st.markdown(f"#### 📋 {ba_config.JENIS_LABEL['evaluasi']}")
        _nd = st.session_state.get("ba_no_evaluasi", "")
        if _nd:
            st.code(_nd, language=None)
        else:
            st.caption("Nomor: klik 🔄 _Auto Nomor_ di kolom kiri")
        st.date_input("Tanggal", value=date.today(), key="ba_tgl_date_evaluasi", format="DD/MM/YYYY", label_visibility="collapsed")
        _dt = st.session_state.get("ba_tgl_date_evaluasi", date.today())
        if isinstance(_dt, date):
            st.session_state["ba_tgl_evaluasi"] = _dt.strftime("%d-%m-%Y")
        st.text_area("Keterangan (opsional)", key="ba_info_evaluasi", height=100, label_visibility="collapsed")
        if st.button("⚡ Cetak & Upload", key="btn_cetak_evaluasi", use_container_width=True, disabled=len(ba_selected) == 0):
            st.session_state["ba_auto_target"] = "evaluasi"

    with _ba_col4:

        st.markdown("### &nbsp;")
        st.markdown(f"#### 📋 {ba_config.JENIS_LABEL['hasil_pemilihan']}")
        _nd = st.session_state.get("ba_no_hasil_pemilihan", "")
        if _nd:
            st.code(_nd, language=None)
        else:
            st.caption("Nomor: klik 🔄 _Auto Nomor_ di kolom kiri")
        st.date_input("Tanggal", value=date.today(), key="ba_tgl_date_hasil_pemilihan", format="DD/MM/YYYY", label_visibility="collapsed")
        _dt = st.session_state.get("ba_tgl_date_hasil_pemilihan", date.today())
        if isinstance(_dt, date):
            st.session_state["ba_tgl_hasil_pemilihan"] = _dt.strftime("%d-%m-%Y")
        st.text_area("Keterangan (opsional)", key="ba_info_hasil_pemilihan", height=100, label_visibility="collapsed")
        if st.button("⚡ Cetak & Upload", key="btn_cetak_hasil_pemilihan", use_container_width=True, disabled=len(ba_selected) == 0):
            st.session_state["ba_auto_target"] = "hasil_pemilihan"

    with _ba_col5:

        st.markdown("### &nbsp;")
        st.markdown(f"#### 📋 {ba_config.JENIS_LABEL['negosiasi']}")
        _nd = st.session_state.get("ba_no_negosiasi", "")
        if _nd:
            st.code(_nd, language=None)
        else:
            st.caption("Nomor: klik 🔄 _Auto Nomor_ di kolom kiri")
        st.date_input("Tanggal", value=date.today(), key="ba_tgl_date_negosiasi", format="DD/MM/YYYY", label_visibility="collapsed")
        _dt = st.session_state.get("ba_tgl_date_negosiasi", date.today())
        if isinstance(_dt, date):
            st.session_state["ba_tgl_negosiasi"] = _dt.strftime("%d-%m-%Y")
        st.text_area("Keterangan (opsional)", key="ba_info_negosiasi", height=100, label_visibility="collapsed")
        if st.button("⚡ Cetak & Upload", key="btn_cetak_negosiasi", use_container_width=True, disabled=len(ba_selected) == 0):
            st.session_state["ba_auto_target"] = "negosiasi"


    # ── BA Lainnya (manual: scan dulu) ────────────────────────────────────
    with _ba_col2:
        st.markdown("#### 📁 BA Lainnya")
        st.caption("Upload manual — gabungkan scan terlebih dahulu.")
        st.date_input("Tanggal BA Lainnya", value=date.today(), key="ba_tgl_date_lainnya", format="DD/MM/YYYY")
        _dt = st.session_state.get("ba_tgl_date_lainnya", date.today())
        if isinstance(_dt, date):
            st.session_state["ba_tgl_lainnya"] = _dt.strftime("%d-%m-%Y")
        st.file_uploader("File PDF", type=["pdf"], key="ba_file_lainnya")
        if st.button(
            f"🚀 Upload BA Lainnya ({len(ba_selected)} paket)",
            key="ba_lainnya_upload",
            disabled=len(ba_selected) == 0 or not st.session_state.get("ba_file_lainnya"),
            use_container_width=True,
        ):
            _file_up = st.session_state.get("ba_file_lainnya")
            _tgl_l = st.session_state.get("ba_tgl_lainnya", "").strip()
            if _file_up and _tgl_l:
                _prog_l = st.progress(0, text="Uploading BA Lainnya...")
                _hasil_l = []
                for _il, _pl in enumerate(ba_selected):
                    try:
                        _r = ba_engine.upload_ba(
                            paket_id=_pl["id_lelang"], jenis_key="lainnya",
                            nomor_ba="", tanggal_ba=_tgl_l,
                            file_bytes=_file_up.getvalue(), file_name=_file_up.name,
                            info="",
                        )
                        _hasil_l.append({"kode": _pl["kode"], "ok": _r["ok"]})
                    except Exception as _e:
                        _hasil_l.append({"kode": _pl["kode"], "ok": False, "err": str(_e)})
                    _prog_l.progress((_il + 1) / len(ba_selected))
                _prog_l.empty()
                _sukses_l = sum(1 for h in _hasil_l if h["ok"])
                st.success(f"✅ {_sukses_l}/{len(_hasil_l)} BA Lainnya berhasil di-upload.")
            else:
                st.warning("⚠️ Lengkapi Tanggal dan File PDF.")

    # ── Proses Cetak & Auto-Upload ───────────────────────────────────────
    _FILE_LABEL_BA = {
        "penjelasan":      "2. Berita Acara Pemberian Penjelasan",
        "evaluasi":        "4. Berita Acara Evaluasi Penawaran",
        "hasil_pemilihan": "8. Berita Acara Hasil Pemilihan",
        "negosiasi":       "10. Berita Acara Negosiasi",
    }
    if st.session_state.get("ba_auto_target"):
        import os as _os
        from config import POKJA_ROOT as _POKJA_ROOT
        jenis_target = st.session_state["ba_auto_target"]
        target_paket = st.session_state.pop("ba_super_paket", None) or ba_selected
        _JENIS_AUTO = [k for k in ba_config.JENIS_KEYS if k != "lainnya"]
        jenis_list = _JENIS_AUTO if jenis_target == "SEMUA" else [jenis_target]
        label_target = "Semua BA" if jenis_target == "SEMUA" else ba_config.JENIS_BA[jenis_target]
        progress = st.progress(0, text=f"Memulai Cetak & Upload {label_target}...")
        hasil_auto = []
        total_ops = len(target_paket) * len(jenis_list)
        op_idx = 0
        for i, p in enumerate(target_paket):
            pid = p["id_lelang"]
            paket_hasil = {"kode": p["kode"], "nama": p["nama"][:50], "ba": []}
            folder_name = f"Cetak_BA_{p['kode']}"
            target_dir = _os.path.join(_POKJA_ROOT, "Asisten_Pokja_Downloads", folder_name)
            _os.makedirs(target_dir, exist_ok=True)
            for jenis_key in jenis_list:
                op_idx += 1
                progress.progress(op_idx / total_ops, text=f"Proses {p['kode']} — {ba_config.JENIS_BA[jenis_key]} ({op_idx}/{total_ops})...")
                nomor = st.session_state.get(f"ba_no_{jenis_key}", "").strip()
                tanggal = st.session_state.get(f"ba_tgl_{jenis_key}", "").strip()
                info = st.session_state.get(f"ba_info_{jenis_key}", "").strip()
                ba_result = {"jenis": ba_config.JENIS_BA[jenis_key], "status": "⏭️ Lewati (nomor/tanggal kosong)"}
                if nomor and tanggal:
                    try:
                        r_cetak = ba_engine.cetak_ba(paket_id=pid, jenis_key=jenis_key, nomor_ba=nomor, tanggal_ba=tanggal)
                        if r_cetak["ok"]:
                            fn = f"{_FILE_LABEL_BA.get(jenis_key, jenis_key)}-{p['kode']}.pdf"
                            with open(_os.path.join(target_dir, fn), "wb") as f:
                                f.write(r_cetak["pdf_bytes"])
                            r_up = ba_engine.upload_ba(paket_id=pid, jenis_key=jenis_key, nomor_ba=nomor, tanggal_ba=tanggal, file_bytes=r_cetak["pdf_bytes"], file_name=fn, info=info)
                            if r_up["ok"]:
                                ba_result["status"] = f"✅ Sukses — `{fn}`"
                            else:
                                ba_result["status"] = f"❌ Upload Error {r_up['status']}"
                        else:
                            ba_result["status"] = f"❌ Cetak Error {r_cetak['status']}: {r_cetak.get('error')}"
                    except Exception as e:
                        ba_result["status"] = f"❌ {e}"
                paket_hasil["ba"].append(ba_result)
            hasil_auto.append(paket_hasil)
        progress.empty()
        st.success(f"✅ Selesai! {label_target} telah dikirim ke SPSE dan backup PDF disimpan.")
        del st.session_state["ba_auto_target"]
        for h in hasil_auto:
            st.markdown(f"**{h['kode']}** — {h['nama']}")
            for b in h["ba"]:
                st.caption(f"{b['status']} — {b['jenis']}")
            st.divider()

# ============================================================
# Tab 6: Download Dokumen Kualifikasi
# ============================================================

with tab_kual:
    # ── Pre-render: fetch semua paket yang dicek tapi belum ada datanya ────────
    if "global_paket_draft" in st.session_state and st.session_state["global_paket_draft"].get("sukses"):
        _kl_perlu_fetch = [
            p for p in st.session_state["global_paket_draft"].get("paket", [])
            if p.get("kode") != "00000000000"
            and st.session_state.get(f"kl_chk_{p['kode']}", False)
            and f"kl_peserta_{p['kode']}" not in st.session_state
        ]
        if _kl_perlu_fetch:
            with st.spinner(f"Memuat peserta {len(_kl_perlu_fetch)} paket..."):
                for _kl_fp in _kl_perlu_fetch:
                    _kl_id = _kl_fp.get("id_lelang") or _kl_fp["kode"]
                    st.session_state[f"kl_peserta_{_kl_fp['kode']}"] = kualifikasi_engine.fetch_peserta_by_id_lelang(_kl_id)

    _kl_col1, _kl_col2 = st.columns([2, 3])

    with _kl_col1:
        st.markdown("#### 1. Pilih Paket")
        if "global_paket_draft" not in st.session_state:
            st.info("⚠️ Data paket belum disinkronkan. Silakan ke **Tab 0** dan klik **🔄 Sinkronkan Paket**.")
        else:
            _kl_draft = st.session_state["global_paket_draft"]
            if not _kl_draft.get("sukses"):
                st.error(f"❌ {_kl_draft.get('pesan', 'Gagal memuat data paket')}")
            else:
                _kl_paket_list = sorted(
                    [p for p in _kl_draft.get("paket", []) if p.get("kode") != "00000000000"],
                    key=lambda p: p.get("tanggal", ""),
                    reverse=True,
                )
                if not _kl_paket_list:
                    st.warning("⚠️ Tidak ada paket aktif ditemukan.")
                else:
                    st.caption(f"📋 {len(_kl_paket_list)} paket — centang satu atau lebih:")
                    for p in _kl_paket_list:
                        _kl_chk_key = f"kl_chk_{p['kode']}"
                        _was = st.session_state.get(_kl_chk_key, False)
                        _checked = st.checkbox(
                            f"{_pokja_label(p)[:70]}  \n_{p.get('status', '')}_",
                            key=_kl_chk_key,
                            value=_was,
                        )

        st.divider()
        st.markdown("#### 2. Peserta per Paket")
        if "global_paket_draft" in st.session_state and st.session_state["global_paket_draft"].get("sukses"):
            _kl_paket_list2 = sorted(
                [p for p in st.session_state["global_paket_draft"].get("paket", []) if p.get("kode") != "00000000000"],
                key=lambda p: p.get("tanggal", ""),
                reverse=True,
            )
            _kl_ada_terpilih = False
            for p in _kl_paket_list2:
                if not st.session_state.get(f"kl_chk_{p['kode']}", False):
                    continue
                _kl_ada_terpilih = True
                kl_res_p = st.session_state.get(f"kl_peserta_{p['kode']}")
                if kl_res_p is None:
                    st.caption(f"⏳ {p['kode']} — menunggu fetch...")
                elif not kl_res_p["ok"]:
                    st.warning(f"❌ {p['kode']}: {kl_res_p['pesan']}")
                    if st.button("🔄 Retry", key=f"kl_retry_{p['kode']}"):
                        _kl_id = p.get("id_lelang") or p["kode"]
                        with st.spinner("..."):
                            st.session_state[f"kl_peserta_{p['kode']}"] = kualifikasi_engine.fetch_peserta_by_id_lelang(_kl_id)
                        st.rerun()
                else:
                    n_p = len(kl_res_p["peserta"])
                    with st.expander(f"**{p['kode']}** — {n_p} peserta", expanded=True):
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("✅ Semua", key=f"kl_all_{p['kode']}", use_container_width=True):
                                for ps in kl_res_p["peserta"]:
                                    st.session_state[f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}"] = True
                                st.rerun()
                        with c2:
                            if st.button("⬜ Batal", key=f"kl_none_{p['kode']}", use_container_width=True):
                                for ps in kl_res_p["peserta"]:
                                    st.session_state[f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}"] = False
                                st.rerun()
                        for i, ps in enumerate(kl_res_p["peserta"], 1):
                            st.checkbox(
                                f"{i}. {ps['nama']}",
                                key=f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}",
                                value=st.session_state.get(f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}", True),
                            )
            if not _kl_ada_terpilih:
                st.caption("← Centang paket di atas untuk memuat peserta.")

    with _kl_col2:
        st.markdown("#### 3. Folder & Aksi")

        # ── Ringkasan paket terpilih + status folder ───────────────────────────
        _kl_paket_dipilih = []
        if "global_paket_draft" in st.session_state and st.session_state["global_paket_draft"].get("sukses"):
            _kl_all_list = sorted(
                [p for p in st.session_state["global_paket_draft"].get("paket", []) if p.get("kode") != "00000000000"],
                key=lambda p: p.get("tanggal", ""),
                reverse=True,
            )
            for p in _kl_all_list:
                if not st.session_state.get(f"kl_chk_{p['kode']}", False):
                    continue
                kl_res_p = st.session_state.get(f"kl_peserta_{p['kode']}")
                if not kl_res_p or not kl_res_p["ok"]:
                    continue
                peserta_terpilih = [
                    ps for ps in kl_res_p["peserta"]
                    if st.session_state.get(f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}", True)
                ]
                resolve = kualifikasi_engine.resolve_folder_paket(p["kode"])
                _kl_paket_dipilih.append({
                    "paket": p,
                    "peserta": peserta_terpilih,
                    "folder": resolve["path"] if resolve["ok"] else None,
                    "folder_info": resolve["pesan"] if resolve["ok"] else resolve["pesan"],
                    "folder_ok": resolve["ok"],
                })

        if not _kl_paket_dipilih:
            st.info("← Centang paket dan tunggu peserta dimuat.")
        else:
            # Tampilkan status folder tiap paket
            _kl_semua_folder_ok = True
            for item in _kl_paket_dipilih:
                p = item["paket"]
                fc1, fc2 = st.columns([4, 1])
                with fc1:
                    if item["folder_ok"]:
                        st.success(f"📁 **{p['kode']}** → `...\\{item['folder_info']}\\1. Dokumen Kualifikasi`")
                    else:
                        st.error(f"❌ **{p['kode']}** — {item['folder_info']}")
                        _kl_semua_folder_ok = False
                with fc2:
                    if item["folder_ok"] and st.button("📂", key=f"kl_open_{p['kode']}", help="Buka folder", use_container_width=True):
                        os.startfile(item["folder"])

                n_ps = len(item["peserta"])
                st.caption(f"  → {n_ps} peserta dipilih" if n_ps else "  → ⚠️ Tidak ada peserta dipilih")

            st.divider()

            # Hitung total peserta
            _kl_total_semua = sum(len(item["peserta"]) for item in _kl_paket_dipilih)
            _kl_total_paket = len(_kl_paket_dipilih)

            # ── Opsi aksi ──────────────────────────────────────────────────────
            _kl_do_download = st.checkbox("⬇️ Download dokumen kualifikasi", value=True, key="kl_opt_download")
            _kl_do_kk = st.checkbox("📋 Parse & simpan KK Evaluasi ke Supabase", value=True, key="kl_opt_kk")

            _kl_btn_label = []
            if _kl_do_download: _kl_btn_label.append("Download")
            if _kl_do_kk: _kl_btn_label.append("Parse KK")
            _kl_btn_text = " + ".join(_kl_btn_label) if _kl_btn_label else "Pilih minimal satu aksi"

            _kl_disabled = (not _kl_btn_label) or (_kl_do_download and not _kl_semua_folder_ok) or (_kl_total_semua == 0)
            if not _kl_semua_folder_ok and _kl_do_download:
                st.warning("⚠️ Ada paket yang foldernya belum ditemukan — buat folder di Tab 0 terlebih dahulu.")

            st.divider()

            if st.button(
                f"▶ Jalankan: {_kl_btn_text} — {_kl_total_paket} paket, {_kl_total_semua} peserta",
                key="kl_jalankan",
                type="primary",
                use_container_width=True,
                disabled=_kl_disabled,
            ):
                log_area = st.empty()
                log_lines = []

                def _log_cb(msg):
                    log_lines.append(msg)
                    log_area.code("\n".join(log_lines[-30:]))

                progress = st.progress(0, text="Memulai...")
                _kl_total_steps = _kl_total_paket * (2 if (_kl_do_download and _kl_do_kk) else 1)
                _kl_step = 0

                for item in _kl_paket_dipilih:
                    p = item["paket"]
                    folder_out = item["folder"]
                    peserta_list = item["peserta"]
                    kode_tender = p["kode"]
                    n_ps = len(peserta_list)

                    _log_cb(f"=== Paket {kode_tender}: {p['nama'][:50]} ({n_ps} peserta) ===")

                    # ── Download dokumen ───────────────────────────────────────
                    if _kl_do_download and folder_out:
                        kualifikasi_engine.save_last_dir(folder_out)
                        for i, ps in enumerate(peserta_list):
                            progress.progress(
                                _kl_step / _kl_total_steps + (i / n_ps) / _kl_total_steps * (0.5 if _kl_do_kk else 1.0),
                                text=f"[{kode_tender}] Download {i+1}/{n_ps}: {ps['nama'][:35]}...",
                            )
                            kualifikasi_engine.download_kualifikasi_peserta(
                                peserta=ps,
                                folder_output=folder_out,
                                urutan=i + 1,
                                total_peserta=n_ps,
                                progress_cb=_log_cb,
                            )
                        _log_cb(f"--- [{kode_tender}] Download selesai ---")
                        _kl_step += 1

                    # ── Parse & simpan KK Evaluasi ─────────────────────────────
                    if _kl_do_kk:
                        _log_cb(f"--- [{kode_tender}] Parse KK Evaluasi ---")
                        semua_data = []
                        for i, ps in enumerate(peserta_list):
                            progress.progress(
                                _kl_step / _kl_total_steps + (i / n_ps) / _kl_total_steps,
                                text=f"[{kode_tender}] Parse KK {i+1}/{n_ps}: {ps['nama'][:35]}...",
                            )
                            slug = re.sub(r'[\\/:*?"<>|]', "", ps["nama"]).strip()[:80]
                            folder_p = os.path.join(folder_out or "", f"{i+1}. {slug}")
                            data_p = kualifikasi_parser.parse_peserta_lengkap(
                                kualifikasi_id=ps["kualifikasi_id"],
                                folder_peserta=folder_p,
                                progress_cb=_log_cb,
                            )
                            if data_p.get("skp_berbeda"):
                                _log_cb(f"  ⚠️ {ps['nama']}: SKP berbeda")
                            semua_data.append(data_p)

                        try:
                            from config import sb as _sb_kk
                            from datetime import datetime, timezone
                            _db_kk = _sb_kk()
                            rows = []
                            for i, d in enumerate(semua_data):
                                pgl = d.get("pengalaman", [])
                                p1 = pgl[0] if len(pgl) > 0 else {}
                                p2 = pgl[1] if len(pgl) > 1 else {}
                                pemilik = d.get("pemilik", [])
                                akta_p = d.get("akta_pendirian", {})
                                akta_k = d.get("akta_perubahan", {})
                                rows.append({
                                    "kode_tender": kode_tender,
                                    "urutan": i + 1,
                                    "nama": d.get("nama"),
                                    "npwp": kk_evaluasi_engine._format_npwp(d.get("npwp", "")),
                                    "nib_nomor": d.get("nib_nomor"),
                                    "nib_berlaku": d.get("nib_berlaku"),
                                    "ss_nomor": d.get("ss_nomor"),
                                    "ss_berlaku": d.get("ss_berlaku"),
                                    "ss_terverifikasi": d.get("ss_terverifikasi"),
                                    "sbu_nomor": d.get("sbu_nomor"),
                                    "sbu_berlaku": d.get("sbu_berlaku"),
                                    "sbu_kualifikasi": d.get("sbu_kualifikasi"),
                                    "sbu_klasifikasi": d.get("sbu_klasifikasi"),
                                    "sbu_subklas_label": d.get("sbu_subklas_label"),
                                    "pgl1_nama": p1.get("nama"),
                                    "pgl1_instansi": p1.get("instansi"),
                                    "pgl1_nilai": p1.get("nilai"),
                                    "pgl1_tanggal": (f"{p1.get('tgl_mulai','')} s/d {p1.get('tgl_selesai','')}"
                                                     if p1.get("tgl_mulai") else p1.get("tgl_selesai", "")),
                                    "pgl1_nomor": p1.get("nomor"),
                                    "pgl2_nama": p2.get("nama"),
                                    "pgl2_instansi": p2.get("instansi"),
                                    "pgl2_nilai": p2.get("nilai"),
                                    "pgl2_tanggal": (f"{p2.get('tgl_mulai','')} s/d {p2.get('tgl_selesai','')}"
                                                     if p2.get("tgl_mulai") else p2.get("tgl_selesai", "")),
                                    "pgl2_nomor": p2.get("nomor"),
                                    "skp": d.get("skp"),
                                    "skp_catatan": d.get("skp_catatan"),
                                    "skp_berbeda": bool(d.get("skp_berbeda")),
                                    "kswp_status": d.get("kswp_status"),
                                    "akta_p_nomor": akta_p.get("nomor"),
                                    "akta_p_tanggal": akta_p.get("tanggal"),
                                    "akta_p_notaris": akta_p.get("notaris"),
                                    "akta_k_nomor": akta_k.get("nomor"),
                                    "akta_k_tanggal": akta_k.get("tanggal"),
                                    "akta_k_notaris": akta_k.get("notaris"),
                                    "pemilik_1": pemilik[0] if len(pemilik) > 0 else None,
                                    "pemilik_2": pemilik[1] if len(pemilik) > 1 else None,
                                    "pemilik_3": pemilik[2] if len(pemilik) > 2 else None,
                                    "pemilik_4": pemilik[3] if len(pemilik) > 3 else None,
                                    "kinerja_ada": bool(d.get("kinerja_ada")),
                                    "kinerja_nilai": d.get("kinerja_nilai"),
                                    "kinerja_kategori": d.get("kinerja_kategori"),
                                    "updated_at": datetime.now(timezone.utc).isoformat(),
                                })
                            _db_kk.table("kk_evaluasi_peserta").upsert(rows).execute()
                            _log_cb(f"✅ [{kode_tender}] {len(rows)} peserta tersimpan ke Supabase.")

                            # Harga Penawaran — scrape hanya peserta dari KK Evaluasi (presisi)
                            try:
                                import penawaran_engine
                                _hp_peserta = [{"peserta_id": ps.get("kualifikasi_id", ""), "nama_peserta": ps.get("nama", "")}
                                               for ps in peserta_list if ps.get("kualifikasi_id")]
                                hasil_hp = penawaran_engine.scrape_dan_upsert_semua(
                                    kode_tender, progress_cb=_log_cb, peserta_override=_hp_peserta or None)
                                _log_cb(f"✅ [{kode_tender}] HP: {hasil_hp['peserta']} peserta, {hasil_hp['items']} item"
                                        if hasil_hp["peserta"] > 0 else f"⚠️ [{kode_tender}] HP: belum ada penawaran")
                            except Exception as e_hp:
                                _log_cb(f"⚠️ [{kode_tender}] HP error: {e_hp}")

                            try:
                                import identitas_engine
                                _po = [{"peserta_id": ps.get("kualifikasi_id", ""), "nama_peserta": ps.get("nama", "")}
                                       for ps in peserta_list if ps.get("kualifikasi_id")]
                                hasil_id = identitas_engine.scrape_dan_upsert_semua(kode_tender, progress_cb=_log_cb, peserta_override=_po or None)
                                _log_cb(f"✅ [{kode_tender}] Identitas: {hasil_id['peserta']} peserta"
                                        if hasil_id["peserta"] > 0 else f"⚠️ [{kode_tender}] Identitas: kosong")
                            except Exception as e_id:
                                _log_cb(f"⚠️ [{kode_tender}] Identitas error: {e_id}")

                        except Exception as e_sb:
                            _log_cb(f"ERROR [{kode_tender}] Supabase: {e_sb}")

                        _kl_step += 1

                progress.progress(1.0, text="Selesai!")
                _parts = []
                if _kl_do_download: _parts.append("dokumen didownload")
                if _kl_do_kk: _parts.append("KK Evaluasi tersimpan")
                st.success(f"✅ Selesai: {' + '.join(_parts)} — {_kl_total_paket} paket, {_kl_total_semua} peserta. Buka Excel → **Muat KK Evaluasi**, **Muat Harga Penawaran**, **Muat Input BA**.")

# ============================================================
# Tab 7: Dokumen Penawaran — Pindah File ke Folder Paket
# ============================================================

with tab_apendo:
    import pindah_penawaran_engine as _pe

    st.markdown("### Dokumen Penawaran")
    st.caption(
        "Scan otomatis hasil decrypt Apendo di `D:\\data\\biddings`, "
        "cocokkan dengan paket + peserta di Supabase, lalu pindah ke folder paket."
    )

    _dp_col_scan, _ = st.columns([1, 3])
    with _dp_col_scan:
        if st.button("🔍 Scan Apendo", key="dp_scan", use_container_width=True):
            st.session_state.pop("dp_scan_result", None)
            st.rerun()

    if "dp_scan_result" not in st.session_state:
        with st.spinner("Scanning D:\\data\\biddings ..."):
            _raw = _pe.scan_apendo()
            if _raw:
                _enriched = _pe.lookup_supabase(_raw)
            else:
                _enriched = []
            st.session_state["dp_scan_result"] = _enriched

    _dp_items = st.session_state.get("dp_scan_result", [])

    if "dp_notif" in st.session_state:
        st.success(st.session_state.pop("dp_notif"))

    if not _dp_items:
        st.info("Tidak ada data di `D:\\data\\biddings`. Download dulu via Apendo.")
    else:
        # Hitung total peserta per paket untuk resolve_dest
        _dp_total: dict[str, int] = {}
        for _it in _dp_items:
            _dp_total[_it["kode_tender"]] = _dp_total.get(_it["kode_tender"], 0) + 1

        # Kelompokkan per paket untuk tampilan
        _dp_by_paket: dict[str, list] = {}
        for _it in _dp_items:
            _dp_by_paket.setdefault(_it["kode_tender"], []).append(_it)

        for _kt, _peserta_list in _dp_by_paket.items():
            _folder_dibuat = _peserta_list[0].get("folder_dibuat", "")
            _paket_label = _folder_dibuat if _folder_dibuat else _peserta_list[0].get("nama_tender", _kt)
            _folder_paket = _peserta_list[0].get("folder_paket", "")
            _folder_ada = bool(_folder_paket and os.path.isdir(_folder_paket))

            with st.expander(f"**{_paket_label}** ({len(_peserta_list)} peserta)", expanded=True):
                if not _folder_ada:
                    st.warning("Folder paket belum ditemukan — buat folder di Tab 0 dulu.")
                else:
                    st.text(f"📂 {_folder_paket}")

                for _ps in _peserta_list:
                    _nama = _ps["nama_perusahaan"]
                    _n_teknis = len(_pe._collect_files(_ps["path_teknis"])) if _ps.get("path_teknis") else 0
                    _n_harga  = len(_pe._collect_files(_ps["path_harga"]))  if _ps.get("path_harga")  else 0
                    st.markdown(f"**Peserta {_ps['urutan']} = {_nama}** — {_n_teknis} file teknis, {_n_harga} file harga")

                if _folder_ada:
                    _dp_run_key = f"dp_run_{_kt}"
                    if st.button(
                        f"🚚 Pindahkan & Gabung PDF — {_paket_label[:40]}",
                        key=_dp_run_key,
                        type="primary",
                        use_container_width=True,
                    ):
                        _log_msgs = []
                        _semua_sukses, _semua_gagal = [], []
                        _dest_dirs = []
                        for _ps in _peserta_list:
                            _dest = _pe.resolve_dest(_ps, _dp_total)
                            _dest_dirs.append(_dest)
                            _hasil = _pe.pindah_dan_gabung(_ps, _dest, log=_log_msgs.append)
                            _semua_sukses.extend(_hasil["sukses"])
                            _semua_gagal.extend(_hasil["gagal"])
                        if _semua_sukses:
                            _notif = (
                                f"✅ {len(_semua_sukses)} file dipindah dari **{_paket_label}** "
                                f"→ `{_dest_dirs[0]}`"
                            )
                            st.session_state["dp_notif"] = _notif
                            st.session_state.pop("dp_scan_result", None)
                            st.rerun()
                        for _msg in _log_msgs:
                            st.caption(_msg)
                        if _semua_gagal:
                            st.error(f"❌ {len(_semua_gagal)} gagal:")
                            for _e in _semua_gagal:
                                st.caption(f"• {_e}")
