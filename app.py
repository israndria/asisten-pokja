"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, date
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

    # ══════════════════════════════════════════
    # KOLOM KANAN — 2. Buat Folder Paket
    # ══════════════════════════════════════════
    with _col_kanan:
        st.markdown("#### 2. Buat Folder Paket")
        st.caption("Buat satu folder atau semua sekaligus.")

        _nomor_terakhir = max((int(_r.get("nomor_urut") or 0) for _r in _draft_rows), default=0)
        _nomor_berikutnya = _nomor_terakhir + 1

        # Filter tahun untuk dropdown (sama dengan filter Section 3)
        _tahun_dd_options = ["Semua"] + [str(t) for t in range(datetime.now().year, datetime.now().year - 5, -1)] + ["Belum Folder", "Sudah Folder"]
        _tahun_dd = st.selectbox("Filter tahun:", _tahun_dd_options, key="filter_dd_tahun")

        def _dd_match(r):
            kt = str(r.get("kode_tender", ""))
            if kt.startswith("_err_") or not r.get("nama_tender"):
                return False
            if _tahun_dd.isdigit():
                return str(r.get("nomor_pp") or "").endswith(_tahun_dd)
            if _tahun_dd == "Belum Folder":
                return not bool(r.get("folder_dibuat"))
            if _tahun_dd == "Sudah Folder":
                return bool(r.get("folder_dibuat"))
            return True

        # Dropdown pilih paket (nama penuh, tanpa potong)
        _opsi_map = {"(input manual)": None}
        for _r in _draft_rows:
            if not _dd_match(_r):
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

        # Tombol download dokumen mandiri (untuk folder yang sudah ada)
        if _folder_ada and _row_terpilih:
            _kt2 = _row_terpilih.get("kode_tender", "")
            _ip2 = str(_row_terpilih.get("id_pesan", ""))
            if _kt2 and _ip2:
                if st.button("📦 Download Dokumen SPSE + Lampiran", use_container_width=True, key="btn_dl_dokumen_saja"):
                    _dl_msgs2 = []
                    def _dl_cb2(msg):
                        _dl_msgs2.append(msg)  # thread-safe, no st calls
                    with st.spinner("Mengunduh dokumen + membuat Draft PDF..."):
                        _dl2 = inbox_engine.download_dokumen_paket(_kt2, _ip2, _target_path, kode_pokja=_row_terpilih.get("kode_pokja",""), progress_cb=_dl_cb2)
                    st.success(
                        f"✅ {len(_dl2['ok'])} file, ⏭ {len(_dl2['skip'])} sudah ada, ❌ {len(_dl2['error'])} gagal"
                        + (f" | 📎 {_os.path.basename(_dl2['draft_pdf'])}" if _dl2.get('draft_pdf') else "")
                    )
                    if _dl_msgs2:
                        with st.expander("Log download"):
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
                                    "folder_dibuat": _nama_folder,
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
                                def _dl_cb(msg):
                                    _dl_msgs.append(msg)  # thread-safe, no st calls
                                with st.spinner("Mengunduh dokumen + membuat Draft PDF..."):
                                    _dl_hasil = inbox_engine.download_dokumen_paket(
                                        _kt, _ip, _target_path,
                                        kode_pokja=_row_terpilih.get("kode_pokja",""),
                                        progress_cb=_dl_cb
                                    )
                                st.success(
                                    f"Download selesai — ✅ {len(_dl_hasil['ok'])} file, "
                                    f"⏭ {len(_dl_hasil['skip'])} sudah ada, "
                                    f"❌ {len(_dl_hasil['error'])} gagal"
                                    + (f" | 📎 {_os.path.basename(_dl_hasil['draft_pdf'])}" if _dl_hasil.get('draft_pdf') else "")
                                )
                                if _dl_msgs:
                                    with st.expander("Log download"):
                                        st.text("\n".join(_dl_msgs))
                                if _dl_hasil["error"]:
                                    with st.expander("Detail error download"):
                                        for _e3 in _dl_hasil["error"]:
                                            st.error(_e3)
                        st.rerun()
                    else:
                        st.error("Setup gagal.")
                        st.code(_res.stdout + "\n" + _res.stderr)
                except _sp.TimeoutExpired:
                    st.error("Timeout.")

        # Bulk Create
        st.divider()
        _bulk_kandidat = [_r for _r in _draft_rows if not _r.get("folder_dibuat") and _r.get("nama_tender")
                          and not str(_r.get("kode_tender","")).startswith("_err_")]
        if _bulk_kandidat:
            _max_urut = max((int(_r.get("nomor_urut") or 0) for _r in _draft_rows), default=0)
            _bulk_plan, _ctr = [], _max_urut
            for _r in sorted(_bulk_kandidat, key=lambda x: x.get("diambil_pada") or ""):
                _n = int(_r["nomor_urut"]) if _r.get("nomor_urut") else (_ctr := _ctr + 1) and _ctr
                _bulk_plan.append({
                    "kode_tender": _r["kode_tender"],
                    "nomor_urut": _n,
                    "nama_folder": f"{_n}. {str(_r.get('nama_tender','')).strip()} - Pokja {str(_r.get('kode_pokja','')).strip()}",
                })
            with st.expander(f"📋 Preview {len(_bulk_plan)} folder yang akan dibuat"):
                for _bp in _bulk_plan:
                    st.caption(_bp["nama_folder"])
            if st.button(f"📁 Buat Semua ({len(_bulk_plan)} folder)", type="secondary",
                         use_container_width=True, key="btn_bulk_buat"):
                from datetime import timezone as _tz2
                _bp2 = st.progress(0.0)
                _bs  = st.empty()
                _ok, _fail = 0, 0
                for _i, _bp in enumerate(_bulk_plan):
                    _bp2.progress((_i+1)/len(_bulk_plan))
                    _bs.info(f"[{_i+1}/{len(_bulk_plan)}] {_bp['nama_folder'][:60]}")
                    try:
                        _r2 = _sp.run([_PY, _SCRIPT, _bp["nama_folder"]],
                                      capture_output=True, text=True, timeout=60,
                                      creationflags=_NO_WIN)
                        if _r2.returncode == 0:
                            _ok += 1
                            try:
                                inbox_engine._sb().table("draft_paket").update({
                                    "nomor_urut": _bp["nomor_urut"],
                                    "folder_dibuat": _bp["nama_folder"],
                                    "folder_dibuat_pada": datetime.now(_tz2.utc).isoformat(),
                                }).eq("kode_tender", _bp["kode_tender"]).execute()
                            except Exception:
                                pass
                        else:
                            _fail += 1
                    except _sp.TimeoutExpired:
                        _fail += 1
                _bs.success(f"Selesai — {_ok} berhasil, {_fail} gagal.")
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
    else:
        st.info("Belum ada data. Klik 'Update Inbox' untuk mulai.")


