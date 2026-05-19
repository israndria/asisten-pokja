"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import pathlib
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
import parse_kak_pl
import pl_kirimpesan_engine

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
        "0️⃣ Import DPA",
        "1️⃣ Draft Paket PL",
        "2️⃣ Kirim Undangan DPP",
        "3️⃣ Buat Jadwal",
        "4️⃣ Setup Paket",
    ])

    # ── Tab 0: Import DPA ─────────────────────────────────────────────────────
    with _pl_tab0:
        import dpa_engine as _dpa

        st.markdown("### 📄 Import DPA / RKA ke Database")
        st.caption("Upload PDF DPA/RKA SKPD — ekstrak semua sub kegiatan dan rincian belanja ke Supabase.")

        _dpa_file = st.file_uploader(
            "Upload PDF DPA:",
            type=["pdf"],
            key="dpa_uploader",
            help="Format standar RKA-BELANJA SKPD Kemendagri. Kompatibel semua tahun.",
        )

        if _dpa_file:
            _dpa_bytes = _dpa_file.read()
            _dpa_nama = _dpa_file.name

            with st.spinner(f"Parsing {_dpa_nama}..."):
                _dpa_result = _dpa.parse_dpa_pdf(_dpa_bytes, _dpa_nama)
                _dpa_sk_list = _dpa.deduplicate_subkegiatan(_dpa_result["subkegiatan"])
                _dpa_rows = _dpa.flatten_to_rows(_dpa_result)

            _dpa_meta = _dpa_result["meta"]
            _dpa_col1, _dpa_col2, _dpa_col3 = st.columns(3)
            _dpa_col1.metric("Satker", _dpa_meta["satker"] or "-")
            _dpa_col2.metric("Tahun", _dpa_meta["tahun_anggaran"] or "-")
            _dpa_col3.metric("Sub Kegiatan", len(_dpa_sk_list))

            _dpa_col4, _dpa_col5 = st.columns(2)
            _dpa_col4.metric("Total Baris Item", len(_dpa_rows))
            _total_alokasi = sum(sk["alokasi_sesudah"] for sk in _dpa_sk_list)
            _dpa_col5.metric("Total Alokasi", f"Rp {_total_alokasi:,.0f}")

            st.divider()
            st.markdown("#### Preview Sub Kegiatan")

            _dpa_preview_data = []
            for sk in _dpa_sk_list:
                _item_count = sum(1 for it in sk["items"] if it["tipe"] == "item")
                _dpa_preview_data.append({
                    "Kode": sk["subkegiatan_kode"],
                    "Nama Sub Kegiatan": sk["subkegiatan_nama"][:60],
                    "Sumber Dana": sk["sumber_pendanaan"],
                    "Alokasi (Rp)": f"{sk['alokasi_sesudah']:,.0f}",
                    "Jml Item": _item_count,
                })
            st.dataframe(_dpa_preview_data, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("#### Simpan ke Supabase")

            _dpa_is_ocr = _dpa_meta.get("sumber") == "ocr"
            if _dpa_is_ocr:
                st.info("⚠️ PDF scan terdeteksi (OCR). Kode/nama sub kegiatan mungkin perlu dikoreksi manual.")

            _dpa_satker_override = st.text_input(
                "Nama Satker (opsional override):",
                value=_dpa_meta["satker"],
                key="dpa_satker_override",
            )
            _dpa_tahun_override = st.text_input(
                "Tahun Anggaran:",
                value=_dpa_meta["tahun_anggaran"],
                key="dpa_tahun_override",
            )

            # Override kode/nama sub kegiatan jika UNKNOWN (hasil OCR tidak bisa parse)
            if _dpa_is_ocr and any(sk["subkegiatan_kode"] == "UNKNOWN" for sk in _dpa_sk_list):
                st.markdown("**Koreksi Sub Kegiatan (OCR tidak bisa parse otomatis):**")
                _dpa_sk_kode_override = st.text_input(
                    "Kode Sub Kegiatan:",
                    placeholder="Contoh: 1.02.02.2.02.0003",
                    key="dpa_sk_kode_override",
                )
                _dpa_sk_nama_override = st.text_input(
                    "Nama Sub Kegiatan:",
                    placeholder="Contoh: Pembangunan Gedung Cytotoxic",
                    key="dpa_sk_nama_override",
                )
            else:
                _dpa_sk_kode_override = None
                _dpa_sk_nama_override = None

            if st.button("💾 Simpan ke Supabase", type="primary", key="dpa_simpan"):
                from config import sb as _sb_dpa_factory
                _dpa_sb = _sb_dpa_factory()
                _dpa_ok = 0
                _dpa_err = 0

                with st.status("Menyimpan data DPA...", expanded=True) as _dpa_status:
                    for sk in _dpa_sk_list:
                        _satker_val = _dpa_satker_override.strip() or _dpa_meta["satker"]
                        _tahun_val = _dpa_tahun_override.strip() or _dpa_meta["tahun_anggaran"]
                        # Terapkan override kode/nama jika UNKNOWN
                        _sk_kode = sk["subkegiatan_kode"]
                        _sk_nama = sk["subkegiatan_nama"]
                        if _sk_kode == "UNKNOWN" and _dpa_sk_kode_override:
                            _sk_kode = _dpa_sk_kode_override.strip()
                        if (_sk_nama == sk["subkegiatan_nama"] and
                                _dpa_sk_nama_override and sk["subkegiatan_kode"] == "UNKNOWN"):
                            _sk_nama = _dpa_sk_nama_override.strip()
                        _sk_id = f"{_satker_val}|{_tahun_val}|{_sk_kode}"

                        _sk_row = {
                            "id": _sk_id,
                            "satker": _satker_val,
                            "subkegiatan_kode": _sk_kode,
                            "subkegiatan_nama": _sk_nama,
                            "tahun_anggaran": _tahun_val,
                            "urusan": _dpa_meta["urusan"],
                            "bidang_urusan": _dpa_meta["bidang_urusan"],
                            "unit_organisasi": _dpa_meta["unit_organisasi"],
                            "nama_file": _dpa_nama,
                            "program_kode": sk["program_kode"],
                            "program_nama": sk["program_nama"],
                            "kegiatan_kode": sk["kegiatan_kode"],
                            "kegiatan_nama": sk["kegiatan_nama"],
                            "sumber_pendanaan": sk["sumber_pendanaan"],
                            "lokasi": sk["lokasi"],
                            "waktu_pelaksanaan": sk["waktu_pelaksanaan"],
                            "alokasi_sebelum": sk["alokasi_sebelum"],
                            "alokasi_sesudah": sk["alokasi_sesudah"],
                            "selisih": sk["selisih"],
                        }

                        try:
                            # Upsert sub kegiatan (hapus items lama via CASCADE)
                            _dpa_sb.table("dpa_subkegiatan").upsert(_sk_row).execute()

                            # Hapus items lama (CASCADE seharusnya, tapi explicit untuk upsert)
                            _dpa_sb.table("dpa_item_belanja").delete().eq("subkegiatan_id", _sk_id).execute()

                            # Insert items baru
                            _item_rows = []
                            for it in sk["items"]:
                                _item_rows.append({
                                    "subkegiatan_id": _sk_id,
                                    "tipe": it["tipe"],
                                    "kode_rekening": it["kode_rekening"],
                                    "level_rekening": it["level"],
                                    "uraian": it["uraian"],
                                    "koefisien": it["koefisien"],
                                    "satuan": it["satuan"],
                                    "harga_sebelum": it["harga_sebelum"],
                                    "jumlah_sebelum": it["jumlah_sebelum"],
                                    "harga_sesudah": it["harga_sesudah"],
                                    "jumlah_sesudah": it["jumlah_sesudah"],
                                    "selisih": it["selisih"],
                                    "spesifikasi": it["spesifikasi"],
                                    "sumber_dana_item": it["sumber_dana_item"],
                                    "nama_paket": it.get("nama_paket"),
                                })
                            if _item_rows:
                                _dpa_sb.table("dpa_item_belanja").insert(_item_rows).execute()

                            st.write(f"✅ {sk['subkegiatan_kode']} — {sk['subkegiatan_nama'][:50]} ({len(_item_rows)} item)")
                            _dpa_ok += 1
                        except Exception as _dpa_ex:
                            st.write(f"❌ {sk['subkegiatan_kode']}: {_dpa_ex}")
                            _dpa_err += 1

                    if _dpa_err == 0:
                        _dpa_status.update(label=f"✅ Selesai — {_dpa_ok} sub kegiatan tersimpan.", state="complete")
                    else:
                        _dpa_status.update(label=f"⚠️ Selesai — {_dpa_ok} OK, {_dpa_err} gagal.", state="error")

        else:
            st.info("Upload PDF DPA untuk memulai parsing.")

        # ── Dashboard / Search DPA ────────────────────────────────────────────
        st.divider()
        st.markdown("### 🔍 Cari Paket di DPA")
        st.caption("Ketik nama pekerjaan → sistem cari di seluruh item belanja DPA yang tersimpan.")

        _dpa_search_q = st.text_input(
            "Nama pekerjaan / uraian belanja:",
            placeholder="Contoh: Pemeliharaan Bangunan Gedung",
            key="dpa_search_q",
        )

        if _dpa_search_q and len(_dpa_search_q.strip()) >= 3:
            from config import sb as _sb_search
            _sb_s = _sb_search()

            with st.spinner("Mencari..."):
                _q = _dpa_search_q.strip()
                _cols = "uraian, kode_rekening, jumlah_sesudah, subkegiatan_id, sumber_dana_item, spesifikasi, nama_paket"
                _r1 = (
                    _sb_s.table("dpa_item_belanja")
                    .select(_cols)
                    .ilike("uraian", f"%{_q}%")
                    .eq("tipe", "item")
                    .order("jumlah_sesudah", desc=True)
                    .limit(50)
                    .execute()
                    .data
                ) or []
                _r2 = (
                    _sb_s.table("dpa_item_belanja")
                    .select(_cols)
                    .ilike("nama_paket", f"%{_q}%")
                    .eq("tipe", "item")
                    .order("jumlah_sesudah", desc=True)
                    .limit(50)
                    .execute()
                    .data
                ) or []
                # Merge deduplicate by (subkegiatan_id, uraian, jumlah_sesudah)
                _seen = set()
                _search_items = []
                for _it in _r1 + _r2:
                    _key = (_it["subkegiatan_id"], _it["uraian"], _it["jumlah_sesudah"])
                    if _key not in _seen:
                        _seen.add(_key)
                        _search_items.append(_it)
                _search_items.sort(key=lambda x: x["jumlah_sesudah"] or 0, reverse=True)
                _search_items = _search_items[:50]

            if not _search_items:
                st.warning("Tidak ada item belanja yang cocok.")
            else:
                # Kumpulkan semua subkegiatan_id unik → batch fetch SK
                _sk_ids = list({it["subkegiatan_id"] for it in _search_items})
                _sk_map = {}
                for _chunk_start in range(0, len(_sk_ids), 20):
                    _chunk = _sk_ids[_chunk_start:_chunk_start+20]
                    _sk_rows = (
                        _sb_s.table("dpa_subkegiatan")
                        .select("id, subkegiatan_kode, subkegiatan_nama, kegiatan_kode, kegiatan_nama, program_nama, alokasi_sesudah, sumber_pendanaan, satker, tahun_anggaran")
                        .in_("id", _chunk)
                        .execute()
                        .data
                    )
                    for _sk in _sk_rows:
                        _sk_map[_sk["id"]] = _sk

                st.markdown(f"**{len(_search_items)} item ditemukan** (maks 50)")

                # Grup hasil per sub kegiatan
                _groups: dict = {}
                for it in _search_items:
                    _sid = it["subkegiatan_id"]
                    if _sid not in _groups:
                        _groups[_sid] = {"sk": _sk_map.get(_sid), "items": []}
                    _groups[_sid]["items"].append(it)

                for _sid, _grp in _groups.items():
                    _sk = _grp["sk"]
                    if _sk:
                        _label = f"📌 {_sk['subkegiatan_kode']} — {_sk['subkegiatan_nama']}"
                        _alokasi_fmt = f"Rp {_sk['alokasi_sesudah']:,.0f}" if _sk['alokasi_sesudah'] else "-"
                    else:
                        _label = f"📌 {_sid}"
                        _alokasi_fmt = "-"

                    with st.expander(_label, expanded=True):
                        if _sk:
                            _i1, _i2, _i3 = st.columns(3)
                            _i1.caption("Kegiatan")
                            _i1.write(f"{_sk['kegiatan_kode']} — {_sk['kegiatan_nama']}")
                            _i2.metric("Alokasi SK", _alokasi_fmt)
                            _i3.metric("Sumber Dana", _sk['sumber_pendanaan'] or '-')
                            _i4, _i5 = st.columns(2)
                            _i4.metric("Satker", _sk['satker'] or '-')
                            _i5.metric("Tahun", _sk['tahun_anggaran'] or '-')
                            st.markdown("---")

                        # Tabel item yang cocok
                        _tbl = []
                        for it in _grp["items"]:
                            _tbl.append({
                                "Kode Rek": it["kode_rekening"] or "-",
                                "Uraian": it["uraian"],
                                "Nama Paket": it.get("nama_paket") or "-",
                                "Jumlah (Rp)": f"{it['jumlah_sesudah']:,.0f}" if it["jumlah_sesudah"] else "-",
                                "Sumber Dana": it["sumber_dana_item"] or "-",
                            })
                        st.dataframe(_tbl, use_container_width=True, hide_index=True)

        elif _dpa_search_q and len(_dpa_search_q.strip()) < 3:
            st.caption("Ketik minimal 3 karakter.")

    # ── Tab 1: Draft Paket PL ─────────────────────────────────────────────────
    with _pl_tab1:
        import os as _pl_os, subprocess as _pl_sp
        from config import POKJA_ROOT as _PL_POKJA_ROOT, OUTPUT_DIR_PL_JKK as _PL_DIR_JKK, OUTPUT_DIR_PL_PK as _PL_DIR_PK

        _PL_PY     = str(pathlib.Path(_PL_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110" / "python" / "python.exe")
        _PL_SCRIPT = str(pathlib.Path(_PL_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110" / "setup_paket_baru.py")
        _PL_NO_WIN = 0x08000000

        _pl_rows = pl_engine.load_draft_pl()
        _pl_col_kiri, _pl_col_kanan = st.columns(2)

        # ══════════════════════════════════════════════════════
        # KOLOM KIRI — Serap SPSE + Daftar Paket
        # ══════════════════════════════════════════════════════
        with _pl_col_kiri:
            st.markdown("#### 1. Serap Paket dari SPSE")
            st.caption("Fetch `/dt/paketpp` (login PP) → scrape HPS + Jenis Kontrak → simpan ke Supabase.")

            _pl_serap_btn = st.button("📥 Serap dari SPSE", type="primary", use_container_width=True, key="btn_serap_pl")
            if _pl_serap_btn:
                import spse_browser as _sb_pl
                _pl_cookie = _sb_pl.get_spse_cookies()
                if not _pl_cookie:
                    st.error("Cookie SPSE kosong — buka Chrome SPSE dan login sebagai PP.")
                else:
                    _pl_pb = st.progress(0.0)
                    _pl_st = st.empty()
                    _pl_logs = []
                    def _pl_log(msg):
                        _pl_logs.append(msg)
                        _pl_st.info(msg)
                    from config import SPSE_BASE_URL as _SPSE_BASE
                    _pl_hasil = pl_engine.serap_paket_pl_dari_spse(
                        _pl_cookie, _SPSE_BASE, log_fn=_pl_log
                    )
                    _pl_pb.progress(1.0)
                    _pl_c1, _pl_c2 = st.columns(2)
                    _pl_c1.metric("✅ Tersimpan", _pl_hasil.get("scraped", 0))
                    _pl_c2.metric("❌ Error", len(_pl_hasil.get("errors", [])))
                    if _pl_hasil.get("errors"):
                        with st.expander("Detail Error"):
                            for _e in _pl_hasil["errors"]:
                                st.error(_e)
                    _pl_rows = pl_engine.load_draft_pl()

            st.divider()
            st.markdown("#### 2. Enrich Data Paket PL")
            st.caption(
                "Update field tambahan: **MAK** (Kode Rekening) dari inbox SPSE, "
                "**Nama & NPWP Penyedia** dari PDF `Draft_PL_*.pdf` di folder paket."
            )
            _pl_e1, _pl_e2 = st.columns(2)
            with _pl_e1:
                _btn_serap_mak = st.button(
                    "📨 Serap MAK dari Inbox PL",
                    key="btn_serap_mak_pl",
                    use_container_width=True,
                )
            with _pl_e2:
                _btn_serap_pyd = st.button(
                    "📄 Serap Penyedia dari Draft_PL",
                    key="btn_serap_penyedia_pl",
                    use_container_width=True,
                )

            if _btn_serap_mak:
                import inbox_engine as _ibe
                _pb_mak = st.progress(0.0)
                _st_mak = st.empty()
                _logs_mak = []
                def _cb_mak(p, m):
                    _pb_mak.progress(min(max(p, 0.0), 1.0))
                    _logs_mak.append(m)
                    _st_mak.info(m)
                try:
                    _r_mak = _ibe.serap_inbox_pl(progress_cb=_cb_mak)
                    _c1, _c2, _c3 = st.columns(3)
                    _c1.metric("Pesan parse", _r_mak.get("scraped", 0))
                    _c2.metric("Paket update", _r_mak.get("matched", 0))
                    _c3.metric("Error", len(_r_mak.get("errors", [])))
                    if _r_mak.get("errors"):
                        with st.expander("Detail Error"):
                            for _e in _r_mak["errors"]:
                                st.warning(_e)
                except Exception as _e:
                    st.error(f"Gagal: {_e}")

            if _btn_serap_pyd:
                import parse_kak_pl as _pkp
                _pb_pyd = st.progress(0.0)
                _st_pyd = st.empty()
                _logs_pyd = []
                def _cb_pyd(p, m):
                    _pb_pyd.progress(min(max(p, 0.0), 1.0))
                    _logs_pyd.append(m)
                    _st_pyd.info(m)
                try:
                    _r_pyd = _pkp.serap_penyedia_pl(progress_cb=_cb_pyd)
                    _c1, _c2, _c3, _c4 = st.columns(4)
                    _c1.metric("Update", _r_pyd.get("updated", 0))
                    _c2.metric("Folder NF", _r_pyd.get("not_found", 0))
                    _c3.metric("No data", _r_pyd.get("no_data", 0))
                    _c4.metric("Error", len(_r_pyd.get("errors", [])))
                    if _r_pyd.get("errors"):
                        with st.expander("Detail Error"):
                            for _e in _r_pyd["errors"]:
                                st.warning(_e)
                except Exception as _e:
                    st.error(f"Gagal: {_e}")

            st.divider()
            st.markdown("#### 3. Daftar Paket PL")

            _pl_filter = st.selectbox(
                "Filter:",
                ["Semua", "JKK", "PK", "Belum Folder", "Sudah Folder"],
                key="pl_filter_jenis",
            )

            def _pl_match(r):
                if _pl_filter == "JKK":    return r.get("jenis_pl") == "JKK"
                if _pl_filter == "PK":     return r.get("jenis_pl") == "PK"
                if _pl_filter == "Belum Folder": return not bool(r.get("folder_dibuat"))
                if _pl_filter == "Sudah Folder": return bool(r.get("folder_dibuat"))
                return True

            _pl_filtered = [r for r in _pl_rows if _pl_match(r)]

            if not _pl_filtered:
                st.info("Belum ada paket PL. Klik 'Serap dari SPSE' atau tambah manual.")
            else:
                for _pr in _pl_filtered:
                    _pr_kode   = _pr.get("kode_paket", "")
                    _pr_nama   = _pr.get("nama_paket", "-")
                    _pr_jenis  = _pr.get("jenis_pl", "")
                    _pr_hps    = _pr.get("nilai_hps", "-")
                    _pr_status = _pr.get("status", "draft")
                    _pr_folder = bool(_pr.get("folder_dibuat"))
                    _pr_icon   = "✅" if _pr_folder else "📋"
                    # Label metode singkat + tanda ⚠️ jika Non Konstruksi
                    _pr_metode_raw = _pr.get("metode_pengadaan", "") or ""
                    _pr_metode_low = _pr_metode_raw.lower()
                    if "non konstruksi" in _pr_metode_low or "non konstruksi" in _pr_metode_low.replace(" ", ""):
                        _pr_metode_lbl = "⚠️ JKK Non-Konstruksi"
                    elif "konstruksi" in _pr_metode_low:
                        _pr_metode_lbl = "JKK Konstruksi"
                    elif "barang" in _pr_metode_low:
                        _pr_metode_lbl = "PK"
                    elif _pr_metode_raw:
                        _pr_metode_lbl = _pr_metode_raw[:30]
                    else:
                        _pr_metode_lbl = _pr_jenis or "-"
                    _pr_label  = f"{_pr_icon} [{_pr_metode_lbl}] {_pr_nama[:45]}"

                    with st.expander(_pr_label):
                        st.caption(f"`{_pr_kode}` | HPS: {_pr_hps} | Status: **{_pr_status}**")
                        if "non konstruksi" in _pr_metode_low:
                            st.warning("⚠️ Metode: Non Konstruksi — minta PPK ubah ke Konstruksi di SPSE.")
                        elif _pr_metode_raw:
                            st.caption(f"Metode: {_pr_metode_raw}")
                        st.caption(f"Satker: {_pr.get('satker','-')} | PPK: {_pr.get('nama_ppk','-')}")

                        _pr_c1, _pr_c2, _pr_c3 = st.columns(3)
                        _pr_status_baru = _pr_c2.selectbox(
                            "Status:",
                            pl_engine.STATUS_LIST,
                            index=pl_engine.STATUS_LIST.index(_pr_status) if _pr_status in pl_engine.STATUS_LIST else 0,
                            key=f"pl_status_{_pr_kode}",
                        )
                        if _pr_c2.button("💾 Update", key=f"pl_upd_{_pr_kode}", use_container_width=True):
                            pl_engine.update_status(_pr_kode, _pr_status_baru)
                            st.rerun()
                        if _pr_c3.button("🗑️ Hapus", key=f"pl_hapus_{_pr_kode}", use_container_width=True):
                            pl_engine.hapus_paket_pl(_pr_kode)
                            st.rerun()

        # ── Ubah Metode Pengadaan via CDP ────────────────────────
        if _pl_rows:
            _pl_non_kon = [r for r in _pl_rows if "non konstruksi" in (r.get("metode_pengadaan") or "").lower()]
            _ekspander_label = f"🔧 Ubah Metode Pengadaan" + (f"  ⚠️ {len(_pl_non_kon)} Non-Konstruksi" if _pl_non_kon else "")
            with st.expander(_ekspander_label):
                st.info("Pastikan CDP browser sudah terbuka dan login sebagai PP.")
                _pl_opsi_ubah = {r.get("nama_paket", r.get("kode_paket")): r.get("kode_paket") for r in _pl_rows}
                _pl_default_sel = [r.get("nama_paket", r.get("kode_paket")) for r in _pl_non_kon]
                _pl_sel_ubah = st.multiselect(
                    "Pilih paket yang diubah:",
                    list(_pl_opsi_ubah.keys()),
                    default=_pl_default_sel,
                    key="pl_ubah_metode_sel",
                )
                _pl_metode_pilihan = st.selectbox(
                    "Target metode:",
                    list(pl_engine.METODE_PL_MAP.keys()),
                    index=list(pl_engine.METODE_PL_MAP.keys()).index("JKK Konstruksi — PL"),
                    key="pl_ubah_metode_target",
                )
                _pl_kat_id, _pl_pilih_val = pl_engine.METODE_PL_MAP[_pl_metode_pilihan]

                if st.button(
                    f"🔄 Ubah Metode ({len(_pl_sel_ubah)} paket) via CDP",
                    disabled=not _pl_sel_ubah,
                    use_container_width=True,
                    key="pl_btn_ubah_metode",
                ):
                    _pl_base_ubah = pl_engine.BASE_URL + "/"
                    _pl_ok_ubah = _pl_fail_ubah = 0
                    for _nm_ubah in _pl_sel_ubah:
                        _kd_ubah = _pl_opsi_ubah[_nm_ubah]
                        if pl_engine.ubah_metode_pl_playwright(_kd_ubah, _pl_kat_id, _pl_pilih_val, _pl_base_ubah):
                            _pl_ok_ubah += 1
                            st.write(f"✅ {_nm_ubah[:45]}")
                        else:
                            _pl_fail_ubah += 1
                            st.write(f"❌ {_nm_ubah[:45]}")
                    st.success(f"Selesai: {_pl_ok_ubah} OK, {_pl_fail_ubah} GAGAL. Serap ulang untuk refresh.")

        # ══════════════════════════════════════════════════════
        # KOLOM KANAN — Buat Folder + Download Dokumen
        # ══════════════════════════════════════════════════════
        with _pl_col_kanan:
            st.markdown("#### 4. Buat Folder Paket")

            if "pl_folder_just_created" in st.session_state:
                _msg = st.session_state.pop("pl_folder_just_created")
                st.toast(f"✅ {_msg}", icon="📁")
                st.success(f"✅ {_msg}")
                st.balloons()

            # Dropdown pilih paket
            def _pl_no_dari_nama(nama: str, fallback: int) -> int:
                """Ekstrak nomor dari nama paket, misal 'Paket 1' → 1."""
                import re as _re
                m = _re.search(r"Paket\s+(\d+)", nama, _re.IGNORECASE)
                return int(m.group(1)) if m else fallback

            _pl_opsi_map = {"(pilih paket)": None}
            for _i, _r in enumerate(_pl_rows, 1):
                if not _r.get("nama_paket"):
                    continue
                _nm = _r.get("nama_paket", "")
                _no = _pl_no_dari_nama(_nm, _i)
                _jenis = _r.get("jenis_pl", "")
                _sudah = " ✅" if _r.get("folder_dibuat") else ""
                _lbl = f"{_no}. {_nm} - {_jenis}{_sudah}"
                _pl_opsi_map[_lbl] = _r

            _pl_pilihan = st.selectbox("Pilih paket:", list(_pl_opsi_map.keys()), key="sel_pl_folder")
            _pl_row_sel = _pl_opsi_map.get(_pl_pilihan)

            # Auto-generate nama folder
            _pl_default_folder = ""
            _pl_jenis_sel = "JKK"
            if _pl_row_sel:
                _pl_nm      = _pl_row_sel.get("nama_paket", "")
                _pl_jenis_sel = _pl_row_sel.get("jenis_pl", "JKK")
                _pl_prefix  = {"JKK": "PLJKK", "PK": "PLPK"}.get(_pl_jenis_sel, f"PL{_pl_jenis_sel}")
                _pl_no_urut = _pl_no_dari_nama(_pl_nm, len(_pl_rows))
                _pl_default_folder = f"{_pl_no_urut}. {_pl_prefix} - {_pl_nm}"

            _pl_nama_folder = st.text_input(
                "Nama folder:",
                value=_pl_default_folder,
                placeholder="1. PLJKK - Perencanaan Pembangunan Jalan ...",
                key="pl_input_nama_folder",
            )

            # Output base dir: JKK → @ Pengadaan Langsung JKK, PK → @ Pengadaan Langsung PK
            _pl_output_base = _PL_DIR_JKK if _pl_jenis_sel == "JKK" else _PL_DIR_PK
            _pl_nama_clean = re.sub(r'[/<>:"\|?*]', "-", _pl_nama_folder).strip() if _pl_nama_folder else ""
            _pl_target = _pl_os.path.join(_pl_output_base, _pl_nama_clean) if _pl_nama_clean else ""
            _pl_folder_ada = bool(_pl_target and _pl_os.path.exists(_pl_target))

            st.caption(f"📂 Output: `{_pl_output_base}`")

            if _pl_folder_ada:
                st.warning(f"Folder sudah ada: `{_pl_target}`")

            _pl_cb1, _pl_cb2 = st.columns(2)
            _pl_dl_dokumen = st.checkbox("📦 Download dokumen SPSE (KAK, Personil, Kontrak)", value=True, key="pl_cb_dl")

            _pl_buat_btn = _pl_cb1.button(
                "📁 Buat Folder",
                type="primary",
                disabled=not bool(_pl_nama_folder),
                use_container_width=True,
                key="pl_btn_buat_folder",
            )
            if _pl_folder_ada:
                if _pl_cb2.button("📂 Buka Explorer", use_container_width=True, key="pl_btn_explorer"):
                    _pl_sp.Popen(f'explorer "{_pl_target.replace("/", chr(92))}"')

            # Tombol download mandiri (jika folder sudah ada)
            if _pl_folder_ada and _pl_row_sel:
                _pl_kode_dl = _pl_row_sel.get("kode_paket", "")
                if _pl_kode_dl and st.button("📦 Download Dokumen SPSE", use_container_width=True, key="pl_btn_dl_saja"):
                    _pl_dl_logs = []
                    _pl_dl_status = st.status("🔽 Mengunduh dokumen...", expanded=True)
                    _pl_dl_area = _pl_dl_status.empty()
                    def _pl_dl_cb(msg):
                        _pl_dl_logs.append(msg)
                        _pl_dl_area.code("\n".join(_pl_dl_logs[-20:]))
                        _pl_dl_status.update(label=f"🔽 {msg[:60]}")
                    _pl_dl_res = pl_engine.download_dokumen_paket_pl(_pl_kode_dl, _pl_target, _pl_dl_cb)
                    _pl_dl_status.update(
                        label=f"✅ {len(_pl_dl_res['ok'])} file, ❌ {len(_pl_dl_res['error'])} error",
                        state="complete", expanded=False,
                    )
                    # Parse KAK PDF → upsert Supabase
                    _kak_p = parse_kak_pl.cari_kak_di_folder(_pl_target)
                    if _kak_p:
                        _kak_d = parse_kak_pl.parse_kak(_kak_p)
                        _kak_u = {k: v for k, v in _kak_d.items() if v}
                        if _kak_u:
                            pl_engine.simpan_paket_pl({"kode_paket": _pl_kode_dl, **_kak_u})
                            st.info(f"📋 KAK ter-parse: {', '.join(_kak_u.keys())}")
                    # Scrape HPS PL otomatis
                    try:
                        import hps_engine as _hps_pl
                        _hps_r = _hps_pl.scrape_dan_upsert_hps_pl(_pl_kode_dl)
                        if _hps_r.get("error"):
                            st.warning(f"⚠ HPS: {_hps_r['error']}")
                        else:
                            st.success(f"💰 HPS: {_hps_r['count']} item, total Rp {_hps_r['total_nilai']:,.0f}")
                    except Exception as _he:
                        st.warning(f"⚠ HPS error: {_he}")

            # Tombol scrape HPS mandiri (kalau download sebelumnya tidak include)
            if _pl_folder_ada and _pl_row_sel:
                _pl_kode_hps = _pl_row_sel.get("kode_paket", "")
                if _pl_kode_hps and st.button("💰 Scrape HPS PL", use_container_width=True, key="pl_btn_hps_saja"):
                    import hps_engine as _hps_pl
                    with st.spinner("Scrape HPS dari SPSE..."):
                        _hps_r = _hps_pl.scrape_dan_upsert_hps_pl(_pl_kode_hps)
                    if _hps_r.get("error"):
                        st.error(f"Gagal: {_hps_r['error']}")
                    else:
                        st.success(f"✅ {_hps_r['count']} item, total Rp {_hps_r['total_nilai']:,.0f}, pembulatan Rp {_hps_r['total_nilai_bulat']:,.0f}")
                        if _hps_r.get("warning"):
                            st.warning(f"⚠ {len(_hps_r['warning'])} item selisih")

            if _pl_buat_btn and _pl_nama_folder:
                with st.spinner(f"Membuat '{_pl_nama_folder}'..."):
                    try:
                        _pl_res = _pl_sp.run(
                            [_PL_PY, _PL_SCRIPT, "--mode", "pl",
                             "--output-dir", _pl_output_base, _pl_nama_clean],
                            capture_output=True, text=True, timeout=60,
                            creationflags=_PL_NO_WIN,
                        )
                        if _pl_res.returncode == 0:
                            if _pl_row_sel:
                                pl_engine.tandai_folder_dibuat(_pl_row_sel["kode_paket"])
                            # Download dokumen jika dicentang
                            if _pl_dl_dokumen and _pl_row_sel:
                                _pl_kp = _pl_row_sel.get("kode_paket", "")
                                if _pl_kp:
                                    _pl_dl_msgs = []
                                    _pl_dl_st2 = st.status("📦 Download dokumen...", expanded=True)
                                    _pl_dl_area2 = _pl_dl_st2.empty()
                                    def _pl_dl_cb2(msg):
                                        _pl_dl_msgs.append(msg)
                                        _pl_dl_area2.code("\n".join(_pl_dl_msgs[-20:]))
                                    _pl_dl_r2 = pl_engine.download_dokumen_paket_pl(
                                        _pl_kp, _pl_target, _pl_dl_cb2
                                    )
                                    _pl_dl_st2.update(
                                        label=f"✅ {len(_pl_dl_r2['ok'])} file, ❌ {len(_pl_dl_r2['error'])} error",
                                        state="complete", expanded=False,
                                    )
                                    # Parse KAK PDF → upsert ke Supabase
                                    _pl_kak_path = parse_kak_pl.cari_kak_di_folder(_pl_target)
                                    if _pl_kak_path:
                                        _pl_kak_data = parse_kak_pl.parse_kak(_pl_kak_path)
                                        _pl_kak_update = {k: v for k, v in _pl_kak_data.items() if v}
                                        if _pl_kak_update:
                                            pl_engine.simpan_paket_pl({"kode_paket": _pl_kp, **_pl_kak_update})
                                            st.info(f"📋 KAK ter-parse: {', '.join(_pl_kak_update.keys())}")
                                    # Scrape HPS PL
                                    try:
                                        import hps_engine as _hps_pl
                                        _hps_r = _hps_pl.scrape_dan_upsert_hps_pl(_pl_kp)
                                        if not _hps_r.get("error"):
                                            st.success(f"💰 HPS: {_hps_r['count']} item, Rp {_hps_r['total_nilai']:,.0f}")
                                    except Exception:
                                        pass
                            st.session_state["pl_folder_just_created"] = f"Folder '{_pl_nama_clean}' berhasil dibuat."
                            st.rerun()
                        else:
                            st.error(f"Gagal buat folder:\n{_pl_res.stderr[:300]}")
                    except Exception as _pe:
                        st.error(f"Error: {_pe}")

            # ── Bulk: Buat Semua Folder ──────────────────────────────
            st.divider()

            _pl_rows_belum = [
                r for r in _pl_rows
                if r.get("nama_paket") and not r.get("folder_dibuat")
            ]

            # Plan: pre-compute nama folder per paket
            _pl_bulk_plan = []
            for _bi0, _br0 in enumerate(_pl_rows_belum, 1):
                _bnm0  = _br0.get("nama_paket", "")
                _bj0   = _br0.get("jenis_pl", "JKK")
                _bpfx0 = {"JKK": "PLJKK", "PK": "PLPK"}.get(_bj0, f"PL{_bj0}")
                _bno0  = _pl_no_dari_nama(_bnm0, _bi0)
                _bnm_folder0 = re.sub(r'[/<>:"\|?*]', "-", f"{_bno0}. {_bpfx0} - {_bnm0}").strip()
                _bout_base0  = _PL_DIR_JKK if _bj0 == "JKK" else _PL_DIR_PK
                _pl_bulk_plan.append({
                    "kode_paket": _br0.get("kode_paket", ""),
                    "nama_folder": _bnm_folder0,
                    "out_base": _bout_base0,
                    "jenis_pl": _bj0,
                })

            st.caption(f"{len(_pl_rows_belum)} paket belum ada folder")
            if _pl_bulk_plan:
                with st.expander(f"📋 Preview {len(_pl_bulk_plan)} folder yang akan dibuat"):
                    for _bp0 in _pl_bulk_plan:
                        st.caption(_bp0["nama_folder"])

            # ── Reset Status Folder (kosongkan folder_dibuat di Supabase) ──
            with st.expander("↩️ Reset Status Folder"):
                st.caption("Kosongkan `folder_dibuat` agar paket muncul kembali di Bulk Create (folder fisik tidak dihapus).")
                _opsi_reset_pl = {
                    f"{r.get('nama_paket','')[:60]} — {r.get('jenis_pl','')}": r.get("kode_paket")
                    for r in _pl_rows if r.get("folder_dibuat") and r.get("kode_paket")
                }
                if _opsi_reset_pl:
                    from config import sb as _sb_reset

                    # Reset Semua
                    _rs_col1, _rs_col2 = st.columns([1, 1])
                    if _rs_col1.button(
                        f"↩️ Reset Semua ({len(_opsi_reset_pl)} paket)",
                        type="secondary",
                        use_container_width=True,
                        key="pl_btn_reset_all",
                    ):
                        _reset_all_ok = 0
                        for _kr_all in _opsi_reset_pl.values():
                            try:
                                _sb_reset().table("draft_paket_pl").update(
                                    {"folder_dibuat": None}
                                ).eq("kode_paket", _kr_all).execute()
                                _reset_all_ok += 1
                            except Exception as _er_all:
                                st.error(f"{_kr_all}: {_er_all}")
                        if _reset_all_ok:
                            st.success(f"✅ {_reset_all_ok} paket berhasil direset.")
                        st.rerun()

                    _pilih_reset_pl = st.multiselect("Pilih paket:", list(_opsi_reset_pl.keys()), key="pl_ms_reset_folder")
                    if _pilih_reset_pl:
                        if st.button("↩️ Reset Pilihan", type="secondary", key="pl_btn_reset_folder"):
                            _reset_ok_pl = 0
                            for _kr in [_opsi_reset_pl[k] for k in _pilih_reset_pl]:
                                try:
                                    _sb_reset().table("draft_paket_pl").update(
                                        {"folder_dibuat": None}
                                    ).eq("kode_paket", _kr).execute()
                                    _reset_ok_pl += 1
                                except Exception as _er_pl:
                                    st.error(f"{_kr}: {_er_pl}")
                            if _reset_ok_pl:
                                st.success(f"✅ {_reset_ok_pl} paket berhasil direset.")
                            st.rerun()
                else:
                    st.info("Tidak ada paket dengan status folder yang bisa direset.")

            # ── Replicate pattern tender (sequential + per-paket log dict) ──
            if st.button(
                f"📁 Buat Semua Folder ({len(_pl_rows_belum)} paket)",
                disabled=len(_pl_rows_belum) == 0,
                use_container_width=True,
                key="pl_btn_buat_semua",
                type="secondary",
            ):
                from streamlit.runtime.scriptrunner import get_script_run_ctx as _pl_grc
                _pl_ctx_bulk = _pl_grc()
                _pl_bp = st.progress(0.0)
                _pl_bulk_status = st.status(f"📁 Memproses {len(_pl_bulk_plan)} paket...", expanded=True)
                _pl_bulk_status_line = _pl_bulk_status.empty()
                _pl_ok, _pl_fail = 0, 0
                _pl_bulk_semua_log = {}  # {nama_folder: [log lines]}
                for _pl_i, _pl_bp_item in enumerate(_pl_bulk_plan):
                    _pl_bp.progress((_pl_i + 1) / len(_pl_bulk_plan))
                    _pl_nf = _pl_bp_item["nama_folder"]
                    _pl_kp_b = _pl_bp_item["kode_paket"]
                    _pl_out_b = _pl_bp_item["out_base"]
                    _pl_target_b = _pl_os.path.join(_pl_out_b, _pl_nf)
                    _pl_bulk_status.update(label=f"[{_pl_i+1}/{len(_pl_bulk_plan)}] {_pl_nf[:60]}")
                    _pl_paket_log = []
                    try:
                        _pl_r2 = _pl_sp.run(
                            [_PL_PY, _PL_SCRIPT, "--mode", "pl", "--output-dir", _pl_out_b, _pl_nf],
                            capture_output=True, text=True, timeout=120,
                            creationflags=_PL_NO_WIN,
                        )
                        if _pl_r2.returncode == 0:
                            _pl_ok += 1
                            _pl_paket_log.append("✅ Folder dibuat")
                            try:
                                pl_engine.tandai_folder_dibuat(_pl_kp_b)
                            except Exception as _pl_e_upd:
                                _pl_paket_log.append(f"⚠ tandai_folder_dibuat: {_pl_e_upd}")
                            # Download dokumen + parse KAK + scrape HPS
                            if _pl_dl_dokumen and _pl_kp_b:
                                def _pl_bulk_cb(msg, _log=_pl_paket_log):
                                    _log.append(msg)
                                    _pl_bulk_status_line.code("\n".join(_log[-10:]))
                                try:
                                    _pl_dl_hasil = pl_engine.download_dokumen_paket_pl(
                                        _pl_kp_b, _pl_target_b,
                                        progress_cb=_pl_bulk_cb,
                                    )
                                    _pl_paket_log.append(
                                        f"📎 Download: ✅{len(_pl_dl_hasil['ok'])} file"
                                        + (f" | Draft: {_pl_os.path.basename(_pl_dl_hasil['draft_pdf'])}" if _pl_dl_hasil.get('draft_pdf') else " | ⚠ Draft tidak terbuat")
                                    )
                                    for _pl_e in _pl_dl_hasil.get("error", []):
                                        _pl_paket_log.append(f"  ❌ {_pl_e}")
                                except Exception as _pl_dl_e:
                                    _pl_paket_log.append(f"❌ Download error: {_pl_dl_e}")
                                # Parse KAK
                                try:
                                    _pl_kak_p = parse_kak_pl.cari_kak_di_folder(_pl_target_b)
                                    if _pl_kak_p:
                                        _pl_kak_d = parse_kak_pl.parse_kak(_pl_kak_p)
                                        _pl_kak_u = {k: v for k, v in _pl_kak_d.items() if v}
                                        if _pl_kak_u:
                                            pl_engine.simpan_paket_pl({"kode_paket": _pl_kp_b, **_pl_kak_u})
                                            _pl_paket_log.append(f"📋 KAK: {','.join(_pl_kak_u.keys())}")
                                except Exception as _pl_kak_e:
                                    _pl_paket_log.append(f"⚠ KAK parse: {_pl_kak_e}")
                            # Scrape HPS
                            if _pl_kp_b:
                                try:
                                    import hps_engine as _pl_hps_eng
                                    _pl_hps_res = _pl_hps_eng.scrape_dan_upsert_hps_pl(_pl_kp_b)
                                    _pl_paket_log.append(f"📊 HPS: {_pl_hps_res.get('count', 0)} item")
                                except Exception as _pl_hps_e:
                                    _pl_paket_log.append(f"⚠ HPS gagal: {_pl_hps_e}")
                        else:
                            _pl_fail += 1
                            _pl_paket_log.append(f"❌ Gagal buat folder: rc={_pl_r2.returncode} {_pl_r2.stderr[:200]}")
                    except _pl_sp.TimeoutExpired:
                        _pl_fail += 1
                        _pl_paket_log.append("❌ Timeout buat folder")
                    except Exception as _pl_e_x:
                        _pl_fail += 1
                        import traceback as _pl_tb
                        _pl_paket_log.append(f"❌ EXC {type(_pl_e_x).__name__}: {_pl_e_x}")
                        _pl_paket_log.append(_pl_tb.format_exc()[-300:])
                    _pl_bulk_semua_log[_pl_nf] = _pl_paket_log

                _pl_bulk_status_line.empty()
                _pl_ringkasan = f"✅ {_pl_ok} folder berhasil, ❌ {_pl_fail} gagal"
                _pl_bulk_status.update(label=_pl_ringkasan, state="complete", expanded=False)
                with st.expander("📋 Log detail per paket", expanded=_pl_fail > 0):
                    for _pl_nf, _pl_logs in _pl_bulk_semua_log.items():
                        st.markdown(f"**{_pl_nf[:70]}**")
                        st.code("\n".join(_pl_logs))
                st.session_state["pl_folder_bulk_created"] = _pl_ringkasan

    # ── Tab 2: Kirim Undangan DPP ─────────────────────────────────────────────
    with _pl_tab2:
        _kd_col_list, _kd_col_detail = st.columns([3, 2])

        with _kd_col_list:
            st.markdown("### 1. Pilih Paket")

            _pl_rows_kd = pl_engine.load_draft_pl()
            if not _pl_rows_kd:
                st.info("⚠️ Belum ada paket PL. Serap dari SPSE di Tab 1 terlebih dahulu.")
            else:
                _kd_sel_col1, _kd_sel_col2 = st.columns(2)
                with _kd_sel_col1:
                    if st.button("✅ Semua", key="kd_sel_all", use_container_width=True):
                        for _rr in _pl_rows_kd:
                            st.session_state[f"kd_chk_{_rr['kode_paket']}"] = True
                        st.rerun()
                with _kd_sel_col2:
                    if st.button("⬜ Kosong", key="kd_sel_none", use_container_width=True):
                        for _rr in _pl_rows_kd:
                            st.session_state[f"kd_chk_{_rr['kode_paket']}"] = False
                        st.rerun()

                _kd_selected = []
                for _rr in _pl_rows_kd:
                    _kd_key     = f"kd_chk_{_rr['kode_paket']}"
                    _kd_tgl_key = f"kd_tgl_acara_{_rr['kode_paket']}"
                    _col_chk, _col_tgl = st.columns([3, 2])
                    with _col_chk:
                        _kd_chk = st.checkbox(
                            f"{_rr['nama_paket'][:55]}",
                            value=st.session_state.get(_kd_key, True),
                            key=_kd_key,
                        )
                    with _col_tgl:
                        _kd_tgl_acara = st.date_input(
                            "Tanggal Acara",
                            value=st.session_state.get(_kd_tgl_key, datetime.now().date()),
                            format="DD/MM/YYYY",
                            key=_kd_tgl_key,
                            label_visibility="collapsed",
                        )
                        st.caption(f"{_HARI_NAMA[_kd_tgl_acara.weekday()]}, {_kd_tgl_acara.day} {_BULAN_NAMA[_kd_tgl_acara.month-1]} {_kd_tgl_acara.year}")
                        if _kd_tgl_acara in _LIBUR_MAP:
                            st.caption(f"⚠️ {_LIBUR_MAP[_kd_tgl_acara]}")
                    if _kd_chk:
                        _kd_selected.append({**_rr, "_tgl_acara": _kd_tgl_acara})

                st.caption(f"**{len(_kd_selected)}** dari **{len(_pl_rows_kd)}** paket dipilih")

            st.divider()
            st.markdown("### 2. Detail Undangan")
            st.caption("Pesan dikirim PP ke PPK — meminta reviu Dokumen Persiapan Pengadaan.")

            st.markdown("**Waktu Acara (berlaku semua paket)**")
            _kd_col_mulai, _kd_col_selesai = st.columns(2)
            with _kd_col_mulai:
                _kd_jam_mulai = st.time_input(
                    "Mulai",
                    value=datetime.strptime("09:00", "%H:%M").time(),
                    key="kd_jam_mulai",
                    step=1800,
                )
            with _kd_col_selesai:
                _kd_jam_selesai = st.time_input(
                    "Selesai",
                    value=datetime.strptime("11:00", "%H:%M").time(),
                    key="kd_jam_selesai",
                    step=1800,
                )

            with st.expander("ℹ️ Libur Nasional Tersisa"):
                _kd_hari_ini = datetime.now().date()
                for _kd_d in sorted(d for d in _LIBUR_MAP if d >= _kd_hari_ini):
                    st.write(f"• {_HARI_NAMA[_kd_d.weekday()]}, {_kd_d.day} {_BULAN_NAMA[_kd_d.month-1]} {_kd_d.year} — {_LIBUR_MAP[_kd_d]}")

            _kd_tempat = st.text_area(
                "Tempat",
                value=pl_kirimpesan_engine.DEFAULT_TEMPAT,
                key="kd_tempat",
                height=100,
            )

            st.divider()
            st.caption("⚠️ Pesan yang terkirim **tidak bisa dihapus** dari SPSE.")

            if not st.session_state.get("kd_konfirmasi"):
                if st.button(
                    f"📨 Kirim Undangan DPP ke {len(_kd_selected)} Paket",
                    key="kd_kirim",
                    type="primary",
                    disabled=len(_kd_selected) == 0,
                    use_container_width=True,
                ):
                    if not _kd_tempat.strip():
                        st.error("❌ Tempat wajib diisi.")
                    else:
                        st.session_state["kd_konfirmasi"] = True
                        st.rerun()
            else:
                _kd_konfirm_lines = "\n".join(
                    f"{i+1}. {p['nama_paket'][:55]}  \n"
                    f"   📅 {_HARI_NAMA[p['_tgl_acara'].weekday()]}, {p['_tgl_acara'].day} {_BULAN_NAMA[p['_tgl_acara'].month-1]} {p['_tgl_acara'].year}"
                    for i, p in enumerate(_kd_selected)
                )
                st.warning(
                    f"Kirim ke **{len(_kd_selected)} paket**\n\n"
                    f"{_kd_konfirm_lines}\n\n"
                    f"- Pukul: {_kd_jam_mulai.strftime('%H.%M')} s.d. {_kd_jam_selesai.strftime('%H.%M')} Wita\n"
                    f"- Tempat: {_kd_tempat.strip()[:80]}\n\n"
                    f"**Tidak bisa dibatalkan setelah dikirim.**"
                )
                _kdc1, _kdc2 = st.columns(2)
                with _kdc1:
                    if st.button("✅ Ya, Kirim", key="kd_ya", type="primary", use_container_width=True):
                        st.session_state["kd_konfirmasi"] = False
                        _kd_progress = st.progress(0, text="Memulai pengiriman...")
                        _kd_hasil = []
                        _tgl_kirim_kd = datetime.now().date()

                        for _ki, _kp in enumerate(_kd_selected):
                            _kd_progress.progress(
                                (_ki + 1) / len(_kd_selected),
                                text=f"Mengirim {_ki+1}/{len(_kd_selected)}...",
                            )
                            _kd_tgl_a  = _kp["_tgl_acara"]
                            _kd_hari_tgl = f"{_HARI_NAMA[_kd_tgl_a.weekday()]}, {_kd_tgl_a.day} {_BULAN_NAMA[_kd_tgl_a.month-1]} {_kd_tgl_a.year}"
                            _kd_pukul    = f"{_kd_jam_mulai.strftime('%H.%M')} s.d. {_kd_jam_selesai.strftime('%H.%M')} Wita"

                            # Generate PDF lampiran otomatis
                            import undangan_pdf_engine as _upe
                            _gen = _upe.generate_undangan_pdf_pl(
                                kode_paket=_kp["kode_paket"],
                                tanggal_kirim=_tgl_kirim_kd,
                                hari_tgl_rapat=_kd_hari_tgl,
                                pukul_rapat=_kd_pukul,
                                tempat_rapat=_kd_tempat.strip(),
                            )
                            _lamp_bytes = _gen["pdf_bytes"] if _gen["sukses"] else None
                            _lamp_nama  = f"Undangan_DPP_{_kp['kode_paket']}.pdf"

                            _waktu_str  = datetime.combine(_kd_tgl_a, _kd_jam_mulai).strftime("%d-%m-%Y %H:%M")
                            _sampai_str = datetime.combine(_kd_tgl_a, _kd_jam_selesai).strftime("%d-%m-%Y %H:%M")

                            _res = pl_kirimpesan_engine.kirim_undangan_pl(
                                kode=_kp["kode_paket"],
                                waktu=_waktu_str,
                                sampai=_sampai_str,
                                tempat=_kd_tempat.strip(),
                                dibawa=pl_kirimpesan_engine.DEFAULT_DIBAWA,
                                hadir=pl_kirimpesan_engine.DEFAULT_HADIR,
                                lampiran_bytes=_lamp_bytes,
                                lampiran_nama=_lamp_nama,
                            )
                            _kd_hasil.append({
                                "Paket": _kp["nama_paket"][:50],
                                "Penerima (PPK)": _res.get("penerima", "-"),
                                "PDF": "✅" if _gen["sukses"] else f"❌ {_gen['pesan']}",
                                "Kirim": "✅" if _res["sukses"] else f"❌ {_res['pesan']}",
                            })

                        _kd_progress.empty()
                        _kd_ok = sum(1 for h in _kd_hasil if h["Kirim"] == "✅")
                        if _kd_ok == len(_kd_hasil):
                            st.success(f"✅ Semua {_kd_ok} undangan berhasil dikirim!")
                        else:
                            st.warning(f"⚠️ {_kd_ok} berhasil, {len(_kd_hasil)-_kd_ok} gagal.")
                        st.dataframe(
                            _kd_hasil,
                            use_container_width=True,
                            column_config={
                                "Paket":          st.column_config.TextColumn("Paket", width="large"),
                                "Penerima (PPK)": st.column_config.TextColumn("Penerima (PPK)"),
                                "PDF":            st.column_config.TextColumn("PDF", width="small"),
                                "Kirim":          st.column_config.TextColumn("Kirim", width="small"),
                            },
                            hide_index=True,
                        )

                with _kdc2:
                    if st.button("❌ Batal", key="kd_batal", use_container_width=True):
                        st.session_state["kd_konfirmasi"] = False
                        st.rerun()

        with _kd_col_detail:
            st.markdown("### Preview")
            if _kd_selected:
                st.caption(f"**{len(_kd_selected)} paket** akan dikirim undangan DPP")
                for _p in _kd_selected:
                    _tgl_a = _p["_tgl_acara"]
                    st.markdown(
                        f"- **{_p['nama_paket'][:55]}**  \n"
                        f"  📅 {_HARI_NAMA[_tgl_a.weekday()]}, {_tgl_a.day} {_BULAN_NAMA[_tgl_a.month-1]} {_tgl_a.year}  \n"
                        f"  🏢 PPK: {_p.get('nama_ppk', '-')}"
                    )
            else:
                st.info("Pilih paket di sebelah kiri.")

            st.divider()
            st.markdown("### Upload BA Reviu DPP")
            st.caption("Upload BA Hasil Reviu Dokumen Persiapan Pemilihan setelah PPK tandatangan.")

            import upload_ba_reviu_pl as _ubrpl
            _pl_rows_ba = pl_engine.load_draft_pl()
            if not _pl_rows_ba:
                st.info("⚠️ Belum ada paket PL.")
            else:
                _ba_pl_selected = []
                for _pp in _pl_rows_ba:
                    _ba_key = f"plba_chk_{_pp['kode_paket']}"
                    _ba_fkey = f"plba_file_{_pp['kode_paket']}"
                    _bcol_chk, _bcol_file = st.columns([3, 2])
                    with _bcol_chk:
                        _ba_chk = st.checkbox(
                            f"**{_pp['kode_paket']}** — {_pp['nama_paket'][:45]}",
                            value=st.session_state.get(_ba_key, False),
                            key=_ba_key,
                        )
                    with _bcol_file:
                        _ba_up = st.file_uploader(
                            "BA Reviu",
                            type=["pdf"],
                            key=_ba_fkey,
                            label_visibility="collapsed",
                        )
                        if _ba_up:
                            st.caption(f"📋 {_ba_up.name}")
                    if _ba_chk:
                        _ba_pl_selected.append({**_pp, "_ba_file": _ba_up})

                _ba_pl_tgl = st.date_input(
                    "Tanggal BA Reviu",
                    value=datetime.now().date(),
                    key="plba_tgl",
                    format="DD/MM/YYYY",
                )
                st.caption(f"{_HARI_NAMA[_ba_pl_tgl.weekday()]}, {_ba_pl_tgl.day} {_BULAN_NAMA[_ba_pl_tgl.month-1]} {_ba_pl_tgl.year}")

                _ba_pl_valid = [_p for _p in _ba_pl_selected if _p.get("_ba_file")]
                if st.button(
                    f"📤 Upload BA Reviu ({len(_ba_pl_valid)} file)",
                    key="plba_upload",
                    type="primary",
                    disabled=len(_ba_pl_valid) == 0,
                    use_container_width=True,
                ):
                    _ba_pl_progress = st.progress(0, text="Memulai upload...")
                    _ba_pl_hasil = []
                    for _i, _p in enumerate(_ba_pl_valid):
                        _ba_pl_progress.progress(
                            (_i + 1) / len(_ba_pl_valid),
                            text=f"Upload {_p['kode_paket']} ({_i+1}/{len(_ba_pl_valid)})...",
                        )
                        _res = _ubrpl.upload_ba_reviu_pl(
                            kode_paket=_p["kode_paket"],
                            file_bytes=_p["_ba_file"].getvalue(),
                            file_name=_p["_ba_file"].name,
                            tgl_ba=_ba_pl_tgl.strftime("%d-%m-%Y"),
                        )
                        _ba_pl_hasil.append({
                            "kode":   _p["kode_paket"],
                            "nama":   _p["nama_paket"][:50],
                            "sukses": _res["ok"],
                            "pesan":  f"HTTP {_res.get('status','?')}" if _res["ok"] else _res.get("error", "?"),
                        })
                    _ba_pl_progress.empty()
                    _ba_pl_ok = sum(1 for h in _ba_pl_hasil if h["sukses"])
                    _ba_pl_fail = len(_ba_pl_hasil) - _ba_pl_ok
                    if _ba_pl_fail == 0:
                        st.success(f"✅ {_ba_pl_ok} BA Reviu berhasil diupload!")
                    else:
                        st.warning(f"⚠️ {_ba_pl_ok} berhasil, {_ba_pl_fail} gagal.")
                    st.dataframe(_ba_pl_hasil, use_container_width=True, hide_index=True)

    # ── Tab 3: Buat Jadwal PL (5 tahap, push langsung ke SPSE) ─────────────
    with _pl_tab3:
        st.markdown("### Buat Jadwal Pengadaan Langsung")
        st.caption("5 tahap PL: Upload Penawaran → Pembukaan → Evaluasi → Klarifikasi+Nego → Tanda Tangan Kontrak. Push langsung ke SPSE.")

        import jadwal_engine_pl as _jepl
        _libur_map_pl = _LIBUR_MAP

        _pljd_rows = pl_engine.load_draft_pl()
        if not _pljd_rows:
            st.info("⚠️ Belum ada paket PL. Serap dari SPSE di Tab 1 terlebih dahulu.")
        else:
            _pljd_col_list, _pljd_col_detail = st.columns([3, 2])

            with _pljd_col_list:
                st.markdown("### 1. Pilih Paket")
                _pljd_a, _pljd_b = st.columns(2)
                with _pljd_a:
                    if st.button("✅ Semua", key="pljd_sel_all", use_container_width=True):
                        for _rr in _pljd_rows:
                            st.session_state[f"pljd_chk_{_rr['kode_paket']}"] = True
                        st.rerun()
                with _pljd_b:
                    if st.button("⬜ Kosong", key="pljd_sel_none", use_container_width=True):
                        for _rr in _pljd_rows:
                            st.session_state[f"pljd_chk_{_rr['kode_paket']}"] = False
                        st.rerun()

                _pljd_selected = []
                for _rr in _pljd_rows:
                    _key = f"pljd_chk_{_rr['kode_paket']}"
                    _chk = st.checkbox(
                        f"{_rr['nama_paket'][:55]} ({_rr.get('jenis_pl','?')})",
                        value=st.session_state.get(_key, False),
                        key=_key,
                    )
                    if _chk:
                        _pljd_selected.append(_rr)

                st.caption(f"**{len(_pljd_selected)}** dari **{len(_pljd_rows)}** paket dipilih")

            with _pljd_col_detail:
                st.markdown("### 2. Tanggal Mulai (T1)")
                _pljd_beda = st.checkbox("Jadwal berbeda per paket", value=False, key="pljd_beda")

                if not _pljd_beda:
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _pljd_tgl_global = st.date_input(
                            "Tanggal",
                            value=datetime.now().date(),
                            format="DD/MM/YYYY",
                            key="pljd_tgl_global",
                        )
                        st.markdown(f"**{_HARI_NAMA[_pljd_tgl_global.weekday()]}, {_pljd_tgl_global.day} {_BULAN_NAMA[_pljd_tgl_global.month-1]} {_pljd_tgl_global.year}**")
                    with _c2:
                        _pljd_jam_global = st.time_input(
                            "Jam",
                            value=datetime.strptime("08:00", "%H:%M").time(),
                            key="pljd_jam_global",
                        )
                    if _pljd_tgl_global in _libur_map_pl:
                        st.warning(f"⚠️ **{_libur_map_pl[_pljd_tgl_global]}**")
                else:
                    if not _pljd_selected:
                        st.info("Pilih paket dulu.")
                    else:
                        for _p in _pljd_selected:
                            _ktgl = f"pljd_tgl_{_p['kode_paket']}"
                            _kjam = f"pljd_jam_{_p['kode_paket']}"
                            _cna, _cdt, _cjm = st.columns([3, 2, 1])
                            with _cna:
                                st.markdown(f"**{_p['nama_paket'][:35]}**")
                            with _cdt:
                                st.date_input(
                                    "Tgl",
                                    value=st.session_state.get(_ktgl, datetime.now().date()),
                                    format="DD/MM/YYYY",
                                    key=_ktgl,
                                    label_visibility="collapsed",
                                )
                            with _cjm:
                                st.time_input(
                                    "Jam",
                                    value=st.session_state.get(_kjam, datetime.strptime("08:00", "%H:%M").time()),
                                    key=_kjam,
                                    label_visibility="collapsed",
                                )

                st.divider()
                st.caption("⚠️ Akan menimpa jadwal yang sudah ada di SPSE.")

                _pljd_submit = st.button(
                    f"🚀 Push Jadwal ke SPSE ({len(_pljd_selected)} paket)",
                    type="primary",
                    use_container_width=True,
                    disabled=len(_pljd_selected) == 0,
                    key="pljd_submit_btn",
                )

                if _pljd_submit:
                    _hasil = []
                    _prog = st.progress(0, text="Mulai...")
                    for _i, _p in enumerate(_pljd_selected):
                        _prog.progress((_i + 1) / len(_pljd_selected),
                                       text=f"{_p['kode_paket']} ({_i+1}/{len(_pljd_selected)})...")
                        if _pljd_beda:
                            _tgl = st.session_state.get(f"pljd_tgl_{_p['kode_paket']}", datetime.now().date())
                            _jam = st.session_state.get(f"pljd_jam_{_p['kode_paket']}", datetime.strptime("08:00", "%H:%M").time())
                        else:
                            _tgl = _pljd_tgl_global
                            _jam = _pljd_jam_global
                        _t1 = datetime.combine(_tgl, _jam)

                        _kp = _p.get("kode_paket")
                        if not _kp:
                            _hasil.append({"paket": _p['nama_paket'][:40], "ok": False, "pesan": "kode_paket kosong"})
                            continue
                        try:
                            _r = _jepl.submit_full_pl(_kp, _t1)
                            _sub = _r["submit_result"]
                            _hasil.append({
                                "paket":  _p['nama_paket'][:40],
                                "ok":     _sub["ok"],
                                "pesan":  f"HTTP {_sub['status']}",
                                "mulai":  _t1.strftime("%d/%m/%Y %H:%M"),
                            })
                            # Simpan T1 + T5 selesai ke Supabase
                            try:
                                _jad = _r["jadwal_list"]
                                pl_engine.simpan_paket_pl({
                                    "kode_paket":            _p["kode_paket"],
                                    "tgl_batas_penawaran":   _jad[0]["selesai"].strftime("%Y-%m-%d"),
                                    "tgl_buka_penawaran":    _jad[1]["mulai"].strftime("%Y-%m-%d"),
                                    "tgl_evaluasi":          _jad[2]["mulai"].strftime("%Y-%m-%d"),
                                    "tgl_negosiasi":         _jad[3]["mulai"].strftime("%Y-%m-%d"),
                                    "tgl_penetapan":         _jad[4]["mulai"].strftime("%Y-%m-%d"),
                                })
                            except Exception:
                                pass
                        except Exception as _e:
                            _hasil.append({"paket": _p['nama_paket'][:40], "ok": False, "pesan": str(_e)[:100]})

                    _prog.empty()
                    _sukses = sum(1 for h in _hasil if h["ok"])
                    _gagal = len(_hasil) - _sukses
                    if _gagal == 0:
                        st.success(f"✅ Semua {_sukses} paket berhasil dijadwalkan!")
                    else:
                        st.warning(f"⚠️ {_sukses} sukses, {_gagal} gagal")
                    for h in _hasil:
                        _ic = "✅" if h["ok"] else "❌"
                        st.markdown(f"{_ic} **{h['paket']}** — {h['pesan']}" + (f" — mulai {h.get('mulai','')}" if h["ok"] else ""))

                with st.expander("ℹ️ Libur Nasional Tersisa"):
                    _hari_ini = datetime.now().date()
                    _sisa = sorted(d for d in _libur_map_pl if d >= _hari_ini)
                    for d in _sisa[:15]:
                        st.write(f"• {_HARI_NAMA[d.weekday()]}, {d.day} {_BULAN_NAMA[d.month-1]} {d.year} — {_libur_map_pl[d]}")

    # ── Tab 4: Setup Paket PL (LDK + Masa Berlaku + Checklist + Upload Dokpil) ─
    with _pl_tab4:
        st.markdown("### Setup Paket Pengadaan Langsung")
        st.caption(
            "Submit LDK (Persyaratan Kualifikasi) + Masa Berlaku Penawaran + "
            "Checklist Dokumen Penawaran + Upload Dokumen Pemilihan (Dokpil PDF) ke SPSE. "
            "KAK / Rancangan Kontrak / Uraian Singkat / Informasi Lainnya tugas PPK (bukan PP)."
        )

        import dokpil_engine_pl as _depl
        import upload_dokpil_pl as _udpl

        @st.cache_data(ttl=3600)
        def _lookup_singkatan_dinas(satker: str) -> str:
            if not satker:
                return "DPUPR"
            try:
                from config import sb as _sb_f
                r = _sb_f().table("master_dinas").select("singkatan").ilike("nama_dinas", f"%{satker[:30]}%").limit(1).execute()
                if r.data:
                    return r.data[0].get("singkatan") or "DPUPR"
            except Exception:
                pass
            return "DPUPR"

        def _lookup_telepon_pp(satker: str) -> str:
            if not satker:
                return ""
            try:
                from config import sb as _sb_f
                r = _sb_f().table("master_dinas").select("telepon_pp").ilike("nama_dinas", f"%{satker[:30]}%").limit(1).execute()
                if r.data:
                    return r.data[0].get("telepon_pp") or ""
            except Exception:
                pass
            return ""

        _plsp_rows = pl_engine.load_draft_pl()
        if not _plsp_rows:
            st.info("⚠️ Belum ada paket PL. Serap dari SPSE di Tab 1 terlebih dahulu.")
        else:
            _plsp_col_list, _plsp_col_kanan = st.columns([2, 3])

            with _plsp_col_list:
                st.markdown("### 1. Pilih Paket + Upload Dokpil")
                _plsp_sel_all, _plsp_sel_none = st.columns(2)
                with _plsp_sel_all:
                    if st.button("✅ Semua", key="plsp_sel_all", use_container_width=True):
                        for _rr in _plsp_rows:
                            st.session_state[f"plsp_chk_{_rr['kode_paket']}"] = True
                        st.rerun()
                with _plsp_sel_none:
                    if st.button("⬜ Kosong", key="plsp_sel_none", use_container_width=True):
                        for _rr in _plsp_rows:
                            st.session_state[f"plsp_chk_{_rr['kode_paket']}"] = False
                        st.rerun()

                import sbu_picker as _sp

                _plsp_selected = []
                for _rr in _plsp_rows:
                    _kp_key = _rr["kode_paket"]
                    _plsp_chk_key  = f"plsp_chk_{_kp_key}"
                    _plsp_file_key = f"plsp_dokpil_{_kp_key}"

                    _col_chk, _col_file = st.columns([3, 2])
                    with _col_chk:
                        _chk = st.checkbox(
                            f"{_rr['nama_paket'][:55]} ({_rr.get('jenis_pl','?')})",
                            value=st.session_state.get(_plsp_chk_key, False),
                            key=_plsp_chk_key,
                        )
                    with _col_file:
                        _dokpil_up = st.file_uploader(
                            "Dokpil PDF",
                            type=["pdf"],
                            key=_plsp_file_key,
                            label_visibility="collapsed",
                        )
                        if _dokpil_up:
                            _ku_prev = _rr.get("kode_unik") or "?"
                            _sk_prev = _lookup_singkatan_dinas(_rr.get("satker", ""))
                            _tgl_prev = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            _no_prev = _udpl.generate_nomor_dokpil(
                                nama_paket=_rr["nama_paket"],
                                kode_unik=_ku_prev,
                                skpd_singkat=_sk_prev,
                                tahun=_tgl_prev.year,
                            )
                            st.caption(f"📄 {_dokpil_up.name}  \n📋 `{_no_prev}`")

                    if _chk:
                        _plsp_selected.append({
                            **_rr,
                            "_dokpil_file": _dokpil_up,
                        })

                st.caption(f"**{len(_plsp_selected)}** dari **{len(_plsp_rows)}** paket dipilih")

            with _plsp_col_kanan:
                st.markdown("### 2. Konfigurasi Setup Paket")

                if not _plsp_selected:
                    st.info("Pilih paket di sebelah kiri.")
                else:
                    # ── SBU Global (satu pilihan apply ke semua paket terpilih) ─────
                    st.markdown("**SBU Global** *(satu pilihan apply ke semua paket terpilih)*")
                    _plsp_klas_list = ["(auto-detect dari paket pertama)"] + _sp.list_klasifikasi()

                    # Auto-detect dari paket pertama terpilih
                    _first_p = _plsp_selected[0]
                    _detected_g = _sp.detect_from_draft(
                        _first_p.get("sbu_baru") or "", _first_p.get("sbu_lama") or ""
                    )
                    _g_kode_baru = _detected_g.get("kode_baru", "")
                    _g_kode_lama = _detected_g.get("kode_lama", "")

                    _g_klas_default = 0
                    if _g_kode_baru:
                        _baru_info_g = _sp.get_sbu_baru_by_kode(_g_kode_baru)
                        _klas_det_g = (_baru_info_g or {}).get("klasifikasi", "")
                        if _klas_det_g in _plsp_klas_list:
                            _g_klas_default = _plsp_klas_list.index(_klas_det_g)

                    if _g_kode_baru:
                        st.caption(f"Auto-detect dari **{_first_p['nama_paket'][:40]}**: `{_g_kode_baru}` / `{_g_kode_lama}`")

                    _g_picked_klas = st.selectbox(
                        "Klasifikasi",
                        _plsp_klas_list,
                        index=_g_klas_default,
                        key="plsp_global_klas",
                    )

                    # SBU Baru dropdown
                    if _g_picked_klas and _g_picked_klas != "(auto-detect dari paket pertama)":
                        _g_baru_options = _sp.list_sbu_baru_by_klasifikasi(_g_picked_klas)
                    else:
                        _g_baru_options = []
                        if _g_kode_baru:
                            _g_baru_options = [_sp.get_sbu_baru_by_kode(_g_kode_baru)]
                    _g_baru_labels = [
                        f"{b['kode']} — {(b.get('nama_singkat') or b.get('nama_full',''))[:70]}"
                        for b in _g_baru_options if b
                    ]
                    _g_baru_default = 0
                    for _gi, _gb in enumerate(_g_baru_options):
                        if _gb and _gb.get("kode") == _g_kode_baru:
                            _g_baru_default = _gi
                            break
                    _g_picked_baru_label = st.selectbox(
                        "SBU Baru (KBLI 2020)",
                        _g_baru_labels or ["(pilih klasifikasi dulu)"],
                        index=_g_baru_default if _g_baru_labels else 0,
                        key="plsp_global_sbu_baru",
                    )
                    _g_picked_baru_kode = (
                        _g_picked_baru_label.split(" — ", 1)[0]
                        if _g_baru_labels and " — " in _g_picked_baru_label else ""
                    )

                    # SBU Lama dropdown (opsional — kosongkan jika tidak dipersyaratkan)
                    _g_lama_options = _sp.list_sbu_lama_padanan(_g_picked_baru_kode) if _g_picked_baru_kode else []
                    _g_lama_labels = ["(tidak dipersyaratkan / hanya SBU 2020)"] + [
                        f"{l['kode']} — {(l.get('nama_singkat') or l.get('nama_full',''))[:70]}"
                        for l in _g_lama_options
                    ]
                    _g_lama_default = 0  # default: tidak dipersyaratkan
                    for _gli, _gl in enumerate(_g_lama_options):
                        if _gl.get("kode") == _g_kode_lama:
                            _g_lama_default = _gli + 1
                            break
                    _g_picked_lama_label = st.selectbox(
                        "SBU Lama (KBLI 2017) — opsional, kosongkan jika tidak dipersyaratkan",
                        _g_lama_labels,
                        index=_g_lama_default,
                        key="plsp_global_sbu_lama",
                    )
                    _g_picked_lama_kode = (
                        _g_picked_lama_label.split(" — ", 1)[0]
                        if " — " in _g_picked_lama_label else ""
                    )

                    # Resolve nama_full SBU global
                    _sbu_baru_global = ""
                    _sbu_lama_global = ""
                    if _g_picked_baru_kode:
                        _baru_obj_g = _sp.get_sbu_baru_by_kode(_g_picked_baru_kode)
                        _sbu_baru_global = (_baru_obj_g or {}).get("nama_full", "")
                    if _g_picked_lama_kode:
                        _lama_obj_g = _sp.get_sbu_lama_by_kode(_g_picked_lama_kode)
                        _sbu_lama_global = (_lama_obj_g or {}).get("nama_full", "")
                    # Fallback SBU baru ke paket pertama jika dropdown kosong
                    if not _sbu_baru_global:
                        _sbu_baru_global = _first_p.get("sbu_baru") or ""
                    # SBU lama: tidak fallback ke paket (user pilih sadar opsional)

                    if _sbu_baru_global:
                        st.caption(f"🔹 Baru: `{_sbu_baru_global[:80]}`")
                    if _sbu_lama_global:
                        st.caption(f"🔸 Lama: `{_sbu_lama_global[:80]}`")
                    elif _sbu_baru_global:
                        st.caption("ℹ️ SBU Lama tidak dipersyaratkan — hanya SBU 2020 di LDK")

                    if st.button(
                        f"💾 Simpan SBU Global ke {len(_plsp_selected)} paket",
                        key="plsp_save_sbu_btn", use_container_width=True,
                    ):
                        from config import sb as _sb_factory
                        _client_sbu = _sb_factory()
                        _ok_sbu = 0
                        for _p in _plsp_selected:
                            try:
                                _client_sbu.table("draft_paket_pl").update({
                                    "sbu_baru": _sbu_baru_global,
                                    "sbu_lama": _sbu_lama_global,
                                }).eq("kode_paket", _p["kode_paket"]).execute()
                                _ok_sbu += 1
                            except Exception as _e:
                                st.error(f"❌ {_p['nama_paket'][:40]}: {_e}")
                        st.success(f"✅ {_ok_sbu}/{len(_plsp_selected)} paket disimpan ke Supabase")

                    st.divider()

                    # ── LDK config: centang admin + teknis
                    st.markdown("**Syarat Administrasi** *(default: centang idx 0-3, skip 422/423)*")
                    _ADMIN_LABEL = {
                        0: "413 — KSWP (Wajib Pajak)",
                        1: "414 — Kapasitas Hukum (Akta Pendirian)",
                        2: "415 — Pakta Integritas",
                        3: "416 — Surat Pernyataan Peserta",
                        4: "422 — (skip default)",
                        5: "423 — (skip default)",
                    }
                    _ldk_centang_admin_indices = []
                    _cols_adm = st.columns(2)
                    for _i, _lbl in _ADMIN_LABEL.items():
                        with _cols_adm[_i % 2]:
                            _default_adm = _i in (0, 1, 2, 3)
                            if st.checkbox(_lbl, value=_default_adm, key=f"plsp_admin_idx_{_i}"):
                                _ldk_centang_admin_indices.append(_i)

                    st.markdown("**Syarat Teknis JKK Konstruksi** *(default: centang 0+1)*")
                    _TEKNIS_LABEL = {
                        0: "433 — Pengalaman ≥1 JKK 4thn terakhir",
                        1: "434 — Pengalaman pekerjaan sejenis",
                        2: "435 — Pengalaman sejenis 10thn terakhir",
                        3: "436 — Dispensasi penyedia kecil baru <3thn",
                    }
                    _ldk_teknis_indices = []
                    _cols_tk = st.columns(2)
                    for _i, _lbl in _TEKNIS_LABEL.items():
                        with _cols_tk[_i % 2]:
                            _default = _i in (0, 1)
                            if st.checkbox(_lbl, value=_default, key=f"plsp_teknis_idx_{_i}"):
                                _ldk_teknis_indices.append(_i)

                    # ── Tambah Syarat Kinerja Penyedia (custom row) ───────────
                    import ldk_config as _ldk_cfg_pl
                    _ldk_tambah_kinerja = st.checkbox(
                        "➕ Tambah Syarat Teknis: Penilaian Kinerja Penyedia (ckm_id=996)",
                        value=True, key="plsp_centang_kinerja",
                    )
                    _ldk_kinerja_text = ""
                    if _ldk_tambah_kinerja:
                        _ldk_kinerja_text = st.text_area(
                            "Teks Syarat Kinerja",
                            value=_ldk_cfg_pl.KINERJA_PENYEDIA_DEFAULT,
                            key="plsp_kinerja_text",
                            height=120,
                        )

                    st.caption(
                        "ℹ️ Default: admin all + teknis idx 0+1 (Pengalaman + Dispensasi). "
                        "NPWP/Akta/Pakta auto by sistem. Kinerja Penyedia = custom row ckm_id=996."
                    )

                    st.divider()

                    # ── Masa Berlaku Penawaran
                    _ldk_masa_berlaku = st.number_input(
                        "Masa Berlaku Penawaran (hari)",
                        min_value=1, max_value=180, value=30,
                        key="plsp_masa_berlaku",
                    )

                    st.divider()

                    # ── Checklist Dokumen Penawaran
                    st.markdown("**Checklist Dokumen Penawaran**")
                    _cd_a, _cd_b, _cd_c = st.columns(3)
                    with _cd_a:
                        _cd_centang_admin = st.checkbox(
                            "Admin (Masa Berlaku, Surat Penawaran)",
                            value=True, key="plsp_cd_admin",
                        )
                    with _cd_b:
                        _cd_centang_syarat = st.checkbox(
                            "Teknis (Metodologi, Pengalaman, Kualif TA)",
                            value=True, key="plsp_cd_syarat",
                        )
                    with _cd_c:
                        _cd_centang_harga = st.checkbox(
                            "Harga (DKH, AHS, Remunerasi)",
                            value=True, key="plsp_cd_harga",
                        )

                    st.divider()

                    # ── Generate Nomor Dokpil
                    st.markdown("**Tanggal Dokumen Pemilihan**")
                    _plsp_tgl_dokpil = st.date_input(
                        "Tanggal Dokpil",
                        value=datetime.now().date(),
                        key="plsp_tgl_dokpil",
                        format="DD/MM/YYYY",
                    )
                    st.caption(
                        f"{_HARI_NAMA[_plsp_tgl_dokpil.weekday()]}, "
                        f"{_plsp_tgl_dokpil.day} {_BULAN_NAMA[_plsp_tgl_dokpil.month-1]} "
                        f"{_plsp_tgl_dokpil.year}"
                    )

                    st.divider()

                    # ── Submit
                    if st.button(
                        f"🚀 Push Setup ke SPSE ({len(_plsp_selected)} paket)",
                        key="plsp_submit_btn",
                        type="primary",
                        use_container_width=True,
                    ):
                        _hasil_sp = []
                        _prog_sp = st.progress(0, text="Mulai...")
                        from config import sb as _sb_factory_sp
                        _client_sp = _sb_factory_sp()
                        for _i, _p in enumerate(_plsp_selected):
                            _kp = _p["kode_paket"]
                            _id_nt = _p.get("id_nontender")
                            _nm = _p["nama_paket"][:40]
                            _prog_sp.progress((_i + 1) / len(_plsp_selected),
                                              text=f"{_nm} ({_i+1}/{len(_plsp_selected)})...")

                            # 0. Simpan tgl_dokpil + SBU global ke Supabase
                            try:
                                _client_sp.table("draft_paket_pl").update({
                                    "tgl_dokpil": _plsp_tgl_dokpil.isoformat(),
                                    "sbu_baru": _sbu_baru_global,
                                    "sbu_lama": _sbu_lama_global,
                                }).eq("kode_paket", _kp).execute()
                            except Exception as _e_save:
                                _hasil_sp.append({"paket": _nm, "step": "Simpan Supabase", "ok": False, "pesan": str(_e_save)[:80]})

                            # 1. Submit LDK (kode_paket, bukan id_nontender)
                            try:
                                _r_ldk = _depl.submit_ldk_pl(
                                    _kp,
                                    sbu_baru=_sbu_baru_global,
                                    sbu_lama=_sbu_lama_global,
                                    centang_admin_indices=_ldk_centang_admin_indices,
                                    teknis_centang_indices=_ldk_teknis_indices,
                                    kinerja_text=_ldk_kinerja_text,
                                )
                                _ijin_note = f" | ijin CDP: {_r_ldk.get('ijin_update','—')}" if _r_ldk.get("ijin_update") else ""
                                _hasil_sp.append({
                                    "paket": _nm, "step": "LDK",
                                    "ok": _r_ldk["ok"], "pesan": f"HTTP {_r_ldk['status']}{_ijin_note}",
                                })
                            except Exception as _e:
                                _hasil_sp.append({"paket": _nm, "step": "LDK", "ok": False, "pesan": str(_e)[:80]})

                            # 2. Masa berlaku penawaran
                            try:
                                _r_mb = _depl.submit_masa_berlaku_pl(_kp, int(_ldk_masa_berlaku))
                                _hasil_sp.append({
                                    "paket": _nm, "step": "Masa Berlaku",
                                    "ok": _r_mb["ok"], "pesan": f"HTTP {_r_mb['status']} ({_ldk_masa_berlaku} hari)",
                                })
                            except Exception as _e:
                                _hasil_sp.append({"paket": _nm, "step": "Masa Berlaku", "ok": False, "pesan": str(_e)[:80]})

                            # 3. Checklist Dokumen Penawaran
                            try:
                                _r_cd = _depl.submit_checklist_pl(
                                    _kp,
                                    centang_admin_all=_cd_centang_admin,
                                    centang_syarat_all=_cd_centang_syarat,
                                    centang_harga_all=_cd_centang_harga,
                                )
                                _hasil_sp.append({
                                    "paket": _nm, "step": "Checklist Dok Penawaran",
                                    "ok": _r_cd["ok"], "pesan": f"HTTP {_r_cd['status']}",
                                })
                            except Exception as _e:
                                _hasil_sp.append({"paket": _nm, "step": "Checklist Dok Penawaran", "ok": False, "pesan": str(_e)[:80]})

                            # 4. Upload Dokpil PDF (jika ada file)
                            _dokpil_file = _p.get("_dokpil_file")
                            if _dokpil_file and _id_nt:
                                try:
                                    # Generate Nomor Dokpil: 000.3.3/01/PL/PP-NN/{KodeUnik}/{SkpdSingkat}/{Tahun}
                                    _kode_unik = _p.get("kode_unik") or ""
                                    _skpd_singkat = _lookup_singkatan_dinas(_p.get("satker", ""))
                                    _nomor_dokpil = _udpl.generate_nomor_dokpil(
                                        nama_paket=_p["nama_paket"],
                                        kode_unik=_kode_unik,
                                        skpd_singkat=_skpd_singkat,
                                        tahun=_plsp_tgl_dokpil.year,
                                    )
                                    _r_up = _udpl.upload_dokpil_pl(
                                        kode_paket=_kp,
                                        file_bytes=_dokpil_file.getvalue(),
                                        file_name=_dokpil_file.name,
                                        nomor_dokpil=_nomor_dokpil,
                                        tgl_dokpil=_plsp_tgl_dokpil.strftime("%d-%m-%Y"),
                                    )
                                    _hasil_sp.append({
                                        "paket": _nm, "step": "Upload Dokpil",
                                        "ok": _r_up["ok"],
                                        "pesan": f"HTTP {_r_up.get('status','?')} | {_nomor_dokpil}",
                                    })
                                    if _r_up["ok"]:
                                        try:
                                            _client_sp.table("draft_paket_pl").update({
                                                "nomor_dokpil": _nomor_dokpil,
                                            }).eq("kode_paket", _kp).execute()
                                        except Exception:
                                            pass
                                except Exception as _e:
                                    _hasil_sp.append({
                                        "paket": _nm, "step": "Upload Dokpil",
                                        "ok": False, "pesan": str(_e)[:80],
                                    })
                            elif _dokpil_file and not _id_nt:
                                _hasil_sp.append({
                                    "paket": _nm, "step": "Upload Dokpil",
                                    "ok": False, "pesan": "id_nontender kosong, tidak bisa upload",
                                })

                        _prog_sp.empty()
                        _sukses_sp = sum(1 for h in _hasil_sp if h["ok"])
                        _gagal_sp = len(_hasil_sp) - _sukses_sp
                        if _gagal_sp == 0:
                            st.success(f"✅ Semua {_sukses_sp} operasi sukses!")
                        else:
                            st.warning(f"⚠️ {_sukses_sp} sukses, {_gagal_sp} gagal")

                        # Tampilkan log per paket
                        import pandas as _pd
                        _df_sp = _pd.DataFrame(_hasil_sp)
                        if not _df_sp.empty:
                            _df_sp["status"] = _df_sp["ok"].map({True: "✅", False: "❌"})
                            st.dataframe(
                                _df_sp[["status", "paket", "step", "pesan"]],
                                use_container_width=True, hide_index=True,
                            )

    # ── Tab 4 Section 2: Pilih Penyedia ke SPSE ─────────────────────────────
    with _pl_tab4:
        st.divider()
        st.markdown("### 🏢 Pilih Penyedia ke SPSE")
        st.caption(
            "Cari penyedia by NPWP → klik pilih ke SPSE (prioritas kabupaten Tapin, "
            "fallback semua kabupaten Kalsel propinsi 22)."
        )

        _pp_rows = pl_engine.load_draft_pl()
        if _pp_rows:
            import pilih_penyedia_pl as _ppp

            _pp_col_list, _pp_col_act = st.columns([2, 3])

            with _pp_col_list:
                st.markdown("**Pilih paket:**")
                _pp_sel_all, _pp_sel_none = st.columns(2)
                with _pp_sel_all:
                    if st.button("✅ Semua", key="pp_sel_all", use_container_width=True):
                        for _rr in _pp_rows:
                            st.session_state[f"pp_chk_{_rr['kode_paket']}"] = True
                        st.rerun()
                with _pp_sel_none:
                    if st.button("⬜ Kosong", key="pp_sel_none", use_container_width=True):
                        for _rr in _pp_rows:
                            st.session_state[f"pp_chk_{_rr['kode_paket']}"] = False
                        st.rerun()

                _pp_selected = []
                for _rr in _pp_rows:
                    _kp = _rr["kode_paket"]
                    _npwp_disp = _rr.get("npwp_penyedia") or "—"
                    _nama_disp = _rr.get("nama_penyedia") or "—"
                    _chk = st.checkbox(
                        f"{_rr['nama_paket'][:45]}",
                        value=st.session_state.get(f"pp_chk_{_kp}", False),
                        key=f"pp_chk_{_kp}",
                        help=f"Penyedia: {_nama_disp} | NPWP: {_npwp_disp}",
                    )
                    if _chk:
                        _pp_selected.append(_rr)

                st.caption(f"**{len(_pp_selected)}** paket dipilih")

            with _pp_col_act:
                if not _pp_selected:
                    st.info("Pilih paket di sebelah kiri.")
                else:
                    # Tabel ringkas paket terpilih
                    import pandas as _pd2
                    _pp_df = _pd2.DataFrame([{
                        "Paket": r["nama_paket"][:45],
                        "Penyedia": r.get("nama_penyedia") or "—",
                        "NPWP": r.get("npwp_penyedia") or "—",
                    } for r in _pp_selected])
                    st.dataframe(_pp_df, use_container_width=True, hide_index=True)

                    _invalid = [r for r in _pp_selected if not r.get("npwp_penyedia")]
                    if _invalid:
                        st.warning(
                            f"⚠️ {len(_invalid)} paket belum ada NPWP penyedia: "
                            + ", ".join(r["nama_paket"][:30] for r in _invalid)
                        )

                    _valid_pp = [r for r in _pp_selected if r.get("npwp_penyedia")]
                    if _valid_pp:
                        if st.button(
                            f"🏢 Pilih Semua Penyedia ke SPSE ({len(_valid_pp)} paket)",
                            key="pp_submit_btn",
                            type="primary",
                            use_container_width=True,
                        ):
                            import spse_browser as _spse_br
                            _ck_pp = _spse_br.get_spse_cookies()
                            _base_pp = pl_engine.BASE_URL

                            _pp_hasil = []
                            _pp_prog = st.progress(0, text="Mulai pilih penyedia...")
                            for _i_pp, _pp_r in enumerate(_valid_pp):
                                _pp_nm = _pp_r["nama_paket"][:40]
                                _pp_prog.progress(
                                    (_i_pp + 1) / len(_valid_pp),
                                    text=f"{_pp_nm} ({_i_pp+1}/{len(_valid_pp)})...",
                                )
                                try:
                                    _res_pp = _ppp.cari_dan_pilih_penyedia(
                                        kode_paket=_pp_r["kode_paket"],
                                        npwp=_pp_r.get("npwp_penyedia") or "",
                                        cookie_str=_ck_pp,
                                        base_url=_base_pp,
                                        nama_penyedia=_pp_r.get("nama_penyedia") or "",
                                    )
                                    _pp_hasil.append({
                                        "paket": _pp_nm,
                                        "ok": _res_pp["ok"],
                                        "pesan": (
                                            f"✅ {_res_pp.get('nama','?')} (kab {_res_pp.get('kabupaten_id','')})"
                                            if _res_pp["ok"]
                                            else f"❌ {_res_pp.get('pesan','?')}"
                                        ),
                                    })
                                except Exception as _e_pp:
                                    _pp_hasil.append({
                                        "paket": _pp_nm,
                                        "ok": False,
                                        "pesan": f"❌ Error: {str(_e_pp)[:80]}",
                                    })

                            _pp_prog.empty()
                            _pp_ok = sum(1 for h in _pp_hasil if h["ok"])
                            if _pp_ok == len(_pp_hasil):
                                st.success(f"✅ {_pp_ok}/{len(_pp_hasil)} paket berhasil dipilih penyedia!")
                            else:
                                st.warning(f"⚠️ {_pp_ok}/{len(_pp_hasil)} sukses")

                            _df_pp = _pd2.DataFrame(_pp_hasil)
                            if not _df_pp.empty:
                                st.dataframe(
                                    _df_pp[["paket", "pesan"]],
                                    use_container_width=True, hide_index=True,
                                )

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
        st.markdown("#### 🔁 Re-parse PDF Paket")
        st.caption("Parse ulang PDF Lembar Disposisi untuk paket yang sudah ada di DB — tanpa harus serap inbox ulang.")

        _tahun_skrg_rp = str(datetime.now().year)
        _reparse_opts = {f"{_r.get('nomor_urut','?')}. {_r.get('nama_tender','?')} ({_r.get('kode_tender','')})": _r
                        for _r in _draft_rows
                        if (_r.get("link_pdf") or _r.get("nomor_surat_dinas"))
                        and _tahun_skrg_rp in str(_r.get("nomor_pp") or "")
                        and not str(_r.get("kode_tender", "")).startswith("_err_")}
        _reparse_opts_label = ["(pilih paket)"] + list(_reparse_opts.keys())
        _reparse_sel = st.selectbox("Pilih paket", _reparse_opts_label, key="sel_reparse_pdf")

        if _reparse_sel != "(pilih paket)":
            _reparse_row = _reparse_opts[_reparse_sel]
            _reparse_link = _reparse_row.get("link_pdf") or ""
            if not _reparse_link:
                st.caption("⚠️ Link PDF belum tersimpan — akan di-fetch otomatis saat re-parse.")
            if st.button("🔁 Re-parse PDF", type="secondary", use_container_width=True, key="btn_reparse_pdf"):
                with st.spinner("Parsing PDF..."):
                    try:
                        _rp_kode = _reparse_row["kode_tender"]
                        # Jika link_pdf belum ada, fetch dari detail pesan
                        if not _reparse_link:
                            _rp_detail = inbox_engine.parse_detail_pesan(str(_reparse_row.get("id_pesan", "")))
                            _reparse_link = _rp_detail.get("link_pdf") or ""
                        if not _reparse_link:
                            st.error("Tidak bisa mendapatkan link PDF untuk paket ini.")
                        else:
                            _rp_hasil = inbox_engine.parse_pdf_inmemory(_reparse_link)
                            _rp_data  = {k: v for k, v in _rp_hasil.items() if k in inbox_engine._KOLOM_DRAFT_PAKET and v}
                            _rp_data["link_pdf"] = _reparse_link  # simpan link agar tidak perlu fetch lagi
                            inbox_engine._sb().table("draft_paket").update(_rp_data).eq("kode_tender", _rp_kode).execute()
                            st.success(f"✅ Re-parse berhasil. Field diperbarui: {', '.join(_rp_data.keys())}")
                            with st.expander("Detail hasil parse"):
                                for k, v in _rp_hasil.items():
                                    st.text(f"{k}: {v}")
                    except Exception as _rp_e:
                        st.error(f"Gagal re-parse: {_rp_e}")

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
                    # Enrich dengan kode_unik + kode_pokja dari Supabase
                    kirimpesan_engine.enrich_paket_supabase(_gd0.get("paket", []))
                    kirimpesan_engine.enrich_paket_supabase(_ga0.get("paket", []))
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
                    kirimpesan_engine.enrich_paket_supabase(_gd_r.get("paket", []))
                    kirimpesan_engine.enrich_paket_supabase(_ga_r.get("paket", []))
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

        # ── Cek Semua Dokumen PPK (batch) ──
        if st.session_state.get("global_paket_draft"):
            st.divider()
            if st.button("🔍 Cek Semua Dokumen PPK", use_container_width=True, key="btn_cek_semua_dok"):
                import dokumen_ppk_engine as _dpk_batch
                # Ambil semua paket yg punya dokumen_snapshot dari Supabase
                _snap_rows = inbox_engine._sb().table("draft_paket") \
                    .select("kode_tender, folder_dibuat, dokumen_snapshot") \
                    .not_.is_("dokumen_snapshot", "null") \
                    .execute()
                _snap_paket = _snap_rows.data if _snap_rows.data else []
                if not _snap_paket:
                    st.info("Belum ada paket dengan snapshot dokumen. Buat folder paket dulu.")
                else:
                    # Build lookup nama paket dari SPSE data
                    _nama_map = {p["kode"]: p["nama"] for p in st.session_state["global_paket_draft"].get("paket", [])}
                    _hasil_batch = []
                    with st.status(f"Memeriksa {len(_snap_paket)} paket...", expanded=True) as _cek_st:
                        for _sp in _snap_paket:
                            _kt = _sp["kode_tender"]
                            _nama = _nama_map.get(_kt) or _sp.get("folder_dibuat") or _kt
                            _cek_st.write(f"🔍 {_nama[:50]}...")
                            try:
                                _diff = _dpk_batch.cek_update_dokumen(_kt)
                                # Deteksi cookie invalid: semua endpoint return kosong
                                _snap_baru_total = sum(len(v) for v in _diff["snapshot_baru"].values())
                                _cookie_invalid = _snap_baru_total == 0
                                # Hanya hitung ada_update jika cookie valid
                                _ada_update = (not _cookie_invalid) and bool(
                                    _diff["berubah"] or _diff["baru"] or _diff.get("hilang")
                                )
                                _hasil_batch.append({
                                    "kode": _kt,
                                    "nama": _nama,
                                    "berubah": _diff["berubah"],
                                    "baru": _diff["baru"],
                                    "hilang": _diff.get("hilang", []),
                                    "ada_update": _ada_update,
                                    "cookie_invalid": _cookie_invalid,
                                })
                            except Exception as _e_cek:
                                _hasil_batch.append({
                                    "kode": _kt,
                                    "nama": _nama,
                                    "error": str(_e_cek),
                                    "ada_update": False,
                                })
                        _cek_st.update(label="✅ Selesai cek dokumen PPK", state="complete")
                    # Simpan juga folder_dibuat per kode untuk download nanti
                    _folder_map = {r["kode_tender"]: r.get("folder_dibuat", "") for r in _snap_paket}
                    st.session_state["_batch_cek_hasil"] = _hasil_batch
                    st.session_state["_batch_folder_map"] = _folder_map

            # Tampil hasil batch (persist setelah rerun)
            if "_batch_cek_hasil" in st.session_state:
                _bh = st.session_state["_batch_cek_hasil"]
                _ada_update_list = [x for x in _bh if x.get("ada_update")]
                _error_list = [x for x in _bh if x.get("error")]
                _cookie_invalid_list = [x for x in _bh if x.get("cookie_invalid") and not x.get("error")]
                if _cookie_invalid_list:
                    st.error(f"⚠️ Cookie SPSE expired ({len(_cookie_invalid_list)} paket tidak bisa dicek). Login ulang di Chrome.")
                if _ada_update_list:
                    st.warning(f"⚠️ {len(_ada_update_list)} paket ada update dokumen PPK")
                    _folder_map_bh = st.session_state.get("_batch_folder_map", {})
                    for _item in _ada_update_list:
                        with st.expander(f"📄 {_item['nama'][:60]}"):
                            if _item.get("cookie_invalid"):
                                st.error("⚠️ Cookie SPSE expired — login ulang di Chrome lalu cek lagi")
                            for _b in _item.get("berubah", []):
                                st.markdown(f"- **Berubah** [{_b['jenis']}]: `{_b['nama_lama']}` → `{_b['nama_baru']}`")
                            for _b in _item.get("baru", []):
                                st.markdown(f"- **File Baru** [{_b['jenis']}]: `{_b['nama']}`")
                            for _b in _item.get("hilang", []):
                                st.markdown(f"- **File Hilang** [{_b['jenis']}]: `{_b['nama']}` — mungkin diganti")
                            # Tombol download update per paket
                            _kt_dl = _item["kode"]
                            _fd_dl = _folder_map_bh.get(_kt_dl, "")
                            _folder_dl = _os.path.join(_POKJA_ROOT, _fd_dl) if _fd_dl else ""
                            if _folder_dl and _os.path.exists(_folder_dl):
                                st.button("⬇️ Download Update", key=f"btn_dl_upd_{_kt_dl}", type="primary")
                            else:
                                st.caption(f"⚠️ Folder tidak ditemukan: `{_folder_dl or 'tidak diketahui'}`")

                    # Proses download di luar expander (hindari nested expander/status)
                    for _item in _ada_update_list:
                        _kt_dl = _item["kode"]
                        if st.session_state.get(f"btn_dl_upd_{_kt_dl}"):
                            _fd_dl = _folder_map_bh.get(_kt_dl, "")
                            _folder_dl = _os.path.join(_POKJA_ROOT, _fd_dl) if _fd_dl else ""
                            import dokumen_ppk_engine as _dpk_dl
                            _sn_r2 = inbox_engine._sb().table("draft_paket").select("dokumen_snapshot").eq("kode_tender", _kt_dl).execute()
                            _sn_lama2 = {}
                            if _sn_r2.data and _sn_r2.data[0].get("dokumen_snapshot"):
                                _raw2 = _sn_r2.data[0]["dokumen_snapshot"]
                                _sn_lama2 = _raw2 if isinstance(_raw2, dict) else __import__("json").loads(_raw2)
                            _diff_dl = _dpk_dl.cek_update_dokumen(_kt_dl)
                            _dl_log4 = []
                            _dl_st4 = st.status(f"⬇️ Mengunduh update {_item['nama'][:40]}...", expanded=True)
                            _dl_area4 = _dl_st4.empty()
                            def _dl_cb4(msg, _log=_dl_log4, _area=_dl_area4, _st=_dl_st4):
                                _log.append(msg)
                                _area.code("\n".join(_log[-15:]))
                                _st.update(label=f"⬇️ {msg[:60]}...")
                            _dl_res4 = _dpk_dl.download_update_dokumen(
                                _kt_dl, _folder_dl,
                                _diff_dl["berubah"], _diff_dl["baru"],
                                _sn_lama2, progress_cb=_dl_cb4,
                            )
                            _dpk_dl.simpan_snapshot(_kt_dl, _diff_dl["snapshot_baru"])
                            _dl_st4.update(
                                label=f"✅ {len(_dl_res4['ok'])} file diupdate, ❌ {len(_dl_res4['error'])} gagal",
                                state="complete", expanded=False,
                            )
                            if _dl_res4["error"]:
                                for _e6 in _dl_res4["error"]:
                                    st.error(_e6)
                            else:
                                st.success(f"✅ {_item['nama'][:50]} — selesai. Parse Draft ulang di Excel.")
                            st.session_state["_batch_cek_hasil"] = [
                                x for x in st.session_state["_batch_cek_hasil"] if x["kode"] != _kt_dl
                            ]
                            st.rerun()
                else:
                    st.success(f"✅ Semua {len(_bh)} paket — tidak ada update dokumen PPK")
                if _error_list:
                    with st.expander(f"⚠️ {len(_error_list)} paket gagal dicek"):
                        for _item in _error_list:
                            st.caption(f"`{_item['kode']}` — {_item['error'][:80]}")

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
        # Fallback: pakai folder_dibuat dari Supabase jika input kosong
        if not _folder_ada and _row_terpilih and _row_terpilih.get("folder_dibuat"):
            _fd = _row_terpilih["folder_dibuat"]
            _fd_path = _os.path.join(_POKJA_ROOT, _fd)
            if _os.path.exists(_fd_path):
                _target_path = _fd_path
                _folder_ada = True
        if _folder_ada:
            st.warning(f"Folder sudah ada: `{_target_path}`")

        _cb1, _cb2 = st.columns(2)
        _buat_btn = _cb1.button("📁 Buat Folder", type="primary",
                                disabled=not bool(_nama_folder),
                                use_container_width=True, key="btn_buat_folder")
        if _folder_ada:
            if _cb2.button("📂 Buka Explorer", use_container_width=True, key="btn_buka_folder"):
                _sp.Popen(f'explorer "{_target_path.replace("/", chr(92))}"')

        # Tombol scrape HPS — muncul selama ada paket dipilih (tidak perlu folder ada)
        if _row_terpilih and _row_terpilih.get("kode_tender"):
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
                    _dl_status2 = st.status("🔽 Mengunduh dokumen...", expanded=True)
                    _dl_log_area2 = _dl_status2.empty()
                    def _dl_cb2(msg):
                        _dl_msgs2.append(msg)
                        _dl_log_area2.code("\n".join(_dl_msgs2[-20:]))
                        _dl_status2.update(label=f"🔽 {msg[:60]}...")

                    from streamlit.runtime.scriptrunner import get_script_run_ctx
                    _ctx = get_script_run_ctx()

                    _dl2 = inbox_engine.download_dokumen_paket(
                        _kt2, _ip2, _target_path,
                        kode_pokja=_row_terpilih.get("kode_pokja",""),
                        progress_cb=_dl_cb2,
                        st_ctx=_ctx
                    )
                    _ringkasan2 = (f"✅ {len(_dl2['ok'])} file, ⏭ {len(_dl2['skip'])} sudah ada, ❌ {len(_dl2['error'])} gagal"
                                   + (f" | 📎 {_os.path.basename(_dl2['draft_pdf'])}" if _dl2.get('draft_pdf') else " | ⚠ Draft PDF tidak terbuat"))
                    _dl_status2.update(label=_ringkasan2, state="complete", expanded=False)
                    if _dl_msgs2:
                        with st.expander("📋 Log download lengkap", expanded=False):
                            _grup2 = []; _grp_title2 = ""; _grp_lines2 = []
                            for _m in _dl_msgs2:
                                if any(_m.startswith(p) for p in ["📨","📄","📅","📎","🏁","⚠","✅ Supabase"]):
                                    if _grp_title2: _grup2.append((_grp_title2, _grp_lines2))
                                    _grp_title2 = _m; _grp_lines2 = []
                                else:
                                    _grp_lines2.append(_m)
                            if _grp_title2: _grup2.append((_grp_title2, _grp_lines2))
                            for _gt, _gl in _grup2:
                                st.markdown(f"**{_gt}**")
                                if _gl: st.code("\n".join(_gl))
                    if _dl2["error"]:
                        with st.expander("❌ Detail error", expanded=True):
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
                        # Download dokumen + Scrape HPS secara PARALEL
                        import concurrent.futures as _cf
                        _do_dl = _dl_dokumen and _row_terpilih and _target_path
                        _do_hps = bool(_row_terpilih and _row_terpilih.get("kode_tender"))
                        _dl_msgs = []
                        _hps_res = None
                        _dl_hasil = None
                        _kt_par = _row_terpilih.get("kode_tender", "") if _row_terpilih else ""
                        _ip_par = str(_row_terpilih.get("id_pesan", "")) if _row_terpilih else ""

                        def _run_dl():
                            if not (_do_dl and _kt_par and _ip_par):
                                return None
                            from streamlit.runtime.scriptrunner import get_script_run_ctx as _grc
                            _ctx_par = _grc()
                            def _dl_cb_par(msg):
                                _dl_msgs.append(msg)
                            return inbox_engine.download_dokumen_paket(
                                _kt_par, _ip_par, _target_path,
                                kode_pokja=_row_terpilih.get("kode_pokja",""),
                                progress_cb=_dl_cb_par,
                                st_ctx=_ctx_par
                            )

                        def _run_hps():
                            if not _do_hps:
                                return None
                            import hps_engine as _hps_eng_par
                            return _hps_eng_par.scrape_dan_upsert_hps(_kt_par)

                        with st.spinner("⏳ Mengunduh dokumen + scraping HPS secara paralel..."):
                            with _cf.ThreadPoolExecutor(max_workers=2) as _pool:
                                _fut_dl = _pool.submit(_run_dl)
                                _fut_hps = _pool.submit(_run_hps)
                                try:
                                    _dl_hasil = _fut_dl.result()
                                except Exception as _dl_exc:
                                    st.warning(f"Download error: {_dl_exc}")
                                try:
                                    _hps_res = _fut_hps.result()
                                except Exception as _hps_exc:
                                    st.warning(f"Scrape HPS error: {_hps_exc}")

                        # Tampilkan hasil download
                        if _dl_hasil is not None:
                            _ringkasan_f = (f"✅ {len(_dl_hasil['ok'])} file, "
                                            f"⏭ {len(_dl_hasil['skip'])} sudah ada, "
                                            f"❌ {len(_dl_hasil['error'])} gagal"
                                            + (f" | 📎 {_os.path.basename(_dl_hasil['draft_pdf'])}" if _dl_hasil.get('draft_pdf') else " | ⚠ Draft PDF tidak terbuat"))
                            _dl_status_f = st.status(_ringkasan_f, expanded=False)
                            _dl_status_f.update(state="complete", expanded=False)
                            if _dl_msgs:
                                with st.expander("📋 Log download lengkap", expanded=False):
                                    _grup = []; _grp_title = ""; _grp_lines = []
                                    for _m in _dl_msgs:
                                        if any(_m.startswith(p) for p in ["📨","📄","📅","📎","🏁","⚠","✅ Supabase"]):
                                            if _grp_title: _grup.append((_grp_title, _grp_lines))
                                            _grp_title = _m; _grp_lines = []
                                        else:
                                            _grp_lines.append(_m)
                                    if _grp_title: _grup.append((_grp_title, _grp_lines))
                                    for _gt, _gl in _grup:
                                        st.markdown(f"**{_gt}**")
                                        if _gl: st.code("\n".join(_gl))
                            if _dl_hasil["error"]:
                                with st.expander("❌ Detail error download", expanded=True):
                                    for _e3 in _dl_hasil["error"]:
                                        st.error(_e3)

                        # Tampilkan hasil HPS
                        if _hps_res is not None:
                            if _hps_res.get("error") is None and _hps_res.get("count", 0) > 0:
                                st.success(f"✅ HPS tersimpan: {_hps_res['count']} item")
                            else:
                                st.warning(f"HPS gagal/kosong: {_hps_res.get('error', '-')}")
                        # Simpan snapshot dokumen PPK saat folder dibuat
                        if _row_terpilih and _row_terpilih.get("kode_tender") and _target_path:
                            try:
                                import dokumen_ppk_engine as _dpk
                                with st.spinner("📸 Menyimpan snapshot dokumen PPK..."):
                                    _snap = _dpk.ambil_snapshot(_row_terpilih["kode_tender"])
                                    _dpk.simpan_snapshot(_row_terpilih["kode_tender"], _snap)
                                _total_snap = sum(len(v) for v in _snap.values())
                                st.success(f"✅ Snapshot dokumen PPK tersimpan: {_total_snap} file")
                            except Exception as _snap_e:
                                st.warning(f"Snapshot dokumen PPK gagal: {_snap_e}")
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
                _bulk_status = st.status(f"📁 Memproses {len(_bulk_plan)} paket...", expanded=True)
                _bulk_status_line = _bulk_status.empty()
                _ok, _fail = 0, 0
                _bulk_semua_log = {}  # {nama_folder: [log lines]}
                for _i, _bp in enumerate(_bulk_plan):
                    _bp2.progress((_i+1)/len(_bulk_plan))
                    _nf = _bp["nama_folder"]
                    _bulk_status.update(label=f"[{_i+1}/{len(_bulk_plan)}] {_nf[:60]}")
                    _paket_log = []
                    try:
                        _r2 = _sp.run([_PY, _SCRIPT, _nf],
                                      capture_output=True, text=True, timeout=60,
                                      creationflags=_NO_WIN)
                        if _r2.returncode == 0:
                            _ok += 1
                            _paket_log.append("✅ Folder dibuat")
                            _bp_target = os.path.join(_POKJA_ROOT, _nf)
                            try:
                                inbox_engine._sb().table("draft_paket").update({
                                    "nomor_urut": _bp["nomor_urut"],
                                    "folder_dibuat": _nf,
                                    "folder_dibuat_pada": datetime.now(_tz2.utc).isoformat(),
                                }).eq("kode_tender", _bp["kode_tender"]).execute()
                            except Exception:
                                pass
                            # Download dokumen SPSE per paket
                            if _bulk_dl and _bp.get("id_pesan") and _bp.get("kode_tender"):
                                def _bulk_cb(msg, _log=_paket_log):
                                    _log.append(msg)
                                    _bulk_status_line.code("\n".join(_log[-10:]))
                                try:
                                    _dl_hasil_bulk = inbox_engine.download_dokumen_paket(
                                        _bp["kode_tender"], str(_bp["id_pesan"]),
                                        _bp_target,
                                        kode_pokja=_bp.get("kode_pokja", ""),
                                        progress_cb=_bulk_cb,
                                        st_ctx=_ctx_bulk,
                                    )
                                    _cdp_gagal = not _dl_hasil_bulk["ok"] and not _dl_hasil_bulk.get("draft_pdf")
                                    if _cdp_gagal:
                                        _paket_log.append("❌ Chrome CDP tidak aktif — buka Chrome dulu lalu jalankan ulang")
                                        _fail += 1; _ok -= 1
                                    else:
                                        _paket_log.append(
                                            f"📎 Download: ✅{len(_dl_hasil_bulk['ok'])} file"
                                            + (f" | Draft: {_os.path.basename(_dl_hasil_bulk['draft_pdf'])}" if _dl_hasil_bulk.get('draft_pdf') else " | ⚠ Draft tidak terbuat")
                                        )
                                    for _e in _dl_hasil_bulk.get("error", []):
                                        _paket_log.append(f"  ❌ {_e}")
                                except Exception as _dl_e:
                                    _paket_log.append(f"❌ Download error: {_dl_e}")
                            # Scrape HPS ke Supabase
                            if _bp.get("kode_tender"):
                                try:
                                    import hps_engine as _hps_eng2
                                    _hps_res2 = _hps_eng2.scrape_dan_upsert_hps(_bp["kode_tender"])
                                    _paket_log.append(f"📊 HPS: {_hps_res2.get('count',0)} item")
                                except Exception as _hps_e2:
                                    _paket_log.append(f"⚠ HPS gagal: {_hps_e2}")
                        else:
                            _fail += 1
                            _paket_log.append(f"❌ Gagal buat folder: {_r2.stderr[:100]}")
                    except _sp.TimeoutExpired:
                        _fail += 1
                        _paket_log.append("❌ Timeout buat folder")
                    _bulk_semua_log[_nf] = _paket_log

                _bulk_status_line.empty()
                _ringkasan_bulk = f"✅ {_ok} folder berhasil, ❌ {_fail} gagal"
                _bulk_status.update(label=_ringkasan_bulk, state="complete", expanded=False)
                with st.expander("📋 Log detail per paket", expanded=_fail > 0):
                    for _nf, _logs in _bulk_semua_log.items():
                        st.markdown(f"**{_nf[:70]}**")
                        st.code("\n".join(_logs))
                st.session_state["_folder_bulk_created"] = f"{_ok} folder berhasil dibuat"
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
        st.caption("Menggunakan file DOKPIL yang sudah diupload di atas. Tanggal upload, lalu klik Upload.")

        _dp_dengan_file = [p for p in sp_selected if p.get("_dokpil")]
        _dp_tanpa_file  = [p for p in sp_selected if not p.get("_dokpil")]
        dp_selected     = _dp_dengan_file

        if not sp_selected:
            st.info("Pilih paket dan upload DOKPIL di atas terlebih dahulu.")
        else:
            if _dp_dengan_file:
                st.caption(f"✅ **{len(_dp_dengan_file)} paket** siap diupload:")
                for _p in _dp_dengan_file:
                    _ku = _p.get("kode_unik") or "?"
                    _kp = _p.get("kode_pokja") or "?"
                    _nomor_auto = f"000.3.3/01/T/{_ku}/POKJA{_kp}/UKPBJ/2026"
                    st.markdown(f"- {_pokja_label(_p)[:80]}  \n  📄 `{_p['_dokpil'].name}`  \n  📋 `{_nomor_auto}`")
            if _dp_tanpa_file:
                st.caption(f"⚠️ **{len(_dp_tanpa_file)} paket** tanpa DOKPIL (dilewati):")
                for _p in _dp_tanpa_file:
                    st.markdown(f"- {_pokja_label(_p)[:80]}")

        # Cek apakah ada paket terpilih dengan kode_unik null
        _dp_tanpa_kode_unik = [p for p in _dp_dengan_file if not p.get("kode_unik")]
        if _dp_tanpa_kode_unik:
            st.warning(f"⚠️ **{len(_dp_tanpa_kode_unik)} paket** belum punya Kode Unik — generate dulu via tombol 'Kode Unik Surat' di Excel.")

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
                import dokpil_engine
                with st.status(f"Mengupload {_dp_n_file} Dokumen Pemilihan...", expanded=True) as status:
                    sukses_count = 0
                    for _p in dp_selected:
                        _kode = str(_p.get("kode", ""))
                        if not _kode:
                            st.error(f"❌ Paket {_pokja_label(_p)} tidak memiliki kode tender valid.")
                            continue
                            
                        _ku = _p.get("kode_unik") or "?"
                        _kp = _p.get("kode_pokja") or "?"
                        _nomor_auto = f"000.3.3/01/T/{_ku}/POKJA{_kp}/UKPBJ/2026"
                        _tgl_str = dp_tgl.strftime('%d-%m-%Y')
                        _file = _p['_dokpil']
                        
                        st.write(f"⏳ Uploading: `{_file.name}` untuk **{_pokja_label(_p)[:60]}** ...")
                        try:
                            _res = dokpil_engine.upload_dokumen_pemilihan(
                                paket_id=_kode,
                                nomor_sdp=_nomor_auto,
                                tanggal_sdp=_tgl_str,
                                file_bytes=_file.getvalue(),
                                file_name=_file.name
                            )
                            if _res["ok"]:
                                st.success(f"✅ Berhasil upload: `{_file.name}`")
                                sukses_count += 1
                            else:
                                st.error(f"❌ Gagal upload: `{_file.name}` (Status: {_res['status']})")
                        except Exception as e:
                            st.error(f"❌ Error upload `{_file.name}`: {e}")
                    
                    status.update(label=f"Selesai! {sukses_count}/{_dp_n_file} dokumen berhasil diupload.", state="complete" if sukses_count == _dp_n_file else "error")

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

        # Opsi SBU dropdown — dari _SBU_RULES inbox_engine (cached per session)
        if "sbu_opts_cache" not in st.session_state:
            _sbu_cache = ldk_config.load_sbu_dari_rules()
            st.session_state["sbu_opts_cache"] = _sbu_cache
        else:
            _sbu_cache = st.session_state["sbu_opts_cache"]

        _sbu_opts_2020 = [""] + _sbu_cache["kbli_2020"]
        _sbu_opts_2015 = [""] + _sbu_cache["kbli_2015"]

        # Validasi: nilai tersimpan harus ada di opsi — reset jika tidak ada
        if st.session_state.get("sbu_2020_1", "") not in _sbu_opts_2020:
            st.session_state["sbu_2020_1"] = ""
        if st.session_state.get("sbu_2015_1", "") not in _sbu_opts_2015:
            st.session_state["sbu_2015_1"] = ""

        _sbu_sumber = _sbu_cache.get("sumber", "rules")
        st.caption(
            f"📋 {len(_sbu_cache['kbli_2020'])} SBU 2020 · {len(_sbu_cache['kbli_2015'])} SBU 2015 "
            f"(sumber: {_sbu_sumber})"
        )

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
                        label_visibility="visible",
                    )
                with col_2015:
                    sbu_2015 = st.selectbox(
                        "SBU KBLI 2015 (opsional — kosongkan jika hanya SBU 2020)",
                        options=_sbu_opts_2015,
                        key="sbu_2015_1",
                        label_visibility="visible",
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
            import tempfile

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

                # Sesuai instruksi: Seluruh konfigurasi LDK (SBU, Izin, Kinerja)
                # mutlak menggunakan input manual dari UI Streamlit (Tab 3 Konfigurasi).
                # Tidak ada lagi parsing otomatis dari file DOKPIL PDF.
                ijin_rows   = _default_ijin
                kinerja_txt = _default_kinerja
                row_result["ldk"] = "—"

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

        st.divider()
        st.markdown("### 3. Sinkronisasi Google Calendar")
        st.caption("Update acara di Google Calendar berdasarkan data jadwal terbaru SPSE.")
        
        col_gcal1, col_gcal2 = st.columns(2)
        
        with col_gcal1:
            gcal_sync_btn = st.button(
                "📅 Sync Jadwal ke GCalendar",
                type="primary",
                use_container_width=True,
                key="jd_sync_gcal"
            )
            
        with col_gcal2:
            gcal_login_btn = st.button(
                "🔑 Re-Login Google Calendar",
                type="secondary",
                help="Gunakan tombol ini JIKA proses sinkronisasi gagal karena Token Expired.",
                use_container_width=True,
                key="jd_login_gcal"
            )
        
        if gcal_sync_btn:
            if not jd_selected:
                st.warning("Pilih minimal satu paket di daftar sebelah kiri untuk didaftarkan dan disinkronkan.")
            else:
                import subprocess as _sp
                import pathlib as _pathlib
                import os as _os
                import pandas as _pd
                from config import POKJA_ROOT as _POKJA_ROOT, SPSE_BASE_URL as _SPSE_BASE_URL
                
                _v19_dir = _pathlib.Path(_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110"
                _db_path = _v19_dir / "database_tender.csv"
                _py_exe = _v19_dir / "python" / "python.exe"
                _script = _v19_dir / "sync_jadwal.py"
                _no_win = 0x08000000
                
                # Memastikan encoding output UTF-8 untuk print emoji
                _env = _os.environ.copy()
                _env["PYTHONIOENCODING"] = "utf-8"
                
                with st.status("🔄 Menyiapkan data Sinkronisasi...", expanded=True) as sync_status:
                    # 1. Update database_tender.csv V19
                    st.write("Mendaftarkan URL paket ke database V19...")
                    try:
                        if _db_path.exists():
                            df_db = _pd.read_csv(_db_path)
                        else:
                            df_db = _pd.DataFrame(columns=['url', 'members', 'nama_paket', 'last_sync', 'content_hash'])
                            
                        # Pastikan kolom wajib ada
                        for _col in ['url', 'members', 'nama_paket', 'last_sync', 'content_hash']:
                            if _col not in df_db.columns:
                                df_db[_col] = ''
                                
                        df_db.set_index('url', inplace=True)
                        
                        for p in jd_selected:
                            _url = f"{_SPSE_BASE_URL.rstrip('/')}/lelang/{p['id_lelang']}/jadwal"
                            _members = p.get('pokja') or p.get('kode', 'Pokja')
                            _nama = p.get('nama', f"Paket {p['id_lelang']}")
                            
                            df_db.loc[_url, 'members'] = _members
                            df_db.loc[_url, 'nama_paket'] = _nama
                            if 'content_hash' not in df_db.loc[_url] or _pd.isna(df_db.loc[_url, 'content_hash']):
                                df_db.loc[_url, 'content_hash'] = ''
                            if 'last_sync' not in df_db.loc[_url] or _pd.isna(df_db.loc[_url, 'last_sync']):
                                df_db.loc[_url, 'last_sync'] = ''
                                
                        df_db.reset_index(inplace=True)
                        df_db.to_csv(_db_path, index=False)
                        
                        _list_paket_str = "\n".join([f"{i+1}. {p.get('nama', p['id_lelang'])}" for i, p in enumerate(jd_selected)])
                        st.success(f"✅ Berhasil mendaftarkan {len(jd_selected)} paket ke radar V19:\n\n{_list_paket_str}")
                    except Exception as e:
                        st.error(f"Gagal mengupdate database: {e}")
                
                    # 2. Jalankan sync_jadwal.py
                    st.write("Memanggil script `sync_jadwal.py`...")
                    log_container = st.empty()
                    try:
                        res = _sp.run(
                            [str(_py_exe), str(_script)],
                            cwd=str(_v19_dir),
                            env=_env,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            creationflags=_no_win,
                            timeout=300
                        )
                        
                        if res.stdout:
                            log_container.code(res.stdout, language="text")
                        if res.stderr:
                            if "RefreshError" in res.stderr or "invalid_grant" in res.stderr:
                                st.error("🔐 **Token Google Calendar Kedaluwarsa!**\n\nSistem Google menolak akses karena sesi login sudah *expired*. Silakan klik tombol **🔑 Re-Login Google Calendar** di sebelah kanan untuk menyegarkan sesi.")
                            else:
                                st.error(f"Error output:\n{res.stderr}")
                            
                        if res.returncode == 0:
                            sync_status.update(label="✅ Sinkronisasi GCalendar Selesai", state="complete")
                        else:
                            sync_status.update(label="⚠️ Sinkronisasi GCalendar Selesai dengan Error", state="error")
                            
                    except Exception as e:
                        st.error(f"Gagal menjalankan script: {e}")
                        sync_status.update(label="⚠️ Terjadi Kesalahan", state="error")
                    
        if gcal_login_btn:
            import subprocess as _sp
            import pathlib as _pathlib
            from config import POKJA_ROOT as _POKJA_ROOT
            
            _v19_dir = _pathlib.Path(_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110"
            _py_exe = _v19_dir / "python" / "python.exe"
            
            _auth_code = f"""
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from google_auth_oauthlib.flow import InstalledAppFlow

cred_path = r"{_v19_dir / 'credentials.json'}"
token_path = r"{_v19_dir / 'token.json'}"
scopes = ['https://www.googleapis.com/auth/calendar']

if os.path.exists(token_path):
    os.remove(token_path)

print("Membuka browser... Silakan login di browser Anda.")
try:
    flow = InstalledAppFlow.from_client_secrets_file(cred_path, scopes)
    creds = flow.run_local_server(port=0)
    with open(token_path, 'w') as f:
        f.write(creds.to_json())
    print("Login berhasil! Token tersimpan.")
except Exception as e:
    print(f"Error: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
            with st.status("🔑 Menunggu Otorisasi Browser...", expanded=True) as auth_status:
                st.write("Jendela browser Google Login akan segera terbuka. Silakan login...")
                try:
                    res = _sp.run(
                        [str(_py_exe), "-c", _auth_code], 
                        cwd=str(_v19_dir),
                        capture_output=True, 
                        text=True, 
                        encoding="utf-8",
                        creationflags=0x08000000,
                        timeout=300
                    )
                    
                    if res.returncode == 0:
                        auth_status.update(label="✅ Login Google Calendar berhasil!", state="complete")
                        st.success("Autentikasi selesai. Kamu bisa menggunakan fitur Sync Jadwal sekarang.")
                    else:
                        auth_status.update(label="⚠️ Login Dibatalkan atau Error", state="error")
                        st.error(res.stderr or "Gagal mendapatkan otorisasi.")
                except _sp.TimeoutExpired:
                    auth_status.update(label="⌛ Waktu tunggu login habis", state="error")
                    st.error("Proses login ditutup karena tidak ada aktivitas lebih dari 5 menit.")
                except Exception as e:
                    auth_status.update(label="⚠️ Terjadi Kesalahan", state="error")
                    st.error(str(e))

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
                        key_chk     = f"kp_chk_{p['id_lelang']}"
                        key_tgl_acara = f"kp_tgl_acara_{p['id_lelang']}"

                        col_chk, col_tgl_p = st.columns([3, 2])
                        with col_chk:
                            checked = st.checkbox(
                                _pokja_label(p),
                                value=st.session_state.get(key_chk, True),
                                key=key_chk,
                            )
                        with col_tgl_p:
                            tgl_acara_p = st.date_input(
                                "Tanggal Acara",
                                value=st.session_state.get(key_tgl_acara, datetime.now().date()),
                                format="DD/MM/YYYY",
                                key=key_tgl_acara,
                                label_visibility="collapsed",
                            )
                            st.caption(f"{_HARI_NAMA[tgl_acara_p.weekday()]}, {tgl_acara_p.day} {_BULAN_NAMA[tgl_acara_p.month-1]} {tgl_acara_p.year}")

                        if checked:
                            kp_selected.append({
                                **p,
                                "_tgl_acara": tgl_acara_p,
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

        _kp_libur_map = _LIBUR_MAP

        st.markdown("**Waktu Acara (berlaku semua paket)**")
        col_mulai, col_selesai = st.columns(2)
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

        with st.expander("ℹ️ Libur Nasional Tersisa"):
            _kp_hari_ini = datetime.now().date()
            _kp_sisa = sorted(d for d in _kp_libur_map if d >= _kp_hari_ini)
            for d in _kp_sisa:
                st.write(f"• {_HARI_NAMA[d.weekday()]}, {d.day} {_BULAN_NAMA[d.month-1]} {d.year} — {_kp_libur_map[d]}")

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
            _kp_konfirm_lines = "\n".join(
                f"{i+1}. Pokja {p.get('pokja', p['kode'])} - {p['nama']}  \n"
                f"   📅 {_HARI_NAMA[p['_tgl_acara'].weekday()]}, {p['_tgl_acara'].day} {_BULAN_NAMA[p['_tgl_acara'].month-1]} {p['_tgl_acara'].year}"
                for i, p in enumerate(kp_selected)
            )
            st.warning(
                f"Kirim ke **{len(kp_selected)} paket**\n\n"
                f"{_kp_konfirm_lines}\n\n"
                f"- Pukul: {kp_jam_mulai.strftime('%H.%M')} s.d. {kp_jam_selesai.strftime('%H.%M')} Wita\n"
                f"- Tempat: {kp_tempat.strip()[:80]}\n\n"
                f"**Tidak bisa dibatalkan setelah dikirim.**"
            )

            col_ya, col_batal = st.columns(2)
            with col_ya:
                if st.button("✅ Ya, Kirim", key="kp_ya", type="primary", use_container_width=True):
                    st.session_state["kp_konfirmasi"] = False

                    import undangan_pdf_engine
                    progress = st.progress(0, text="Memulai pengiriman...")
                    hasil_list = []
                    _tgl_kirim = datetime.now().date()

                    for i, paket in enumerate(kp_selected):
                        progress.progress(
                            (i + 1) / len(kp_selected),
                            text=f"Mengirim ke Pokja {paket.get('pokja', paket['kode'])} ({i+1}/{len(kp_selected)})..."
                        )

                        # Generate PDF lampiran otomatis
                        _tgl_acara = paket["_tgl_acara"]
                        _hari_tgl  = f"{_HARI_NAMA[_tgl_acara.weekday()]}, {_tgl_acara.day} {_BULAN_NAMA[_tgl_acara.month-1]} {_tgl_acara.year}"
                        _pukul_str = f"{kp_jam_mulai.strftime('%H.%M')} s.d. {kp_jam_selesai.strftime('%H.%M')} Wita"
                        _kode_pokja = paket.get("pokja", "000")

                        gen_res = undangan_pdf_engine.generate_undangan_pdf(
                            kode_tender=paket["kode"],
                            tanggal_kirim=_tgl_kirim,
                            hari_tgl_rapat=_hari_tgl,
                            pukul_rapat=_pukul_str,
                            tempat_rapat=kp_tempat.strip(),
                            output_path=None,
                        )
                        _lamp_bytes = gen_res["pdf_bytes"] if gen_res["sukses"] else None
                        _lamp_nama  = f"Undangan_{_kode_pokja.zfill(3)}.pdf"

                        waktu_str  = datetime.combine(_tgl_acara, kp_jam_mulai).strftime("%d-%m-%Y %H:%M")
                        sampai_str = datetime.combine(_tgl_acara, kp_jam_selesai).strftime("%d-%m-%Y %H:%M")

                        res = kirimpesan_engine.kirim_undangan(
                            paket_id=paket["id_lelang"],
                            waktu=waktu_str,
                            sampai=sampai_str,
                            tempat=kp_tempat.strip(),
                            dibawa=kp_dibawa.strip(),
                            hadir=kp_hadir.strip(),
                            is_online=False,
                            link_pembuktian="",
                            lampiran_bytes=_lamp_bytes,
                            lampiran_nama=_lamp_nama,
                        )

                        hasil_list.append({
                            "pokja": f"Pokja {_kode_pokja.zfill(3)}",
                            "nama": paket["nama"],
                            "pdf": "✅" if gen_res["sukses"] else f"❌ {gen_res['pesan']}",
                            "kirim": "✅" if res["sukses"] else f"❌ {res['pesan']}",
                        })

                    progress.empty()

                    sukses_n = sum(1 for h in hasil_list if h["kirim"] == "✅")
                    gagal_n  = len(hasil_list) - sukses_n
                    if gagal_n == 0:
                        st.success(f"✅ Semua {sukses_n} undangan berhasil dikirim!")
                    else:
                        st.warning(f"⚠️ {sukses_n} berhasil, {gagal_n} gagal.")

                    st.dataframe(
                        hasil_list,
                        use_container_width=True,
                        column_config={
                            "pokja": st.column_config.TextColumn("Pokja", width="small"),
                            "nama":  st.column_config.TextColumn("Nama Paket", width="large"),
                            "pdf":   st.column_config.TextColumn("PDF", width="small"),
                            "kirim": st.column_config.TextColumn("Kirim", width="small"),
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

    ba_selected = []

    # ── Pilih Paket ──────────────────────────────────────────────────────
    st.markdown("### Pilih Paket")
    if "global_paket_draft" not in st.session_state:
        st.info("⚠️ Data paket belum disinkronkan. Silakan ke **Tab 0** dan klik **🔄 Sinkronkan Paket**.")
    else:
        _ba_r = st.session_state["global_paket_draft"]
        if not _ba_r.get("sukses"):
            st.error(f"❌ {_ba_r.get('pesan', 'Gagal memuat data paket')}")
        else:
            paket_list_ba = _ba_r.get("paket", [])
            if not paket_list_ba:
                st.warning("⚠️ Tidak ada paket draft ditemukan.")
            else:
                st.caption(f"📋 {len(paket_list_ba)} paket draft tersedia — pilih:")
                _ba_sel_c1, _ba_sel_c2 = st.columns(2)
                with _ba_sel_c1:
                    if st.button("✅ Semua", key="ba_sel_all", use_container_width=True):
                        for p in paket_list_ba:
                            st.session_state[f"ba_chk_{p['id_lelang']}"] = True
                        st.rerun()
                with _ba_sel_c2:
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
                            st.session_state["ba_pending_target"] = "SEMUA"
                            st.session_state["ba_pending_paket"] = [p]
                            st.rerun()
                    if checked:
                        ba_selected.append(p)
                st.caption(f"**{len(ba_selected)}** dari **{len(paket_list_ba)}** paket dipilih")
                st.divider()
                if st.button(
                    f"🚀 Cetak & Upload SEMUA BA — {len(ba_selected)} Paket",
                    key="ba_super_all",
                    disabled=len(ba_selected) == 0,
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state["ba_pending_target"] = "SEMUA"
                    st.session_state["ba_pending_paket"] = ba_selected[:]
                    st.rerun()

    # ── Inisialisasi session state BA ─────────────────────────────────────
    for jenis_key in ba_config.JENIS_KEYS:
        if f"ba_tgl_{jenis_key}" not in st.session_state:
            st.session_state[f"ba_tgl_{jenis_key}"] = datetime.today().strftime("%d-%m-%Y")
        if f"ba_info_{jenis_key}" not in st.session_state:
            st.session_state[f"ba_info_{jenis_key}"] = ba_config.DEFAULT_INFO.get(jenis_key, "")

    # ── Auto-generate nomor BA + tanggal GCal untuk semua paket di ba_selected ──
    # Key per-paket: ba_no_{jenis}_{id}, ba_tgl_{jenis}_{id}, ba_tgl_date_{jenis}_{id}
    # Key global (paket pertama): ba_no_{jenis}, ba_tgl_{jenis} — untuk kompatibilitas
    _ba_sel_ids = tuple(p["id_lelang"] for p in ba_selected)
    if _ba_sel_ids and st.session_state.get("_ba_last_sel_ids") != _ba_sel_ids:
        try:
            import gcal_helper as _gcal
        except Exception:
            _gcal = None
        for _px in ba_selected:
            _pid_x = _px["id_lelang"]
            _ku = _px.get("kode_unik") or ""
            _kp = _px.get("kode_pokja") or ""
            if _ku and _kp:
                _nomor_dokpil = f"000.3.3/01/T/{_ku}/POKJA{_kp}/UKPBJ/2026"
                for jenis_key in ba_config.JENIS_KEYS:
                    _urut = ba_config.NOMOR_URUT[jenis_key]
                    _no = ba_engine.derive_nomor_ba(_nomor_dokpil, _urut)
                    st.session_state[f"ba_no_{jenis_key}_{_pid_x}"] = _no
            if _gcal:
                try:
                    _tgl_map = _gcal.get_tanggal_ba_dari_gcal(_px["nama"])
                    for _jk, _d in _tgl_map.items():
                        if _d is not None:
                            st.session_state[f"ba_tgl_date_{_jk}_{_pid_x}"] = _d
                            st.session_state[f"ba_tgl_{_jk}_{_pid_x}"] = _d.strftime("%d-%m-%Y")
                except Exception:
                    pass
        st.session_state["_ba_last_sel_ids"] = _ba_sel_ids

    if ba_selected and not ba_selected[0].get("kode_unik"):
        st.warning("⚠️ Paket ini belum punya Kode Unik — generate dulu via Excel.")

    # ── Konfirmasi sebelum cetak ──────────────────────────────────────────
    if st.session_state.get("ba_pending_target"):
        st.divider()
        _pending_target = st.session_state["ba_pending_target"]
        _pending_paket  = st.session_state.get("ba_pending_paket") or ba_selected
        _JENIS_AUTO = [k for k in ba_config.JENIS_KEYS if k != "lainnya"]
        _jenis_konfirm = _JENIS_AUTO if _pending_target == "SEMUA" else [_pending_target]
        _label_target = "Semua BA" if _pending_target == "SEMUA" else ba_config.JENIS_BA[_pending_target]

        _paket_blocks = []
        _total_kosong = []
        for _pp in _pending_paket:
            _pid_k = _pp["id_lelang"]
            _blok_lines = [f"**{_pokja_label(_pp)}**"]
            for _jk in _jenis_konfirm:
                _no  = st.session_state.get(f"ba_no_{_jk}_{_pid_k}", "")
                _tgl = st.session_state.get(f"ba_tgl_{_jk}_{_pid_k}", "")
                _label = ba_config.JENIS_LABEL[_jk]
                if _no and _tgl:
                    _tgl_date = st.session_state.get(f"ba_tgl_date_{_jk}_{_pid_k}")
                    if isinstance(_tgl_date, date):
                        _tgl_fmt = f"{_HARI_NAMA[_tgl_date.weekday()]}, {_tgl_date.day} {_BULAN_NAMA[_tgl_date.month-1]} {_tgl_date.year}"
                    else:
                        _tgl_fmt = _tgl
                    _blok_lines.append(f"- {_label}: `{_no}` — 📅 {_tgl_fmt}")
                else:
                    _blok_lines.append(f"- {_label}: ⚠️ _(akan dilewati — tanggal tidak ada di GCal)_")
                    _total_kosong.append(f"{_pokja_label(_pp)} / {_label}")
            _paket_blocks.append("\n".join(_blok_lines))

        _detail = "\n\n".join(_paket_blocks)
        _warn_msg = (
            f"**Konfirmasi Cetak & Upload — {_label_target}**\n\n"
            f"{_detail}"
        )
        if _total_kosong:
            _warn_msg += f"\n\n⚠️ **{len(_total_kosong)} jenis akan dilewati** (tanggal tidak ditemukan di GCal)"

        st.warning(_warn_msg)
        _konfirm_c1, _konfirm_c2 = st.columns(2)
        with _konfirm_c1:
            if st.button("✅ Ya, Cetak & Upload", key="ba_konfirm_ya", type="primary", use_container_width=True):
                st.session_state["ba_auto_target"] = st.session_state.pop("ba_pending_target")
                st.session_state["ba_super_paket"]  = st.session_state.pop("ba_pending_paket", None)
                st.rerun()
        with _konfirm_c2:
            if st.button("❌ Batal", key="ba_konfirm_batal", use_container_width=True):
                st.session_state.pop("ba_pending_target", None)
                st.session_state.pop("ba_pending_paket", None)
                st.rerun()

    # ── BA Lainnya (per paket) ────────────────────────────────────────────
    if ba_selected:
        st.divider()
        st.markdown("#### 📁 BA Lainnya")
        st.caption("Upload scan manual — spesifik per paket.")
        for _pl in ba_selected:
            _pid = _pl["id_lelang"]
            with st.expander(f"📁 {_pokja_label(_pl)}", expanded=False):
                _file_key = f"ba_file_lainnya_{_pid}"
                st.file_uploader("File PDF", type=["pdf"], key=_file_key)
                _file_l = st.session_state.get(_file_key)
                if st.button(
                    "🚀 Upload BA Lainnya",
                    key=f"ba_lainnya_upload_{_pid}",
                    disabled=not _file_l,
                    use_container_width=True,
                ):
                    _tgl_str_l = date.today().strftime("%d-%m-%Y")
                    try:
                        _r = ba_engine.upload_ba(
                            paket_id=_pid, jenis_key="lainnya",
                            nomor_ba="", tanggal_ba=_tgl_str_l,
                            file_bytes=_file_l.getvalue(), file_name=_file_l.name,
                            info="",
                        )
                        if _r["ok"]:
                            st.success(f"✅ BA Lainnya berhasil di-upload.")
                        else:
                            st.error(f"❌ Upload gagal: {_r.get('status')}")
                    except Exception as _e:
                        st.error(f"❌ {_e}")

    # ── Proses Cetak & Auto-Upload ───────────────────────────────────────
    _FILE_LABEL_BA = {
        "penjelasan":      "2. Berita Acara Pemberian Penjelasan",
        "evaluasi":        "4. Berita Acara Evaluasi Penawaran",
        "hasil_pemilihan": "8. Berita Acara Hasil Pemilihan",
        "negosiasi":       "10. Berita Acara Negosiasi",
    }
    if st.session_state.get("ba_auto_target"):
        import os as _os
        import re as _re
        from config import POKJA_ROOT as _POKJA_ROOT
        from config import sb as _sb_ba
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
            # Resolve folder paket dari Supabase → subfolder "BA + Summary"
            try:
                _sb_row = _sb_ba().table("draft_paket").select("folder_dibuat").eq("kode_tender", p["kode"]).maybe_single().execute()
                _folder_dibuat = (_sb_row.data or {}).get("folder_dibuat", "")
                if _folder_dibuat:
                    _folder_safe = _re.sub(r'[/\\:*?"<>|]', "-", _folder_dibuat).strip()
                    target_dir = _os.path.join(_POKJA_ROOT, _folder_safe, "BA + Summary")
                else:
                    target_dir = _os.path.join(_POKJA_ROOT, "Asisten_Pokja_Downloads", f"Cetak_BA_{p['kode']}")
            except Exception:
                target_dir = _os.path.join(_POKJA_ROOT, "Asisten_Pokja_Downloads", f"Cetak_BA_{p['kode']}")
            _os.makedirs(target_dir, exist_ok=True)
            for jenis_key in jenis_list:
                op_idx += 1
                progress.progress(op_idx / total_ops, text=f"Proses {p['kode']} — {ba_config.JENIS_BA[jenis_key]} ({op_idx}/{total_ops})...")
                nomor = st.session_state.get(f"ba_no_{jenis_key}_{pid}", "").strip()
                tanggal = st.session_state.get(f"ba_tgl_{jenis_key}_{pid}", "").strip()
                info = ba_config.DEFAULT_INFO.get(jenis_key, "")
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
        st.success(f"✅ Selesai! {label_target} telah dikirim ke SPSE dan backup PDF disimpan ke folder paket.")
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
                        # auto-centang pertama kali (session key belum ada)
                        if _kl_chk_key not in st.session_state:
                            st.session_state[_kl_chk_key] = True
                        _checked = st.checkbox(
                            f"{_pokja_label(p)[:70]}  \n_{p.get('status', '')}_",
                            key=_kl_chk_key,
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

                            # ── Conflict detection: sync personil & alat dari PDF
                            try:
                                import conflict_engine
                                for i, d in enumerate(semua_data):
                                    pid  = peserta_list[i].get("kualifikasi_id", "")
                                    nama = d.get("nama", "")
                                    conflict_engine.sync_from_pdf(
                                        kode_tender, pid, nama,
                                        d.get("personel_list", []),
                                        d.get("peralatan_list", []),
                                        log=_log_cb,
                                    )
                                _log_cb(f"✅ [{kode_tender}] Conflict sync selesai.")
                            except Exception as e_cf:
                                _log_cb(f"⚠️ [{kode_tender}] Conflict sync error: {e_cf}")

                        except Exception as e_sb:
                            _log_cb(f"ERROR [{kode_tender}] Supabase: {e_sb}")

                        _kl_step += 1

                progress.progress(1.0, text="Selesai!")
                _parts = []
                if _kl_do_download: _parts.append("dokumen didownload")
                if _kl_do_kk: _parts.append("KK Evaluasi tersimpan")
                st.success(f"✅ Selesai: {' + '.join(_parts)} — {_kl_total_paket} paket, {_kl_total_semua} peserta. Buka Excel → **Muat KK Evaluasi**, **Muat Harga Penawaran**, **Muat Input BA**.")

                # ── Tampilkan konflik personil & alat lintas paket
                if _kl_do_kk:
                    try:
                        import conflict_engine as _ce
                        for _kt in [item["paket"]["kode"] for item in _kl_paket_dipilih]:
                            _kf_p = _ce.get_konflik_personil(_kt)
                            _kf_a = _ce.get_konflik_alat(_kt)
                            if _kf_p or _kf_a:
                                with st.expander(f"⚠️ Konflik Lintas Paket — {_kt}", expanded=True):
                                    if _kf_p:
                                        st.markdown("**Personil digunakan di >1 paket:**")
                                        for k in _kf_p:
                                            paket_str = ", ".join(
                                                f"{e['kode_tender']} ({e['nama_penyedia']})"
                                                for e in k["paket"]
                                            )
                                            st.error(f"🔴 {k['nama_personil']} → {paket_str}")
                                    if _kf_a:
                                        st.markdown("**Alat digunakan di >1 paket:**")
                                        for k in _kf_a:
                                            paket_str = ", ".join(
                                                f"{e['kode_tender']} ({e['nama_penyedia']})"
                                                for e in k["paket"]
                                            )
                                            st.warning(f"🟡 {k['nama_alat']} → {paket_str}")
                    except Exception as _e_kf:
                        st.caption(f"Conflict check error: {_e_kf}")

        # ── Dashboard Konflik Personil & Alat (semua paket) ──────────────────
        st.divider()
        st.markdown("### ⚠️ Konflik Personil & Alat Lintas Paket")
        st.caption("Personil atau alat yang diajukan penyedia di >1 paket aktif (berdasarkan Draft Paket).")
        if st.button("🔄 Cek Konflik", key="kual_cek_konflik"):
            try:
                import conflict_engine as _ce_dash
                _kf_p_all = _ce_dash.get_konflik_personil()
                _kf_a_all = _ce_dash.get_konflik_alat()
                if not _kf_p_all and not _kf_a_all:
                    st.success("✅ Tidak ada konflik ditemukan.")
                else:
                    if _kf_p_all:
                        st.markdown(f"**Personil konflik: {len(_kf_p_all)} nama**")
                        _rows_kf = []
                        for k in _kf_p_all:
                            for e in k["paket"]:
                                _rows_kf.append({
                                    "Nama Personil": k["nama_personil"],
                                    "Kode Tender": e["kode_tender"],
                                    "Penyedia": e["nama_penyedia"] or "-",
                                })
                        st.dataframe(_rows_kf, use_container_width=True, hide_index=True)
                    if _kf_a_all:
                        st.markdown(f"**Alat konflik: {len(_kf_a_all)} nama**")
                        _rows_ka = []
                        for k in _kf_a_all:
                            for e in k["paket"]:
                                _rows_ka.append({
                                    "Nama Alat": k["nama_alat"],
                                    "Kode Tender": e["kode_tender"],
                                    "Penyedia": e["nama_penyedia"] or "-",
                                })
                        st.dataframe(_rows_ka, use_container_width=True, hide_index=True)
            except Exception as _e_dash:
                st.error(f"Error: {_e_dash}")

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