# ============================================================
# Tab Setup Paket: LDK Auto-fill + Checklist + Masa Berlaku
# ============================================================

with tab_setup:
    # ── Layout 2 kolom: kiri = pilih paket + upload dokpil, kanan = konfigurasi ─
    _sp_col_kiri, _sp_col_kanan = st.columns([2, 3])

    with _sp_col_kiri:
        st.markdown("### 1. Ambil Data Paket")
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
        st.markdown("### 1. Ambil Data Paket")
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
                            f"**{p['kode']}** — {p['nama']}",
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
        st.markdown("### 1. Ambil Data Paket")
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
                            f"**{p['kode']}** — {p['nama']}",
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
        st.markdown("### 1. Ambil Data Paket")
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
                    st.warning("⚠️ Tidak ada paket ditemukan.")
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
                        key_lamp_bytes = f"kp_lamp_bytes_{p['id_lelang']}"
                        key_lamp_nama  = f"kp_lamp_nama_{p['id_lelang']}"

                        col_chk, col_lamp = st.columns([3, 2])
                        with col_chk:
                            checked = st.checkbox(
                                f"**{p['kode']}** — {p['nama']}",
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
                                col_gen, col_up = st.columns(2)
                                with col_gen:
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
                                with col_up:
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
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket.")

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
        if st.button("🔍 Ambil Paket Draft", key="r1_ba_fetch_draft", use_container_width=True):
            with st.spinner("Mengambil daftar paket..."):
                _ba_result = kirimpesan_engine.fetch_paket_draft()
            st.session_state["r1_ba_paket_draft"] = _ba_result
            for _k in list(st.session_state.keys()):
                if _k.startswith("r1_ba_chk_"):
                    del st.session_state[_k]

        ba_selected = []
        if "r1_ba_paket_draft" in st.session_state:
            _ba_r = st.session_state["r1_ba_paket_draft"]
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

        st.markdown("### 1. Ambil Data Paket")


        col_bafetch, col_baall, col_banone = st.columns([3, 1, 1])

        with col_bafetch:

            if st.button("🔍 Ambil Data Paket", key="ba5_fetch_draft", use_container_width=True):

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

                    st.warning("⚠️ Tidak ada paket ditemukan.")

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
                        key_chk = f'ba_chk_{p["id_lelang"]}'
                        _chk_col, _super_col = st.columns([3, 1])
                        with _chk_col:
                            checked = st.checkbox(
                                f"**{p['kode']}** — {p['nama']}",
                                value=st.session_state.get(key_chk, True), key=key_chk,
                            )
                        with _super_col:
                            if st.button('🚀', key=f'btn_super_{p["id_lelang"]}', use_container_width=True, help='Cetak & Upload SEMUA BA untuk paket ini'):
                                st.session_state["ba_auto_target"] = "SEMUA"
                                st.session_state["ba_super_paket"] = [p]
                        if checked:
                            ba_selected.append(p)

                    st.caption(f"**{len(ba_selected)}** dari **{len(paket_list_ba)}** paket dipilih")

        else:

            st.info("Klik tombol di atas untuk mengambil daftar paket.")

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
    _kl_col1, _kl_col2 = st.columns([2, 3])

    with _kl_col1:
        st.markdown("### 1. Pilih Paket")

        _kl_fetch_col, _kl_ref_col = st.columns([3, 1])
        with _kl_fetch_col:
            if st.button("🔍 Ambil Data Paket", key="kl_fetch_draft", use_container_width=True):
                with st.spinner("Mengambil daftar paket..."):
                    _kl_draft = kirimpesan_engine.fetch_paket_aktif()
                st.session_state["kl_paket_draft"] = _kl_draft
                st.session_state["kl_paket_aktif"] = None
                st.session_state["kl_peserta"] = None
                for k in list(st.session_state.keys()):
                    if k.startswith("kl_cek_"):
                        del st.session_state[k]
        with _kl_ref_col:
            if st.button("🔄", key="kl_refresh", use_container_width=True, help="Refresh ulang daftar paket"):
                st.session_state.pop("kl_paket_draft", None)
                st.session_state.pop("kl_paket_aktif", None)
                st.session_state.pop("kl_peserta", None)
                st.rerun()

        if "kl_paket_draft" in st.session_state:
            _kl_draft = st.session_state["kl_paket_draft"]
            if not _kl_draft["sukses"]:
                st.error(f"❌ {_kl_draft['pesan']}")
            else:
                _kl_paket_list = _kl_draft.get("paket", [])
                if not _kl_paket_list:
                    st.warning("⚠️ Tidak ada paket aktif ditemukan.")
                else:
                    st.caption(f"{len(_kl_paket_list)} paket aktif — pilih satu:")
                    for p in _kl_paket_list:
                        _kl_chk_key = f"kl_chk_{p['kode']}"
                        _checked = st.checkbox(
                            f"**{p['kode']}**  \n{p['nama'][:60]}  \n_{p.get('status', '')}_",
                            key=_kl_chk_key,
                            value=st.session_state.get(_kl_chk_key, False),
                        )
                        if _checked:
                            _prev = st.session_state.get("kl_paket_aktif")
                            if _prev and _prev["kode"] != p["kode"]:
                                # uncheck paket sebelumnya — hanya 1 aktif
                                st.session_state[f"kl_chk_{_prev['kode']}"] = False
                            st.session_state["kl_paket_aktif"] = p
        else:
            st.info("Klik tombol di atas untuk mengambil daftar paket.")

        with st.expander("🔗 Atau masukkan URL manual"):
            url_penawaran = st.text_input(
                "URL halaman /penawaran",
                key="kl_url_penawaran",
                placeholder="https://spse.inaproc.id/tapinkab/peserta/10096884000/penawaran",
                label_visibility="collapsed",
            )
            if st.button("Fetch via URL", key="kl_fetch_url", use_container_width=True):
                if not url_penawaran.strip():
                    st.warning("Masukkan URL /penawaran terlebih dahulu.")
                else:
                    with st.spinner("Mengambil daftar peserta..."):
                        res = kualifikasi_engine.fetch_peserta(url_penawaran.strip())
                    st.session_state["kl_peserta"] = res
                    st.session_state["kl_paket_aktif"] = None
                    for k in list(st.session_state.keys()):
                        if k.startswith("kl_cek_"):
                            del st.session_state[k]

        # ── Fetch peserta dari paket terpilih ──────────────────────────────
        _kl_paket_aktif = st.session_state.get("kl_paket_aktif")
        if _kl_paket_aktif:
            st.markdown(f"### 2. Peserta — {_kl_paket_aktif['kode']}")
            if st.button("🔍 Fetch Peserta", key="kl_fetch", use_container_width=True):
                with st.spinner("Mengambil daftar peserta..."):
                    res = kualifikasi_engine.fetch_peserta_by_kode(_kl_paket_aktif["kode"])
                st.session_state["kl_peserta"] = res
                for k in list(st.session_state.keys()):
                    if k.startswith("kl_cek_"):
                        del st.session_state[k]

        kl_res = st.session_state.get("kl_peserta")
        if kl_res:
            if not kl_res["ok"]:
                st.error(kl_res["pesan"])
            else:
                st.success(kl_res["pesan"])
                _kl_total = len(kl_res["peserta"])

                col_all, col_none = st.columns(2)
                with col_all:
                    if st.button("✅ Semua", key="kl_all", use_container_width=True):
                        for p in kl_res["peserta"]:
                            st.session_state[f"kl_cek_{p['kualifikasi_id']}"] = True
                        st.rerun()
                with col_none:
                    if st.button("⬜ Hapus", key="kl_none", use_container_width=True):
                        for p in kl_res["peserta"]:
                            st.session_state[f"kl_cek_{p['kualifikasi_id']}"] = False
                        st.rerun()

                for i, p in enumerate(kl_res["peserta"], 1):
                    st.checkbox(
                        f"{i}. {p['nama']}",
                        key=f"kl_cek_{p['kualifikasi_id']}",
                        value=st.session_state.get(f"kl_cek_{p['kualifikasi_id']}", True),
                    )

    with _kl_col2:
        st.markdown("### 3. Folder & Download")

        # ── Resolve folder otomatis dari Supabase ──────────────────────────
        _kl_paket_aktif2 = st.session_state.get("kl_paket_aktif")
        _kl_folder_auto = None
        _kl_folder_info = ""

        if _kl_paket_aktif2:
            _kl_resolve = kualifikasi_engine.resolve_folder_paket(_kl_paket_aktif2["kode"])
            if _kl_resolve["ok"]:
                _kl_folder_auto = _kl_resolve["path"]
                _kl_folder_info = _kl_resolve["pesan"]
                st.success(f"📁 **Auto:** `...\\{_kl_folder_info}\\Dokumen Evaluasi`")
            else:
                st.warning(f"⚠️ Folder auto tidak ditemukan: {_kl_resolve['pesan']}")

        # ── Fallback folder manual ─────────────────────────────────────────
        with st.expander("📂 Override folder manual" if _kl_folder_auto else "📂 Pilih folder manual"):
            _kl_default_dir = kualifikasi_engine.get_last_dir()
            kl_folder_manual = st.text_input(
                "Path folder tujuan",
                key="kl_folder",
                value=st.session_state.get("kl_folder_val", _kl_default_dir),
                label_visibility="collapsed",
            )
            if st.button("📁 Browse", key="kl_browse", use_container_width=True):
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()
                    root.wm_attributes("-topmost", True)
                    selected = filedialog.askdirectory(
                        initialdir=st.session_state.get("kl_folder_val", _kl_default_dir),
                        title="Pilih Folder Tujuan",
                    )
                    root.destroy()
                    if selected:
                        st.session_state["kl_folder_val"] = selected.replace("/", "\\")
                        st.rerun()
                except Exception as e:
                    st.warning(f"Dialog tidak bisa dibuka: {e} — ketik path manual.")

        # Folder efektif yang dipakai
        _kl_folder_efektif = _kl_folder_auto or st.session_state.get("kl_folder_val", "")

        if _kl_folder_efektif and os.path.isdir(_kl_folder_efektif):
            if st.button("📂 Buka Folder", key="kl_open_folder", use_container_width=True):
                os.startfile(_kl_folder_efektif)

        # ── Preview peserta terpilih & tombol download ─────────────────────
        kl_res2 = st.session_state.get("kl_peserta")
        if kl_res2 and kl_res2["ok"]:
            _kl_total2 = len(kl_res2["peserta"])
            kl_selected = [
                p for p in kl_res2["peserta"]
                if st.session_state.get(f"kl_cek_{p['kualifikasi_id']}", True)
            ]

            if kl_selected:
                st.markdown(f"**{len(kl_selected)} peserta dipilih** (total {_kl_total2}):")
                for i, p in enumerate(kl_selected, 1):
                    if _kl_total2 >= 2:
                        st.caption(f"{i}. {p['nama']} → subfolder `{i}. {p['nama'][:30]}/`")
                    else:
                        st.caption(f"1. {p['nama']} → langsung di `Dokumen Evaluasi/`")

                st.divider()

                if st.button(
                    f"⬇️ Download {len(kl_selected)} Dokumen Kualifikasi",
                    key="kl_download",
                    type="primary",
                    use_container_width=True,
                    disabled=not _kl_folder_efektif,
                ):
                    if not _kl_folder_efektif:
                        st.error("Folder tidak ditemukan — pilih folder manual.")
                    else:
                        kualifikasi_engine.save_last_dir(_kl_folder_efektif)

                        log_area = st.empty()
                        log_lines = []

                        def _log_cb(msg):
                            log_lines.append(msg)
                            log_area.code("\n".join(log_lines[-20:]))

                        progress = st.progress(0, text="Memulai download...")
                        hasil_kl = []

                        for i, peserta in enumerate(kl_selected):
                            progress.progress(
                                i / len(kl_selected),
                                text=f"Downloading {peserta['nama']} ({i+1}/{len(kl_selected)})...",
                            )
                            res_dl = kualifikasi_engine.download_kualifikasi_peserta(
                                peserta=peserta,
                                folder_output=_kl_folder_efektif,
                                urutan=i + 1,
                                total_peserta=_kl_total2,
                                progress_cb=_log_cb,
                            )
                            hasil_kl.append({**peserta, **res_dl})

                        progress.progress(1.0, text="Selesai!")

                        sukses = [h for h in hasil_kl if h["ok"]]
                        gagal = [h for h in hasil_kl if not h["ok"]]

                        if sukses:
                            st.success(f"✅ {len(sukses)} peserta selesai didownload ke `{_kl_folder_efektif}`")
                            for h in sukses:
                                st.caption(f"• {h['nama']}: {h['pesan']}")
                        if gagal:
                            st.error(f"❌ {len(gagal)} gagal:")
                            for h in gagal:
                                st.caption(f"• {h['nama']}: {h['pesan']}")
            else:
                st.info("Pilih peserta di kolom kiri.")

            # ── Auto-Fill KK Evaluasi Kualifikasi ─────────────────────────────
            st.divider()
            st.markdown("### 4. Auto-Fill KK Evaluasi Kualifikasi")

            _kl_paket_kk = st.session_state.get("kl_paket_aktif")
            kl_res_kk = st.session_state.get("kl_peserta")

            if not _kl_paket_kk or not kl_res_kk or not kl_res_kk.get("ok"):
                st.info("Fetch peserta terlebih dahulu (langkah 1-2).")
            elif not _kl_folder_efektif or not os.path.isdir(_kl_folder_efektif):
                st.warning("Folder belum diketahui — resolve folder paket terlebih dahulu.")
            else:
                # Cari file Excel BA PK di folder paket (satu level di atas Dokumen Evaluasi)
                _kl_folder_paket = os.path.dirname(_kl_folder_efektif)
                _kl_excel_candidates = [
                    f for f in os.listdir(_kl_folder_paket)
                    if f.endswith(".xlsm") and "BA PK" in f
                ]

                if not _kl_excel_candidates:
                    st.warning(f"File .xlsm BA PK tidak ditemukan di `{_kl_folder_paket}`")
                else:
                    _kl_excel_path = os.path.join(_kl_folder_paket, _kl_excel_candidates[0])
                    st.caption(f"Excel: `{_kl_excel_candidates[0]}`")

                    _kl_total_kk = len(kl_res_kk["peserta"])
                    kl_selected_kk = [
                        p for p in kl_res_kk["peserta"]
                        if st.session_state.get(f"kl_cek_{p['kualifikasi_id']}", True)
                    ]

                    if st.button(
                        f"📋 Auto-Fill KK Evaluasi ({len(kl_selected_kk)} peserta)",
                        key="kl_autofill_kk",
                        type="primary",
                        use_container_width=True,
                    ):
                        log_area_kk = st.empty()
                        log_kk = []

                        def _log_kk(msg):
                            log_kk.append(msg)
                            log_area_kk.code("\n".join(log_kk[-25:]))

                        progress_kk = st.progress(0, text="Memulai parsing...")
                        semua_data_peserta = []

                        for i, peserta in enumerate(kl_selected_kk):
                            progress_kk.progress(
                                i / len(kl_selected_kk),
                                text=f"Parsing {peserta['nama']} ({i+1}/{len(kl_selected_kk)})...",
                            )
                            # Tentukan folder peserta (sama dengan logika download)
                            if _kl_total_kk >= 2:
                                import kualifikasi_engine as _kl_eng
                                slug = re.sub(r'[\\/:*?"<>|]', "", peserta["nama"]).strip()[:80]
                                folder_p = os.path.join(_kl_folder_efektif, f"{i+1}. {slug}")
                            else:
                                folder_p = _kl_folder_efektif

                            data_p = kualifikasi_parser.parse_peserta_lengkap(
                                kualifikasi_id=peserta["kualifikasi_id"],
                                folder_peserta=folder_p,
                                progress_cb=_log_kk,
                            )
                            if data_p.get("skp_berbeda"):
                                _log_kk(f"  ⚠️ {peserta['nama']}: SKP berbeda antara SPSE dan Formulir")
                            semua_data_peserta.append(data_p)

                        progress_kk.progress(0.8, text="Mengisi Excel...")
                        _log_kk("Mengisi sheet KK Evaluasi Kualifikasi...")

                        res_fill = kk_evaluasi_engine.fill_kk_evaluasi(
                            excel_path=_kl_excel_path,
                            semua_peserta=semua_data_peserta,
                            progress_cb=_log_kk,
                        )

                        progress_kk.progress(1.0, text="Selesai!")

                        if res_fill["ok"]:
                            st.success(f"✅ {res_fill['pesan']}")
                            peringatan_skp = [
                                d for d in semua_data_peserta if d.get("skp_berbeda")
                            ]
                            if peringatan_skp:
                                st.warning(
                                    "⚠️ SKP berbeda antara SPSE preview dan Formulir Isian pada: "
                                    + ", ".join(d.get("nama", "?") for d in peringatan_skp)
                                    + " — harap cek manual."
                                )
                        else:
                            st.error(f"❌ {res_fill['pesan']}")

        else:
            st.info("Fetch peserta terlebih dahulu dari kolom kiri.")

# ============================================================
# Tab 7: Dokumen Penawaran — Pindah File ke Folder Paket
# ============================================================

_DP_DEFAULT_SRC = r"D:\data"
_DP_SUBFOLDER_TEKNIS = "teknis"
_DP_SUBFOLDER_HARGA  = "harga"
_DP_DEST_SUBFOLDER   = "Dokumen Penawaran"


def _dp_list_files(folder: str, subfolders: list[str]) -> list[dict]:
    """Kumpulkan file dari subfolder teknis/harga di folder sumber."""
    hasil = []
    for sub in subfolders:
        path = os.path.join(folder, sub)
        if not os.path.isdir(path):
            continue
        for fname in os.listdir(path):
            fpath = os.path.join(path, fname)
            if os.path.isfile(fpath):
                hasil.append({
                    "nama": fname,
                    "sumber": fpath,
                    "subfolder": sub,
                    "ukuran": os.path.getsize(fpath),
                })
    return hasil


def _dp_pindah(files: list[dict], dest_dir: str) -> dict:
    """Pindah (move) file ke dest_dir. Buat folder jika belum ada."""
    import shutil
    os.makedirs(dest_dir, exist_ok=True)
    sukses, gagal = [], []
    for f in files:
        tujuan = os.path.join(dest_dir, f["nama"])
        try:
            shutil.move(f["sumber"], tujuan)
            sukses.append(f["nama"])
        except Exception as e:
            gagal.append(f"{f['nama']}: {e}")
    return {"sukses": sukses, "gagal": gagal}


with tab_apendo:
    st.markdown("### Pindah Dokumen Penawaran ke Folder Paket")
    st.caption(
        "Setelah download manual via Apendo, gunakan fitur ini untuk memindahkan "
        "file dari subfolder **teknis** dan **harga** ke folder **Dokumen Penawaran** "
        "di dalam folder paket yang dipilih."
    )

    _dp_col_kiri, _dp_col_kanan = st.columns([2, 3])

    with _dp_col_kiri:
        st.markdown("#### 1. Folder Sumber (Hasil Download)")

        dp_src = st.text_input(
            "Folder sumber",
            key="dp_src",
            value=st.session_state.get("dp_src_val", _DP_DEFAULT_SRC),
            label_visibility="collapsed",
            placeholder=r"D:\data",
        )
        st.caption(f"Default: `{_DP_DEFAULT_SRC}` — akan dicari subfolder `teknis/` dan `harga/`")

        _dp_browse_col, _dp_open_col = st.columns(2)
        with _dp_browse_col:
            if st.button("📁 Pilih Folder", key="dp_browse_src", use_container_width=True):
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()
                    root.wm_attributes("-topmost", True)
                    sel = filedialog.askdirectory(
                        initialdir=st.session_state.get("dp_src_val", _DP_DEFAULT_SRC),
                        title="Pilih Folder Hasil Download Apendo",
                    )
                    root.destroy()
                    if sel:
                        st.session_state["dp_src_val"] = sel.replace("/", "\\")
                        st.rerun()
                except Exception as e:
                    st.warning(f"Dialog gagal: {e} — ketik path manual.")
        with _dp_open_col:
            _dp_src_now = st.session_state.get("dp_src_val", _DP_DEFAULT_SRC) or dp_src
            if st.button(
                "📂 Buka",
                key="dp_open_src",
                use_container_width=True,
                disabled=not (_dp_src_now and os.path.isdir(_dp_src_now)),
            ):
                os.startfile(_dp_src_now)

        # Preview file yang akan dipindah
        _dp_src_now = st.session_state.get("dp_src_val", _DP_DEFAULT_SRC) or dp_src
        if _dp_src_now and os.path.isdir(_dp_src_now):
            _dp_files = _dp_list_files(_dp_src_now, [_DP_SUBFOLDER_TEKNIS, _DP_SUBFOLDER_HARGA])
            if _dp_files:
                st.success(f"✅ {len(_dp_files)} file ditemukan:")
                for fi in _dp_files:
                    kb = fi["ukuran"] // 1024
                    st.caption(f"• [{fi['subfolder']}] {fi['nama']} ({kb} KB)")
                st.session_state["dp_files_preview"] = _dp_files
            else:
                st.warning("Tidak ada file di subfolder `teknis/` atau `harga/`.")
                st.session_state["dp_files_preview"] = []
        else:
            st.info("Masukkan folder sumber yang valid.")
            st.session_state["dp_files_preview"] = []

    with _dp_col_kanan:
        st.markdown("#### 2. Folder Paket Tujuan")

        if st.button("🔍 Ambil Daftar Paket", key="dp_fetch_paket", use_container_width=True):
            with st.spinner("Mengambil paket dari Supabase..."):
                try:
                    from config import sb as _sb_dp
                    _r = _sb_dp().table("draft_paket").select("kode_tender,nama_paket,folder_dibuat").order("nama_paket").execute()
                    st.session_state["dp_paket_list"] = _r.data or []
                except Exception as e:
                    st.error(f"Gagal fetch paket: {e}")
                    st.session_state["dp_paket_list"] = []

        dp_paket_list = st.session_state.get("dp_paket_list", [])
        if dp_paket_list:
            _dp_labels = [
                f"{p.get('nama_paket', p['kode_tender'])}"
                for p in dp_paket_list
            ]
            dp_paket_idx = st.selectbox(
                "Pilih paket tujuan",
                options=range(len(dp_paket_list)),
                format_func=lambda i: _dp_labels[i],
                key="dp_paket_idx",
                label_visibility="collapsed",
            )
            dp_paket_sel = dp_paket_list[dp_paket_idx]
            dp_folder_paket = dp_paket_sel.get("folder_dibuat", "")

            if dp_folder_paket and os.path.isdir(dp_folder_paket):
                _dp_dest = os.path.join(dp_folder_paket, _DP_DEST_SUBFOLDER)
                st.info(f"📂 Tujuan: `{_dp_dest}`")

                if st.button(
                    "📂 Buka Folder Paket",
                    key="dp_open_paket",
                    use_container_width=True,
                ):
                    os.startfile(dp_folder_paket)

                st.markdown("#### 3. Pindahkan File")

                _dp_files_ok = st.session_state.get("dp_files_preview", [])
                if not _dp_files_ok:
                    st.warning("Tidak ada file untuk dipindah — cek folder sumber di kiri.")
                else:
                    st.write(f"**{len(_dp_files_ok)} file** akan dipindah ke `Dokumen Penawaran/`")
                    if st.button(
                        "🚚 Pindahkan Sekarang",
                        key="dp_run",
                        type="primary",
                        use_container_width=True,
                    ):
                        hasil = _dp_pindah(_dp_files_ok, _dp_dest)
                        if hasil["sukses"]:
                            st.success(f"✅ {len(hasil['sukses'])} file dipindah:")
                            for nm in hasil["sukses"]:
                                st.caption(f"• {nm}")
                            # Bersihkan preview supaya tidak double-run
                            st.session_state["dp_files_preview"] = []
                        if hasil["gagal"]:
                            st.error(f"❌ {len(hasil['gagal'])} file gagal:")
                            for err in hasil["gagal"]:
                                st.caption(f"• {err}")
                        if hasil["sukses"]:
                            if st.button("📂 Buka Folder Dokumen Penawaran", key="dp_open_dest"):
                                os.startfile(_dp_dest)
            elif dp_folder_paket:
                st.error(f"Folder paket tidak ditemukan: `{dp_folder_paket}`")
            else:
                st.warning("Paket ini belum punya folder yang dibuat. Buat folder di Tab 0 dulu.")
        else:
            st.info("Klik **Ambil Daftar Paket** untuk memilih tujuan.")

        st.markdown("---")
        st.markdown("#### Atau — Ketik Path Manual")
        dp_manual = st.text_input(
            "Path folder paket tujuan (manual)",
            key="dp_manual_path",
            placeholder=r"D:\Dokumen\@ POKJA 2026\1. Pokja 086 - ...",
            label_visibility="collapsed",
        )
        if dp_manual and os.path.isdir(dp_manual):
            _dp_dest_manual = os.path.join(dp_manual, _DP_DEST_SUBFOLDER)
            st.info(f"📂 Tujuan: `{_dp_dest_manual}`")
            _dp_files_manual = st.session_state.get("dp_files_preview", [])
            if _dp_files_manual:
                if st.button(
                    "🚚 Pindahkan ke Path Manual",
                    key="dp_run_manual",
                    type="primary",
                    use_container_width=True,
                ):
                    hasil = _dp_pindah(_dp_files_manual, _dp_dest_manual)
                    if hasil["sukses"]:
                        st.success(f"✅ {len(hasil['sukses'])} file dipindah.")
                        st.session_state["dp_files_preview"] = []
                    if hasil["gagal"]:
                        st.error(f"❌ Gagal: {', '.join(hasil['gagal'])}")
        elif dp_manual:
            st.error("Path tidak ditemukan.")
