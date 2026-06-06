"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import glob as _glob_mod
import pathlib
import re
import sys
import threading
import time
from datetime import datetime, timedelta, date
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Suppress Playwright/CDP/Node stderr noise di console Streamlit
import io as _io
_devnull = open(os.devnull, "w", encoding="utf-8")


class _SuppressPlaywrightStderr:
    """Context manager: mute stderr selama operasi CDP agar terminal tidak kedap-kedip."""
    def __enter__(self):
        self._orig = sys.stderr
        sys.stderr = _devnull
        return self
    def __exit__(self, *_):
        sys.stderr = self._orig


def _pokja_label(p: dict) -> str:
    """Buat label ringkas paket: 'Pokja 086 · 10096884000 — Nama Paket'."""
    pokja_raw = p.get("pokja") or ""
    m = re.search(r"\d+", pokja_raw)
    pokja_no = m.group() if m else p.get("kode", "")
    return f"Pokja {pokja_no} · {p['kode']} — {p['nama']}"


def _get_paket_gabungan() -> list[dict]:
    """Gabung global_paket_draft + global_paket_aktif, deduplikasi by kode."""
    draft_list = st.session_state.get("global_paket_draft", {}).get("paket", [])
    aktif_list = st.session_state.get("global_paket_aktif", {}).get("paket", [])
    seen, result = set(), []
    for p in draft_list + aktif_list:
        if p["kode"] not in seen:
            seen.add(p["kode"])
            result.append(p)
    return result

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
_MODE_OPTIONS = ["Tender", "PL - Konsultansi", "PL - Konstruksi"]
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
                ok = spse_browser.refresh_browser()
                if not ok:
                    st.toast("⚠️ Reload gagal — CDP tidak responsif", icon="⚠️")
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

if st.session_state["app_mode"] == "PL - Konsultansi":
    # ============================================================
    # MODE: PENGADAAN LANGSUNG (PL JKK & PL PK)
    # ============================================================
    _pl_tab0, _pl_tab1, _pl_tab2, _pl_tab3, _pl_tab4, _pl_tab5, _pl_tab6, _pl_tab7, _pl_tab8 = st.tabs([
        "0️⃣ Import DPA",
        "1️⃣ Draft Paket PL",
        "2️⃣ Kirim Undangan DPP",
        "3️⃣ Buat Jadwal",
        "4️⃣ Setup Paket",
        "5️⃣ Download Kualifikasi",
        "6️⃣ Evaluasi & Teknis/Biaya",
        "7️⃣ Kirim Verifikasi",
        "8️⃣ Upload BA PL",
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

        # ── Tools: Gabung Semua BA PL JKK (Bulk Print) ────────────────────────
        st.divider()
        st.markdown("### 🖨️ Gabung Semua BA PL JKK")
        st.caption(
            "Scan semua folder paket di **@ Pengadaan Langsung JKK** → ambil file `BA_PLJKK_*.pdf` "
            "tiap folder → gabung jadi satu file untuk print sekali."
        )

        import os as _ba_os
        import re as _ba_re

        # Root folder PL JKK (parent dari semua folder paket)
        _ba_root = r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung JKK"
        _ba_root_in = st.text_input(
            "Folder root PL JKK:",
            value=_ba_root,
            key="ba_bulk_root",
        )

        def _ba_nomor_folder(nama):
            """Ambil nomor urut dari nama folder (mis. '10. PLJKK...' → 10). Tanpa nomor → 9999."""
            m = _ba_re.match(r"\s*(\d+)", nama)
            return int(m.group(1)) if m else 9999

        _ba_found = []  # (nomor, nama_folder, path_pdf)
        if _ba_os.path.isdir(_ba_root_in):
            for _entry in _ba_os.listdir(_ba_root_in):
                _sub = _ba_os.path.join(_ba_root_in, _entry)
                if not _ba_os.path.isdir(_sub):
                    continue
                # Match BA_PLJKK_*.pdf (bukan BA_REVIU_* / BA lain)
                _matches = [
                    f for f in _ba_os.listdir(_sub)
                    if _ba_re.match(r"(?i)^BA_PLJKK_.*\.pdf$", f)
                ]
                for _mf in _matches:
                    _ba_found.append((
                        _ba_nomor_folder(_entry), _entry,
                        _ba_os.path.join(_sub, _mf),
                    ))
            _ba_found.sort(key=lambda x: (x[0], x[1]))
        else:
            st.error(f"Folder tidak ditemukan: {_ba_root_in}")

        if _ba_found:
            st.success(f"✅ Ditemukan {len(_ba_found)} file BA_PLJKK (urut nomor paket):")
            _ba_prev = [
                {"No": n, "Folder": fol, "File": _ba_os.path.basename(p)}
                for n, fol, p in _ba_found
            ]
            st.dataframe(_ba_prev, use_container_width=True, hide_index=True)

            _ba_out_nama = st.text_input(
                "Nama file gabungan:",
                value="_KUMPULAN_BA_PL_JKK.pdf",
                key="ba_bulk_out_nama",
            )

            if st.button("🖨️ Gabung Semua BA", type="primary", key="ba_bulk_run"):
                from pypdf import PdfReader as _BaReader, PdfWriter as _BaWriter

                _writer = _BaWriter()
                _ok, _err = 0, []
                with st.status("Menggabungkan BA...", expanded=True) as _ba_status:
                    for _n, _fol, _path in _ba_found:
                        try:
                            _rdr = _BaReader(_path)
                            for _pg in _rdr.pages:
                                _writer.add_page(_pg)
                            st.write(f"✅ Paket {_n} — {len(_rdr.pages)} hlm")
                            _ok += 1
                        except Exception as _ex:
                            st.write(f"❌ Paket {_n} ({_fol}): {_ex}")
                            _err.append(_fol)

                    if len(_writer.pages) == 0:
                        _ba_status.update(label="❌ Tidak ada halaman tergabung.", state="error")
                    else:
                        # Tulis ke root folder; fallback suffix jika file terkunci (Nitro/dll)
                        _out_nama = _ba_out_nama.strip() or "_KUMPULAN_BA_PL_JKK.pdf"
                        if not _out_nama.lower().endswith(".pdf"):
                            _out_nama += ".pdf"
                        _base, _ext = _ba_os.path.splitext(_out_nama)
                        _target = _ba_os.path.join(_ba_root_in, _out_nama)
                        _written = None
                        for _attempt in range(6):
                            _try_path = _target if _attempt == 0 else \
                                _ba_os.path.join(_ba_root_in, f"{_base}_v{_attempt + 1}{_ext}")
                            try:
                                with open(_try_path, "wb") as _fh:
                                    _writer.write(_fh)
                                _written = _try_path
                                break
                            except PermissionError:
                                continue
                        if _written:
                            _ba_status.update(
                                label=f"✅ {_ok} BA digabung → {len(_writer.pages)} halaman.",
                                state="complete",
                            )
                            st.success(f"📁 Tersimpan: `{_written}`")
                            if _err:
                                st.warning(f"⚠️ Gagal: {', '.join(_err)}")
                        else:
                            _ba_status.update(
                                label="❌ Gagal tulis (file terkunci). Tutup PDF viewer dulu.",
                                state="error",
                            )
        elif _ba_os.path.isdir(_ba_root_in):
            st.info("Tidak ada file `BA_PLJKK_*.pdf` ditemukan di folder paket manapun.")

    # ── Tab 1: Draft Paket PL ─────────────────────────────────────────────────
    with _pl_tab1:
        import os as _pl_os, subprocess as _pl_sp
        from config import POKJA_ROOT as _PL_POKJA_ROOT, OUTPUT_DIR_PL_JKK as _PL_DIR_JKK, OUTPUT_DIR_PL_PK as _PL_DIR_PK
        _TEMPLATE_DIR_PL    = str(__import__("pathlib").Path(_PL_POKJA_ROOT) / "Paket Experiment - Pengadaan Langsung" / "Development - PL - JKK")
        _TEMPLATE_DIR_PL_PK = str(__import__("pathlib").Path(_PL_POKJA_ROOT) / "Paket Experiment - Pengadaan Langsung" / "Development - PL - PK")

        _PL_PY     = str(pathlib.Path(_PL_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110" / "python" / "python.exe")
        _PL_SCRIPT = str(pathlib.Path(_PL_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110" / "setup_paket_baru.py")
        _PL_NO_WIN = 0x08000000

        def _cari_xlsm_pl(folder):
            """Cari .xlsm utama di folder paket PL (prefix '0. BA', skip Backup)."""
            try:
                xs = [f for f in _pl_os.listdir(folder)
                      if f.lower().endswith(".xlsm") and "backup" not in f.lower()]
            except Exception:
                return None
            if not xs:
                return None
            xs.sort(key=lambda f: (not f.lower().startswith("0. ba"), f))
            return _pl_os.path.join(folder, xs[0])

        _pl_rows = pl_engine.load_draft_pl()

        # ── Buang duplikat row lama (paket di-ulang → kode baru, row lama nyangkut) ──
        _pl_rows, _pl_dup_n = pl_engine.buang_duplikat_paket_lama(_pl_rows)
        if _pl_dup_n:
            st.caption(f"♻️ {_pl_dup_n} row lama duplikat (paket ulang) disembunyikan otomatis.")

        # ── #4: Filter paket selesai (penandatanganan kontrak) ──────────────────
        _pl_show_done = st.checkbox(
            "Tampilkan paket selesai (sudah teken kontrak)",
            value=False,
            key="pl_show_done",
        )
        _pl_done_n = sum(1 for r in _pl_rows if pl_engine.is_paket_selesai(r))
        if not _pl_show_done:
            _pl_rows = [r for r in _pl_rows if not pl_engine.is_paket_selesai(r)]
            if _pl_done_n:
                st.caption(f"🔒 {_pl_done_n} paket selesai (Penandatanganan Kontrak) disembunyikan — centang di atas untuk tampilkan.")

        _pl_col_kiri, _pl_col_kanan = st.columns(2)

        # ══════════════════════════════════════════════════════
        # KOLOM KIRI — Serap Data + Daftar Paket
        # ══════════════════════════════════════════════════════
        with _pl_col_kiri:
            # ── #1: Gabung Serap SPSE + MAK + HPS ──────────────────────────────
            st.markdown("#### 1. Serap Data Paket PL")
            st.caption("Pilih aksi lalu klik tombol — aksi berjalan berurutan sesuai centang.")
            _cb_serap_spse = st.checkbox("Serap dari SPSE (daftar paket + status)", value=True, key="pl_cb_serap_spse")
            _cb_serap_mak  = st.checkbox("Serap MAK dari Inbox PL",               value=True, key="pl_cb_serap_mak")
            _cb_hps_all    = st.checkbox("Scrape HPS semua paket berfolder → Excel", value=True, key="pl_cb_hps_all")

            if st.button("🚀 Serap Data Paket PL", type="primary", use_container_width=True, key="btn_serap_pl_gabung"):
                # Aksi 1: Serap dari SPSE
                if _cb_serap_spse:
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
                            with st.expander("Detail Error SPSE"):
                                for _e in _pl_hasil["errors"]:
                                    st.error(_e)
                        # Reload setelah serap SPSE agar data paket terkini
                        _pl_rows = pl_engine.load_draft_pl()
                        if not _pl_show_done:
                            _pl_rows = [r for r in _pl_rows if not _pl_is_done(r)]

                # Aksi 2: Serap MAK dari Inbox
                if _cb_serap_mak:
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
                            with st.expander("Detail Error MAK"):
                                for _e in _r_mak["errors"]:
                                    st.warning(_e)
                    except Exception as _e:
                        st.error(f"Gagal serap MAK: {_e}")

                # Aksi 3: HPS bulk semua paket berfolder
                if _cb_hps_all:
                    import hps_engine as _hps_pl_bulk
                    import kualifikasi_engine_pl as _keng_pl_hb
                    _pl_rows_hps_bulk = [
                        r for r in _pl_rows
                        if r.get("kode_paket") and r.get("folder_dibuat")
                    ]
                    if not _pl_rows_hps_bulk:
                        st.info("Tidak ada paket dengan folder untuk scrape HPS.")
                    else:
                        _hps_bulk_ok, _hps_bulk_fail = 0, 0
                        _hps_bulk_gagal = []
                        _hps_bulk_status = st.status(
                            f"💰 Scrape HPS {len(_pl_rows_hps_bulk)} paket...", expanded=True
                        )
                        _hps_bulk_line = _hps_bulk_status.empty()
                        _hps_bulk_bp = st.progress(0.0)
                        for _hb_i, _hb_row in enumerate(_pl_rows_hps_bulk):
                            _hb_kp   = _hb_row.get("kode_paket", "")
                            _hb_nama = _hb_row.get("nama_paket", _hb_kp)[:50]
                            _hps_bulk_status.update(label=f"[{_hb_i+1}/{len(_pl_rows_hps_bulk)}] {_hb_nama}")
                            _hps_bulk_bp.progress((_hb_i + 1) / len(_pl_rows_hps_bulk))
                            _hb_xlsm = None
                            try:
                                _hb_fr = _keng_pl_hb.resolve_folder_paket_pl(_hb_kp)
                                _hb_root = _hb_fr.get("pesan", "") if _hb_fr.get("ok") else ""
                                if _hb_root and _pl_os.path.isdir(_hb_root):
                                    _hb_xlsm = _cari_xlsm_pl(_hb_root)
                            except Exception:
                                _hb_xlsm = None
                            if not _hb_xlsm:
                                _hps_bulk_fail += 1
                                _hb_alasan = "folder/xlsm paket tidak ditemukan"
                                _hps_bulk_gagal.append(f"{_hb_nama}: {_hb_alasan}")
                                _hps_bulk_line.write(f"⚠ [{_hb_i+1}] {_hb_nama} — {_hb_alasan}")
                                continue
                            try:
                                _hb_r = _hps_pl_bulk.scrape_hps_pl_ke_excel(_hb_kp, _hb_xlsm)
                                if _hb_r.get("ok"):
                                    _hps_bulk_ok += 1
                                    _hps_bulk_line.write(f"✅ [{_hb_i+1}] {_hb_nama} — {_hb_r['count']} item, Rp {_hb_r.get('total_nilai_bulat',0):,.0f}")
                                else:
                                    _hps_bulk_fail += 1
                                    _hb_alasan = _hb_r.get("pesan", "-")
                                    _hps_bulk_gagal.append(f"{_hb_nama}: {_hb_alasan}")
                                    _hps_bulk_line.write(f"❌ [{_hb_i+1}] {_hb_nama} — {_hb_alasan}")
                            except Exception as _hb_e:
                                _hps_bulk_fail += 1
                                _hps_bulk_gagal.append(f"{_hb_nama}: {_hb_e}")
                                _hps_bulk_line.write(f"❌ [{_hb_i+1}] {_hb_nama} — {_hb_e}")
                        _hps_bulk_bp.progress(1.0)
                        _hps_bulk_line.empty()
                        _hps_bulk_status.update(
                            label=f"💰 HPS Bulk selesai: ✅ {_hps_bulk_ok} sukses, ❌ {_hps_bulk_fail} gagal",
                            state="complete", expanded=_hps_bulk_fail > 0,
                        )
                        if _hps_bulk_gagal:
                            st.warning("Paket gagal:\n" + "\n".join(_hps_bulk_gagal))

            st.divider()
            st.markdown("#### 2. Daftar Paket PL")

            _pl_filter = st.selectbox(
                "Filter:",
                ["Semua", "JKK", "PK", "Belum Folder", "Sudah Folder"],
                key="pl_filter_jenis",
            )

            def _pl_match(r):
                _jp = (r.get("jenis_pl") or "").upper()
                if _pl_filter == "JKK":    return _jp == "JKK"
                if _pl_filter == "PK":     return _jp == "PK"
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
                    _pr_jenis  = (_pr.get("jenis_pl") or "").upper()
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

                        _pr_c1, _pr_c2 = st.columns([3, 1])
                        if _pr_c2.button("🗑️ Hapus", key=f"pl_hapus_{_pr_kode}", use_container_width=True):
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
                _jenis = (_r.get("jenis_pl") or "").upper()
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
                _pl_jenis_sel = (_pl_row_sel.get("jenis_pl") or "JKK").upper()
                _pl_prefix  = {"JKK": "PLJKK", "PK": "PLPK"}.get(_pl_jenis_sel, f"PL{_pl_jenis_sel}")
                _pl_no_urut = _pl_no_dari_nama(_pl_nm, len(_pl_rows))
                _pl_default_folder = f"{_pl_no_urut}. {_pl_prefix} - {_pl_nm}"

            _pl_nama_folder = st.text_input(
                "Nama folder:",
                value=_pl_default_folder,
                placeholder="1. PLJKK - Perencanaan Pembangunan Jalan ...",
                key="pl_input_nama_folder",
            )

            _pl_paksa_ulang = st.checkbox(
                "Paksa suffix (PL - Ulang)",
                value=False,
                key="pl_cb_paksa_ulang",
                help="Centang untuk tempel ' (PL - Ulang)' walau folder lama belum ada. "
                     "Default: auto-suffix hanya jika folder dengan nama sama sudah ada di disk.",
            )

            # Output base dir: JKK → @ Pengadaan Langsung JKK, PK → @ Pengadaan Langsung PK
            _pl_output_base = _PL_DIR_JKK if _pl_jenis_sel == "JKK" else _PL_DIR_PK
            _pl_nama_clean = re.sub(r'[/<>:"\|?*]', "-", _pl_nama_folder).strip() if _pl_nama_folder else ""
            if _pl_nama_clean:
                _pl_nama_clean = pl_engine.nama_folder_dengan_suffix_ulang(
                    _pl_output_base, _pl_nama_clean, paksa_suffix=_pl_paksa_ulang,
                )
                if _pl_nama_clean != re.sub(r'[/<>:"\|?*]', "-", _pl_nama_folder).strip():
                    st.caption(f"♻️ Paket ulang terdeteksi → folder: `{_pl_nama_clean}`")
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
                    # Scrape HPS PL otomatis → tulis langsung ke Excel (tanpa DB)
                    try:
                        import hps_engine as _hps_pl
                        _xl_pl = _cari_xlsm_pl(_pl_target)
                        if _xl_pl:
                            _hps_r = _hps_pl.scrape_hps_pl_ke_excel(_pl_kode_dl, _xl_pl)
                            if _hps_r.get("ok"):
                                st.success(f"💰 {_hps_r['pesan']} — Total Rp {_hps_r.get('total_nilai_bulat',0):,.0f}")
                            else:
                                st.warning(f"⚠ HPS: {_hps_r.get('pesan','-')}")
                        else:
                            st.caption("💰 HPS dilewati — tidak ada .xlsm di folder.")
                    except Exception as _he:
                        st.warning(f"⚠ HPS error: {_he}")

            # Tombol scrape HPS mandiri (kalau download sebelumnya tidak include)
            if _pl_folder_ada and _pl_row_sel:
                _pl_kode_hps = _pl_row_sel.get("kode_paket", "")
                if _pl_kode_hps and st.button("💰 Scrape HPS PL → Excel", use_container_width=True, key="pl_btn_hps_saja"):
                    import hps_engine as _hps_pl
                    _xl_pl2 = _cari_xlsm_pl(_pl_target)
                    if not _xl_pl2:
                        st.error("Tidak ada file .xlsm di folder paket untuk diisi HPS.")
                    else:
                        with st.spinner("Scrape HPS dari SPSE → tulis Excel..."):
                            _hps_r = _hps_pl.scrape_hps_pl_ke_excel(_pl_kode_hps, _xl_pl2)
                        if _hps_r.get("ok"):
                            st.success(f"✅ {_hps_r['pesan']} — Total Rp {_hps_r.get('total_nilai_bulat',0):,.0f}")
                            if _hps_r.get("warning"):
                                st.warning(f"⚠ {len(_hps_r['warning'])} item selisih (highlight kuning di Excel)")
                        else:
                            st.error(f"Gagal: {_hps_r.get('pesan','-')}")

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
                                    # Scrape HPS PL → tulis langsung ke Excel
                                    try:
                                        import hps_engine as _hps_pl
                                        _xl_pl3 = _cari_xlsm_pl(_pl_target)
                                        if _xl_pl3:
                                            _hps_r = _hps_pl.scrape_hps_pl_ke_excel(_pl_kp, _xl_pl3)
                                            if _hps_r.get("ok"):
                                                st.success(f"💰 {_hps_r['pesan']} — Rp {_hps_r.get('total_nilai_bulat',0):,.0f}")
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
                _bj0   = (_br0.get("jenis_pl") or "JKK").upper()
                _bpfx0 = {"JKK": "PLJKK", "PK": "PLPK"}.get(_bj0, f"PL{_bj0}")
                _bno0  = _pl_no_dari_nama(_bnm0, _bi0)
                _bnm_folder0 = re.sub(r'[/<>:"\|?*]', "-", f"{_bno0}. {_bpfx0} - {_bnm0}").strip()
                _bout_base0  = _PL_DIR_JKK if _bj0 == "JKK" else _PL_DIR_PK
                _bnm_folder0 = pl_engine.nama_folder_dengan_suffix_ulang(_bout_base0, _bnm_folder0)
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

            # ── #2: Checklist pilih paket untuk buat folder ──────────────────
            if _pl_rows_belum:
                st.markdown("**Pilih paket yang akan dibuat foldernya:**")
                _plf_col1, _plf_col2 = st.columns(2)
                # Tombol pilih semua / batal semua (tiru pola Tab 5)
                if _plf_col1.button("✅ Pilih Semua", key="plf_pilih_semua", use_container_width=True):
                    for _br_chk in _pl_rows_belum:
                        st.session_state[f"plf_chk_{_br_chk.get('kode_paket','')}"] = True
                    st.rerun()
                if _plf_col2.button("❌ Batal Semua", key="plf_batal_semua", use_container_width=True):
                    for _br_chk in _pl_rows_belum:
                        st.session_state[f"plf_chk_{_br_chk.get('kode_paket','')}"] = False
                    st.rerun()
                for _br_chk in _pl_rows_belum:
                    _bkp_chk = _br_chk.get("kode_paket", "")
                    st.checkbox(
                        f"{_br_chk.get('nama_paket','')[:60]} — {(_br_chk.get('jenis_pl') or '').upper()}",
                        value=st.session_state.get(f"plf_chk_{_bkp_chk}", True),
                        key=f"plf_chk_{_bkp_chk}",
                    )
                # Hitung yang dicentang untuk label tombol
                _pl_terpilih_plan = [
                    item for item in _pl_bulk_plan
                    if st.session_state.get(f"plf_chk_{item['kode_paket']}", True)
                ]
                if st.button(
                    f"📁 Buat Folder Terpilih ({len(_pl_terpilih_plan)} paket)",
                    disabled=len(_pl_terpilih_plan) == 0,
                    use_container_width=True,
                    key="pl_btn_buat_terpilih",
                    type="primary",
                ):
                    _pl_bp = st.progress(0.0)
                    _pl_bulk_status = st.status(f"📁 Memproses {len(_pl_terpilih_plan)} paket terpilih...", expanded=True)
                    _pl_bulk_status_line = _pl_bulk_status.empty()
                    _pl_ok, _pl_fail = 0, 0
                    _pl_bulk_semua_log = {}
                    for _pl_i, _pl_bp_item in enumerate(_pl_terpilih_plan):
                        _pl_bp.progress((_pl_i + 1) / len(_pl_terpilih_plan))
                        _pl_nf = _pl_bp_item["nama_folder"]
                        _pl_kp_b = _pl_bp_item["kode_paket"]
                        _pl_out_b = _pl_bp_item["out_base"]
                        _pl_target_b = _pl_os.path.join(_pl_out_b, _pl_nf)
                        _pl_bulk_status.update(label=f"[{_pl_i+1}/{len(_pl_terpilih_plan)}] {_pl_nf[:60]}")
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
                                if _pl_dl_dokumen and _pl_kp_b:
                                    def _pl_bulk_cb(msg, _log=_pl_paket_log):
                                        _log.append(msg)
                                        _pl_bulk_status_line.code("\n".join(_log[-10:]))
                                    try:
                                        _pl_dl_hasil = pl_engine.download_dokumen_paket_pl(
                                            _pl_kp_b, _pl_target_b, progress_cb=_pl_bulk_cb,
                                        )
                                        _pl_paket_log.append(
                                            f"📎 Download: ✅{len(_pl_dl_hasil['ok'])} file"
                                            + (f" | Draft: {_pl_os.path.basename(_pl_dl_hasil['draft_pdf'])}" if _pl_dl_hasil.get('draft_pdf') else " | ⚠ Draft tidak terbuat")
                                        )
                                        for _pl_e in _pl_dl_hasil.get("error", []):
                                            _pl_paket_log.append(f"  ❌ {_pl_e}")
                                    except Exception as _pl_dl_e:
                                        _pl_paket_log.append(f"❌ Download error: {_pl_dl_e}")
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
                                if _pl_kp_b:
                                    try:
                                        import hps_engine as _pl_hps_eng
                                        _xl_plb = _cari_xlsm_pl(_pl_target_b)
                                        if _xl_plb:
                                            _pl_hps_res = _pl_hps_eng.scrape_hps_pl_ke_excel(_pl_kp_b, _xl_plb)
                                            if _pl_hps_res.get("ok"):
                                                _pl_paket_log.append(f"📊 HPS: {_pl_hps_res.get('count', 0)} baris → Excel")
                                            else:
                                                _pl_paket_log.append(f"⚠ HPS: {_pl_hps_res.get('pesan','-')}")
                                        else:
                                            _pl_paket_log.append("⚠ HPS dilewati — tidak ada .xlsm")
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
            # ── #3: Serap Penyedia + Download Dokumen Bulk ───────────────────────
            st.divider()
            st.markdown("#### 3. Serap Penyedia + Download Dokumen SPSE")
            st.caption("Pilih aksi lalu klik tombol — berjalan untuk semua paket berfolder.")
            _cb_serap_pyd  = st.checkbox("Serap Penyedia dari Draft_PL (nama, NPWP)", value=True, key="pl_cb_serap_pyd")
            _cb_dl_dok_bulk = st.checkbox("Download Dokumen SPSE bulk (KAK, Personil, Kontrak)", value=True, key="pl_cb_dl_dok_bulk")

            if st.button("📦 Serap Penyedia + Dokumen SPSE", use_container_width=True, key="btn_pyd_dl_gabung"):
                # Aksi: Serap penyedia dari Draft_PL PDF
                if _cb_serap_pyd:
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
                            with st.expander("Detail Error Penyedia"):
                                for _e in _r_pyd["errors"]:
                                    st.warning(_e)
                    except Exception as _e:
                        st.error(f"Gagal serap penyedia: {_e}")

                # Aksi: Download dokumen bulk semua paket berfolder
                if _cb_dl_dok_bulk:
                    import kualifikasi_engine_pl as _keng_pl_dl
                    _pl_rows_dl_bulk = [
                        r for r in _pl_rows
                        if r.get("kode_paket") and r.get("folder_dibuat")
                    ]
                    if not _pl_rows_dl_bulk:
                        st.info("Tidak ada paket dengan folder untuk download dokumen.")
                    else:
                        _dl_bulk_ok, _dl_bulk_fail = 0, 0
                        _dl_bulk_status = st.status(
                            f"📦 Download dokumen {len(_pl_rows_dl_bulk)} paket...", expanded=True
                        )
                        _dl_bulk_line = _dl_bulk_status.empty()
                        _dl_bulk_bp = st.progress(0.0)
                        for _db_i, _db_row in enumerate(_pl_rows_dl_bulk):
                            _db_kp   = _db_row.get("kode_paket", "")
                            _db_nama = _db_row.get("nama_paket", _db_kp)[:50]
                            _dl_bulk_status.update(label=f"[{_db_i+1}/{len(_pl_rows_dl_bulk)}] {_db_nama}")
                            _dl_bulk_bp.progress((_db_i + 1) / len(_pl_rows_dl_bulk))
                            _db_root = ""
                            try:
                                _db_fr = _keng_pl_dl.resolve_folder_paket_pl(_db_kp)
                                _db_root = _db_fr.get("pesan", "") if _db_fr.get("ok") else ""
                            except Exception:
                                _db_root = ""
                            if not _db_root or not _pl_os.path.isdir(_db_root):
                                _dl_bulk_fail += 1
                                _dl_bulk_line.write(f"⚠ [{_db_i+1}] {_db_nama} — folder tidak ditemukan")
                                continue
                            try:
                                _db_dl_logs = []
                                def _db_dl_cb(msg, _log=_db_dl_logs):
                                    _log.append(msg)
                                _db_dl_res = pl_engine.download_dokumen_paket_pl(_db_kp, _db_root, _db_dl_cb)
                                _dl_bulk_ok += 1
                                _dl_bulk_line.write(f"✅ [{_db_i+1}] {_db_nama} — {len(_db_dl_res.get('ok',[]))} file")
                                # Parse KAK setelah download
                                _db_kak_p = parse_kak_pl.cari_kak_di_folder(_db_root)
                                if _db_kak_p:
                                    _db_kak_d = parse_kak_pl.parse_kak(_db_kak_p)
                                    _db_kak_u = {k: v for k, v in _db_kak_d.items() if v}
                                    if _db_kak_u:
                                        pl_engine.simpan_paket_pl({"kode_paket": _db_kp, **_db_kak_u})
                            except Exception as _db_e:
                                _dl_bulk_fail += 1
                                _dl_bulk_line.write(f"❌ [{_db_i+1}] {_db_nama} — {_db_e}")
                        _dl_bulk_bp.progress(1.0)
                        _dl_bulk_line.empty()
                        _dl_bulk_status.update(
                            label=f"📦 Download selesai: ✅ {_dl_bulk_ok} sukses, ❌ {_dl_bulk_fail} gagal",
                            state="complete", expanded=_dl_bulk_fail > 0,
                        )


            # ── #5: Reset Status Folder — multiselect (kosong = semua) ───────
            with st.expander("↩️ Reset Status Folder"):
                st.caption("Kosongkan `folder_dibuat` agar paket muncul kembali di Buat Folder (folder fisik tidak dihapus).")
                _opsi_reset_pl = {
                    f"{r.get('nama_paket','')[:60]} — {r.get('jenis_pl','')}": r.get("kode_paket")
                    for r in _pl_rows if r.get("folder_dibuat") and r.get("kode_paket")
                }
                if _opsi_reset_pl:
                    from config import sb as _sb_reset
                    _pilih_reset_pl = st.multiselect(
                        "Pilih paket reset (kosong = semua):",
                        list(_opsi_reset_pl.keys()),
                        key="pl_ms_reset",
                    )
                    if st.button("↩️ Reset Status Folder", type="secondary", key="pl_btn_reset_folder"):
                        # Jika kosong → reset semua; jika ada pilihan → reset pilihan saja
                        _target_reset = _pilih_reset_pl if _pilih_reset_pl else list(_opsi_reset_pl.keys())
                        _reset_ok_pl = 0
                        for _kr in [_opsi_reset_pl[k] for k in _target_reset]:
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
                            # Scrape HPS → tulis langsung ke Excel
                            if _pl_kp_b:
                                try:
                                    import hps_engine as _pl_hps_eng
                                    _xl_plb = _cari_xlsm_pl(_pl_target_b)
                                    if _xl_plb:
                                        _pl_hps_res = _pl_hps_eng.scrape_hps_pl_ke_excel(_pl_kp_b, _xl_plb)
                                        if _pl_hps_res.get("ok"):
                                            _pl_paket_log.append(f"📊 HPS: {_pl_hps_res.get('count', 0)} baris → Excel")
                                        else:
                                            _pl_paket_log.append(f"⚠ HPS: {_pl_hps_res.get('pesan','-')}")
                                    else:
                                        _pl_paket_log.append("⚠ HPS dilewati — tidak ada .xlsm")
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

            # ── Refresh Template ke Folder PL Existing ────────────────────────
            st.divider()
            with st.expander("🔄 Refresh Template ke Folder PL Existing"):
                st.caption("Copy file template terbaru ke folder paket yang sudah dibuat (tanpa download ulang SPSE).")
                from refresh_template import refresh_template_paket as _rt_refresh
                from pathlib import Path as _rt_Path

                # Scan folder fisik (folder_dibuat di Supabase = True boolean, bukan nama folder)
                _rt_scan_jkk = [
                    ("JKK", p) for p in _rt_Path(_PL_DIR_JKK).iterdir()
                    if p.is_dir()
                ] if _rt_Path(_PL_DIR_JKK).exists() else []
                _rt_scan_pk = [
                    ("PK", p) for p in _rt_Path(_PL_DIR_PK).iterdir()
                    if p.is_dir()
                ] if _rt_Path(_PL_DIR_PK).exists() else []
                _rt_semua_folder = _rt_scan_jkk + _rt_scan_pk

                if not _rt_semua_folder:
                    st.info("Belum ada folder paket PL di output directory.")
                else:
                    _rt_opsi_pl = {
                        f"{p.name} ({jenis})": (jenis, p)
                        for jenis, p in _rt_semua_folder
                    }
                    _rt_all_pl = st.checkbox("Pilih Semua", key="rt_all_pl")
                    _rt_pilih_pl = st.multiselect(
                        "Pilih paket PL:",
                        list(_rt_opsi_pl.keys()),
                        default=list(_rt_opsi_pl.keys()) if _rt_all_pl else [],
                        key="rt_ms_pl",
                    )
                    _rt_dry_pl = st.checkbox("Dry-run (preview saja, tidak ada perubahan)", value=True, key="rt_dry_pl")
                    _rt_relink_pl = True  # Selalu relink Word → Excel setelah copy template

                    if _rt_pilih_pl and st.button(
                        f"🔄 Refresh Template PL ke {len(_rt_pilih_pl)} Paket",
                        type="primary",
                        key="rt_btn_pl",
                    ):
                        _rt_folder_pl = []
                        for _rt_k in _rt_pilih_pl:
                            _rt_jenis, _rt_full = _rt_opsi_pl[_rt_k]
                            _rt_folder_pl.append((_rt_jenis, _rt_full))

                        _rt_ok_pl, _rt_fail_pl = 0, 0
                        _rt_log_container = st.container(border=True)
                        for _rt_jenis_f, _rt_fld in _rt_folder_pl:
                            _rt_mode = "pl_jkk" if _rt_jenis_f == "JKK" else "pl_pk"
                            _rt_src   = _rt_Path(_TEMPLATE_DIR_PL if _rt_jenis_f == "JKK" else _TEMPLATE_DIR_PL_PK)
                            _rt_res   = _rt_refresh(
                                [_rt_fld], _rt_src, _rt_mode,
                                auto_relink=_rt_relink_pl, dry_run=_rt_dry_pl,
                            )
                            for _rt_fk, _rt_logs in _rt_res.items():
                                _ok_f = all("❌" not in l for l in _rt_logs)
                                if _ok_f:
                                    _rt_ok_pl += 1
                                else:
                                    _rt_fail_pl += 1
                                _rt_log_container.markdown(f"**{_rt_Path(_rt_fk).name[:60]}**")
                                for _l in _rt_logs:
                                    _rt_log_container.caption(_l)
                        _rt_label = f"✅ {_rt_ok_pl} OK, ❌ {_rt_fail_pl} gagal"
                        if _rt_dry_pl:
                            _rt_label = "[DRY-RUN] " + _rt_label
                        if _rt_fail_pl == 0:
                            st.success(_rt_label)
                        else:
                            st.warning(_rt_label)

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
                            _ku_lamp = _kp.get("kode_unik") or _kp["kode_paket"]
                            _lamp_nama  = f"undangan_reviu_{_ku_lamp}.pdf"
                            if _lamp_bytes:
                                st.session_state.setdefault("_kd_pdf_cache", {})[_ku_lamp] = (_lamp_nama, _lamp_bytes)

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
                        # Tombol download per PDF
                        for _ku_dl, (_nm_dl, _by_dl) in st.session_state.get("_kd_pdf_cache", {}).items():
                            st.download_button(
                                f"⬇️ Download {_nm_dl}",
                                data=_by_dl,
                                file_name=_nm_dl,
                                mime="application/pdf",
                                key=f"kd_dl_{_ku_dl}",
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
                # Tanggal BA — di atas daftar paket
                _ba_pl_tgl = st.date_input(
                    "Tanggal BA Reviu",
                    value=datetime.now().date(),
                    key="plba_tgl",
                    format="DD/MM/YYYY",
                )
                st.caption(f"{_HARI_NAMA[_ba_pl_tgl.weekday()]}, {_ba_pl_tgl.day} {_BULAN_NAMA[_ba_pl_tgl.month-1]} {_ba_pl_tgl.year}")

                def _do_upload_ba_pl(paket_list, tgl):
                    hasil = []
                    prog = st.progress(0, text="Memulai upload...")
                    for _i, _p in enumerate(paket_list):
                        prog.progress(
                            (_i + 1) / len(paket_list),
                            text=f"Upload {_p['kode_paket']} ({_i+1}/{len(paket_list)})...",
                        )
                        _res = _ubrpl.upload_ba_reviu_pl(
                            kode_paket=_p["kode_paket"],
                            file_bytes=_p["_ba_file"].getvalue(),
                            file_name=_p["_ba_file"].name,
                            tgl_ba=tgl.strftime("%d-%m-%Y"),
                        )
                        hasil.append({
                            "kode":   _p["kode_paket"],
                            "nama":   _p["nama_paket"][:50],
                            "sukses": _res["ok"],
                            "pesan":  f"HTTP {_res.get('status','?')}" if _res["ok"] else _res.get("error", "?"),
                        })
                    prog.empty()
                    _ok = sum(1 for h in hasil if h["sukses"])
                    _fail = len(hasil) - _ok
                    if _fail == 0:
                        st.success(f"✅ {_ok} BA Reviu berhasil diupload!")
                    else:
                        st.warning(f"⚠️ {_ok} berhasil, {_fail} gagal.")
                    st.dataframe(hasil, use_container_width=True, hide_index=True)

                # Centang Semua / Hapus Semua
                _ba_col_sel, _ba_col_clr, _ = st.columns([1, 1, 4])
                with _ba_col_sel:
                    if st.button("☑️ Centang Semua", key="plba_sel_all", use_container_width=True):
                        for _pp2 in _pl_rows_ba:
                            st.session_state[f"plba_chk_{_pp2['kode_paket']}"] = True
                        st.rerun()
                with _ba_col_clr:
                    if st.button("🔲 Hapus Semua", key="plba_clr_all", use_container_width=True):
                        for _pp2 in _pl_rows_ba:
                            st.session_state[f"plba_chk_{_pp2['kode_paket']}"] = False
                        st.rerun()

                # Daftar paket — per baris: checkbox + file uploader + tombol upload per paket
                _ba_pl_selected = []
                for _pp in _pl_rows_ba:
                    _ba_key  = f"plba_chk_{_pp['kode_paket']}"
                    _ba_fkey = f"plba_file_{_pp['kode_paket']}"
                    _bcol_chk, _bcol_file, _bcol_btn = st.columns([3, 3, 1])
                    with _bcol_chk:
                        _ba_chk = st.checkbox(
                            f"**{_pp['kode_paket']}** — {_pp['nama_paket'][:40]}",
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
                    with _bcol_btn:
                        if _ba_up and st.button("📤", key=f"plba_up1_{_pp['kode_paket']}", help="Upload paket ini"):
                            _do_upload_ba_pl([{**_pp, "_ba_file": _ba_up}], _ba_pl_tgl)
                    if _ba_chk:
                        _ba_pl_selected.append({**_pp, "_ba_file": _ba_up})

                # Tombol upload semua yang sudah centang + ada file
                _ba_pl_valid = [_p for _p in _ba_pl_selected if _p.get("_ba_file")]
                if st.button(
                    f"📤 Upload Semua BA Reviu ({len(_ba_pl_valid)} file)",
                    key="plba_upload",
                    type="primary",
                    disabled=len(_ba_pl_valid) == 0,
                    use_container_width=True,
                ):
                    _do_upload_ba_pl(_ba_pl_valid, _ba_pl_tgl)

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
                            # Simpan tgl ke Supabase + push GCal
                            if _sub["ok"]:
                                try:
                                    _jad = _r["jadwal_list"]
                                    pl_engine.simpan_paket_pl({
                                        "kode_paket":            _p["kode_paket"],
                                        "tgl_batas_penawaran":   _jad[0]["selesai"].strftime("%Y-%m-%d"),
                                        "tgl_buka_penawaran":    _jad[1]["mulai"].strftime("%Y-%m-%d"),
                                        "tgl_evaluasi":          _jad[2]["selesai"].strftime("%Y-%m-%d"),
                                        "tgl_negosiasi":         _jad[3]["mulai"].strftime("%Y-%m-%d"),
                                        "tgl_penetapan":         _jad[4]["mulai"].strftime("%Y-%m-%d"),
                                    })
                                except Exception:
                                    pass
                                try:
                                    import gcal_pl_helper as _gcalpl
                                    _gcalpl.push_jadwal_pl_ke_gcal(_kp, _p["nama_paket"], _r["jadwal_list"])
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

        st.divider()
        st.markdown("#### 🔄 Sync Jadwal ke Google Calendar")
        st.caption("Baca jadwal aktual dari SPSE → update GCal + Supabase tgl_evaluasi/tgl_negosiasi/tgl_penetapan. Jalankan setelah ada perubahan jadwal di SPSE.")
        _gcalpl_col1, _gcalpl_col2 = st.columns([2, 3])
        with _gcalpl_col1:
            _sync_gcal_pl_btn = st.button("🔄 Sync GCal PL", key="sync_gcal_pl_btn", use_container_width=True, type="primary")
        if _sync_gcal_pl_btn:
            import gcal_pl_helper as _gcalpl
            _gcalpl_prog = st.progress(0.0, text="Memulai sync...")
            _gcalpl_results = _gcalpl.sync_semua_paket_pl(
                progress_cb=lambda f, m: _gcalpl_prog.progress(f, text=m)
            )
            _gcalpl_prog.empty()
            _gcalpl_ok = sum(1 for r in _gcalpl_results if r["ok"])
            _gcalpl_skip = sum(1 for r in _gcalpl_results if not r["ok"] and "kosong" in r.get("error", ""))
            _gcalpl_err = len(_gcalpl_results) - _gcalpl_ok - _gcalpl_skip
            if _gcalpl_err == 0:
                st.success(f"✅ {_gcalpl_ok} paket sync OK, {_gcalpl_skip} skip (jadwal belum diisi SPSE).")
            else:
                st.warning(f"⚠️ {_gcalpl_ok} OK, {_gcalpl_skip} skip, {_gcalpl_err} error.")
            _gcalpl_display = [
                {
                    "Paket": r["nama_paket"],
                    "Status": "✅" if r["ok"] else ("⏭ Skip" if "kosong" in r.get("error","") else "❌"),
                    "GCal +": r["gcal_inserted"],
                    "GCal -": r["gcal_deleted"],
                    "Tgl Evaluasi": r["tgl_evaluasi"],
                    "Tgl Negosiasi": r["tgl_negosiasi"],
                    "Tgl Penetapan": r["tgl_penetapan"],
                    "Error": r["error"][:60] if r["error"] else "",
                }
                for r in _gcalpl_results
            ]
            st.dataframe(_gcalpl_display, use_container_width=True, hide_index=True)

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
                            # Tanggal: dari DB (tgl_dokpil) → fallback session → hari ini
                            _tgl_db = _rr.get("tgl_dokpil")
                            if _tgl_db:
                                try:
                                    from datetime import date as _date
                                    _tgl_prev = _date.fromisoformat(str(_tgl_db))
                                except Exception:
                                    _tgl_prev = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            else:
                                _tgl_prev = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            # Nomor: dari DB → fallback generate
                            _no_prev = _rr.get("nomor_dokpil") or _udpl.generate_nomor_dokpil(
                                nama_paket=_rr["nama_paket"],
                                kode_unik=_ku_prev,
                                skpd_singkat=_sk_prev,
                                tahun=_tgl_prev.year,
                            )
                            st.caption(f"📄 {_dokpil_up.name}  \n📋 `{_no_prev}`  \n📅 {_tgl_prev.strftime('%d-%m-%Y')}")
                            if st.button("📤 Upload Dokpil", key=f"plsp_upload_only_{_kp_key}", use_container_width=True):
                                with st.spinner("Mengupload dokpil..."):
                                    try:
                                        _r_up_only = _udpl.upload_dokpil_pl(
                                            kode_paket=_kp_key,
                                            file_bytes=_dokpil_up.getvalue(),
                                            file_name=_dokpil_up.name,
                                            nomor_dokpil=_no_prev,
                                            tgl_dokpil=_tgl_prev.strftime("%d-%m-%Y"),
                                        )
                                        if _r_up_only["ok"]:
                                            from config import sb as _sb_up_only
                                            _sb_up_only().table("draft_paket_pl").update({
                                                "nomor_dokpil": _no_prev,
                                            }).eq("kode_paket", _kp_key).execute()
                                            st.success(f"✅ Upload berhasil — {_no_prev}")
                                        else:
                                            st.error(f"❌ HTTP {_r_up_only.get('status','?')} — {_r_up_only.get('error') or _r_up_only.get('body','')[:300]}")
                                            st.json(_r_up_only)
                                    except Exception as _e_up_only:
                                        st.error(f"❌ Exception: {_e_up_only}")

                    if _chk:
                        _plsp_selected.append({
                            **_rr,
                            "_dokpil_file": _dokpil_up,
                        })

                st.caption(f"**{len(_plsp_selected)}** dari **{len(_plsp_rows)}** paket dipilih")

                # Kumpulkan semua paket yang sudah ada file dokpil
                _all_with_file = [
                    {**_rr, "_dokpil_file": st.session_state.get(f"plsp_dokpil_{_rr['kode_paket']}")}
                    for _rr in _plsp_rows
                    if st.session_state.get(f"plsp_dokpil_{_rr['kode_paket']}")
                ]
                if _all_with_file:
                    st.divider()
                    if st.button(f"📤 Upload Semua Dokpil ({len(_all_with_file)} file)", key="plsp_upload_all_dokpil", use_container_width=True, type="primary"):
                        from config import sb as _sb_upall
                        _cl_upall = _sb_upall()
                        for _rr_up in _all_with_file:
                            _kp_up = _rr_up["kode_paket"]
                            _f_up = _rr_up["_dokpil_file"]
                            _ku_up = _rr_up.get("kode_unik") or "?"
                            _sk_up = _lookup_singkatan_dinas(_rr_up.get("satker", ""))
                            # Tanggal dari DB, fallback session
                            _tgl_db_up = _rr_up.get("tgl_dokpil")
                            if _tgl_db_up:
                                try:
                                    from datetime import date as _date2
                                    _tgl_up = _date2.fromisoformat(str(_tgl_db_up))
                                except Exception:
                                    _tgl_up = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            else:
                                _tgl_up = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            # Nomor dari DB, fallback generate
                            _no_up = _rr_up.get("nomor_dokpil") or _udpl.generate_nomor_dokpil(
                                nama_paket=_rr_up["nama_paket"],
                                kode_unik=_ku_up,
                                skpd_singkat=_sk_up,
                                tahun=_tgl_up.year,
                            )
                            try:
                                _r_upall = _udpl.upload_dokpil_pl(
                                    kode_paket=_kp_up,
                                    file_bytes=_f_up.getvalue(),
                                    file_name=_f_up.name,
                                    nomor_dokpil=_no_up,
                                    tgl_dokpil=_tgl_up.strftime("%d-%m-%Y"),
                                )
                                if _r_upall["ok"]:
                                    _cl_upall.table("draft_paket_pl").update({"nomor_dokpil": _no_up}).eq("kode_paket", _kp_up).execute()
                                    st.success(f"✅ {_rr_up['nama_paket'][:40]} — {_no_up}")
                                else:
                                    st.error(f"❌ {_rr_up['nama_paket'][:40]} HTTP {_r_upall.get('status','?')} — {_r_upall.get('body','')[:100]}")
                            except Exception as _e_upall:
                                st.error(f"❌ {_rr_up['nama_paket'][:40]}: {_e_upall}")

            with _plsp_col_kanan:
                st.markdown("### 2. Konfigurasi Setup Paket")

                if not _plsp_selected:
                    st.info("Pilih paket di sebelah kiri.")
                else:
                    # ── SEKSI 1: SBU Global ───────────────────────────────────
                    st.markdown("#### 🏗️ Seksi 1 — SBU Global")
                    st.caption("Satu pilihan SBU apply ke semua paket terpilih.")

                    _plsp_klas_list = ["(auto-detect dari paket pertama)"] + _sp.list_klasifikasi()

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

                    _g_lama_options = _sp.list_sbu_lama_padanan(_g_picked_baru_kode) if _g_picked_baru_kode else []
                    _g_lama_labels = ["(tidak dipersyaratkan / hanya SBU 2020)"] + [
                        f"{l['kode']} — {(l.get('nama_singkat') or l.get('nama_full',''))[:70]}"
                        for l in _g_lama_options
                    ]
                    _g_lama_default = 0
                    for _gli, _gl in enumerate(_g_lama_options):
                        if _gl.get("kode") == _g_kode_lama:
                            _g_lama_default = _gli + 1
                            break
                    _g_picked_lama_label = st.selectbox(
                        "SBU Lama (KBLI 2017) — opsional",
                        _g_lama_labels,
                        index=_g_lama_default,
                        key="plsp_global_sbu_lama",
                    )
                    _g_picked_lama_kode = (
                        _g_picked_lama_label.split(" — ", 1)[0]
                        if " — " in _g_picked_lama_label else ""
                    )

                    _sbu_baru_global = ""
                    _sbu_lama_global = ""
                    if _g_picked_baru_kode:
                        _baru_obj_g = _sp.get_sbu_baru_by_kode(_g_picked_baru_kode)
                        _sbu_baru_global = (_baru_obj_g or {}).get("nama_full", "")
                    if _g_picked_lama_kode:
                        _lama_obj_g = _sp.get_sbu_lama_by_kode(_g_picked_lama_kode)
                        _sbu_lama_global = (_lama_obj_g or {}).get("nama_full", "")
                    if not _sbu_baru_global:
                        _sbu_baru_global = _first_p.get("sbu_baru") or ""

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

                    # ── SEKSI 2: Tanggal Dokpil & Masa Berlaku ────────────────
                    st.markdown("#### 📅 Seksi 2 — Tanggal Dokpil & Masa Berlaku Penawaran")

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

                    _ldk_masa_berlaku = st.number_input(
                        "Masa Berlaku Penawaran (hari)",
                        min_value=1, max_value=180, value=30,
                        key="plsp_masa_berlaku",
                    )

                    if st.button("💾 Submit Masa Berlaku", key="plsp_btn_masa_berlaku", use_container_width=True):
                        from config import sb as _sb_factory_mb
                        _client_mb = _sb_factory_mb()
                        for _p in _plsp_selected:
                            # Simpan tgl_dokpil ke Supabase agar Isi Data PL bisa baca
                            try:
                                _client_mb.table("draft_paket_pl").update({
                                    "tgl_dokpil": _plsp_tgl_dokpil.isoformat(),
                                }).eq("kode_paket", _p["kode_paket"]).execute()
                            except Exception as _e_mb:
                                st.warning(f"⚠️ Gagal simpan tgl_dokpil {_p['nama_paket'][:30]}: {_e_mb}")
                            _r_mb = _depl.submit_masa_berlaku_pl(_p["kode_paket"], int(_ldk_masa_berlaku))
                            st.write(f"{'✅' if _r_mb['ok'] else '❌'} {_p['nama_paket'][:40]} — HTTP {_r_mb['status']}")

                    st.divider()

                    # ── SEKSI 3: Dokumen Kualifikasi (LDK) ───────────────────
                    st.markdown("#### 📋 Seksi 3 — Dokumen Kualifikasi (LDK)")
                    st.caption("ℹ️ Di-submit ke SPSE bagian Persyaratan Kualifikasi (LDK).")

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

                    if st.button("📋 Submit Dokumen Kualifikasi (LDK)", key="plsp_btn_ldk", use_container_width=True):
                        from config import sb as _sb_factory_ldk
                        _client_ldk = _sb_factory_ldk()
                        for _p in _plsp_selected:
                            try:
                                _client_ldk.table("draft_paket_pl").update({
                                    "sbu_baru": _sbu_baru_global,
                                    "sbu_lama": _sbu_lama_global,
                                }).eq("kode_paket", _p["kode_paket"]).execute()
                            except Exception:
                                pass
                            _r_ldk = _depl.submit_ldk_pl(
                                _p["kode_paket"],
                                sbu_baru=_sbu_baru_global,
                                sbu_lama=_sbu_lama_global,
                                centang_admin_indices=_ldk_centang_admin_indices,
                                teknis_centang_indices=_ldk_teknis_indices,
                                kinerja_text=_ldk_kinerja_text,
                            )
                            st.write(f"{'✅' if _r_ldk['ok'] else '❌'} {_p['nama_paket'][:40]} — HTTP {_r_ldk['status']}")

                    st.divider()

                    # ── SEKSI 4: Dokumen Penawaran (Checklist) ────────────────
                    st.markdown("#### 📝 Seksi 4 — Dokumen Penawaran (Checklist)")
                    st.caption("ℹ️ Centang sesuai dokumen penawaran yang diminta ke peserta. Di-submit ke SPSE bagian Checklist Dokumen Penawaran.")

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

                    if st.button("📝 Submit Dokumen Penawaran (Checklist)", key="plsp_btn_checklist", use_container_width=True):
                        for _p in _plsp_selected:
                            _r_cd = _depl.submit_checklist_pl(
                                _p["kode_paket"],
                                centang_admin_all=_cd_centang_admin,
                                centang_syarat_all=_cd_centang_syarat,
                                centang_harga_all=_cd_centang_harga,
                            )
                            st.write(f"{'✅' if _r_cd['ok'] else '❌'} {_p['nama_paket'][:40]} — HTTP {_r_cd['status']}")

                    st.divider()
                    st.caption("⬇️ Atau jalankan semua seksi sekaligus:")

                    # ── Submit All-in-One ─────────────────────────────────────
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

    # ── Tab 7: Kirim Verifikasi Penyedia ─────────────────────────────────────
    with _pl_tab7:
        import verifikasi_penyedia_pl as _verif_pl
        from gcal_helper import get_jadwal_klarifikasi_pl as _gcal_klarifikasi

        st.markdown("## 📨 Kirim Undangan Verifikasi Penyedia")
        st.caption("Kirim undangan pembuktian kualifikasi ke penyedia via SPSE non-tender.")

        # Dropdown paket — gabung draft_pl + aktif_pl (dedup by id_nontender)
        _verif_rows = []
        try:
            _verif_rows = pl_engine._sb().table("draft_paket_pl").select(
                "kode_paket, id_nontender, nama_paket, kode_unik, nama_penyedia, npwp_penyedia, tgl_negosiasi, tgl_undangan_verifikasi, status_undangan_verifikasi"
            ).order("kode_paket").execute().data or []
        except Exception as _ev_err:
            st.error(f"Gagal load paket PL: {_ev_err}")

        # ── Monitoring Pendaftaran Peserta (semua paket) ──────────────────────
        with st.expander("📊 Monitoring Pendaftaran Peserta — Semua Paket", expanded=False):
            import peserta_monitor_pl as _pm_pl
            _mon_col1, _mon_col2 = st.columns([6, 1])
            _mon_col1.caption("Jumlah peserta yang sudah mendaftar per paket (data publik SPSE).")
            if _mon_col2.button("🔄 Refresh", key="btn_refresh_peserta_pl"):
                st.cache_data.clear()
            if _verif_rows:
                _mon_kodes = [r["kode_paket"] for r in _verif_rows if r.get("kode_paket")]
                with st.spinner("Mengambil data pendaftaran..."):
                    _mon_hasil = _pm_pl.fetch_status_semua_paket(_mon_kodes)
                # Hitung summary
                _mon_belum = [r for r in _verif_rows if _mon_hasil.get(r["kode_paket"], {}).get("jumlah", 0) == 0]
                _mon_sudah = [r for r in _verif_rows if _mon_hasil.get(r["kode_paket"], {}).get("jumlah", 0) > 0]
                _mc1, _mc2 = st.columns(2)
                _mc1.metric("✅ Sudah Ada Peserta", len(_mon_sudah))
                _mc2.metric("⚠️ Belum Ada Peserta", len(_mon_belum))
                if _mon_belum:
                    st.warning("⚠️ Paket berikut belum ada peserta mendaftar — pertimbangkan perpanjangan jadwal:")
                    for _br in _mon_belum:
                        st.write(f"- **{_br.get('kode_unik') or _br['kode_paket']}** — {_br['nama_paket']}")
                # Tabel lengkap
                _mon_data = []
                for r in _verif_rows:
                    _kp = r["kode_paket"]
                    _info = _mon_hasil.get(_kp, {})
                    _jml = _info.get("jumlah", 0)
                    _mon_data.append({
                        "Paket": r.get("kode_unik") or _kp,
                        "Nama Paket": r["nama_paket"][:45],
                        "Peserta Daftar": _jml,
                        "Status": "✅ Ada" if _jml > 0 else "⚠️ Belum",
                    })
                st.dataframe(_mon_data, use_container_width=True, hide_index=True)
            else:
                st.info("Belum ada paket PL di database.")

        if not _verif_rows:
            st.info("Belum ada paket PL di database.")
        else:
            _verif_opts = {
                f"{r['kode_unik'] or r['kode_paket']} — {r['nama_paket'][:50]}": r
                for r in _verif_rows if r.get("id_nontender")
            }
            _verif_sel_label = st.selectbox(
                "Pilih Paket PL",
                options=list(_verif_opts.keys()),
                key="verif_paket_sel",
            )
            _verif_paket = _verif_opts.get(_verif_sel_label)

            if _verif_paket:
                _verif_id_nt = _verif_paket.get("id_nontender", "")
                _verif_kode = _verif_paket.get("kode_paket", "")

                # Info penyedia
                st.markdown("#### 🏢 Info Penyedia")
                _vc1, _vc2 = st.columns(2)
                _vc1.markdown(f"**Nama:** {_verif_paket.get('nama_penyedia') or '—'}")
                _vc2.markdown(f"**NPWP:** {_verif_paket.get('npwp_penyedia') or '—'}")

                # Debug GCal — expander tersembunyi
                with st.expander("🔍 Debug GCal Search", expanded=False):
                    try:
                        from gcal_helper import _build_service as _gcal_svc
                        from datetime import datetime as _dt_gcal, timedelta as _td_gcal, date as _d_gcal
                        _svc = _gcal_svc()
                        _now = _d_gcal.today()
                        _tmin = (_now - _td_gcal(days=60)).isoformat() + "T00:00:00Z"
                        _tmax = (_now + _td_gcal(days=120)).isoformat() + "T23:59:59Z"
                        _gevents = _svc.events().list(
                            calendarId="primary",
                            timeMin=_tmin, timeMax=_tmax,
                            maxResults=100, singleEvents=True,
                            q="Klarifikasi",
                        ).execute().get("items", [])
                        st.write(f"**Mencari kode_nontender:** `{_verif_kode}`")
                        st.write(f"**Event GCal mengandung 'Klarifikasi' ({len(_gevents)} event):**")
                        for _ge in _gevents:
                            _gs = _ge.get("start", {}).get("date") or _ge.get("start", {}).get("dateTime", "")[:10]
                            _gdesc = (_ge.get("description") or "").replace("\n", " ")[:100]
                            _match = "✅ MATCH" if _verif_kode in (_ge.get("description") or "") else ""
                            st.write(f"- `{_gs}` **{_ge.get('summary','')}** | desc: {_gdesc} {_match}")
                        if not _gevents:
                            st.warning("Tidak ada event GCal mengandung 'Klarifikasi' di rentang ±60-120 hari")
                    except Exception as _dbg_err:
                        st.error(f"Debug GCal error: {_dbg_err}")

                # Hitung waktu verifikasi dari GCal
                st.markdown("#### 🕐 Waktu Verifikasi")
                _tgl_nego_raw = _verif_paket.get("tgl_negosiasi")
                _fallback_tgl = None
                if _tgl_nego_raw:
                    try:
                        from datetime import date as _date_cls
                        _fallback_tgl = _date_cls.fromisoformat(str(_tgl_nego_raw)[:10])
                    except Exception:
                        pass

                _verif_start_default = ""
                _verif_end_default = ""
                _verif_warning = None
                try:
                    _verif_start_default, _verif_end_default, _verif_warning = (
                        _verif_pl.hitung_waktu_verifikasi(_verif_kode, fallback_tgl=_fallback_tgl)
                    )
                except Exception as _wt_err:
                    _verif_warning = f"Error hitung waktu: {_wt_err}"

                if _verif_warning:
                    st.warning(_verif_warning)
                    if "invalid_grant" in str(_verif_warning) or "expired" in str(_verif_warning).lower() or "tidak ditemukan" in str(_verif_warning):
                        if st.button("🔑 Login Google Calendar", key="btn_reset_gcal_token"):
                            try:
                                import gcal_helper as _gcalh
                                _gcalh.generate_token()
                                st.success("✅ Token GCal berhasil dibuat. Refresh halaman.")
                                st.rerun()
                            except Exception as _ge:
                                st.error(f"Gagal generate token: {_ge}")

                _vt1, _vt2 = st.columns(2)
                _verif_start = _vt1.text_input(
                    "Mulai (DD-MM-YYYY HH:MM)",
                    value=_verif_start_default or "",
                    key="verif_waktu_start",
                    placeholder="02-06-2026 09:00",
                )
                _verif_end = _vt2.text_input(
                    "Selesai (DD-MM-YYYY HH:MM)",
                    value=_verif_end_default or "",
                    key="verif_waktu_end",
                    placeholder="02-06-2026 15:00",
                )

                # Form fields
                st.markdown("#### 📋 Detail Undangan")
                _verif_tempat = st.text_area(
                    "Tempat",
                    value=_verif_pl.TEMPAT_DEFAULT,
                    height=80,
                    key="verif_tempat",
                )
                # Tombol kirim
                if st.button("📨 Kirim Verifikasi ke Penyedia", key="btn_kirim_verifikasi"):
                    if not _verif_id_nt:
                        st.error("id_nontender kosong — sinkron paket PL dari SPSE dulu.")
                    elif not _verif_start or not _verif_end:
                        st.error("Waktu mulai dan selesai wajib diisi.")
                    else:
                        with st.spinner("Mengirim undangan verifikasi ke SPSE..."):
                            _verif_result = _verif_pl.kirim_verifikasi(
                                id_nontender=_verif_id_nt,
                                waktu_start=_verif_start,
                                waktu_end=_verif_end,
                                tempat=_verif_tempat,
                                yang_harus_hadir=_verif_pl.YANG_HARUS_HADIR_DEFAULT,
                                yang_harus_dibawa=_verif_pl.YANG_HARUS_DIBAWA_DEFAULT,
                            )
                        if _verif_result["ok"]:
                            st.success(f"✅ {_verif_result['msg']}")
                        else:
                            st.error(f"❌ Gagal: {_verif_result['msg']}")

        # ── Kirim Batch ke Semua Paket ───────────────────────────────────────
        st.divider()
        st.markdown("### 📨 Kirim Undangan Verifikasi — Batch (Semua Paket)")
        st.caption("Centang paket yang ingin dikirim sekaligus. Hanya paket dengan peserta terdaftar yang tampil.")

        # Load status peserta untuk filter
        _batch_rows = _verif_rows  # sudah di-load di atas
        if _batch_rows:
            # Fetch jumlah peserta semua paket
            import peserta_monitor_pl as _pm_batch
            _batch_kodes = [r["kode_paket"] for r in _batch_rows if r.get("kode_paket")]
            with st.spinner("Mengecek peserta terdaftar..."):
                _batch_mon = _pm_batch.fetch_status_semua_paket(_batch_kodes)

            # Filter hanya paket yang ada peserta
            _batch_eligible = [
                r for r in _batch_rows
                if _batch_mon.get(r["kode_paket"], {}).get("jumlah", 0) > 0
                and r.get("id_nontender")
            ]

            if not _batch_eligible:
                st.info("Belum ada paket dengan peserta terdaftar.")
            else:
                st.caption(f"{len(_batch_eligible)} paket tersedia (sudah ada peserta).")

                # Waktu — dropdown dari GCal + fallback input manual
                import datetime as _dt_bv
                _today_bv = _dt_bv.date.today()

                _bwc1, _bwc2 = st.columns(2)
                with _bwc1:
                    st.caption("**Waktu Mulai**")
                    _bv_start_d = st.date_input("Tanggal Mulai", value=_today_bv, format="DD-MM-YYYY", key="batch_verif_start_d")
                    _bv_start_t = st.time_input("Jam Mulai", value=_dt_bv.time(9, 0), step=300, key="batch_verif_start_t")
                with _bwc2:
                    st.caption("**Waktu Selesai**")
                    _bv_end_d = st.date_input("Tanggal Selesai", value=_today_bv, format="DD-MM-YYYY", key="batch_verif_end_d")
                    _bv_end_t = st.time_input("Jam Selesai", value=_dt_bv.time(15, 0), step=300, key="batch_verif_end_t")

                _batch_start = f"{_bv_start_d.strftime('%d-%m-%Y')} {_bv_start_t.strftime('%H:%M')}"
                _batch_end   = f"{_bv_end_d.strftime('%d-%m-%Y')} {_bv_end_t.strftime('%H:%M')}"

                # Checkbox list paket
                st.markdown("**Pilih paket yang akan dikirim:**")
                _sudah_kirim = [r for r in _batch_eligible if r.get("status_undangan_verifikasi") == "terkirim"]
                _belum_kirim = [r for r in _batch_eligible if r.get("status_undangan_verifikasi") != "terkirim"]
                if _sudah_kirim:
                    st.caption(f"✅ {len(_sudah_kirim)} sudah terkirim | ⏳ {len(_belum_kirim)} belum")
                _batch_selected = []
                _bc1, _bc2 = st.columns(2)
                for _bi, _br in enumerate(_batch_eligible):
                    _ku = _br.get('kode_unik') or _br['kode_paket']
                    _tgl_kirim = _br.get("tgl_undangan_verifikasi")
                    _sudah = _br.get("status_undangan_verifikasi") == "terkirim"
                    if _sudah and _tgl_kirim:
                        import datetime as _dtlb
                        try:
                            _tgl_fmt = _dtlb.datetime.fromisoformat(_tgl_kirim.replace("Z","+00:00")).strftime("%d-%m-%Y")
                        except Exception:
                            _tgl_fmt = _tgl_kirim[:10]
                        _label = f"{_ku} — {_br['nama_paket'][:35]} ✅ {_tgl_fmt}"
                    else:
                        _label = f"{_ku} — {_br['nama_paket'][:40]}"
                    _col = _bc1 if _bi % 2 == 0 else _bc2
                    _default_chk = not _sudah  # belum terkirim → default centang; sudah → default uncheck
                    if _col.checkbox(_label, value=_default_chk, key=f"batch_chk_{_br['kode_paket']}"):
                        _batch_selected.append(_br)

                st.markdown(f"**{len(_batch_selected)} paket dipilih**")

                # Tombol Preview dulu
                if st.button("👁 Preview Sebelum Kirim", key="btn_batch_preview"):
                    if not _batch_start or not _batch_end:
                        st.error("Waktu mulai dan selesai wajib diisi.")
                    elif not _batch_selected:
                        st.warning("Tidak ada paket yang dipilih.")
                    else:
                        st.session_state["batch_verif_preview"] = True

                if st.session_state.get("batch_verif_preview"):
                    st.markdown("#### 📋 Preview Pengiriman")
                    st.write(f"- **Waktu:** {_batch_start} s/d {_batch_end}")
                    st.write(f"- **Jumlah paket:** {len(_batch_selected)}")
                    for _bp in _batch_selected:
                        _jp = _batch_mon.get(_bp["kode_paket"], {}).get("jumlah", 0)
                        st.write(f"  ✅ {_bp.get('kode_unik') or _bp['kode_paket']} — {_bp['nama_paket']} ({_jp} peserta)")
                    st.write(f"- **Penyedia (referensi Supabase):** nama_penyedia per paket")

                    if st.button("📨 Konfirmasi & Kirim Semua", key="btn_batch_kirim_konfirm", type="primary"):
                        if not _batch_start or not _batch_end:
                            st.error("Waktu wajib diisi.")
                        else:
                            import verifikasi_penyedia_pl as _vpl_batch
                            _hasil_batch = []
                            _prog = st.progress(0, text="Mengirim...")
                            for _bi2, _bp2 in enumerate(_batch_selected):
                                _prog.progress((_bi2 + 1) / len(_batch_selected), text=f"Kirim ke {_bp2.get('kode_unik') or _bp2['kode_paket']}...")
                                _res = _vpl_batch.kirim_verifikasi(
                                    id_nontender=_bp2["id_nontender"],
                                    waktu_start=_batch_start,
                                    waktu_end=_batch_end,
                                )
                                _hasil_batch.append({
                                    "paket": _bp2.get("kode_unik") or _bp2["kode_paket"],
                                    "nama": _bp2["nama_paket"][:40],
                                    "ok": _res["ok"],
                                    "msg": _res["msg"],
                                })
                            _prog.empty()
                            st.session_state["batch_verif_preview"] = False

                            # Tampilkan hasil
                            _ok_list = [h for h in _hasil_batch if h["ok"]]
                            _fail_list = [h for h in _hasil_batch if not h["ok"]]
                            if _ok_list:
                                st.success(f"✅ Berhasil: {len(_ok_list)} paket")
                                for h in _ok_list:
                                    st.write(f"  ✅ {h['paket']} — {h['nama']}")
                            if _fail_list:
                                st.error(f"❌ Gagal: {len(_fail_list)} paket")
                                for h in _fail_list:
                                    st.write(f"  ❌ {h['paket']} — {h['nama']}: {h['msg']}")

    # ── Tab 8: Upload BA PL ───────────────────────────────────────────────────
    with _pl_tab8:
        import ba_engine_pl as _ba_pl_engine5
        import ba_config_pl as _ba_cfg_pl
        import os as _os8
        import re as _re8
        import datetime as _dt8

        st.markdown("## Berita Acara — Pengadaan Langsung")

        # Load paket PL sekali
        _pl8_rows = []
        try:
            _pl8_rows = pl_engine._sb().table("draft_paket_pl").select(
                "kode_paket, nama_paket, nomor_urut, kode_unik, id_nontender, "
                "nomor_dokpil, tgl_evaluasi, satker, folder_dibuat"
            ).order("nomor_urut").execute().data or []
        except Exception as _e8:
            st.error(f"Gagal load paket PL: {_e8}")

        # ── Helper auto nomor + tanggal (otomatis seperti mode tender) ───────
        def _skpd_pl8(_satker):
            if not _satker:
                return "DPUPR"
            try:
                from config import sb as _sbf8
                _r = _sbf8().table("master_dinas").select("singkatan").ilike(
                    "nama_dinas", f"%{_satker[:30]}%").limit(1).execute()
                if _r.data:
                    return _r.data[0].get("singkatan") or "DPUPR"
            except Exception:
                pass
            return "DPUPR"

        def _nomor_dokpil_pl8(_row):
            """Nomor dokpil dasar (slot /01/) — dari DB jika ada, else generate."""
            _nd = (_row.get("nomor_dokpil") or "").strip()
            if _nd:
                return _nd
            try:
                import upload_dokpil_pl as _udpl8
                return _udpl8.generate_nomor_dokpil(
                    nama_paket=_row.get("nama_paket", ""),
                    kode_unik=_row.get("kode_unik") or "",
                    skpd_singkat=_skpd_pl8(_row.get("satker", "")),
                )
            except Exception:
                return ""

        def _auto_nomor_pl8(_row, _jenis_key):
            """Derive nomor BA per jenis: ganti slot /NN/ pertama."""
            _base = _nomor_dokpil_pl8(_row)
            if not _base:
                return ""
            return ba_engine.derive_nomor_ba(_base, _ba_cfg_pl.NOMOR_URUT_PL[_jenis_key])

        def _auto_tgl_pl8(_row):
            """Tanggal BA = end Evaluasi Penawaran (tgl_evaluasi), fallback live SPSE."""
            _v = _row.get("tgl_evaluasi")
            if _v:
                try:
                    return _dt8.date.fromisoformat(str(_v)[:10])
                except Exception:
                    pass
            try:
                import gcal_pl_helper as _gph8
                _jd = _gph8.parse_jadwal_pl_dari_spse(_row.get("kode_paket", ""))
                if _jd and len(_jd) > 2:
                    return _jd[2]["selesai"].date()
            except Exception:
                pass
            return None

        def _backup_pdf_pl8(_row, _jenis_key, _pdf_bytes):
            """Simpan PDF cetak ke folder masing-masing paket. Return path atau ''."""
            _kp = _row.get("kode_paket", "")
            _dir = None
            # 1) resolver folder paket PL resmi (folder_paket root)
            try:
                import kualifikasi_engine_pl as _kepl8
                _rf = _kepl8.resolve_folder_paket_pl(_kp)
                if _rf.get("ok"):
                    _root = _rf.get("pesan") or ""  # pesan = folder_paket root
                    if _root and _os8.path.isdir(_root):
                        _dir = _root
            except Exception:
                pass
            # 2) fallback: Asisten_Pokja_Downloads
            if not _dir:
                try:
                    from config import POKJA_ROOT as _PR8
                    _dir = _os8.path.join(_PR8, "Asisten_Pokja_Downloads", f"Cetak_BA_PL_{_kp}")
                except Exception:
                    return ""
            try:
                _os8.makedirs(_dir, exist_ok=True)
                _fn = f"{_ba_cfg_pl.FILE_LABEL_PL[_jenis_key]}-{_kp}.pdf"
                _fp = _os8.path.join(_dir, _fn)
                with open(_fp, "wb") as _fh:
                    _fh.write(_pdf_bytes)
                return _fp
            except Exception:
                return ""

        def _proses_ba_pl8(_row, _jenis_key, _nomor, _tgl):
            """Cetak → backup → upload satu BA. Return (ok: bool, pesan: str)."""
            # Endpoint cetak/upload BA nontender pakai kode_paket (BUKAN id_nontender)
            _id = _row.get("kode_paket")
            if not _nomor:
                return False, "nomor kosong"
            if not _tgl:
                return False, "tanggal kosong (Evaluasi belum dijadwal)"
            _tgls = _tgl.strftime("%d-%m-%Y")
            try:
                _rc = _ba_pl_engine5.cetak_ba_pl(
                    id_nontender=_id, jenis_key=_jenis_key,
                    nomor_ba=_nomor, tanggal_ba=_tgls,
                )
                if not _rc["ok"]:
                    return False, f"cetak gagal ({_rc.get('status')}) {_rc.get('error','')}"
                _backup_pdf_pl8(_row, _jenis_key, _rc["pdf_bytes"])
                _fn = f"{_ba_cfg_pl.FILE_LABEL_PL[_jenis_key]}-{_row.get('kode_paket','')}.pdf"
                _ru = _ba_pl_engine5.upload_ba_pl(
                    id_nontender=_id, jenis_key=_jenis_key,
                    nomor_ba=_nomor, tanggal_ba=_tgls,
                    file_bytes=_rc["pdf_bytes"], file_name=_fn,
                )
                if _ru.get("ok"):
                    return True, "OK"
                return False, f"upload gagal ({_ru.get('status')})"
            except Exception as _e:
                return False, str(_e)[:100]

        # ── SECTION 1: 2 BA AUTO (Evaluasi + Hasil) ──────────────────────────
        st.markdown("### 1. Cetak + Upload Otomatis")
        st.caption("BA Evaluasi Penawaran dan BA Hasil Non Tender dicetak langsung dari SPSE lalu di-upload kembali.")

        if not _pl8_rows:
            st.info("Tidak ada paket PL di database.")
        else:
            # Tanggal: default OTOMATIS dari tgl_evaluasi per paket (mode tender).
            _pl8_tgl_mode = st.radio(
                "Mode Tanggal",
                ["Otomatis (tgl Evaluasi per paket)", "Satu tanggal semua manual"],
                horizontal=True, key="pl8_tgl_mode",
            )
            _pl8_tgl_global = None
            if _pl8_tgl_mode == "Satu tanggal semua manual":
                _pl8_tgl_global = st.date_input(
                    "Tanggal BA (semua paket)", value=datetime.now().date(),
                    format="DD/MM/YYYY", key="pl8_tgl_global",
                )
                st.caption(f"{_HARI_NAMA[_pl8_tgl_global.weekday()]}, {_pl8_tgl_global.day} "
                           f"{_BULAN_NAMA[_pl8_tgl_global.month-1]} {_pl8_tgl_global.year}")
            else:
                st.caption("Tanggal otomatis = hari terakhir Evaluasi Penawaran (dari jadwal). "
                           "Nomor BA auto-derive dari Nomor Dokpil.")

            # ── Tombol BULK: cetak+upload SEMUA paket × 2 BA tanpa centang ──
            if st.button(
                f"🚀🚀 Cetak + Upload SEMUA Paket ({len(_pl8_rows)} paket × 2 BA)",
                type="primary", key="pl8_bulk_all_paket", use_container_width=True,
            ):
                with st.status(f"Proses {len(_pl8_rows)} paket × 2 BA...", expanded=True) as _stb8:
                    _ok_total, _gagal_total = 0, 0
                    for _pbulk in _pl8_rows:
                        _kb = _pbulk.get("kode_paket", "")
                        _tgl_b = _pl8_tgl_global if _pl8_tgl_mode == "Satu tanggal semua manual" else _auto_tgl_pl8(_pbulk)
                        _stb8.write(f"**{_pbulk.get('nomor_urut') or ''}. {_kb}**")
                        for _jkb, _lblb in [("evaluasi", "Evaluasi"), ("hasil", "Hasil")]:
                            _nob = _auto_nomor_pl8(_pbulk, _jkb)
                            _okb, _pesb = _proses_ba_pl8(_pbulk, _jkb, _nob, _tgl_b)
                            if _okb:
                                _stb8.write(f"  ✅ BA {_lblb}")
                                _ok_total += 1
                            else:
                                _stb8.write(f"  ❌ BA {_lblb} — {_pesb}")
                                _gagal_total += 1
                    _stb8.update(
                        label=f"Selesai — {_ok_total} BA OK, {_gagal_total} gagal.",
                        state="complete" if _gagal_total == 0 else "error",
                    )

            st.divider()

            # Header tabel per paket
            _pl8_valid_auto = []  # untuk batch
            for _p8 in _pl8_rows:
                _k8    = _p8.get("kode_paket", "")
                _id8   = _k8  # BA nontender pakai kode_paket
                _label8 = f"**{_p8.get('nomor_urut') or ''}. {_p8.get('nama_paket','')[:60]}**"
                with st.container(border=True):
                    st.markdown(_label8)
                    st.caption(f"kode paket: `{_k8}`")

                    # Tanggal per paket: OTOMATIS dari tgl_evaluasi (atau manual global)
                    if _pl8_tgl_mode == "Satu tanggal semua manual":
                        _tgl8 = _pl8_tgl_global
                    else:
                        _tgl8 = _auto_tgl_pl8(_p8)

                    if _tgl8:
                        st.caption(f"📅 {_HARI_NAMA[_tgl8.weekday()]}, {_tgl8.day} "
                                   f"{_BULAN_NAMA[_tgl8.month-1]} {_tgl8.year}")
                    else:
                        st.caption("⚠️ Tanggal Evaluasi belum ada — isi jadwal dulu atau pakai mode manual.")

                    # Nomor per jenis BA: default OTOMATIS dari Nomor Dokpil (bisa diedit)
                    _auto_ev = _auto_nomor_pl8(_p8, "evaluasi")
                    _auto_hs = _auto_nomor_pl8(_p8, "hasil")
                    _c8ev, _c8hs = st.columns(2)
                    with _c8ev:
                        st.markdown(f"**{_ba_cfg_pl.JENIS_LABEL_PL['evaluasi']}**")
                        _no8ev = st.text_input(
                            "Nomor", value=_auto_ev, placeholder="000.3.3/05/PL/...",
                            key=f"pl8_no_evaluasi_{_k8}", label_visibility="collapsed",
                        )
                    with _c8hs:
                        st.markdown(f"**{_ba_cfg_pl.JENIS_LABEL_PL['hasil']}**")
                        _no8hs = st.text_input(
                            "Nomor", value=_auto_hs, placeholder="000.3.3/07/PL/...",
                            key=f"pl8_no_hasil_{_k8}", label_visibility="collapsed",
                        )

                    # Tombol per paket
                    _btn8c1, _btn8c2, _btn8c3 = st.columns([2, 2, 1])
                    with _btn8c1:
                        if st.button(
                            "🖨️ Cetak+Upload Evaluasi",
                            key=f"pl8_ev_{_k8}",
                            disabled=not _no8ev,
                            use_container_width=True,
                        ):
                            with st.spinner(f"Proses BA Evaluasi {_k8}..."):
                                _tgl8s = _tgl8.strftime("%d-%m-%Y") if _tgl8 else ""
                                _rc8 = _ba_pl_engine5.cetak_ba_pl(
                                    id_nontender=_id8, jenis_key="evaluasi",
                                    nomor_ba=_no8ev, tanggal_ba=_tgl8s,
                                )
                                if _rc8["ok"]:
                                    _backup_pdf_pl8(_p8, "evaluasi", _rc8["pdf_bytes"])
                                    _fn8 = f"{_ba_cfg_pl.FILE_LABEL_PL['evaluasi']}-{_k8}.pdf"
                                    _ru8 = _ba_pl_engine5.upload_ba_pl(
                                        id_nontender=_id8, jenis_key="evaluasi",
                                        nomor_ba=_no8ev, tanggal_ba=_tgl8s,
                                        file_bytes=_rc8["pdf_bytes"], file_name=_fn8,
                                    )
                                    if _ru8.get("ok"):
                                        st.success(f"✅ BA Evaluasi {_k8} berhasil")
                                    else:
                                        st.error(f"❌ Upload gagal: status {_ru8.get('status')}")
                                else:
                                    st.error(f"❌ Cetak gagal: {_rc8.get('error')} (status {_rc8.get('status')})")
                    with _btn8c2:
                        if st.button(
                            "🖨️ Cetak+Upload Hasil",
                            key=f"pl8_hs_{_k8}",
                            disabled=not _no8hs,
                            use_container_width=True,
                        ):
                            with st.spinner(f"Proses BA Hasil {_k8}..."):
                                _tgl8s = _tgl8.strftime("%d-%m-%Y") if _tgl8 else ""
                                _rc8h = _ba_pl_engine5.cetak_ba_pl(
                                    id_nontender=_id8, jenis_key="hasil",
                                    nomor_ba=_no8hs, tanggal_ba=_tgl8s,
                                )
                                if _rc8h["ok"]:
                                    _backup_pdf_pl8(_p8, "hasil", _rc8h["pdf_bytes"])
                                    _fn8h = f"{_ba_cfg_pl.FILE_LABEL_PL['hasil']}-{_k8}.pdf"
                                    _ru8h = _ba_pl_engine5.upload_ba_pl(
                                        id_nontender=_id8, jenis_key="hasil",
                                        nomor_ba=_no8hs, tanggal_ba=_tgl8s,
                                        file_bytes=_rc8h["pdf_bytes"], file_name=_fn8h,
                                    )
                                    if _ru8h.get("ok"):
                                        st.success(f"✅ BA Hasil {_k8} berhasil")
                                    else:
                                        st.error(f"❌ Upload gagal: status {_ru8h.get('status')}")
                                else:
                                    st.error(f"❌ Cetak gagal: {_rc8h.get('error')} (status {_rc8h.get('status')})")
                    with _btn8c3:
                        _chk8 = st.checkbox("Batch", key=f"pl8ba_chk_{_k8}", value=False)

                    if _chk8 and _no8ev and _no8hs:
                        _pl8_valid_auto.append({
                            **_p8,
                            "_id8": _id8, "_tgl8": _tgl8,
                            "_no8ev": _no8ev, "_no8hs": _no8hs,
                        })

            # Tombol batch semua
            if _pl8_valid_auto:
                if st.button(
                    f"🚀 Cetak+Upload Semua BA ({len(_pl8_valid_auto)} paket × 2 BA)",
                    type="primary", key="pl8_batch_all", use_container_width=True,
                ):
                    with st.status(f"Proses {len(_pl8_valid_auto)} paket...", expanded=True) as _st8:
                        for _pb8 in _pl8_valid_auto:
                            _tgl8s = _pb8["_tgl8"].strftime("%d-%m-%Y") if _pb8["_tgl8"] else ""
                            for _jk8, _no8, _lbl8 in [
                                ("evaluasi", _pb8["_no8ev"], "Evaluasi"),
                                ("hasil",    _pb8["_no8hs"], "Hasil"),
                            ]:
                                _st8.write(f"⏳ {_pb8['kode_paket']} — BA {_lbl8}...")
                                try:
                                    _rc = _ba_pl_engine5.cetak_ba_pl(
                                        id_nontender=_pb8["_id8"], jenis_key=_jk8,
                                        nomor_ba=_no8, tanggal_ba=_tgl8s,
                                    )
                                    if _rc["ok"]:
                                        _backup_pdf_pl8(_pb8, _jk8, _rc["pdf_bytes"])
                                        _fn = f"{_ba_cfg_pl.FILE_LABEL_PL[_jk8]}-{_pb8['kode_paket']}.pdf"
                                        _ru = _ba_pl_engine5.upload_ba_pl(
                                            id_nontender=_pb8["_id8"], jenis_key=_jk8,
                                            nomor_ba=_no8, tanggal_ba=_tgl8s,
                                            file_bytes=_rc["pdf_bytes"], file_name=_fn,
                                        )
                                        if _ru.get("ok"):
                                            _st8.write(f"  ✅ BA {_lbl8} OK")
                                        else:
                                            _st8.write(f"  ❌ Upload BA {_lbl8} — status {_ru.get('status')}")
                                    else:
                                        _st8.write(f"  ❌ Cetak BA {_lbl8} — {_rc.get('error')}")
                                except Exception as _e8b:
                                    _st8.write(f"  ❌ Error: {_e8b}")

        # ── SECTION 2: BA LAINNYA (upload-only) ──────────────────────────────
        st.divider()
        st.markdown("### 2. BA Lainnya (Upload Manual)")
        st.caption("BA Penjelasan, Pengumuman Pemenang, dll — upload file PDF langsung ke SPSE.")

        if _pl8_rows:
            _JENIS_LAINNYA = {
                "penjelasan":   "BA Penjelasan",
                "pengumuman":   "Pengumuman Pemenang Akhir",
            }
            _pl8_lc1, _pl8_lc2 = st.columns([1, 2])
            with _pl8_lc1:
                _jenis_lain8 = st.selectbox(
                    "Jenis BA",
                    options=list(_JENIS_LAINNYA.keys()),
                    format_func=lambda k: _JENIS_LAINNYA[k],
                    key="pl8_jenis_lain",
                )
            with _pl8_lc2:
                _nomor_lain8  = st.text_input(
                    "Nomor BA",
                    placeholder="000.3.3/06/PL/PP-01/KPP1/DPUPR/2026",
                    key="pl8_nomor_lain",
                )
            _tgl_lain8 = st.date_input(
                "Tanggal BA", value=datetime.now().date(), format="DD/MM/YYYY",
                key="pl8_tgl_lain",
            )
            st.caption(f"{_HARI_NAMA[_tgl_lain8.weekday()]}, {_tgl_lain8.day} "
                       f"{_BULAN_NAMA[_tgl_lain8.month-1]} {_tgl_lain8.year}")
            _tempat_lain8 = ""
            if _jenis_lain8 == "pengumuman":
                _tempat_lain8 = st.text_input("Tempat", placeholder="Contoh: Kantor RSUD", key="pl8_tempat_lain")
            _info_lain8 = st.text_area("Keterangan Tambahan", value="", key="pl8_info_lain", height=68)

            st.markdown("**Pilih Paket + Upload File:**")
            _pl8_lain_valid = []
            for _p8l in _pl8_rows:
                _k8l  = _p8l.get("kode_paket", "")
                _id8l = _k8l  # BA nontender pakai kode_paket
                _lc1, _lc2, _lc3 = st.columns([3, 3, 1])
                with _lc1:
                    st.caption(f"{_p8l.get('nomor_urut') or ''}. {_p8l.get('nama_paket','')[:50]}")
                with _lc2:
                    _fl8 = st.file_uploader(
                        "PDF", type=["pdf"], key=f"pl8_lain_file_{_k8l}",
                        label_visibility="collapsed",
                    )
                with _lc3:
                    if _fl8 and st.button("📤", key=f"pl8_lain_up_{_k8l}", use_container_width=True):
                        with st.spinner(f"Upload {_k8l}..."):
                            _rl8 = _ba_pl_engine5.upload_ba_pl(
                                id_nontender=_id8l, jenis_key=_jenis_lain8,
                                nomor_ba=_nomor_lain8,
                                tanggal_ba=_tgl_lain8.strftime("%d-%m-%Y"),
                                info=_info_lain8,
                                file_bytes=_fl8.read(), file_name=_fl8.name,
                                tempat=_tempat_lain8,
                            )
                        if _rl8.get("ok"):
                            st.success(f"✅ {_k8l} — berhasil")
                        else:
                            st.error(f"❌ {_k8l} — status {_rl8.get('status')}")
                if _fl8:
                    _pl8_lain_valid.append({**_p8l, "_id8l": _id8l, "_fl8": _fl8})

            if _pl8_lain_valid:
                if st.button(
                    f"📤 Upload Semua ({len(_pl8_lain_valid)} paket)",
                    key="pl8_lain_all", use_container_width=True,
                ):
                    with st.status(f"Upload {len(_pl8_lain_valid)} paket...", expanded=True) as _st8l:
                        for _pbl in _pl8_lain_valid:
                            _st8l.write(f"⏳ {_pbl['kode_paket']}...")
                            _rbl = _ba_pl_engine5.upload_ba_pl(
                                id_nontender=_pbl["_id8l"], jenis_key=_jenis_lain8,
                                nomor_ba=_nomor_lain8,
                                tanggal_ba=_tgl_lain8.strftime("%d-%m-%Y"),
                                info=_info_lain8,
                                file_bytes=_pbl["_fl8"].read(), file_name=_pbl["_fl8"].name,
                                tempat=_tempat_lain8,
                            )
                            if _rbl.get("ok"):
                                _st8l.write(f"  ✅ {_pbl['kode_paket']} — berhasil")
                            else:
                                _st8l.write(f"  ❌ {_pbl['kode_paket']} — status {_rbl.get('status')}")

    # ── Tab 5: Download Dok Kualifikasi PL ───────────────────────────────────
    with _pl_tab5:
        import kualifikasi_engine_pl as _ke_pl
        import kualifikasi_parser_pl as _kp_pl
        import hasil_evaluasi_pl_engine as _he_pl

        st.markdown("## Download Dokumen Kualifikasi — Pengadaan Langsung")
        st.caption("Download dok kualifikasi peserta dari SPSE + populate sheet Hasil Evaluasi di BAPLJKK.")

        # Cache paket list di session state — hindari query Supabase tiap render
        if "pl7_rows" not in st.session_state:
            try:
                st.session_state["pl7_rows"] = pl_engine._sb().table("draft_paket_pl").select(
                    "kode_paket, nama_paket, jenis_pl, nomor_urut, kode_unik"
                ).order("nomor_urut").execute().data or []
            except Exception as _e7:
                st.session_state["pl7_rows"] = []
                st.error(f"Gagal load paket PL: {_e7}")
        _pl7_rows = st.session_state["pl7_rows"]

        if not _pl7_rows:
            st.info("Tidak ada paket PL di database.")
            if st.button("🔄 Reload", key="pl7_reload"):
                del st.session_state["pl7_rows"]
                st.rerun()
        else:
            _pl7c1, _pl7c2 = st.columns([1, 1])

            with _pl7c1:
                st.markdown("#### Pilih Paket")
                if "pl7_checked" not in st.session_state:
                    st.session_state["pl7_checked"] = {}

                _pl7_kodes = [r["kode_paket"] for r in _pl7_rows]
                _pl7_btn_col1, _pl7_btn_col2 = st.columns(2)
                # Pilih Semua / Batal Semua — hanya set state, TIDAK fetch CDP
                if _pl7_btn_col1.button("✅ Pilih Semua", key="pl7_select_all", use_container_width=True):
                    for _k in _pl7_kodes:
                        st.session_state[f"pl7_chk_{_k}"] = True
                        st.session_state["pl7_checked"][_k] = True
                if _pl7_btn_col2.button("❌ Batal Semua", key="pl7_deselect_all", use_container_width=True):
                    for _k in _pl7_kodes:
                        st.session_state[f"pl7_chk_{_k}"] = False
                        st.session_state["pl7_checked"][_k] = False

                for _rpl7 in _pl7_rows:
                    _kpl7 = _rpl7["kode_paket"]
                    _nomor7 = _rpl7.get("nomor_urut") or ""
                    _label7 = f"{_nomor7}. {_rpl7.get('nama_paket','?')}" if _nomor7 else _rpl7.get("nama_paket", "?") or "?"
                    _chk7 = st.checkbox(_label7, key=f"pl7_chk_{_kpl7}")
                    st.session_state["pl7_checked"][_kpl7] = _chk7

            with _pl7c2:
                st.markdown("#### Aksi")

                _pl7_selected_kodes = [k for k in _pl7_kodes if st.session_state["pl7_checked"].get(k)]
                _pl7_selected_rows  = [r for r in _pl7_rows if r["kode_paket"] in _pl7_selected_kodes]
                _n_paket7 = len(_pl7_selected_rows)

                if not _pl7_selected_rows:
                    st.info("Centang minimal 1 paket di kiri.")
                else:
                    st.markdown(f"**{_n_paket7} paket** dipilih")
                    st.caption("Peserta akan di-fetch via CDP saat tombol Jalankan diklik.")

                    _do_download7 = st.checkbox("⬇️ Download dokumen kualifikasi", value=True, key="pl7_do_dl")
                    _do_parse7    = st.checkbox("📋 Parse & populate sheet Hasil Evaluasi", value=True, key="pl7_do_parse")

                    _btn7 = st.button(
                        f"▶ Jalankan — {_n_paket7} paket",
                        type="primary", key="pl7_run", use_container_width=True,
                    )

                    if _btn7:
                        _pb7 = st.progress(0.0, text="Memulai...")
                        _log7_lines = []  # akumulasi log — update sekali per paket, bukan per baris
                        _ringkasan7: list = []  # kumpul status tiap paket untuk ringkasan akhir

                        def _flush7(container):
                            """Render log terakumulasi ke container — 1 update per paket."""
                            container.code("\n".join(_log7_lines[-60:]))  # max 60 baris terakhir

                        for _i7, _rpl7 in enumerate(_pl7_selected_rows):
                            _kpl7    = _rpl7["kode_paket"]
                            _nama7   = _rpl7.get("nama_paket", "?")
                            _status7 = st.status(f"Paket {_i7+1}/{_n_paket7} — {_nama7}", expanded=True)

                            with _status7:
                                _log7_lines.clear()
                                _log7_box = st.empty()

                                def _lcb7(msg, _box=_log7_box, _lines=_log7_lines):
                                    _lines.append(msg)
                                    _box.code("\n".join(_lines[-40:]))

                                # Fetch peserta
                                _lcb7(f"[{_i7+1}/{_n_paket7}] Fetch peserta SPSE...")
                                _pb7.progress((_i7) / _n_paket7, text=f"{_nama7} — fetch peserta")
                                _fp7 = _ke_pl.fetch_peserta_pl(_kpl7)
                                if not _fp7.get("ok"):
                                    _lcb7(f"[SKIP] Peserta: {_fp7['pesan']}")
                                    _status7.update(label=f"SKIP {_nama7} — {_fp7['pesan']}", state="error", expanded=False)
                                    _ringkasan7.append({"nama": _nama7, "status": "skip", "detail": _fp7["pesan"]})
                                    continue
                                _peserta7 = _fp7["peserta"]
                                _lcb7(f"Peserta ({len(_peserta7)}): {', '.join(p['nama'] for p in _peserta7)}")

                                # Resolve folder
                                _folder7 = _ke_pl.resolve_folder_paket_pl(_kpl7)
                                if not _folder7.get("ok"):
                                    _lcb7(f"[SKIP] Folder: {_folder7['pesan']}")
                                    _status7.update(label=f"SKIP {_nama7} — folder tidak ditemukan", state="error", expanded=False)
                                    _ringkasan7.append({"nama": _nama7, "status": "skip", "detail": _folder7.get("pesan", "folder tidak ditemukan")})
                                    continue
                                _folder_kual7 = _folder7["path"]

                                # Download kualifikasi
                                if _do_download7:
                                    _pb7.progress((_i7 + 0.3) / _n_paket7, text=f"{_nama7} — download kualifikasi")
                                    for _ui7, _p7 in enumerate(_peserta7, 1):
                                        _lcb7(f"--- Download [{_ui7}/{len(_peserta7)}] {_p7['nama']} ---")
                                        _ke_pl.download_kualifikasi_peserta_pl(
                                            _p7, _folder_kual7, _ui7, len(_peserta7), _lcb7,
                                        )

                                # Parse evaluasi
                                if _do_parse7:
                                    _pb7.progress((_i7 + 0.7) / _n_paket7, text=f"{_nama7} — parse evaluasi")
                                    _lcb7("--- Populate sheet Hasil Evaluasi ---")
                                    _hasil7 = _he_pl.populate_hasil_evaluasi_pl(_kpl7, _peserta7, _lcb7)
                                    _lcb7(f"{'[OK]' if _hasil7.get('ok') else '[GAGAL]'} {_hasil7['pesan']}")
                                    _ringkasan7.append({
                                        "nama"  : _nama7,
                                        "status": "ok" if _hasil7.get("ok") else "gagal",
                                        "detail": _hasil7.get("pesan", ""),
                                    })
                                else:
                                    # Tidak ada parse → anggap OK (hanya download)
                                    _ringkasan7.append({"nama": _nama7, "status": "ok", "detail": "download saja"})

                                _status7.update(label=f"Selesai — {_nama7}", state="complete", expanded=False)

                            _pb7.progress((_i7 + 1) / _n_paket7, text=f"Selesai {_i7+1}/{_n_paket7} paket")

                        _pb7.progress(1.0, text="Semua paket selesai.")
                        from batch_summary import render_ringkasan_batch as _rrb7
                        _rrb7(st, _ringkasan7)

    # ── Tab 6: Evaluasi SPSE + Download Teknis/Biaya ─────────────────────────
    with _pl_tab6:
        import evaluasi_admin_kualifikasi_pl as _eval_pl
        import dokumen_teknis_biaya_pl as _dtb_pl
        import penawaran_pl_engine as _penawaran_pl

        st.markdown("## Evaluasi SPSE & Download Teknis/Biaya — Pengadaan Langsung")
        st.caption("Submit evaluasi Admin+Kualifikasi LULUS di SPSE, lalu download dokumen teknis/biaya peserta.")

        # Cache paket list (share dengan Tab 7)
        if "pl7_rows" not in st.session_state:
            try:
                st.session_state["pl7_rows"] = pl_engine._sb().table("draft_paket_pl").select(
                    "kode_paket, nama_paket, jenis_pl, nomor_urut, kode_unik"
                ).order("nomor_urut").execute().data or []
            except Exception:
                st.session_state["pl7_rows"] = []
        _pl8_rows = st.session_state["pl7_rows"]

        if not _pl8_rows:
            st.info("Tidak ada paket PL. Reload di Tab 7.")
        else:
            _pl8c1, _pl8c2 = st.columns([1, 1])

            with _pl8c1:
                st.markdown("#### Pilih Paket")
                if "pl8_checked" not in st.session_state:
                    st.session_state["pl8_checked"] = {}

                _pl8_kodes = [r["kode_paket"] for r in _pl8_rows]
                _pl8bc1, _pl8bc2 = st.columns(2)
                if _pl8bc1.button("✅ Pilih Semua", key="pl8_select_all", use_container_width=True):
                    for _k in _pl8_kodes:
                        st.session_state[f"pl8_chk_{_k}"] = True
                        st.session_state["pl8_checked"][_k] = True
                if _pl8bc2.button("❌ Batal Semua", key="pl8_deselect_all", use_container_width=True):
                    for _k in _pl8_kodes:
                        st.session_state[f"pl8_chk_{_k}"] = False
                        st.session_state["pl8_checked"][_k] = False

                for _rpl8 in _pl8_rows:
                    _kpl8 = _rpl8["kode_paket"]
                    _nomor8 = _rpl8.get("nomor_urut") or ""
                    _label8 = f"{_nomor8}. {_rpl8.get('nama_paket','?')}" if _nomor8 else _rpl8.get("nama_paket", "?") or "?"
                    _chk8 = st.checkbox(_label8, key=f"pl8_chk_{_kpl8}")
                    st.session_state["pl8_checked"][_kpl8] = _chk8

            with _pl8c2:
                st.markdown("#### Aksi")

                _pl8_selected_rows = [r for r in _pl8_rows if st.session_state["pl8_checked"].get(r["kode_paket"])]
                _n_paket8 = len(_pl8_selected_rows)

                if not _pl8_selected_rows:
                    st.info("Centang minimal 1 paket di kiri.")
                else:
                    st.markdown(f"**{_n_paket8} paket** dipilih")
                    st.caption("Peserta di-scrape dari SPSE saat Jalankan.")

                    _do_eval_admin = st.checkbox("⚖️ Submit evaluasi Admin + Kualifikasi LULUS di SPSE", value=True, key="pl8_do_eval_admin")
                    _do_eval_teknis = st.checkbox("⚙️ Submit evaluasi Teknis LULUS di SPSE", value=True, key="pl8_do_eval_teknis")
                    _do_eval_harga = st.checkbox("💰 Submit evaluasi Harga LULUS di SPSE", value=True, key="pl8_do_eval_harga")

                    _do_tekbio8  = st.checkbox("⬇️ Download dokumen teknis/biaya + gabung PDF", value=True, key="pl8_do_tekbio")
                    _do_penawaran8 = st.checkbox("📊 Tulis rincian penawaran ke sheet '6. Penawaran' Excel", value=True, key="pl8_do_penawaran")

                    st.divider()
                    st.warning("Evaluasi LULUS bersifat **permanen** — modifikasi data SPSE production.")
                    _konfirmasi8 = st.checkbox(
                        "Saya paham tindakan ini tidak bisa dibatalkan.",
                        value=False, key="pl8_konfirmasi",
                    )

                    _btn8_disabled = (_do_eval_admin or _do_eval_teknis or _do_eval_harga) and not _konfirmasi8
                    if _btn8_disabled:
                        st.info("Centang konfirmasi untuk mengaktifkan tombol.")

                    _btn8 = st.button(
                        f"▶ Jalankan — {_n_paket8} paket",
                        type="primary", key="pl8_run", use_container_width=True,
                        disabled=_btn8_disabled,
                    )

                    if _btn8:
                        _pb8 = st.progress(0.0, text="Memulai...")
                        _ringkasan8: list = []  # kumpul status tiap paket untuk ringkasan akhir

                        for _i8, _rpl8 in enumerate(_pl8_selected_rows):
                            _kpl8  = _rpl8["kode_paket"]
                            _nama8 = _rpl8.get("nama_paket", "?")
                            _status8 = st.status(f"Paket {_i8+1}/{_n_paket8} — {_nama8}", expanded=True)

                            with _status8:
                                _log8_lines = []
                                _log8_box   = st.empty()

                                def _lcb8(msg, _box=_log8_box, _lines=_log8_lines):
                                    _lines.append(msg)
                                    _box.code("\n".join(_lines[-40:]))

                                # Scrape id_nontender per peserta
                                _lcb8("Scrape peserta evaluasi dari SPSE...")
                                _pb8.progress(_i8 / _n_paket8, text=f"{_nama8} — scrape peserta")
                                _res_peserta8 = _eval_pl.scrape_peserta_evaluasi(_kpl8)
                                if not _res_peserta8.get("ok"):
                                    _lcb8(f"[SKIP] {_res_peserta8['pesan']}")
                                    _status8.update(label=f"SKIP {_nama8} — {_res_peserta8['pesan']}", state="error", expanded=False)
                                    _ringkasan8.append({"nama": _nama8, "status": "skip", "detail": _res_peserta8["pesan"]})
                                    continue
                                _peserta8 = _res_peserta8["peserta"]
                                _lcb8(f"Peserta ({len(_peserta8)}): {', '.join(p['nama'] for p in _peserta8)}")

                                # Resolve folder paket root
                                _folder8      = _ke_pl.resolve_folder_paket_pl(_kpl8)
                                _folder_paket8 = _folder8.get("pesan", "") if _folder8.get("ok") else ""

                                # Evaluasi LULUS
                                if _do_eval_admin or _do_eval_teknis or _do_eval_harga:
                                    _pb8.progress((_i8 + 0.3) / _n_paket8, text=f"{_nama8} — submit evaluasi")
                                    _lcb8(f"--- Submit evaluasi LULUS (Admin:{_do_eval_admin}, Teknis:{_do_eval_teknis}, Harga:{_do_eval_harga}) ---")
                                    _eval8 = _eval_pl.evaluasi_batch_lulus(
                                        _kpl8,
                                        admin=_do_eval_admin,
                                        kualifikasi=_do_eval_admin,
                                        teknis=_do_eval_teknis,
                                        harga=_do_eval_harga,
                                        progress_cb=_lcb8
                                    )
                                    _lcb8(f"{'[OK]' if _eval8.get('ok') else '[SEBAGIAN GAGAL]'} {_eval8['ringkasan']}")

                                # Download teknis/biaya
                                if _do_tekbio8:
                                    if not _folder_paket8:
                                        _lcb8("[SKIP] Folder paket tidak ditemukan")
                                    else:
                                        _pb8.progress((_i8 + 0.6) / _n_paket8, text=f"{_nama8} — download teknis/biaya")
                                        for _ui8, _ep8 in enumerate(_peserta8, 1):
                                            _lcb8(f"--- Download [{_ui8}/{len(_peserta8)}] {_ep8['nama']} ---")
                                            _res_tb8 = _dtb_pl.download_teknis_biaya_peserta(
                                                id_nontender=_ep8["id_nontender"],
                                                nama_peserta=_ep8["nama"],
                                                folder_paket=_folder_paket8,
                                                urutan=_ui8,
                                                progress_cb=_lcb8,
                                            )
                                            _lcb8(f"{'[OK]' if _res_tb8['ok'] else '[GAGAL]'} {_res_tb8['pesan']}")

                                # Tulis penawaran ke sheet 6. Penawaran
                                if _do_penawaran8:
                                    if not _folder_paket8:
                                        _lcb8("[SKIP] Folder paket tidak ditemukan, skip penawaran")
                                    else:
                                        _pb8.progress((_i8 + 0.8) / _n_paket8, text=f"{_nama8} — tulis penawaran")
                                        _lcb8("--- Tulis rincian penawaran ke Excel ---")
                                        for _ep8_p in _peserta8:
                                            _lcb8(f"  Peserta: {_ep8_p['nama']}")
                                            _res_pnw8 = _penawaran_pl.tulis_penawaran_ke_excel(
                                                folder_paket=_folder_paket8,
                                                id_nontender=_ep8_p["id_nontender"],
                                                progress_cb=_lcb8,
                                            )
                                            _lcb8(f"  {'[OK]' if _res_pnw8['ok'] else '[GAGAL]'} {_res_pnw8['pesan']}" +
                                                  (f" — Total Rp {_res_pnw8['total_penawaran']:,.0f}" if _res_pnw8.get('total_penawaran') else ""))

                                _ringkasan8.append({"nama": _nama8, "status": "ok", "detail": ""})
                                _status8.update(label=f"Selesai — {_nama8}", state="complete", expanded=False)

                            _pb8.progress((_i8 + 1) / _n_paket8, text=f"Selesai {_i8+1}/{_n_paket8} paket")

                        _pb8.progress(1.0, text="Semua paket selesai.")
                        from batch_summary import render_ringkasan_batch as _rrb8
                        _rrb8(st, _ringkasan8)

    st.stop()  # Jangan render tab Tender jika mode PL

if st.session_state["app_mode"] == "PL - Konstruksi":
    # ============================================================
    # MODE: PENGADAAN LANGSUNG — PEKERJAAN KONSTRUKSI (PL PK)
    # ============================================================
    # Rebind engine PK-specific ke varian _plpk (scope module, mode PK only)
    import pl_engine_plpk as pl_engine
    _pl_tab0, _pl_tab1, _pl_tab2, _pl_tab3, _pl_tab4, _pl_tab5, _pl_tab6, _pl_tab7, _pl_tab8 = st.tabs([
        "0️⃣ Import DPA",
        "1️⃣ Draft Paket PL",
        "2️⃣ Kirim Undangan DPP",
        "3️⃣ Buat Jadwal",
        "4️⃣ Setup Paket",
        "5️⃣ Download Kualifikasi",
        "6️⃣ Evaluasi & Teknis/Biaya",
        "7️⃣ Kirim Verifikasi",
        "8️⃣ Upload BA PL",
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

        # ── Tools: Gabung Semua BA PL JKK (Bulk Print) ────────────────────────
        st.divider()
        st.markdown("### 🖨️ Gabung Semua BA PL JKK")
        st.caption(
            "Scan semua folder paket di **@ Pengadaan Langsung JKK** → ambil file `BA_PLJKK_*.pdf` "
            "tiap folder → gabung jadi satu file untuk print sekali."
        )

        import os as _ba_os
        import re as _ba_re

        # Root folder PL JKK (parent dari semua folder paket)
        _ba_root = r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ Pengadaan Langsung JKK"
        _ba_root_in = st.text_input(
            "Folder root PL JKK:",
            value=_ba_root,
            key="ba_bulk_root",
        )

        def _ba_nomor_folder(nama):
            """Ambil nomor urut dari nama folder (mis. '10. PLJKK...' → 10). Tanpa nomor → 9999."""
            m = _ba_re.match(r"\s*(\d+)", nama)
            return int(m.group(1)) if m else 9999

        _ba_found = []  # (nomor, nama_folder, path_pdf)
        if _ba_os.path.isdir(_ba_root_in):
            for _entry in _ba_os.listdir(_ba_root_in):
                _sub = _ba_os.path.join(_ba_root_in, _entry)
                if not _ba_os.path.isdir(_sub):
                    continue
                # Match BA_PLJKK_*.pdf (bukan BA_REVIU_* / BA lain)
                _matches = [
                    f for f in _ba_os.listdir(_sub)
                    if _ba_re.match(r"(?i)^BA_PLJKK_.*\.pdf$", f)
                ]
                for _mf in _matches:
                    _ba_found.append((
                        _ba_nomor_folder(_entry), _entry,
                        _ba_os.path.join(_sub, _mf),
                    ))
            _ba_found.sort(key=lambda x: (x[0], x[1]))
        else:
            st.error(f"Folder tidak ditemukan: {_ba_root_in}")

        if _ba_found:
            st.success(f"✅ Ditemukan {len(_ba_found)} file BA_PLJKK (urut nomor paket):")
            _ba_prev = [
                {"No": n, "Folder": fol, "File": _ba_os.path.basename(p)}
                for n, fol, p in _ba_found
            ]
            st.dataframe(_ba_prev, use_container_width=True, hide_index=True)

            _ba_out_nama = st.text_input(
                "Nama file gabungan:",
                value="_KUMPULAN_BA_PL_JKK.pdf",
                key="ba_bulk_out_nama",
            )

            if st.button("🖨️ Gabung Semua BA", type="primary", key="ba_bulk_run"):
                from pypdf import PdfReader as _BaReader, PdfWriter as _BaWriter

                _writer = _BaWriter()
                _ok, _err = 0, []
                with st.status("Menggabungkan BA...", expanded=True) as _ba_status:
                    for _n, _fol, _path in _ba_found:
                        try:
                            _rdr = _BaReader(_path)
                            for _pg in _rdr.pages:
                                _writer.add_page(_pg)
                            st.write(f"✅ Paket {_n} — {len(_rdr.pages)} hlm")
                            _ok += 1
                        except Exception as _ex:
                            st.write(f"❌ Paket {_n} ({_fol}): {_ex}")
                            _err.append(_fol)

                    if len(_writer.pages) == 0:
                        _ba_status.update(label="❌ Tidak ada halaman tergabung.", state="error")
                    else:
                        # Tulis ke root folder; fallback suffix jika file terkunci (Nitro/dll)
                        _out_nama = _ba_out_nama.strip() or "_KUMPULAN_BA_PL_JKK.pdf"
                        if not _out_nama.lower().endswith(".pdf"):
                            _out_nama += ".pdf"
                        _base, _ext = _ba_os.path.splitext(_out_nama)
                        _target = _ba_os.path.join(_ba_root_in, _out_nama)
                        _written = None
                        for _attempt in range(6):
                            _try_path = _target if _attempt == 0 else \
                                _ba_os.path.join(_ba_root_in, f"{_base}_v{_attempt + 1}{_ext}")
                            try:
                                with open(_try_path, "wb") as _fh:
                                    _writer.write(_fh)
                                _written = _try_path
                                break
                            except PermissionError:
                                continue
                        if _written:
                            _ba_status.update(
                                label=f"✅ {_ok} BA digabung → {len(_writer.pages)} halaman.",
                                state="complete",
                            )
                            st.success(f"📁 Tersimpan: `{_written}`")
                            if _err:
                                st.warning(f"⚠️ Gagal: {', '.join(_err)}")
                        else:
                            _ba_status.update(
                                label="❌ Gagal tulis (file terkunci). Tutup PDF viewer dulu.",
                                state="error",
                            )
        elif _ba_os.path.isdir(_ba_root_in):
            st.info("Tidak ada file `BA_PLJKK_*.pdf` ditemukan di folder paket manapun.")

    # ── Tab 1: Draft Paket PL ─────────────────────────────────────────────────
    with _pl_tab1:
        import os as _pl_os, subprocess as _pl_sp
        from config import POKJA_ROOT as _PL_POKJA_ROOT, OUTPUT_DIR_PL_JKK as _PL_DIR_JKK, OUTPUT_DIR_PL_PK as _PL_DIR_PK
        _TEMPLATE_DIR_PL    = str(__import__("pathlib").Path(_PL_POKJA_ROOT) / "Paket Experiment - Pengadaan Langsung" / "Development - PL - JKK")
        _TEMPLATE_DIR_PL_PK = str(__import__("pathlib").Path(_PL_POKJA_ROOT) / "Paket Experiment - Pengadaan Langsung" / "Development - PL - PK")

        _PL_PY     = str(pathlib.Path(_PL_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110" / "python" / "python.exe")
        _PL_SCRIPT = str(pathlib.Path(_PL_POKJA_ROOT) / "V19_Scheduler" / "WPy64-313110" / "setup_paket_baru.py")
        _PL_NO_WIN = 0x08000000

        def _cari_xlsm_pl(folder):
            """Cari .xlsm utama di folder paket PL (prefix '0. BA', skip Backup)."""
            try:
                xs = [f for f in _pl_os.listdir(folder)
                      if f.lower().endswith(".xlsm") and "backup" not in f.lower()]
            except Exception:
                return None
            if not xs:
                return None
            xs.sort(key=lambda f: (not f.lower().startswith("0. ba"), f))
            return _pl_os.path.join(folder, xs[0])

        _pl_rows = pl_engine.load_draft_pl()

        # ── Buang duplikat row lama (paket di-ulang → kode baru, row lama nyangkut) ──
        _pl_rows, _pl_dup_n = pl_engine.buang_duplikat_paket_lama(_pl_rows)
        if _pl_dup_n:
            st.caption(f"♻️ {_pl_dup_n} row lama duplikat (paket ulang) disembunyikan otomatis.")

        # ── #4: Filter paket selesai (penandatanganan kontrak) ──────────────────
        _pl_show_done = st.checkbox(
            "Tampilkan paket selesai (sudah teken kontrak)",
            value=False,
            key="pl_show_done",
        )
        _pl_done_n = sum(1 for r in _pl_rows if pl_engine.is_paket_selesai(r))
        if not _pl_show_done:
            _pl_rows = [r for r in _pl_rows if not pl_engine.is_paket_selesai(r)]
            if _pl_done_n:
                st.caption(f"🔒 {_pl_done_n} paket selesai (Penandatanganan Kontrak) disembunyikan — centang di atas untuk tampilkan.")

        _pl_col_kiri, _pl_col_kanan = st.columns(2)

        # ══════════════════════════════════════════════════════
        # KOLOM KIRI — Serap Data + Daftar Paket
        # ══════════════════════════════════════════════════════
        with _pl_col_kiri:
            # ── #1: Gabung Serap SPSE + MAK + HPS ──────────────────────────────
            st.markdown("#### 1. Serap Data Paket PL")
            st.caption("Pilih aksi lalu klik tombol — aksi berjalan berurutan sesuai centang.")
            _cb_serap_spse = st.checkbox("Serap dari SPSE (daftar paket + status)", value=True, key="pl_cb_serap_spse")
            _cb_serap_mak  = st.checkbox("Serap MAK dari Inbox PL",               value=True, key="pl_cb_serap_mak")
            _cb_hps_all    = st.checkbox("Scrape HPS semua paket berfolder → Excel", value=True, key="pl_cb_hps_all")

            if st.button("🚀 Serap Data Paket PL", type="primary", use_container_width=True, key="btn_serap_pl_gabung"):
                # Aksi 1: Serap dari SPSE
                if _cb_serap_spse:
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
                            with st.expander("Detail Error SPSE"):
                                for _e in _pl_hasil["errors"]:
                                    st.error(_e)
                        # Reload setelah serap SPSE agar data paket terkini
                        _pl_rows = pl_engine.load_draft_pl()
                        if not _pl_show_done:
                            _pl_rows = [r for r in _pl_rows if not _pl_is_done(r)]

                # Aksi 2: Serap MAK dari Inbox
                if _cb_serap_mak:
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
                            with st.expander("Detail Error MAK"):
                                for _e in _r_mak["errors"]:
                                    st.warning(_e)
                    except Exception as _e:
                        st.error(f"Gagal serap MAK: {_e}")

                # Aksi 3: HPS bulk semua paket berfolder
                if _cb_hps_all:
                    import hps_engine as _hps_pl_bulk
                    import kualifikasi_engine_plpk as _keng_pl_hb
                    _pl_rows_hps_bulk = [
                        r for r in _pl_rows
                        if r.get("kode_paket") and r.get("folder_dibuat")
                    ]
                    if not _pl_rows_hps_bulk:
                        st.info("Tidak ada paket dengan folder untuk scrape HPS.")
                    else:
                        _hps_bulk_ok, _hps_bulk_fail = 0, 0
                        _hps_bulk_gagal = []
                        _hps_bulk_status = st.status(
                            f"💰 Scrape HPS {len(_pl_rows_hps_bulk)} paket...", expanded=True
                        )
                        _hps_bulk_line = _hps_bulk_status.empty()
                        _hps_bulk_bp = st.progress(0.0)
                        for _hb_i, _hb_row in enumerate(_pl_rows_hps_bulk):
                            _hb_kp   = _hb_row.get("kode_paket", "")
                            _hb_nama = _hb_row.get("nama_paket", _hb_kp)[:50]
                            _hps_bulk_status.update(label=f"[{_hb_i+1}/{len(_pl_rows_hps_bulk)}] {_hb_nama}")
                            _hps_bulk_bp.progress((_hb_i + 1) / len(_pl_rows_hps_bulk))
                            _hb_xlsm = None
                            try:
                                _hb_fr = _keng_pl_hb.resolve_folder_paket_pl(_hb_kp)
                                _hb_root = _hb_fr.get("pesan", "") if _hb_fr.get("ok") else ""
                                if _hb_root and _pl_os.path.isdir(_hb_root):
                                    _hb_xlsm = _cari_xlsm_pl(_hb_root)
                            except Exception:
                                _hb_xlsm = None
                            if not _hb_xlsm:
                                _hps_bulk_fail += 1
                                _hb_alasan = "folder/xlsm paket tidak ditemukan"
                                _hps_bulk_gagal.append(f"{_hb_nama}: {_hb_alasan}")
                                _hps_bulk_line.write(f"⚠ [{_hb_i+1}] {_hb_nama} — {_hb_alasan}")
                                continue
                            try:
                                _hb_r = _hps_pl_bulk.scrape_hps_pl_ke_excel(_hb_kp, _hb_xlsm)
                                if _hb_r.get("ok"):
                                    _hps_bulk_ok += 1
                                    _hps_bulk_line.write(f"✅ [{_hb_i+1}] {_hb_nama} — {_hb_r['count']} item, Rp {_hb_r.get('total_nilai_bulat',0):,.0f}")
                                else:
                                    _hps_bulk_fail += 1
                                    _hb_alasan = _hb_r.get("pesan", "-")
                                    _hps_bulk_gagal.append(f"{_hb_nama}: {_hb_alasan}")
                                    _hps_bulk_line.write(f"❌ [{_hb_i+1}] {_hb_nama} — {_hb_alasan}")
                            except Exception as _hb_e:
                                _hps_bulk_fail += 1
                                _hps_bulk_gagal.append(f"{_hb_nama}: {_hb_e}")
                                _hps_bulk_line.write(f"❌ [{_hb_i+1}] {_hb_nama} — {_hb_e}")
                        _hps_bulk_bp.progress(1.0)
                        _hps_bulk_line.empty()
                        _hps_bulk_status.update(
                            label=f"💰 HPS Bulk selesai: ✅ {_hps_bulk_ok} sukses, ❌ {_hps_bulk_fail} gagal",
                            state="complete", expanded=_hps_bulk_fail > 0,
                        )
                        if _hps_bulk_gagal:
                            st.warning("Paket gagal:\n" + "\n".join(_hps_bulk_gagal))

            st.divider()
            st.markdown("#### 2. Daftar Paket PL")

            _pl_filter = st.selectbox(
                "Filter:",
                ["Semua", "JKK", "PK", "Belum Folder", "Sudah Folder"],
                key="pl_filter_jenis",
            )

            def _pl_match(r):
                _jp = (r.get("jenis_pl") or "").upper()
                if _pl_filter == "JKK":    return _jp == "JKK"
                if _pl_filter == "PK":     return _jp == "PK"
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
                    _pr_jenis  = (_pr.get("jenis_pl") or "").upper()
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

                        _pr_c1, _pr_c2 = st.columns([3, 1])
                        if _pr_c2.button("🗑️ Hapus", key=f"pl_hapus_{_pr_kode}", use_container_width=True):
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
                _jenis = (_r.get("jenis_pl") or "").upper()
                _sudah = " ✅" if _r.get("folder_dibuat") else ""
                _lbl = f"{_no}. {_nm} - {_jenis}{_sudah}"
                _pl_opsi_map[_lbl] = _r

            _pl_pilihan = st.selectbox("Pilih paket:", list(_pl_opsi_map.keys()), key="sel_pl_folder")
            _pl_row_sel = _pl_opsi_map.get(_pl_pilihan)

            # Auto-generate nama folder
            _pl_default_folder = ""
            _pl_jenis_sel = "PK"
            if _pl_row_sel:
                _pl_nm      = _pl_row_sel.get("nama_paket", "")
                _pl_jenis_sel = (_pl_row_sel.get("jenis_pl") or "PK").upper()
                _pl_prefix  = {"JKK": "PLJKK", "PK": "PLPK"}.get(_pl_jenis_sel, f"PL{_pl_jenis_sel}")
                _pl_no_urut = _pl_no_dari_nama(_pl_nm, len(_pl_rows))
                _pl_default_folder = f"{_pl_no_urut}. {_pl_prefix} - {_pl_nm}"

            _pl_nama_folder = st.text_input(
                "Nama folder:",
                value=_pl_default_folder,
                placeholder="1. PLJKK - Perencanaan Pembangunan Jalan ...",
                key="pl_input_nama_folder",
            )

            _pl_paksa_ulang = st.checkbox(
                "Paksa suffix (PL - Ulang)",
                value=False,
                key="pl_cb_paksa_ulang",
                help="Centang untuk tempel ' (PL - Ulang)' walau folder lama belum ada. "
                     "Default: auto-suffix hanya jika folder dengan nama sama sudah ada di disk.",
            )

            # Output base dir: JKK → @ Pengadaan Langsung JKK, PK → @ Pengadaan Langsung PK
            _pl_output_base = _PL_DIR_JKK if _pl_jenis_sel == "JKK" else _PL_DIR_PK
            _pl_nama_clean = re.sub(r'[/<>:"\|?*]', "-", _pl_nama_folder).strip() if _pl_nama_folder else ""
            if _pl_nama_clean:
                _pl_nama_clean = pl_engine.nama_folder_dengan_suffix_ulang(
                    _pl_output_base, _pl_nama_clean, paksa_suffix=_pl_paksa_ulang,
                )
                if _pl_nama_clean != re.sub(r'[/<>:"\|?*]', "-", _pl_nama_folder).strip():
                    st.caption(f"♻️ Paket ulang terdeteksi → folder: `{_pl_nama_clean}`")
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
                    # Scrape HPS PL otomatis → tulis langsung ke Excel (tanpa DB)
                    try:
                        import hps_engine as _hps_pl
                        _xl_pl = _cari_xlsm_pl(_pl_target)
                        if _xl_pl:
                            _hps_r = _hps_pl.scrape_hps_pl_ke_excel(_pl_kode_dl, _xl_pl)
                            if _hps_r.get("ok"):
                                st.success(f"💰 {_hps_r['pesan']} — Total Rp {_hps_r.get('total_nilai_bulat',0):,.0f}")
                            else:
                                st.warning(f"⚠ HPS: {_hps_r.get('pesan','-')}")
                        else:
                            st.caption("💰 HPS dilewati — tidak ada .xlsm di folder.")
                    except Exception as _he:
                        st.warning(f"⚠ HPS error: {_he}")

            # Tombol scrape HPS mandiri (kalau download sebelumnya tidak include)
            if _pl_folder_ada and _pl_row_sel:
                _pl_kode_hps = _pl_row_sel.get("kode_paket", "")
                if _pl_kode_hps and st.button("💰 Scrape HPS PL → Excel", use_container_width=True, key="pl_btn_hps_saja"):
                    import hps_engine as _hps_pl
                    _xl_pl2 = _cari_xlsm_pl(_pl_target)
                    if not _xl_pl2:
                        st.error("Tidak ada file .xlsm di folder paket untuk diisi HPS.")
                    else:
                        with st.spinner("Scrape HPS dari SPSE → tulis Excel..."):
                            _hps_r = _hps_pl.scrape_hps_pl_ke_excel(_pl_kode_hps, _xl_pl2)
                        if _hps_r.get("ok"):
                            st.success(f"✅ {_hps_r['pesan']} — Total Rp {_hps_r.get('total_nilai_bulat',0):,.0f}")
                            if _hps_r.get("warning"):
                                st.warning(f"⚠ {len(_hps_r['warning'])} item selisih (highlight kuning di Excel)")
                        else:
                            st.error(f"Gagal: {_hps_r.get('pesan','-')}")

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
                                    # Scrape HPS PL → tulis langsung ke Excel
                                    try:
                                        import hps_engine as _hps_pl
                                        _xl_pl3 = _cari_xlsm_pl(_pl_target)
                                        if _xl_pl3:
                                            _hps_r = _hps_pl.scrape_hps_pl_ke_excel(_pl_kp, _xl_pl3)
                                            if _hps_r.get("ok"):
                                                st.success(f"💰 {_hps_r['pesan']} — Rp {_hps_r.get('total_nilai_bulat',0):,.0f}")
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
                _bj0   = (_br0.get("jenis_pl") or "PK").upper()
                _bpfx0 = {"JKK": "PLJKK", "PK": "PLPK"}.get(_bj0, f"PL{_bj0}")
                _bno0  = _pl_no_dari_nama(_bnm0, _bi0)
                _bnm_folder0 = re.sub(r'[/<>:"\|?*]', "-", f"{_bno0}. {_bpfx0} - {_bnm0}").strip()
                _bout_base0  = _PL_DIR_JKK if _bj0 == "JKK" else _PL_DIR_PK
                _bnm_folder0 = pl_engine.nama_folder_dengan_suffix_ulang(_bout_base0, _bnm_folder0)
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

            # ── #2: Checklist pilih paket untuk buat folder ──────────────────
            if _pl_rows_belum:
                st.markdown("**Pilih paket yang akan dibuat foldernya:**")
                _plf_col1, _plf_col2 = st.columns(2)
                # Tombol pilih semua / batal semua (tiru pola Tab 5)
                if _plf_col1.button("✅ Pilih Semua", key="plf_pilih_semua", use_container_width=True):
                    for _br_chk in _pl_rows_belum:
                        st.session_state[f"plf_chk_{_br_chk.get('kode_paket','')}"] = True
                    st.rerun()
                if _plf_col2.button("❌ Batal Semua", key="plf_batal_semua", use_container_width=True):
                    for _br_chk in _pl_rows_belum:
                        st.session_state[f"plf_chk_{_br_chk.get('kode_paket','')}"] = False
                    st.rerun()
                for _br_chk in _pl_rows_belum:
                    _bkp_chk = _br_chk.get("kode_paket", "")
                    st.checkbox(
                        f"{_br_chk.get('nama_paket','')[:60]} — {(_br_chk.get('jenis_pl') or '').upper()}",
                        value=st.session_state.get(f"plf_chk_{_bkp_chk}", True),
                        key=f"plf_chk_{_bkp_chk}",
                    )
                # Hitung yang dicentang untuk label tombol
                _pl_terpilih_plan = [
                    item for item in _pl_bulk_plan
                    if st.session_state.get(f"plf_chk_{item['kode_paket']}", True)
                ]
                if st.button(
                    f"📁 Buat Folder Terpilih ({len(_pl_terpilih_plan)} paket)",
                    disabled=len(_pl_terpilih_plan) == 0,
                    use_container_width=True,
                    key="pl_btn_buat_terpilih",
                    type="primary",
                ):
                    _pl_bp = st.progress(0.0)
                    _pl_bulk_status = st.status(f"📁 Memproses {len(_pl_terpilih_plan)} paket terpilih...", expanded=True)
                    _pl_bulk_status_line = _pl_bulk_status.empty()
                    _pl_ok, _pl_fail = 0, 0
                    _pl_bulk_semua_log = {}
                    for _pl_i, _pl_bp_item in enumerate(_pl_terpilih_plan):
                        _pl_bp.progress((_pl_i + 1) / len(_pl_terpilih_plan))
                        _pl_nf = _pl_bp_item["nama_folder"]
                        _pl_kp_b = _pl_bp_item["kode_paket"]
                        _pl_out_b = _pl_bp_item["out_base"]
                        _pl_target_b = _pl_os.path.join(_pl_out_b, _pl_nf)
                        _pl_bulk_status.update(label=f"[{_pl_i+1}/{len(_pl_terpilih_plan)}] {_pl_nf[:60]}")
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
                                if _pl_dl_dokumen and _pl_kp_b:
                                    def _pl_bulk_cb(msg, _log=_pl_paket_log):
                                        _log.append(msg)
                                        _pl_bulk_status_line.code("\n".join(_log[-10:]))
                                    try:
                                        _pl_dl_hasil = pl_engine.download_dokumen_paket_pl(
                                            _pl_kp_b, _pl_target_b, progress_cb=_pl_bulk_cb,
                                        )
                                        _pl_paket_log.append(
                                            f"📎 Download: ✅{len(_pl_dl_hasil['ok'])} file"
                                            + (f" | Draft: {_pl_os.path.basename(_pl_dl_hasil['draft_pdf'])}" if _pl_dl_hasil.get('draft_pdf') else " | ⚠ Draft tidak terbuat")
                                        )
                                        for _pl_e in _pl_dl_hasil.get("error", []):
                                            _pl_paket_log.append(f"  ❌ {_pl_e}")
                                    except Exception as _pl_dl_e:
                                        _pl_paket_log.append(f"❌ Download error: {_pl_dl_e}")
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
                                if _pl_kp_b:
                                    try:
                                        import hps_engine as _pl_hps_eng
                                        _xl_plb = _cari_xlsm_pl(_pl_target_b)
                                        if _xl_plb:
                                            _pl_hps_res = _pl_hps_eng.scrape_hps_pl_ke_excel(_pl_kp_b, _xl_plb)
                                            if _pl_hps_res.get("ok"):
                                                _pl_paket_log.append(f"📊 HPS: {_pl_hps_res.get('count', 0)} baris → Excel")
                                            else:
                                                _pl_paket_log.append(f"⚠ HPS: {_pl_hps_res.get('pesan','-')}")
                                        else:
                                            _pl_paket_log.append("⚠ HPS dilewati — tidak ada .xlsm")
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
            # ── #3: Serap Penyedia + Download Dokumen Bulk ───────────────────────
            st.divider()
            st.markdown("#### 3. Serap Penyedia + Download Dokumen SPSE")
            st.caption("Pilih aksi lalu klik tombol — berjalan untuk semua paket berfolder.")
            _cb_serap_pyd  = st.checkbox("Serap Penyedia dari Draft_PL (nama, NPWP)", value=True, key="pl_cb_serap_pyd")
            _cb_dl_dok_bulk = st.checkbox("Download Dokumen SPSE bulk (KAK, Personil, Kontrak)", value=True, key="pl_cb_dl_dok_bulk")

            if st.button("📦 Serap Penyedia + Dokumen SPSE", use_container_width=True, key="btn_pyd_dl_gabung"):
                # Aksi: Serap penyedia dari Draft_PL PDF
                if _cb_serap_pyd:
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
                            with st.expander("Detail Error Penyedia"):
                                for _e in _r_pyd["errors"]:
                                    st.warning(_e)
                    except Exception as _e:
                        st.error(f"Gagal serap penyedia: {_e}")

                # Aksi: Download dokumen bulk semua paket berfolder
                if _cb_dl_dok_bulk:
                    import kualifikasi_engine_plpk as _keng_pl_dl
                    _pl_rows_dl_bulk = [
                        r for r in _pl_rows
                        if r.get("kode_paket") and r.get("folder_dibuat")
                    ]
                    if not _pl_rows_dl_bulk:
                        st.info("Tidak ada paket dengan folder untuk download dokumen.")
                    else:
                        _dl_bulk_ok, _dl_bulk_fail = 0, 0
                        _dl_bulk_status = st.status(
                            f"📦 Download dokumen {len(_pl_rows_dl_bulk)} paket...", expanded=True
                        )
                        _dl_bulk_line = _dl_bulk_status.empty()
                        _dl_bulk_bp = st.progress(0.0)
                        for _db_i, _db_row in enumerate(_pl_rows_dl_bulk):
                            _db_kp   = _db_row.get("kode_paket", "")
                            _db_nama = _db_row.get("nama_paket", _db_kp)[:50]
                            _dl_bulk_status.update(label=f"[{_db_i+1}/{len(_pl_rows_dl_bulk)}] {_db_nama}")
                            _dl_bulk_bp.progress((_db_i + 1) / len(_pl_rows_dl_bulk))
                            _db_root = ""
                            try:
                                _db_fr = _keng_pl_dl.resolve_folder_paket_pl(_db_kp)
                                _db_root = _db_fr.get("pesan", "") if _db_fr.get("ok") else ""
                            except Exception:
                                _db_root = ""
                            if not _db_root or not _pl_os.path.isdir(_db_root):
                                _dl_bulk_fail += 1
                                _dl_bulk_line.write(f"⚠ [{_db_i+1}] {_db_nama} — folder tidak ditemukan")
                                continue
                            try:
                                _db_dl_logs = []
                                def _db_dl_cb(msg, _log=_db_dl_logs):
                                    _log.append(msg)
                                _db_dl_res = pl_engine.download_dokumen_paket_pl(_db_kp, _db_root, _db_dl_cb)
                                _dl_bulk_ok += 1
                                _dl_bulk_line.write(f"✅ [{_db_i+1}] {_db_nama} — {len(_db_dl_res.get('ok',[]))} file")
                                # Parse KAK setelah download
                                _db_kak_p = parse_kak_pl.cari_kak_di_folder(_db_root)
                                if _db_kak_p:
                                    _db_kak_d = parse_kak_pl.parse_kak(_db_kak_p)
                                    _db_kak_u = {k: v for k, v in _db_kak_d.items() if v}
                                    if _db_kak_u:
                                        pl_engine.simpan_paket_pl({"kode_paket": _db_kp, **_db_kak_u})
                            except Exception as _db_e:
                                _dl_bulk_fail += 1
                                _dl_bulk_line.write(f"❌ [{_db_i+1}] {_db_nama} — {_db_e}")
                        _dl_bulk_bp.progress(1.0)
                        _dl_bulk_line.empty()
                        _dl_bulk_status.update(
                            label=f"📦 Download selesai: ✅ {_dl_bulk_ok} sukses, ❌ {_dl_bulk_fail} gagal",
                            state="complete", expanded=_dl_bulk_fail > 0,
                        )


            # ── #5: Reset Status Folder — multiselect (kosong = semua) ───────
            with st.expander("↩️ Reset Status Folder"):
                st.caption("Kosongkan `folder_dibuat` agar paket muncul kembali di Buat Folder (folder fisik tidak dihapus).")
                _opsi_reset_pl = {
                    f"{r.get('nama_paket','')[:60]} — {r.get('jenis_pl','')}": r.get("kode_paket")
                    for r in _pl_rows if r.get("folder_dibuat") and r.get("kode_paket")
                }
                if _opsi_reset_pl:
                    from config import sb as _sb_reset
                    _pilih_reset_pl = st.multiselect(
                        "Pilih paket reset (kosong = semua):",
                        list(_opsi_reset_pl.keys()),
                        key="pl_ms_reset",
                    )
                    if st.button("↩️ Reset Status Folder", type="secondary", key="pl_btn_reset_folder"):
                        # Jika kosong → reset semua; jika ada pilihan → reset pilihan saja
                        _target_reset = _pilih_reset_pl if _pilih_reset_pl else list(_opsi_reset_pl.keys())
                        _reset_ok_pl = 0
                        for _kr in [_opsi_reset_pl[k] for k in _target_reset]:
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
                            # Scrape HPS → tulis langsung ke Excel
                            if _pl_kp_b:
                                try:
                                    import hps_engine as _pl_hps_eng
                                    _xl_plb = _cari_xlsm_pl(_pl_target_b)
                                    if _xl_plb:
                                        _pl_hps_res = _pl_hps_eng.scrape_hps_pl_ke_excel(_pl_kp_b, _xl_plb)
                                        if _pl_hps_res.get("ok"):
                                            _pl_paket_log.append(f"📊 HPS: {_pl_hps_res.get('count', 0)} baris → Excel")
                                        else:
                                            _pl_paket_log.append(f"⚠ HPS: {_pl_hps_res.get('pesan','-')}")
                                    else:
                                        _pl_paket_log.append("⚠ HPS dilewati — tidak ada .xlsm")
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

            # ── Refresh Template ke Folder PL Existing ────────────────────────
            st.divider()
            with st.expander("🔄 Refresh Template ke Folder PL Existing"):
                st.caption("Copy file template terbaru ke folder paket yang sudah dibuat (tanpa download ulang SPSE).")
                from refresh_template import refresh_template_paket as _rt_refresh
                from pathlib import Path as _rt_Path

                # Scan folder fisik (folder_dibuat di Supabase = True boolean, bukan nama folder)
                _rt_scan_jkk = [
                    ("JKK", p) for p in _rt_Path(_PL_DIR_JKK).iterdir()
                    if p.is_dir()
                ] if _rt_Path(_PL_DIR_JKK).exists() else []
                _rt_scan_pk = [
                    ("PK", p) for p in _rt_Path(_PL_DIR_PK).iterdir()
                    if p.is_dir()
                ] if _rt_Path(_PL_DIR_PK).exists() else []
                _rt_semua_folder = _rt_scan_jkk + _rt_scan_pk

                if not _rt_semua_folder:
                    st.info("Belum ada folder paket PL di output directory.")
                else:
                    _rt_opsi_pl = {
                        f"{p.name} ({jenis})": (jenis, p)
                        for jenis, p in _rt_semua_folder
                    }
                    _rt_all_pl = st.checkbox("Pilih Semua", key="rt_all_pl")
                    _rt_pilih_pl = st.multiselect(
                        "Pilih paket PL:",
                        list(_rt_opsi_pl.keys()),
                        default=list(_rt_opsi_pl.keys()) if _rt_all_pl else [],
                        key="rt_ms_pl",
                    )
                    _rt_dry_pl = st.checkbox("Dry-run (preview saja, tidak ada perubahan)", value=True, key="rt_dry_pl")
                    _rt_relink_pl = True  # Selalu relink Word → Excel setelah copy template

                    if _rt_pilih_pl and st.button(
                        f"🔄 Refresh Template PL ke {len(_rt_pilih_pl)} Paket",
                        type="primary",
                        key="rt_btn_pl",
                    ):
                        _rt_folder_pl = []
                        for _rt_k in _rt_pilih_pl:
                            _rt_jenis, _rt_full = _rt_opsi_pl[_rt_k]
                            _rt_folder_pl.append((_rt_jenis, _rt_full))

                        _rt_ok_pl, _rt_fail_pl = 0, 0
                        _rt_log_container = st.container(border=True)
                        for _rt_jenis_f, _rt_fld in _rt_folder_pl:
                            _rt_mode = "pl_jkk" if _rt_jenis_f == "JKK" else "pl_pk"
                            _rt_src   = _rt_Path(_TEMPLATE_DIR_PL if _rt_jenis_f == "JKK" else _TEMPLATE_DIR_PL_PK)
                            _rt_res   = _rt_refresh(
                                [_rt_fld], _rt_src, _rt_mode,
                                auto_relink=_rt_relink_pl, dry_run=_rt_dry_pl,
                            )
                            for _rt_fk, _rt_logs in _rt_res.items():
                                _ok_f = all("❌" not in l for l in _rt_logs)
                                if _ok_f:
                                    _rt_ok_pl += 1
                                else:
                                    _rt_fail_pl += 1
                                _rt_log_container.markdown(f"**{_rt_Path(_rt_fk).name[:60]}**")
                                for _l in _rt_logs:
                                    _rt_log_container.caption(_l)
                        _rt_label = f"✅ {_rt_ok_pl} OK, ❌ {_rt_fail_pl} gagal"
                        if _rt_dry_pl:
                            _rt_label = "[DRY-RUN] " + _rt_label
                        if _rt_fail_pl == 0:
                            st.success(_rt_label)
                        else:
                            st.warning(_rt_label)

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
                            _ku_lamp = _kp.get("kode_unik") or _kp["kode_paket"]
                            _lamp_nama  = f"undangan_reviu_{_ku_lamp}.pdf"
                            if _lamp_bytes:
                                st.session_state.setdefault("_kd_pdf_cache", {})[_ku_lamp] = (_lamp_nama, _lamp_bytes)

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
                        # Tombol download per PDF
                        for _ku_dl, (_nm_dl, _by_dl) in st.session_state.get("_kd_pdf_cache", {}).items():
                            st.download_button(
                                f"⬇️ Download {_nm_dl}",
                                data=_by_dl,
                                file_name=_nm_dl,
                                mime="application/pdf",
                                key=f"kd_dl_{_ku_dl}",
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
                # Tanggal BA — di atas daftar paket
                _ba_pl_tgl = st.date_input(
                    "Tanggal BA Reviu",
                    value=datetime.now().date(),
                    key="plba_tgl",
                    format="DD/MM/YYYY",
                )
                st.caption(f"{_HARI_NAMA[_ba_pl_tgl.weekday()]}, {_ba_pl_tgl.day} {_BULAN_NAMA[_ba_pl_tgl.month-1]} {_ba_pl_tgl.year}")

                def _do_upload_ba_pl(paket_list, tgl):
                    hasil = []
                    prog = st.progress(0, text="Memulai upload...")
                    for _i, _p in enumerate(paket_list):
                        prog.progress(
                            (_i + 1) / len(paket_list),
                            text=f"Upload {_p['kode_paket']} ({_i+1}/{len(paket_list)})...",
                        )
                        _res = _ubrpl.upload_ba_reviu_pl(
                            kode_paket=_p["kode_paket"],
                            file_bytes=_p["_ba_file"].getvalue(),
                            file_name=_p["_ba_file"].name,
                            tgl_ba=tgl.strftime("%d-%m-%Y"),
                        )
                        hasil.append({
                            "kode":   _p["kode_paket"],
                            "nama":   _p["nama_paket"][:50],
                            "sukses": _res["ok"],
                            "pesan":  f"HTTP {_res.get('status','?')}" if _res["ok"] else _res.get("error", "?"),
                        })
                    prog.empty()
                    _ok = sum(1 for h in hasil if h["sukses"])
                    _fail = len(hasil) - _ok
                    if _fail == 0:
                        st.success(f"✅ {_ok} BA Reviu berhasil diupload!")
                    else:
                        st.warning(f"⚠️ {_ok} berhasil, {_fail} gagal.")
                    st.dataframe(hasil, use_container_width=True, hide_index=True)

                # Centang Semua / Hapus Semua
                _ba_col_sel, _ba_col_clr, _ = st.columns([1, 1, 4])
                with _ba_col_sel:
                    if st.button("☑️ Centang Semua", key="plba_sel_all", use_container_width=True):
                        for _pp2 in _pl_rows_ba:
                            st.session_state[f"plba_chk_{_pp2['kode_paket']}"] = True
                        st.rerun()
                with _ba_col_clr:
                    if st.button("🔲 Hapus Semua", key="plba_clr_all", use_container_width=True):
                        for _pp2 in _pl_rows_ba:
                            st.session_state[f"plba_chk_{_pp2['kode_paket']}"] = False
                        st.rerun()

                # Daftar paket — per baris: checkbox + file uploader + tombol upload per paket
                _ba_pl_selected = []
                for _pp in _pl_rows_ba:
                    _ba_key  = f"plba_chk_{_pp['kode_paket']}"
                    _ba_fkey = f"plba_file_{_pp['kode_paket']}"
                    _bcol_chk, _bcol_file, _bcol_btn = st.columns([3, 3, 1])
                    with _bcol_chk:
                        _ba_chk = st.checkbox(
                            f"**{_pp['kode_paket']}** — {_pp['nama_paket'][:40]}",
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
                    with _bcol_btn:
                        if _ba_up and st.button("📤", key=f"plba_up1_{_pp['kode_paket']}", help="Upload paket ini"):
                            _do_upload_ba_pl([{**_pp, "_ba_file": _ba_up}], _ba_pl_tgl)
                    if _ba_chk:
                        _ba_pl_selected.append({**_pp, "_ba_file": _ba_up})

                # Tombol upload semua yang sudah centang + ada file
                _ba_pl_valid = [_p for _p in _ba_pl_selected if _p.get("_ba_file")]
                if st.button(
                    f"📤 Upload Semua BA Reviu ({len(_ba_pl_valid)} file)",
                    key="plba_upload",
                    type="primary",
                    disabled=len(_ba_pl_valid) == 0,
                    use_container_width=True,
                ):
                    _do_upload_ba_pl(_ba_pl_valid, _ba_pl_tgl)

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
                            # Simpan tgl ke Supabase + push GCal
                            if _sub["ok"]:
                                try:
                                    _jad = _r["jadwal_list"]
                                    pl_engine.simpan_paket_pl({
                                        "kode_paket":            _p["kode_paket"],
                                        "tgl_batas_penawaran":   _jad[0]["selesai"].strftime("%Y-%m-%d"),
                                        "tgl_buka_penawaran":    _jad[1]["mulai"].strftime("%Y-%m-%d"),
                                        "tgl_evaluasi":          _jad[2]["selesai"].strftime("%Y-%m-%d"),
                                        "tgl_negosiasi":         _jad[3]["mulai"].strftime("%Y-%m-%d"),
                                        "tgl_penetapan":         _jad[4]["mulai"].strftime("%Y-%m-%d"),
                                    })
                                except Exception:
                                    pass
                                try:
                                    import gcal_pl_helper as _gcalpl
                                    _gcalpl.push_jadwal_pl_ke_gcal(_kp, _p["nama_paket"], _r["jadwal_list"])
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

        st.divider()
        st.markdown("#### 🔄 Sync Jadwal ke Google Calendar")
        st.caption("Baca jadwal aktual dari SPSE → update GCal + Supabase tgl_evaluasi/tgl_negosiasi/tgl_penetapan. Jalankan setelah ada perubahan jadwal di SPSE.")
        _gcalpl_col1, _gcalpl_col2 = st.columns([2, 3])
        with _gcalpl_col1:
            _sync_gcal_pl_btn = st.button("🔄 Sync GCal PL", key="sync_gcal_pl_btn", use_container_width=True, type="primary")
        if _sync_gcal_pl_btn:
            import gcal_pl_helper as _gcalpl
            _gcalpl_prog = st.progress(0.0, text="Memulai sync...")
            _gcalpl_results = _gcalpl.sync_semua_paket_pl(
                progress_cb=lambda f, m: _gcalpl_prog.progress(f, text=m)
            )
            _gcalpl_prog.empty()
            _gcalpl_ok = sum(1 for r in _gcalpl_results if r["ok"])
            _gcalpl_skip = sum(1 for r in _gcalpl_results if not r["ok"] and "kosong" in r.get("error", ""))
            _gcalpl_err = len(_gcalpl_results) - _gcalpl_ok - _gcalpl_skip
            if _gcalpl_err == 0:
                st.success(f"✅ {_gcalpl_ok} paket sync OK, {_gcalpl_skip} skip (jadwal belum diisi SPSE).")
            else:
                st.warning(f"⚠️ {_gcalpl_ok} OK, {_gcalpl_skip} skip, {_gcalpl_err} error.")
            _gcalpl_display = [
                {
                    "Paket": r["nama_paket"],
                    "Status": "✅" if r["ok"] else ("⏭ Skip" if "kosong" in r.get("error","") else "❌"),
                    "GCal +": r["gcal_inserted"],
                    "GCal -": r["gcal_deleted"],
                    "Tgl Evaluasi": r["tgl_evaluasi"],
                    "Tgl Negosiasi": r["tgl_negosiasi"],
                    "Tgl Penetapan": r["tgl_penetapan"],
                    "Error": r["error"][:60] if r["error"] else "",
                }
                for r in _gcalpl_results
            ]
            st.dataframe(_gcalpl_display, use_container_width=True, hide_index=True)

    # ── Tab 4: Setup Paket PL (LDK + Masa Berlaku + Checklist + Upload Dokpil) ─
    with _pl_tab4:
        st.markdown("### Setup Paket Pengadaan Langsung")
        st.caption(
            "Submit LDK (Persyaratan Kualifikasi) + Masa Berlaku Penawaran + "
            "Checklist Dokumen Penawaran + Upload Dokumen Pemilihan (Dokpil PDF) ke SPSE. "
            "KAK / Rancangan Kontrak / Uraian Singkat / Informasi Lainnya tugas PPK (bukan PP)."
        )

        import dokpil_engine_plpk as _depl
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
                            # Tanggal: dari DB (tgl_dokpil) → fallback session → hari ini
                            _tgl_db = _rr.get("tgl_dokpil")
                            if _tgl_db:
                                try:
                                    from datetime import date as _date
                                    _tgl_prev = _date.fromisoformat(str(_tgl_db))
                                except Exception:
                                    _tgl_prev = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            else:
                                _tgl_prev = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            # Nomor: dari DB → fallback generate
                            _no_prev = _rr.get("nomor_dokpil") or _udpl.generate_nomor_dokpil(
                                nama_paket=_rr["nama_paket"],
                                kode_unik=_ku_prev,
                                skpd_singkat=_sk_prev,
                                tahun=_tgl_prev.year,
                            )
                            st.caption(f"📄 {_dokpil_up.name}  \n📋 `{_no_prev}`  \n📅 {_tgl_prev.strftime('%d-%m-%Y')}")
                            if st.button("📤 Upload Dokpil", key=f"plsp_upload_only_{_kp_key}", use_container_width=True):
                                with st.spinner("Mengupload dokpil..."):
                                    try:
                                        _r_up_only = _udpl.upload_dokpil_pl(
                                            kode_paket=_kp_key,
                                            file_bytes=_dokpil_up.getvalue(),
                                            file_name=_dokpil_up.name,
                                            nomor_dokpil=_no_prev,
                                            tgl_dokpil=_tgl_prev.strftime("%d-%m-%Y"),
                                        )
                                        if _r_up_only["ok"]:
                                            from config import sb as _sb_up_only
                                            _sb_up_only().table("draft_paket_pl").update({
                                                "nomor_dokpil": _no_prev,
                                            }).eq("kode_paket", _kp_key).execute()
                                            st.success(f"✅ Upload berhasil — {_no_prev}")
                                        else:
                                            st.error(f"❌ HTTP {_r_up_only.get('status','?')} — {_r_up_only.get('error') or _r_up_only.get('body','')[:300]}")
                                            st.json(_r_up_only)
                                    except Exception as _e_up_only:
                                        st.error(f"❌ Exception: {_e_up_only}")

                    if _chk:
                        _plsp_selected.append({
                            **_rr,
                            "_dokpil_file": _dokpil_up,
                        })

                st.caption(f"**{len(_plsp_selected)}** dari **{len(_plsp_rows)}** paket dipilih")

                # Kumpulkan semua paket yang sudah ada file dokpil
                _all_with_file = [
                    {**_rr, "_dokpil_file": st.session_state.get(f"plsp_dokpil_{_rr['kode_paket']}")}
                    for _rr in _plsp_rows
                    if st.session_state.get(f"plsp_dokpil_{_rr['kode_paket']}")
                ]
                if _all_with_file:
                    st.divider()
                    if st.button(f"📤 Upload Semua Dokpil ({len(_all_with_file)} file)", key="plsp_upload_all_dokpil", use_container_width=True, type="primary"):
                        from config import sb as _sb_upall
                        _cl_upall = _sb_upall()
                        for _rr_up in _all_with_file:
                            _kp_up = _rr_up["kode_paket"]
                            _f_up = _rr_up["_dokpil_file"]
                            _ku_up = _rr_up.get("kode_unik") or "?"
                            _sk_up = _lookup_singkatan_dinas(_rr_up.get("satker", ""))
                            # Tanggal dari DB, fallback session
                            _tgl_db_up = _rr_up.get("tgl_dokpil")
                            if _tgl_db_up:
                                try:
                                    from datetime import date as _date2
                                    _tgl_up = _date2.fromisoformat(str(_tgl_db_up))
                                except Exception:
                                    _tgl_up = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            else:
                                _tgl_up = st.session_state.get("plsp_tgl_dokpil") or datetime.now().date()
                            # Nomor dari DB, fallback generate
                            _no_up = _rr_up.get("nomor_dokpil") or _udpl.generate_nomor_dokpil(
                                nama_paket=_rr_up["nama_paket"],
                                kode_unik=_ku_up,
                                skpd_singkat=_sk_up,
                                tahun=_tgl_up.year,
                            )
                            try:
                                _r_upall = _udpl.upload_dokpil_pl(
                                    kode_paket=_kp_up,
                                    file_bytes=_f_up.getvalue(),
                                    file_name=_f_up.name,
                                    nomor_dokpil=_no_up,
                                    tgl_dokpil=_tgl_up.strftime("%d-%m-%Y"),
                                )
                                if _r_upall["ok"]:
                                    _cl_upall.table("draft_paket_pl").update({"nomor_dokpil": _no_up}).eq("kode_paket", _kp_up).execute()
                                    st.success(f"✅ {_rr_up['nama_paket'][:40]} — {_no_up}")
                                else:
                                    st.error(f"❌ {_rr_up['nama_paket'][:40]} HTTP {_r_upall.get('status','?')} — {_r_upall.get('body','')[:100]}")
                            except Exception as _e_upall:
                                st.error(f"❌ {_rr_up['nama_paket'][:40]}: {_e_upall}")

            with _plsp_col_kanan:
                st.markdown("### 2. Konfigurasi Setup Paket")

                if not _plsp_selected:
                    st.info("Pilih paket di sebelah kiri.")
                else:
                    # ── SEKSI 1: SBU Global ───────────────────────────────────
                    st.markdown("#### 🏗️ Seksi 1 — SBU Global")
                    st.caption("Satu pilihan SBU apply ke semua paket terpilih.")

                    _plsp_klas_list = ["(auto-detect dari paket pertama)"] + _sp.list_klasifikasi()

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

                    _g_lama_options = _sp.list_sbu_lama_padanan(_g_picked_baru_kode) if _g_picked_baru_kode else []
                    _g_lama_labels = ["(tidak dipersyaratkan / hanya SBU 2020)"] + [
                        f"{l['kode']} — {(l.get('nama_singkat') or l.get('nama_full',''))[:70]}"
                        for l in _g_lama_options
                    ]
                    _g_lama_default = 0
                    for _gli, _gl in enumerate(_g_lama_options):
                        if _gl.get("kode") == _g_kode_lama:
                            _g_lama_default = _gli + 1
                            break
                    _g_picked_lama_label = st.selectbox(
                        "SBU Lama (KBLI 2017) — opsional",
                        _g_lama_labels,
                        index=_g_lama_default,
                        key="plsp_global_sbu_lama",
                    )
                    _g_picked_lama_kode = (
                        _g_picked_lama_label.split(" — ", 1)[0]
                        if " — " in _g_picked_lama_label else ""
                    )

                    _sbu_baru_global = ""
                    _sbu_lama_global = ""
                    if _g_picked_baru_kode:
                        _baru_obj_g = _sp.get_sbu_baru_by_kode(_g_picked_baru_kode)
                        _sbu_baru_global = (_baru_obj_g or {}).get("nama_full", "")
                    if _g_picked_lama_kode:
                        _lama_obj_g = _sp.get_sbu_lama_by_kode(_g_picked_lama_kode)
                        _sbu_lama_global = (_lama_obj_g or {}).get("nama_full", "")
                    if not _sbu_baru_global:
                        _sbu_baru_global = _first_p.get("sbu_baru") or ""

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

                    # ── SEKSI 2: Tanggal Dokpil & Masa Berlaku ────────────────
                    st.markdown("#### 📅 Seksi 2 — Tanggal Dokpil & Masa Berlaku Penawaran")

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

                    _ldk_masa_berlaku = st.number_input(
                        "Masa Berlaku Penawaran (hari)",
                        min_value=1, max_value=180, value=30,
                        key="plsp_masa_berlaku",
                    )

                    if st.button("💾 Submit Masa Berlaku", key="plsp_btn_masa_berlaku", use_container_width=True):
                        from config import sb as _sb_factory_mb
                        _client_mb = _sb_factory_mb()
                        for _p in _plsp_selected:
                            # Simpan tgl_dokpil ke Supabase agar Isi Data PL bisa baca
                            try:
                                _client_mb.table("draft_paket_pl").update({
                                    "tgl_dokpil": _plsp_tgl_dokpil.isoformat(),
                                }).eq("kode_paket", _p["kode_paket"]).execute()
                            except Exception as _e_mb:
                                st.warning(f"⚠️ Gagal simpan tgl_dokpil {_p['nama_paket'][:30]}: {_e_mb}")
                            _r_mb = _depl.submit_masa_berlaku_pl(_p["kode_paket"], int(_ldk_masa_berlaku))
                            st.write(f"{'✅' if _r_mb['ok'] else '❌'} {_p['nama_paket'][:40]} — HTTP {_r_mb['status']}")

                    st.divider()

                    # ── SEKSI 3: Dokumen Kualifikasi (LDK) ───────────────────
                    st.markdown("#### 📋 Seksi 3 — Dokumen Kualifikasi (LDK)")
                    st.caption("ℹ️ Di-submit ke SPSE bagian Persyaratan Kualifikasi (LDK).")

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

                    if st.button("📋 Submit Dokumen Kualifikasi (LDK)", key="plsp_btn_ldk", use_container_width=True):
                        from config import sb as _sb_factory_ldk
                        _client_ldk = _sb_factory_ldk()
                        for _p in _plsp_selected:
                            try:
                                _client_ldk.table("draft_paket_pl").update({
                                    "sbu_baru": _sbu_baru_global,
                                    "sbu_lama": _sbu_lama_global,
                                }).eq("kode_paket", _p["kode_paket"]).execute()
                            except Exception:
                                pass
                            _r_ldk = _depl.submit_ldk_pl(
                                _p["kode_paket"],
                                sbu_baru=_sbu_baru_global,
                                sbu_lama=_sbu_lama_global,
                                centang_admin_indices=_ldk_centang_admin_indices,
                                teknis_centang_indices=_ldk_teknis_indices,
                                kinerja_text=_ldk_kinerja_text,
                            )
                            st.write(f"{'✅' if _r_ldk['ok'] else '❌'} {_p['nama_paket'][:40]} — HTTP {_r_ldk['status']}")

                    st.divider()

                    # ── SEKSI 4: Dokumen Penawaran (Checklist) ────────────────
                    st.markdown("#### 📝 Seksi 4 — Dokumen Penawaran (Checklist)")
                    st.caption("ℹ️ Centang sesuai dokumen penawaran yang diminta ke peserta. Di-submit ke SPSE bagian Checklist Dokumen Penawaran.")

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

                    if st.button("📝 Submit Dokumen Penawaran (Checklist)", key="plsp_btn_checklist", use_container_width=True):
                        for _p in _plsp_selected:
                            _r_cd = _depl.submit_checklist_pl(
                                _p["kode_paket"],
                                centang_admin_all=_cd_centang_admin,
                                centang_syarat_all=_cd_centang_syarat,
                                centang_harga_all=_cd_centang_harga,
                            )
                            st.write(f"{'✅' if _r_cd['ok'] else '❌'} {_p['nama_paket'][:40]} — HTTP {_r_cd['status']}")

                    st.divider()
                    st.caption("⬇️ Atau jalankan semua seksi sekaligus:")

                    # ── Submit All-in-One ─────────────────────────────────────
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

    # ── Tab 7: Kirim Verifikasi Penyedia ─────────────────────────────────────
    with _pl_tab7:
        import verifikasi_penyedia_pl as _verif_pl
        from gcal_helper import get_jadwal_klarifikasi_pl as _gcal_klarifikasi

        st.markdown("## 📨 Kirim Undangan Verifikasi Penyedia")
        st.caption("Kirim undangan pembuktian kualifikasi ke penyedia via SPSE non-tender.")

        # Dropdown paket — gabung draft_pl + aktif_pl (dedup by id_nontender)
        _verif_rows = []
        try:
            _verif_rows = pl_engine._sb().table("draft_paket_pl").select(
                "kode_paket, id_nontender, nama_paket, kode_unik, nama_penyedia, npwp_penyedia, tgl_negosiasi, tgl_undangan_verifikasi, status_undangan_verifikasi"
            ).order("kode_paket").execute().data or []
        except Exception as _ev_err:
            st.error(f"Gagal load paket PL: {_ev_err}")

        # ── Monitoring Pendaftaran Peserta (semua paket) ──────────────────────
        with st.expander("📊 Monitoring Pendaftaran Peserta — Semua Paket", expanded=False):
            import peserta_monitor_pl as _pm_pl
            _mon_col1, _mon_col2 = st.columns([6, 1])
            _mon_col1.caption("Jumlah peserta yang sudah mendaftar per paket (data publik SPSE).")
            if _mon_col2.button("🔄 Refresh", key="btn_refresh_peserta_pl"):
                st.cache_data.clear()
            if _verif_rows:
                _mon_kodes = [r["kode_paket"] for r in _verif_rows if r.get("kode_paket")]
                with st.spinner("Mengambil data pendaftaran..."):
                    _mon_hasil = _pm_pl.fetch_status_semua_paket(_mon_kodes)
                # Hitung summary
                _mon_belum = [r for r in _verif_rows if _mon_hasil.get(r["kode_paket"], {}).get("jumlah", 0) == 0]
                _mon_sudah = [r for r in _verif_rows if _mon_hasil.get(r["kode_paket"], {}).get("jumlah", 0) > 0]
                _mc1, _mc2 = st.columns(2)
                _mc1.metric("✅ Sudah Ada Peserta", len(_mon_sudah))
                _mc2.metric("⚠️ Belum Ada Peserta", len(_mon_belum))
                if _mon_belum:
                    st.warning("⚠️ Paket berikut belum ada peserta mendaftar — pertimbangkan perpanjangan jadwal:")
                    for _br in _mon_belum:
                        st.write(f"- **{_br.get('kode_unik') or _br['kode_paket']}** — {_br['nama_paket']}")
                # Tabel lengkap
                _mon_data = []
                for r in _verif_rows:
                    _kp = r["kode_paket"]
                    _info = _mon_hasil.get(_kp, {})
                    _jml = _info.get("jumlah", 0)
                    _mon_data.append({
                        "Paket": r.get("kode_unik") or _kp,
                        "Nama Paket": r["nama_paket"][:45],
                        "Peserta Daftar": _jml,
                        "Status": "✅ Ada" if _jml > 0 else "⚠️ Belum",
                    })
                st.dataframe(_mon_data, use_container_width=True, hide_index=True)
            else:
                st.info("Belum ada paket PL di database.")

        if not _verif_rows:
            st.info("Belum ada paket PL di database.")
        else:
            _verif_opts = {
                f"{r['kode_unik'] or r['kode_paket']} — {r['nama_paket'][:50]}": r
                for r in _verif_rows if r.get("id_nontender")
            }
            _verif_sel_label = st.selectbox(
                "Pilih Paket PL",
                options=list(_verif_opts.keys()),
                key="verif_paket_sel",
            )
            _verif_paket = _verif_opts.get(_verif_sel_label)

            if _verif_paket:
                _verif_id_nt = _verif_paket.get("id_nontender", "")
                _verif_kode = _verif_paket.get("kode_paket", "")

                # Info penyedia
                st.markdown("#### 🏢 Info Penyedia")
                _vc1, _vc2 = st.columns(2)
                _vc1.markdown(f"**Nama:** {_verif_paket.get('nama_penyedia') or '—'}")
                _vc2.markdown(f"**NPWP:** {_verif_paket.get('npwp_penyedia') or '—'}")

                # Debug GCal — expander tersembunyi
                with st.expander("🔍 Debug GCal Search", expanded=False):
                    try:
                        from gcal_helper import _build_service as _gcal_svc
                        from datetime import datetime as _dt_gcal, timedelta as _td_gcal, date as _d_gcal
                        _svc = _gcal_svc()
                        _now = _d_gcal.today()
                        _tmin = (_now - _td_gcal(days=60)).isoformat() + "T00:00:00Z"
                        _tmax = (_now + _td_gcal(days=120)).isoformat() + "T23:59:59Z"
                        _gevents = _svc.events().list(
                            calendarId="primary",
                            timeMin=_tmin, timeMax=_tmax,
                            maxResults=100, singleEvents=True,
                            q="Klarifikasi",
                        ).execute().get("items", [])
                        st.write(f"**Mencari kode_nontender:** `{_verif_kode}`")
                        st.write(f"**Event GCal mengandung 'Klarifikasi' ({len(_gevents)} event):**")
                        for _ge in _gevents:
                            _gs = _ge.get("start", {}).get("date") or _ge.get("start", {}).get("dateTime", "")[:10]
                            _gdesc = (_ge.get("description") or "").replace("\n", " ")[:100]
                            _match = "✅ MATCH" if _verif_kode in (_ge.get("description") or "") else ""
                            st.write(f"- `{_gs}` **{_ge.get('summary','')}** | desc: {_gdesc} {_match}")
                        if not _gevents:
                            st.warning("Tidak ada event GCal mengandung 'Klarifikasi' di rentang ±60-120 hari")
                    except Exception as _dbg_err:
                        st.error(f"Debug GCal error: {_dbg_err}")

                # Hitung waktu verifikasi dari GCal
                st.markdown("#### 🕐 Waktu Verifikasi")
                _tgl_nego_raw = _verif_paket.get("tgl_negosiasi")
                _fallback_tgl = None
                if _tgl_nego_raw:
                    try:
                        from datetime import date as _date_cls
                        _fallback_tgl = _date_cls.fromisoformat(str(_tgl_nego_raw)[:10])
                    except Exception:
                        pass

                _verif_start_default = ""
                _verif_end_default = ""
                _verif_warning = None
                try:
                    _verif_start_default, _verif_end_default, _verif_warning = (
                        _verif_pl.hitung_waktu_verifikasi(_verif_kode, fallback_tgl=_fallback_tgl)
                    )
                except Exception as _wt_err:
                    _verif_warning = f"Error hitung waktu: {_wt_err}"

                if _verif_warning:
                    st.warning(_verif_warning)
                    if "invalid_grant" in str(_verif_warning) or "expired" in str(_verif_warning).lower() or "tidak ditemukan" in str(_verif_warning):
                        if st.button("🔑 Login Google Calendar", key="btn_reset_gcal_token"):
                            try:
                                import gcal_helper as _gcalh
                                _gcalh.generate_token()
                                st.success("✅ Token GCal berhasil dibuat. Refresh halaman.")
                                st.rerun()
                            except Exception as _ge:
                                st.error(f"Gagal generate token: {_ge}")

                _vt1, _vt2 = st.columns(2)
                _verif_start = _vt1.text_input(
                    "Mulai (DD-MM-YYYY HH:MM)",
                    value=_verif_start_default or "",
                    key="verif_waktu_start",
                    placeholder="02-06-2026 09:00",
                )
                _verif_end = _vt2.text_input(
                    "Selesai (DD-MM-YYYY HH:MM)",
                    value=_verif_end_default or "",
                    key="verif_waktu_end",
                    placeholder="02-06-2026 15:00",
                )

                # Form fields
                st.markdown("#### 📋 Detail Undangan")
                _verif_tempat = st.text_area(
                    "Tempat",
                    value=_verif_pl.TEMPAT_DEFAULT,
                    height=80,
                    key="verif_tempat",
                )
                # Tombol kirim
                if st.button("📨 Kirim Verifikasi ke Penyedia", key="btn_kirim_verifikasi"):
                    if not _verif_id_nt:
                        st.error("id_nontender kosong — sinkron paket PL dari SPSE dulu.")
                    elif not _verif_start or not _verif_end:
                        st.error("Waktu mulai dan selesai wajib diisi.")
                    else:
                        with st.spinner("Mengirim undangan verifikasi ke SPSE..."):
                            _verif_result = _verif_pl.kirim_verifikasi(
                                id_nontender=_verif_id_nt,
                                waktu_start=_verif_start,
                                waktu_end=_verif_end,
                                tempat=_verif_tempat,
                                yang_harus_hadir=_verif_pl.YANG_HARUS_HADIR_DEFAULT,
                                yang_harus_dibawa=_verif_pl.YANG_HARUS_DIBAWA_DEFAULT,
                            )
                        if _verif_result["ok"]:
                            st.success(f"✅ {_verif_result['msg']}")
                        else:
                            st.error(f"❌ Gagal: {_verif_result['msg']}")

        # ── Kirim Batch ke Semua Paket ───────────────────────────────────────
        st.divider()
        st.markdown("### 📨 Kirim Undangan Verifikasi — Batch (Semua Paket)")
        st.caption("Centang paket yang ingin dikirim sekaligus. Hanya paket dengan peserta terdaftar yang tampil.")

        # Load status peserta untuk filter
        _batch_rows = _verif_rows  # sudah di-load di atas
        if _batch_rows:
            # Fetch jumlah peserta semua paket
            import peserta_monitor_pl as _pm_batch
            _batch_kodes = [r["kode_paket"] for r in _batch_rows if r.get("kode_paket")]
            with st.spinner("Mengecek peserta terdaftar..."):
                _batch_mon = _pm_batch.fetch_status_semua_paket(_batch_kodes)

            # Filter hanya paket yang ada peserta
            _batch_eligible = [
                r for r in _batch_rows
                if _batch_mon.get(r["kode_paket"], {}).get("jumlah", 0) > 0
                and r.get("id_nontender")
            ]

            if not _batch_eligible:
                st.info("Belum ada paket dengan peserta terdaftar.")
            else:
                st.caption(f"{len(_batch_eligible)} paket tersedia (sudah ada peserta).")

                # Waktu — dropdown dari GCal + fallback input manual
                import datetime as _dt_bv
                _today_bv = _dt_bv.date.today()

                _bwc1, _bwc2 = st.columns(2)
                with _bwc1:
                    st.caption("**Waktu Mulai**")
                    _bv_start_d = st.date_input("Tanggal Mulai", value=_today_bv, format="DD-MM-YYYY", key="batch_verif_start_d")
                    _bv_start_t = st.time_input("Jam Mulai", value=_dt_bv.time(9, 0), step=300, key="batch_verif_start_t")
                with _bwc2:
                    st.caption("**Waktu Selesai**")
                    _bv_end_d = st.date_input("Tanggal Selesai", value=_today_bv, format="DD-MM-YYYY", key="batch_verif_end_d")
                    _bv_end_t = st.time_input("Jam Selesai", value=_dt_bv.time(15, 0), step=300, key="batch_verif_end_t")

                _batch_start = f"{_bv_start_d.strftime('%d-%m-%Y')} {_bv_start_t.strftime('%H:%M')}"
                _batch_end   = f"{_bv_end_d.strftime('%d-%m-%Y')} {_bv_end_t.strftime('%H:%M')}"

                # Checkbox list paket
                st.markdown("**Pilih paket yang akan dikirim:**")
                _sudah_kirim = [r for r in _batch_eligible if r.get("status_undangan_verifikasi") == "terkirim"]
                _belum_kirim = [r for r in _batch_eligible if r.get("status_undangan_verifikasi") != "terkirim"]
                if _sudah_kirim:
                    st.caption(f"✅ {len(_sudah_kirim)} sudah terkirim | ⏳ {len(_belum_kirim)} belum")
                _batch_selected = []
                _bc1, _bc2 = st.columns(2)
                for _bi, _br in enumerate(_batch_eligible):
                    _ku = _br.get('kode_unik') or _br['kode_paket']
                    _tgl_kirim = _br.get("tgl_undangan_verifikasi")
                    _sudah = _br.get("status_undangan_verifikasi") == "terkirim"
                    if _sudah and _tgl_kirim:
                        import datetime as _dtlb
                        try:
                            _tgl_fmt = _dtlb.datetime.fromisoformat(_tgl_kirim.replace("Z","+00:00")).strftime("%d-%m-%Y")
                        except Exception:
                            _tgl_fmt = _tgl_kirim[:10]
                        _label = f"{_ku} — {_br['nama_paket'][:35]} ✅ {_tgl_fmt}"
                    else:
                        _label = f"{_ku} — {_br['nama_paket'][:40]}"
                    _col = _bc1 if _bi % 2 == 0 else _bc2
                    _default_chk = not _sudah  # belum terkirim → default centang; sudah → default uncheck
                    if _col.checkbox(_label, value=_default_chk, key=f"batch_chk_{_br['kode_paket']}"):
                        _batch_selected.append(_br)

                st.markdown(f"**{len(_batch_selected)} paket dipilih**")

                # Tombol Preview dulu
                if st.button("👁 Preview Sebelum Kirim", key="btn_batch_preview"):
                    if not _batch_start or not _batch_end:
                        st.error("Waktu mulai dan selesai wajib diisi.")
                    elif not _batch_selected:
                        st.warning("Tidak ada paket yang dipilih.")
                    else:
                        st.session_state["batch_verif_preview"] = True

                if st.session_state.get("batch_verif_preview"):
                    st.markdown("#### 📋 Preview Pengiriman")
                    st.write(f"- **Waktu:** {_batch_start} s/d {_batch_end}")
                    st.write(f"- **Jumlah paket:** {len(_batch_selected)}")
                    for _bp in _batch_selected:
                        _jp = _batch_mon.get(_bp["kode_paket"], {}).get("jumlah", 0)
                        st.write(f"  ✅ {_bp.get('kode_unik') or _bp['kode_paket']} — {_bp['nama_paket']} ({_jp} peserta)")
                    st.write(f"- **Penyedia (referensi Supabase):** nama_penyedia per paket")

                    if st.button("📨 Konfirmasi & Kirim Semua", key="btn_batch_kirim_konfirm", type="primary"):
                        if not _batch_start or not _batch_end:
                            st.error("Waktu wajib diisi.")
                        else:
                            import verifikasi_penyedia_pl as _vpl_batch
                            _hasil_batch = []
                            _prog = st.progress(0, text="Mengirim...")
                            for _bi2, _bp2 in enumerate(_batch_selected):
                                _prog.progress((_bi2 + 1) / len(_batch_selected), text=f"Kirim ke {_bp2.get('kode_unik') or _bp2['kode_paket']}...")
                                _res = _vpl_batch.kirim_verifikasi(
                                    id_nontender=_bp2["id_nontender"],
                                    waktu_start=_batch_start,
                                    waktu_end=_batch_end,
                                )
                                _hasil_batch.append({
                                    "paket": _bp2.get("kode_unik") or _bp2["kode_paket"],
                                    "nama": _bp2["nama_paket"][:40],
                                    "ok": _res["ok"],
                                    "msg": _res["msg"],
                                })
                            _prog.empty()
                            st.session_state["batch_verif_preview"] = False

                            # Tampilkan hasil
                            _ok_list = [h for h in _hasil_batch if h["ok"]]
                            _fail_list = [h for h in _hasil_batch if not h["ok"]]
                            if _ok_list:
                                st.success(f"✅ Berhasil: {len(_ok_list)} paket")
                                for h in _ok_list:
                                    st.write(f"  ✅ {h['paket']} — {h['nama']}")
                            if _fail_list:
                                st.error(f"❌ Gagal: {len(_fail_list)} paket")
                                for h in _fail_list:
                                    st.write(f"  ❌ {h['paket']} — {h['nama']}: {h['msg']}")

    # ── Tab 8: Upload BA PL ───────────────────────────────────────────────────
    with _pl_tab8:
        import ba_engine_pl as _ba_pl_engine5
        import ba_config_pl as _ba_cfg_pl
        import os as _os8
        import re as _re8
        import datetime as _dt8

        st.markdown("## Berita Acara — Pengadaan Langsung")

        # Load paket PL sekali
        _pl8_rows = []
        try:
            _pl8_rows = pl_engine._sb().table("draft_paket_pl").select(
                "kode_paket, nama_paket, nomor_urut, kode_unik, id_nontender, "
                "nomor_dokpil, tgl_evaluasi, satker, folder_dibuat"
            ).order("nomor_urut").execute().data or []
        except Exception as _e8:
            st.error(f"Gagal load paket PL: {_e8}")

        # ── Helper auto nomor + tanggal (otomatis seperti mode tender) ───────
        def _skpd_pl8(_satker):
            if not _satker:
                return "DPUPR"
            try:
                from config import sb as _sbf8
                _r = _sbf8().table("master_dinas").select("singkatan").ilike(
                    "nama_dinas", f"%{_satker[:30]}%").limit(1).execute()
                if _r.data:
                    return _r.data[0].get("singkatan") or "DPUPR"
            except Exception:
                pass
            return "DPUPR"

        def _nomor_dokpil_pl8(_row):
            """Nomor dokpil dasar (slot /01/) — dari DB jika ada, else generate."""
            _nd = (_row.get("nomor_dokpil") or "").strip()
            if _nd:
                return _nd
            try:
                import upload_dokpil_pl as _udpl8
                return _udpl8.generate_nomor_dokpil(
                    nama_paket=_row.get("nama_paket", ""),
                    kode_unik=_row.get("kode_unik") or "",
                    skpd_singkat=_skpd_pl8(_row.get("satker", "")),
                )
            except Exception:
                return ""

        def _auto_nomor_pl8(_row, _jenis_key):
            """Derive nomor BA per jenis: ganti slot /NN/ pertama."""
            _base = _nomor_dokpil_pl8(_row)
            if not _base:
                return ""
            return ba_engine.derive_nomor_ba(_base, _ba_cfg_pl.NOMOR_URUT_PL[_jenis_key])

        def _auto_tgl_pl8(_row):
            """Tanggal BA = end Evaluasi Penawaran (tgl_evaluasi), fallback live SPSE."""
            _v = _row.get("tgl_evaluasi")
            if _v:
                try:
                    return _dt8.date.fromisoformat(str(_v)[:10])
                except Exception:
                    pass
            try:
                import gcal_pl_helper as _gph8
                _jd = _gph8.parse_jadwal_pl_dari_spse(_row.get("kode_paket", ""))
                if _jd and len(_jd) > 2:
                    return _jd[2]["selesai"].date()
            except Exception:
                pass
            return None

        def _backup_pdf_pl8(_row, _jenis_key, _pdf_bytes):
            """Simpan PDF cetak ke folder masing-masing paket. Return path atau ''."""
            _kp = _row.get("kode_paket", "")
            _dir = None
            # 1) resolver folder paket PL resmi (folder_paket root)
            try:
                import kualifikasi_engine_plpk as _kepl8
                _rf = _kepl8.resolve_folder_paket_pl(_kp)
                if _rf.get("ok"):
                    _root = _rf.get("pesan") or ""  # pesan = folder_paket root
                    if _root and _os8.path.isdir(_root):
                        _dir = _root
            except Exception:
                pass
            # 2) fallback: Asisten_Pokja_Downloads
            if not _dir:
                try:
                    from config import POKJA_ROOT as _PR8
                    _dir = _os8.path.join(_PR8, "Asisten_Pokja_Downloads", f"Cetak_BA_PL_{_kp}")
                except Exception:
                    return ""
            try:
                _os8.makedirs(_dir, exist_ok=True)
                _fn = f"{_ba_cfg_pl.FILE_LABEL_PL[_jenis_key]}-{_kp}.pdf"
                _fp = _os8.path.join(_dir, _fn)
                with open(_fp, "wb") as _fh:
                    _fh.write(_pdf_bytes)
                return _fp
            except Exception:
                return ""

        def _proses_ba_pl8(_row, _jenis_key, _nomor, _tgl):
            """Cetak → backup → upload satu BA. Return (ok: bool, pesan: str)."""
            # Endpoint cetak/upload BA nontender pakai kode_paket (BUKAN id_nontender)
            _id = _row.get("kode_paket")
            if not _nomor:
                return False, "nomor kosong"
            if not _tgl:
                return False, "tanggal kosong (Evaluasi belum dijadwal)"
            _tgls = _tgl.strftime("%d-%m-%Y")
            try:
                _rc = _ba_pl_engine5.cetak_ba_pl(
                    id_nontender=_id, jenis_key=_jenis_key,
                    nomor_ba=_nomor, tanggal_ba=_tgls,
                )
                if not _rc["ok"]:
                    return False, f"cetak gagal ({_rc.get('status')}) {_rc.get('error','')}"
                _backup_pdf_pl8(_row, _jenis_key, _rc["pdf_bytes"])
                _fn = f"{_ba_cfg_pl.FILE_LABEL_PL[_jenis_key]}-{_row.get('kode_paket','')}.pdf"
                _ru = _ba_pl_engine5.upload_ba_pl(
                    id_nontender=_id, jenis_key=_jenis_key,
                    nomor_ba=_nomor, tanggal_ba=_tgls,
                    file_bytes=_rc["pdf_bytes"], file_name=_fn,
                )
                if _ru.get("ok"):
                    return True, "OK"
                return False, f"upload gagal ({_ru.get('status')})"
            except Exception as _e:
                return False, str(_e)[:100]

        # ── SECTION 1: 2 BA AUTO (Evaluasi + Hasil) ──────────────────────────
        st.markdown("### 1. Cetak + Upload Otomatis")
        st.caption("BA Evaluasi Penawaran dan BA Hasil Non Tender dicetak langsung dari SPSE lalu di-upload kembali.")

        if not _pl8_rows:
            st.info("Tidak ada paket PL di database.")
        else:
            # Tanggal: default OTOMATIS dari tgl_evaluasi per paket (mode tender).
            _pl8_tgl_mode = st.radio(
                "Mode Tanggal",
                ["Otomatis (tgl Evaluasi per paket)", "Satu tanggal semua manual"],
                horizontal=True, key="pl8_tgl_mode",
            )
            _pl8_tgl_global = None
            if _pl8_tgl_mode == "Satu tanggal semua manual":
                _pl8_tgl_global = st.date_input(
                    "Tanggal BA (semua paket)", value=datetime.now().date(),
                    format="DD/MM/YYYY", key="pl8_tgl_global",
                )
                st.caption(f"{_HARI_NAMA[_pl8_tgl_global.weekday()]}, {_pl8_tgl_global.day} "
                           f"{_BULAN_NAMA[_pl8_tgl_global.month-1]} {_pl8_tgl_global.year}")
            else:
                st.caption("Tanggal otomatis = hari terakhir Evaluasi Penawaran (dari jadwal). "
                           "Nomor BA auto-derive dari Nomor Dokpil.")

            # ── Tombol BULK: cetak+upload SEMUA paket × 2 BA tanpa centang ──
            if st.button(
                f"🚀🚀 Cetak + Upload SEMUA Paket ({len(_pl8_rows)} paket × 2 BA)",
                type="primary", key="pl8_bulk_all_paket", use_container_width=True,
            ):
                with st.status(f"Proses {len(_pl8_rows)} paket × 2 BA...", expanded=True) as _stb8:
                    _ok_total, _gagal_total = 0, 0
                    for _pbulk in _pl8_rows:
                        _kb = _pbulk.get("kode_paket", "")
                        _tgl_b = _pl8_tgl_global if _pl8_tgl_mode == "Satu tanggal semua manual" else _auto_tgl_pl8(_pbulk)
                        _stb8.write(f"**{_pbulk.get('nomor_urut') or ''}. {_kb}**")
                        for _jkb, _lblb in [("evaluasi", "Evaluasi"), ("hasil", "Hasil")]:
                            _nob = _auto_nomor_pl8(_pbulk, _jkb)
                            _okb, _pesb = _proses_ba_pl8(_pbulk, _jkb, _nob, _tgl_b)
                            if _okb:
                                _stb8.write(f"  ✅ BA {_lblb}")
                                _ok_total += 1
                            else:
                                _stb8.write(f"  ❌ BA {_lblb} — {_pesb}")
                                _gagal_total += 1
                    _stb8.update(
                        label=f"Selesai — {_ok_total} BA OK, {_gagal_total} gagal.",
                        state="complete" if _gagal_total == 0 else "error",
                    )

            st.divider()

            # Header tabel per paket
            _pl8_valid_auto = []  # untuk batch
            for _p8 in _pl8_rows:
                _k8    = _p8.get("kode_paket", "")
                _id8   = _k8  # BA nontender pakai kode_paket
                _label8 = f"**{_p8.get('nomor_urut') or ''}. {_p8.get('nama_paket','')[:60]}**"
                with st.container(border=True):
                    st.markdown(_label8)
                    st.caption(f"kode paket: `{_k8}`")

                    # Tanggal per paket: OTOMATIS dari tgl_evaluasi (atau manual global)
                    if _pl8_tgl_mode == "Satu tanggal semua manual":
                        _tgl8 = _pl8_tgl_global
                    else:
                        _tgl8 = _auto_tgl_pl8(_p8)

                    if _tgl8:
                        st.caption(f"📅 {_HARI_NAMA[_tgl8.weekday()]}, {_tgl8.day} "
                                   f"{_BULAN_NAMA[_tgl8.month-1]} {_tgl8.year}")
                    else:
                        st.caption("⚠️ Tanggal Evaluasi belum ada — isi jadwal dulu atau pakai mode manual.")

                    # Nomor per jenis BA: default OTOMATIS dari Nomor Dokpil (bisa diedit)
                    _auto_ev = _auto_nomor_pl8(_p8, "evaluasi")
                    _auto_hs = _auto_nomor_pl8(_p8, "hasil")
                    _c8ev, _c8hs = st.columns(2)
                    with _c8ev:
                        st.markdown(f"**{_ba_cfg_pl.JENIS_LABEL_PL['evaluasi']}**")
                        _no8ev = st.text_input(
                            "Nomor", value=_auto_ev, placeholder="000.3.3/05/PL/...",
                            key=f"pl8_no_evaluasi_{_k8}", label_visibility="collapsed",
                        )
                    with _c8hs:
                        st.markdown(f"**{_ba_cfg_pl.JENIS_LABEL_PL['hasil']}**")
                        _no8hs = st.text_input(
                            "Nomor", value=_auto_hs, placeholder="000.3.3/07/PL/...",
                            key=f"pl8_no_hasil_{_k8}", label_visibility="collapsed",
                        )

                    # Tombol per paket
                    _btn8c1, _btn8c2, _btn8c3 = st.columns([2, 2, 1])
                    with _btn8c1:
                        if st.button(
                            "🖨️ Cetak+Upload Evaluasi",
                            key=f"pl8_ev_{_k8}",
                            disabled=not _no8ev,
                            use_container_width=True,
                        ):
                            with st.spinner(f"Proses BA Evaluasi {_k8}..."):
                                _tgl8s = _tgl8.strftime("%d-%m-%Y") if _tgl8 else ""
                                _rc8 = _ba_pl_engine5.cetak_ba_pl(
                                    id_nontender=_id8, jenis_key="evaluasi",
                                    nomor_ba=_no8ev, tanggal_ba=_tgl8s,
                                )
                                if _rc8["ok"]:
                                    _backup_pdf_pl8(_p8, "evaluasi", _rc8["pdf_bytes"])
                                    _fn8 = f"{_ba_cfg_pl.FILE_LABEL_PL['evaluasi']}-{_k8}.pdf"
                                    _ru8 = _ba_pl_engine5.upload_ba_pl(
                                        id_nontender=_id8, jenis_key="evaluasi",
                                        nomor_ba=_no8ev, tanggal_ba=_tgl8s,
                                        file_bytes=_rc8["pdf_bytes"], file_name=_fn8,
                                    )
                                    if _ru8.get("ok"):
                                        st.success(f"✅ BA Evaluasi {_k8} berhasil")
                                    else:
                                        st.error(f"❌ Upload gagal: status {_ru8.get('status')}")
                                else:
                                    st.error(f"❌ Cetak gagal: {_rc8.get('error')} (status {_rc8.get('status')})")
                    with _btn8c2:
                        if st.button(
                            "🖨️ Cetak+Upload Hasil",
                            key=f"pl8_hs_{_k8}",
                            disabled=not _no8hs,
                            use_container_width=True,
                        ):
                            with st.spinner(f"Proses BA Hasil {_k8}..."):
                                _tgl8s = _tgl8.strftime("%d-%m-%Y") if _tgl8 else ""
                                _rc8h = _ba_pl_engine5.cetak_ba_pl(
                                    id_nontender=_id8, jenis_key="hasil",
                                    nomor_ba=_no8hs, tanggal_ba=_tgl8s,
                                )
                                if _rc8h["ok"]:
                                    _backup_pdf_pl8(_p8, "hasil", _rc8h["pdf_bytes"])
                                    _fn8h = f"{_ba_cfg_pl.FILE_LABEL_PL['hasil']}-{_k8}.pdf"
                                    _ru8h = _ba_pl_engine5.upload_ba_pl(
                                        id_nontender=_id8, jenis_key="hasil",
                                        nomor_ba=_no8hs, tanggal_ba=_tgl8s,
                                        file_bytes=_rc8h["pdf_bytes"], file_name=_fn8h,
                                    )
                                    if _ru8h.get("ok"):
                                        st.success(f"✅ BA Hasil {_k8} berhasil")
                                    else:
                                        st.error(f"❌ Upload gagal: status {_ru8h.get('status')}")
                                else:
                                    st.error(f"❌ Cetak gagal: {_rc8h.get('error')} (status {_rc8h.get('status')})")
                    with _btn8c3:
                        _chk8 = st.checkbox("Batch", key=f"pl8ba_chk_{_k8}", value=False)

                    if _chk8 and _no8ev and _no8hs:
                        _pl8_valid_auto.append({
                            **_p8,
                            "_id8": _id8, "_tgl8": _tgl8,
                            "_no8ev": _no8ev, "_no8hs": _no8hs,
                        })

            # Tombol batch semua
            if _pl8_valid_auto:
                if st.button(
                    f"🚀 Cetak+Upload Semua BA ({len(_pl8_valid_auto)} paket × 2 BA)",
                    type="primary", key="pl8_batch_all", use_container_width=True,
                ):
                    with st.status(f"Proses {len(_pl8_valid_auto)} paket...", expanded=True) as _st8:
                        for _pb8 in _pl8_valid_auto:
                            _tgl8s = _pb8["_tgl8"].strftime("%d-%m-%Y") if _pb8["_tgl8"] else ""
                            for _jk8, _no8, _lbl8 in [
                                ("evaluasi", _pb8["_no8ev"], "Evaluasi"),
                                ("hasil",    _pb8["_no8hs"], "Hasil"),
                            ]:
                                _st8.write(f"⏳ {_pb8['kode_paket']} — BA {_lbl8}...")
                                try:
                                    _rc = _ba_pl_engine5.cetak_ba_pl(
                                        id_nontender=_pb8["_id8"], jenis_key=_jk8,
                                        nomor_ba=_no8, tanggal_ba=_tgl8s,
                                    )
                                    if _rc["ok"]:
                                        _backup_pdf_pl8(_pb8, _jk8, _rc["pdf_bytes"])
                                        _fn = f"{_ba_cfg_pl.FILE_LABEL_PL[_jk8]}-{_pb8['kode_paket']}.pdf"
                                        _ru = _ba_pl_engine5.upload_ba_pl(
                                            id_nontender=_pb8["_id8"], jenis_key=_jk8,
                                            nomor_ba=_no8, tanggal_ba=_tgl8s,
                                            file_bytes=_rc["pdf_bytes"], file_name=_fn,
                                        )
                                        if _ru.get("ok"):
                                            _st8.write(f"  ✅ BA {_lbl8} OK")
                                        else:
                                            _st8.write(f"  ❌ Upload BA {_lbl8} — status {_ru.get('status')}")
                                    else:
                                        _st8.write(f"  ❌ Cetak BA {_lbl8} — {_rc.get('error')}")
                                except Exception as _e8b:
                                    _st8.write(f"  ❌ Error: {_e8b}")

        # ── SECTION 2: BA LAINNYA (upload-only) ──────────────────────────────
        st.divider()
        st.markdown("### 2. BA Lainnya (Upload Manual)")
        st.caption("BA Penjelasan, Pengumuman Pemenang, dll — upload file PDF langsung ke SPSE.")

        if _pl8_rows:
            _JENIS_LAINNYA = {
                "penjelasan":   "BA Penjelasan",
                "pengumuman":   "Pengumuman Pemenang Akhir",
            }
            _pl8_lc1, _pl8_lc2 = st.columns([1, 2])
            with _pl8_lc1:
                _jenis_lain8 = st.selectbox(
                    "Jenis BA",
                    options=list(_JENIS_LAINNYA.keys()),
                    format_func=lambda k: _JENIS_LAINNYA[k],
                    key="pl8_jenis_lain",
                )
            with _pl8_lc2:
                _nomor_lain8  = st.text_input(
                    "Nomor BA",
                    placeholder="000.3.3/06/PL/PP-01/KPP1/DPUPR/2026",
                    key="pl8_nomor_lain",
                )
            _tgl_lain8 = st.date_input(
                "Tanggal BA", value=datetime.now().date(), format="DD/MM/YYYY",
                key="pl8_tgl_lain",
            )
            st.caption(f"{_HARI_NAMA[_tgl_lain8.weekday()]}, {_tgl_lain8.day} "
                       f"{_BULAN_NAMA[_tgl_lain8.month-1]} {_tgl_lain8.year}")
            _tempat_lain8 = ""
            if _jenis_lain8 == "pengumuman":
                _tempat_lain8 = st.text_input("Tempat", placeholder="Contoh: Kantor RSUD", key="pl8_tempat_lain")
            _info_lain8 = st.text_area("Keterangan Tambahan", value="", key="pl8_info_lain", height=68)

            st.markdown("**Pilih Paket + Upload File:**")
            _pl8_lain_valid = []
            for _p8l in _pl8_rows:
                _k8l  = _p8l.get("kode_paket", "")
                _id8l = _k8l  # BA nontender pakai kode_paket
                _lc1, _lc2, _lc3 = st.columns([3, 3, 1])
                with _lc1:
                    st.caption(f"{_p8l.get('nomor_urut') or ''}. {_p8l.get('nama_paket','')[:50]}")
                with _lc2:
                    _fl8 = st.file_uploader(
                        "PDF", type=["pdf"], key=f"pl8_lain_file_{_k8l}",
                        label_visibility="collapsed",
                    )
                with _lc3:
                    if _fl8 and st.button("📤", key=f"pl8_lain_up_{_k8l}", use_container_width=True):
                        with st.spinner(f"Upload {_k8l}..."):
                            _rl8 = _ba_pl_engine5.upload_ba_pl(
                                id_nontender=_id8l, jenis_key=_jenis_lain8,
                                nomor_ba=_nomor_lain8,
                                tanggal_ba=_tgl_lain8.strftime("%d-%m-%Y"),
                                info=_info_lain8,
                                file_bytes=_fl8.read(), file_name=_fl8.name,
                                tempat=_tempat_lain8,
                            )
                        if _rl8.get("ok"):
                            st.success(f"✅ {_k8l} — berhasil")
                        else:
                            st.error(f"❌ {_k8l} — status {_rl8.get('status')}")
                if _fl8:
                    _pl8_lain_valid.append({**_p8l, "_id8l": _id8l, "_fl8": _fl8})

            if _pl8_lain_valid:
                if st.button(
                    f"📤 Upload Semua ({len(_pl8_lain_valid)} paket)",
                    key="pl8_lain_all", use_container_width=True,
                ):
                    with st.status(f"Upload {len(_pl8_lain_valid)} paket...", expanded=True) as _st8l:
                        for _pbl in _pl8_lain_valid:
                            _st8l.write(f"⏳ {_pbl['kode_paket']}...")
                            _rbl = _ba_pl_engine5.upload_ba_pl(
                                id_nontender=_pbl["_id8l"], jenis_key=_jenis_lain8,
                                nomor_ba=_nomor_lain8,
                                tanggal_ba=_tgl_lain8.strftime("%d-%m-%Y"),
                                info=_info_lain8,
                                file_bytes=_pbl["_fl8"].read(), file_name=_pbl["_fl8"].name,
                                tempat=_tempat_lain8,
                            )
                            if _rbl.get("ok"):
                                _st8l.write(f"  ✅ {_pbl['kode_paket']} — berhasil")
                            else:
                                _st8l.write(f"  ❌ {_pbl['kode_paket']} — status {_rbl.get('status')}")

    # ── Tab 5: Download Dok Kualifikasi PL ───────────────────────────────────
    with _pl_tab5:
        import kualifikasi_engine_plpk as _ke_pl
        import kualifikasi_parser_pl as _kp_pl
        import hasil_evaluasi_plpk_engine as _he_pl

        st.markdown("## Download Dokumen Kualifikasi — Pengadaan Langsung")
        st.caption("Download dok kualifikasi peserta dari SPSE + populate sheet Hasil Evaluasi di BAPLJKK.")

        # Cache paket list di session state — hindari query Supabase tiap render
        if "pl7_rows" not in st.session_state:
            try:
                st.session_state["pl7_rows"] = pl_engine._sb().table("draft_paket_pl").select(
                    "kode_paket, nama_paket, jenis_pl, nomor_urut, kode_unik"
                ).order("nomor_urut").execute().data or []
            except Exception as _e7:
                st.session_state["pl7_rows"] = []
                st.error(f"Gagal load paket PL: {_e7}")
        _pl7_rows = st.session_state["pl7_rows"]

        if not _pl7_rows:
            st.info("Tidak ada paket PL di database.")
            if st.button("🔄 Reload", key="pl7_reload"):
                del st.session_state["pl7_rows"]
                st.rerun()
        else:
            _pl7c1, _pl7c2 = st.columns([1, 1])

            with _pl7c1:
                st.markdown("#### Pilih Paket")
                if "pl7_checked" not in st.session_state:
                    st.session_state["pl7_checked"] = {}

                _pl7_kodes = [r["kode_paket"] for r in _pl7_rows]
                _pl7_btn_col1, _pl7_btn_col2 = st.columns(2)
                # Pilih Semua / Batal Semua — hanya set state, TIDAK fetch CDP
                if _pl7_btn_col1.button("✅ Pilih Semua", key="pl7_select_all", use_container_width=True):
                    for _k in _pl7_kodes:
                        st.session_state[f"pl7_chk_{_k}"] = True
                        st.session_state["pl7_checked"][_k] = True
                if _pl7_btn_col2.button("❌ Batal Semua", key="pl7_deselect_all", use_container_width=True):
                    for _k in _pl7_kodes:
                        st.session_state[f"pl7_chk_{_k}"] = False
                        st.session_state["pl7_checked"][_k] = False

                for _rpl7 in _pl7_rows:
                    _kpl7 = _rpl7["kode_paket"]
                    _nomor7 = _rpl7.get("nomor_urut") or ""
                    _label7 = f"{_nomor7}. {_rpl7.get('nama_paket','?')}" if _nomor7 else _rpl7.get("nama_paket", "?") or "?"
                    _chk7 = st.checkbox(_label7, key=f"pl7_chk_{_kpl7}")
                    st.session_state["pl7_checked"][_kpl7] = _chk7

            with _pl7c2:
                st.markdown("#### Aksi")

                _pl7_selected_kodes = [k for k in _pl7_kodes if st.session_state["pl7_checked"].get(k)]
                _pl7_selected_rows  = [r for r in _pl7_rows if r["kode_paket"] in _pl7_selected_kodes]
                _n_paket7 = len(_pl7_selected_rows)

                if not _pl7_selected_rows:
                    st.info("Centang minimal 1 paket di kiri.")
                else:
                    st.markdown(f"**{_n_paket7} paket** dipilih")
                    st.caption("Peserta akan di-fetch via CDP saat tombol Jalankan diklik.")

                    _do_download7 = st.checkbox("⬇️ Download dokumen kualifikasi", value=True, key="pl7_do_dl")
                    _do_parse7    = st.checkbox("📋 Parse & populate sheet Hasil Evaluasi", value=True, key="pl7_do_parse")

                    _btn7 = st.button(
                        f"▶ Jalankan — {_n_paket7} paket",
                        type="primary", key="pl7_run", use_container_width=True,
                    )

                    if _btn7:
                        _pb7 = st.progress(0.0, text="Memulai...")
                        _log7_lines = []  # akumulasi log — update sekali per paket, bukan per baris
                        _ringkasan7: list = []  # kumpul status tiap paket untuk ringkasan akhir

                        def _flush7(container):
                            """Render log terakumulasi ke container — 1 update per paket."""
                            container.code("\n".join(_log7_lines[-60:]))  # max 60 baris terakhir

                        for _i7, _rpl7 in enumerate(_pl7_selected_rows):
                            _kpl7    = _rpl7["kode_paket"]
                            _nama7   = _rpl7.get("nama_paket", "?")
                            _status7 = st.status(f"Paket {_i7+1}/{_n_paket7} — {_nama7}", expanded=True)

                            with _status7:
                                _log7_lines.clear()
                                _log7_box = st.empty()

                                def _lcb7(msg, _box=_log7_box, _lines=_log7_lines):
                                    _lines.append(msg)
                                    _box.code("\n".join(_lines[-40:]))

                                # Fetch peserta
                                _lcb7(f"[{_i7+1}/{_n_paket7}] Fetch peserta SPSE...")
                                _pb7.progress((_i7) / _n_paket7, text=f"{_nama7} — fetch peserta")
                                _fp7 = _ke_pl.fetch_peserta_pl(_kpl7)
                                if not _fp7.get("ok"):
                                    _lcb7(f"[SKIP] Peserta: {_fp7['pesan']}")
                                    _status7.update(label=f"SKIP {_nama7} — {_fp7['pesan']}", state="error", expanded=False)
                                    _ringkasan7.append({"nama": _nama7, "status": "skip", "detail": _fp7["pesan"]})
                                    continue
                                _peserta7 = _fp7["peserta"]
                                _lcb7(f"Peserta ({len(_peserta7)}): {', '.join(p['nama'] for p in _peserta7)}")

                                # Resolve folder
                                _folder7 = _ke_pl.resolve_folder_paket_pl(_kpl7)
                                if not _folder7.get("ok"):
                                    _lcb7(f"[SKIP] Folder: {_folder7['pesan']}")
                                    _status7.update(label=f"SKIP {_nama7} — folder tidak ditemukan", state="error", expanded=False)
                                    _ringkasan7.append({"nama": _nama7, "status": "skip", "detail": _folder7.get("pesan", "folder tidak ditemukan")})
                                    continue
                                _folder_kual7 = _folder7["path"]

                                # Download kualifikasi
                                if _do_download7:
                                    _pb7.progress((_i7 + 0.3) / _n_paket7, text=f"{_nama7} — download kualifikasi")
                                    for _ui7, _p7 in enumerate(_peserta7, 1):
                                        _lcb7(f"--- Download [{_ui7}/{len(_peserta7)}] {_p7['nama']} ---")
                                        _ke_pl.download_kualifikasi_peserta_pl(
                                            _p7, _folder_kual7, _ui7, len(_peserta7), _lcb7,
                                        )

                                # Parse evaluasi
                                if _do_parse7:
                                    _pb7.progress((_i7 + 0.7) / _n_paket7, text=f"{_nama7} — parse evaluasi")
                                    _lcb7("--- Populate sheet Hasil Evaluasi ---")
                                    _hasil7 = _he_pl.populate_hasil_evaluasi_pl(_kpl7, _peserta7, _lcb7)
                                    _lcb7(f"{'[OK]' if _hasil7.get('ok') else '[GAGAL]'} {_hasil7['pesan']}")
                                    _ringkasan7.append({
                                        "nama"  : _nama7,
                                        "status": "ok" if _hasil7.get("ok") else "gagal",
                                        "detail": _hasil7.get("pesan", ""),
                                    })
                                else:
                                    # Tidak ada parse → anggap OK (hanya download)
                                    _ringkasan7.append({"nama": _nama7, "status": "ok", "detail": "download saja"})

                                _status7.update(label=f"Selesai — {_nama7}", state="complete", expanded=False)

                            _pb7.progress((_i7 + 1) / _n_paket7, text=f"Selesai {_i7+1}/{_n_paket7} paket")

                        _pb7.progress(1.0, text="Semua paket selesai.")
                        from batch_summary import render_ringkasan_batch as _rrb7
                        _rrb7(st, _ringkasan7)

    # ── Tab 6: Evaluasi SPSE + Download Teknis/Biaya ─────────────────────────
    with _pl_tab6:
        import evaluasi_admin_kualifikasi_pl as _eval_pl
        import dokumen_teknis_biaya_pl as _dtb_pl
        import penawaran_pl_engine as _penawaran_pl

        st.markdown("## Evaluasi SPSE & Download Teknis/Biaya — Pengadaan Langsung")
        st.caption("Submit evaluasi Admin+Kualifikasi LULUS di SPSE, lalu download dokumen teknis/biaya peserta.")

        # Cache paket list (share dengan Tab 7)
        if "pl7_rows" not in st.session_state:
            try:
                st.session_state["pl7_rows"] = pl_engine._sb().table("draft_paket_pl").select(
                    "kode_paket, nama_paket, jenis_pl, nomor_urut, kode_unik"
                ).order("nomor_urut").execute().data or []
            except Exception:
                st.session_state["pl7_rows"] = []
        _pl8_rows = st.session_state["pl7_rows"]

        if not _pl8_rows:
            st.info("Tidak ada paket PL. Reload di Tab 7.")
        else:
            _pl8c1, _pl8c2 = st.columns([1, 1])

            with _pl8c1:
                st.markdown("#### Pilih Paket")
                if "pl8_checked" not in st.session_state:
                    st.session_state["pl8_checked"] = {}

                _pl8_kodes = [r["kode_paket"] for r in _pl8_rows]
                _pl8bc1, _pl8bc2 = st.columns(2)
                if _pl8bc1.button("✅ Pilih Semua", key="pl8_select_all", use_container_width=True):
                    for _k in _pl8_kodes:
                        st.session_state[f"pl8_chk_{_k}"] = True
                        st.session_state["pl8_checked"][_k] = True
                if _pl8bc2.button("❌ Batal Semua", key="pl8_deselect_all", use_container_width=True):
                    for _k in _pl8_kodes:
                        st.session_state[f"pl8_chk_{_k}"] = False
                        st.session_state["pl8_checked"][_k] = False

                for _rpl8 in _pl8_rows:
                    _kpl8 = _rpl8["kode_paket"]
                    _nomor8 = _rpl8.get("nomor_urut") or ""
                    _label8 = f"{_nomor8}. {_rpl8.get('nama_paket','?')}" if _nomor8 else _rpl8.get("nama_paket", "?") or "?"
                    _chk8 = st.checkbox(_label8, key=f"pl8_chk_{_kpl8}")
                    st.session_state["pl8_checked"][_kpl8] = _chk8

            with _pl8c2:
                st.markdown("#### Aksi")

                _pl8_selected_rows = [r for r in _pl8_rows if st.session_state["pl8_checked"].get(r["kode_paket"])]
                _n_paket8 = len(_pl8_selected_rows)

                if not _pl8_selected_rows:
                    st.info("Centang minimal 1 paket di kiri.")
                else:
                    st.markdown(f"**{_n_paket8} paket** dipilih")
                    st.caption("Peserta di-scrape dari SPSE saat Jalankan.")

                    _do_eval_admin = st.checkbox("⚖️ Submit evaluasi Admin + Kualifikasi LULUS di SPSE", value=True, key="pl8_do_eval_admin")
                    _do_eval_teknis = st.checkbox("⚙️ Submit evaluasi Teknis LULUS di SPSE", value=True, key="pl8_do_eval_teknis")
                    _do_eval_harga = st.checkbox("💰 Submit evaluasi Harga LULUS di SPSE", value=True, key="pl8_do_eval_harga")

                    _do_tekbio8  = st.checkbox("⬇️ Download dokumen teknis/biaya + gabung PDF", value=True, key="pl8_do_tekbio")
                    _do_penawaran8 = st.checkbox("📊 Tulis rincian penawaran ke sheet '6. Penawaran' Excel", value=True, key="pl8_do_penawaran")

                    st.divider()
                    st.warning("Evaluasi LULUS bersifat **permanen** — modifikasi data SPSE production.")
                    _konfirmasi8 = st.checkbox(
                        "Saya paham tindakan ini tidak bisa dibatalkan.",
                        value=False, key="pl8_konfirmasi",
                    )

                    _btn8_disabled = (_do_eval_admin or _do_eval_teknis or _do_eval_harga) and not _konfirmasi8
                    if _btn8_disabled:
                        st.info("Centang konfirmasi untuk mengaktifkan tombol.")

                    _btn8 = st.button(
                        f"▶ Jalankan — {_n_paket8} paket",
                        type="primary", key="pl8_run", use_container_width=True,
                        disabled=_btn8_disabled,
                    )

                    if _btn8:
                        _pb8 = st.progress(0.0, text="Memulai...")
                        _ringkasan8: list = []  # kumpul status tiap paket untuk ringkasan akhir

                        for _i8, _rpl8 in enumerate(_pl8_selected_rows):
                            _kpl8  = _rpl8["kode_paket"]
                            _nama8 = _rpl8.get("nama_paket", "?")
                            _status8 = st.status(f"Paket {_i8+1}/{_n_paket8} — {_nama8}", expanded=True)

                            with _status8:
                                _log8_lines = []
                                _log8_box   = st.empty()

                                def _lcb8(msg, _box=_log8_box, _lines=_log8_lines):
                                    _lines.append(msg)
                                    _box.code("\n".join(_lines[-40:]))

                                # Scrape id_nontender per peserta
                                _lcb8("Scrape peserta evaluasi dari SPSE...")
                                _pb8.progress(_i8 / _n_paket8, text=f"{_nama8} — scrape peserta")
                                _res_peserta8 = _eval_pl.scrape_peserta_evaluasi(_kpl8)
                                if not _res_peserta8.get("ok"):
                                    _lcb8(f"[SKIP] {_res_peserta8['pesan']}")
                                    _status8.update(label=f"SKIP {_nama8} — {_res_peserta8['pesan']}", state="error", expanded=False)
                                    _ringkasan8.append({"nama": _nama8, "status": "skip", "detail": _res_peserta8["pesan"]})
                                    continue
                                _peserta8 = _res_peserta8["peserta"]
                                _lcb8(f"Peserta ({len(_peserta8)}): {', '.join(p['nama'] for p in _peserta8)}")

                                # Resolve folder paket root
                                _folder8      = _ke_pl.resolve_folder_paket_pl(_kpl8)
                                _folder_paket8 = _folder8.get("pesan", "") if _folder8.get("ok") else ""

                                # Evaluasi LULUS
                                if _do_eval_admin or _do_eval_teknis or _do_eval_harga:
                                    _pb8.progress((_i8 + 0.3) / _n_paket8, text=f"{_nama8} — submit evaluasi")
                                    _lcb8(f"--- Submit evaluasi LULUS (Admin:{_do_eval_admin}, Teknis:{_do_eval_teknis}, Harga:{_do_eval_harga}) ---")
                                    _eval8 = _eval_pl.evaluasi_batch_lulus(
                                        _kpl8,
                                        admin=_do_eval_admin,
                                        kualifikasi=_do_eval_admin,
                                        teknis=_do_eval_teknis,
                                        harga=_do_eval_harga,
                                        progress_cb=_lcb8
                                    )
                                    _lcb8(f"{'[OK]' if _eval8.get('ok') else '[SEBAGIAN GAGAL]'} {_eval8['ringkasan']}")

                                # Download teknis/biaya
                                if _do_tekbio8:
                                    if not _folder_paket8:
                                        _lcb8("[SKIP] Folder paket tidak ditemukan")
                                    else:
                                        _pb8.progress((_i8 + 0.6) / _n_paket8, text=f"{_nama8} — download teknis/biaya")
                                        for _ui8, _ep8 in enumerate(_peserta8, 1):
                                            _lcb8(f"--- Download [{_ui8}/{len(_peserta8)}] {_ep8['nama']} ---")
                                            _res_tb8 = _dtb_pl.download_teknis_biaya_peserta(
                                                id_nontender=_ep8["id_nontender"],
                                                nama_peserta=_ep8["nama"],
                                                folder_paket=_folder_paket8,
                                                urutan=_ui8,
                                                progress_cb=_lcb8,
                                            )
                                            _lcb8(f"{'[OK]' if _res_tb8['ok'] else '[GAGAL]'} {_res_tb8['pesan']}")

                                # Tulis penawaran ke sheet 6. Penawaran
                                if _do_penawaran8:
                                    if not _folder_paket8:
                                        _lcb8("[SKIP] Folder paket tidak ditemukan, skip penawaran")
                                    else:
                                        _pb8.progress((_i8 + 0.8) / _n_paket8, text=f"{_nama8} — tulis penawaran")
                                        _lcb8("--- Tulis rincian penawaran ke Excel ---")
                                        for _ep8_p in _peserta8:
                                            _lcb8(f"  Peserta: {_ep8_p['nama']}")
                                            _res_pnw8 = _penawaran_pl.tulis_penawaran_ke_excel(
                                                folder_paket=_folder_paket8,
                                                id_nontender=_ep8_p["id_nontender"],
                                                progress_cb=_lcb8,
                                            )
                                            _lcb8(f"  {'[OK]' if _res_pnw8['ok'] else '[GAGAL]'} {_res_pnw8['pesan']}" +
                                                  (f" — Total Rp {_res_pnw8['total_penawaran']:,.0f}" if _res_pnw8.get('total_penawaran') else ""))

                                _ringkasan8.append({"nama": _nama8, "status": "ok", "detail": ""})
                                _status8.update(label=f"Selesai — {_nama8}", state="complete", expanded=False)

                            _pb8.progress((_i8 + 1) / _n_paket8, text=f"Selesai {_i8+1}/{_n_paket8} paket")

                        _pb8.progress(1.0, text="Semua paket selesai.")
                        from batch_summary import render_ringkasan_batch as _rrb8
                        _rrb8(st, _ringkasan8)

    st.stop()  # Jangan render tab Tender jika mode PL

# ============================================================
# MODE: TENDER
# ============================================================
tab0, tab9, tab8, tab_setup, tab7, tab_kual, tab_apendo, tab_ba = st.tabs([
    "0️⃣ Persiapan Draft Paket",
    "1️⃣ Kirim Undangan DPP", "2️⃣ Buat Jadwal",
    "3️⃣ Setup Paket", "4️⃣ Pemberian Penjelasan",
    "5️⃣ Download Kualifikasi", "6️⃣ Dokumen Penawaran",
    "7️⃣ Upload & Cetak 5 BA",
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
        if st.session_state.get("global_paket_draft") or st.session_state.get("global_paket_aktif"):
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
                    _nama_map = {p["kode"]: p["nama"] for p in _get_paket_gabungan()}
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

        # Tombol scrape HPS — tulis langsung ke sheet "5. HPS" di Excel paket (tanpa DB).
        # Butuh folder paket ada + ada file .xlsm di dalamnya.
        if _row_terpilih and _row_terpilih.get("kode_tender"):
            # Cari .xlsm di folder paket (utamakan "0. BAPK")
            _hps_xlsm = None
            if _folder_ada and _target_path:
                _xlsms = [f for f in _os.listdir(_target_path) if f.lower().endswith(".xlsm")]
                _xlsms.sort(key=lambda f: (not f.lower().startswith("0. bapk"), f))
                if _xlsms:
                    _hps_xlsm = _os.path.join(_target_path, _xlsms[0])

            if not _folder_ada:
                st.caption("📊 Buat folder paket dulu untuk Scrape HPS (ditulis ke Excel-nya).")
            elif not _hps_xlsm:
                st.caption("📊 Tidak ada file .xlsm di folder paket untuk diisi HPS.")
            elif st.button("📊 Scrape HPS → Excel", use_container_width=True, key="btn_scrape_hps_saja"):
                import hps_engine as _hps_eng3
                _hps_log = []
                _hps_st = st.status("📊 Scraping HPS + tulis ke Excel...", expanded=True)
                _hps_area = _hps_st.empty()
                def _hps_cb(m):
                    _hps_log.append(m)
                    _hps_area.code("\n".join(_hps_log[-12:]))
                _hps_r = _hps_eng3.scrape_hps_ke_excel(
                    _row_terpilih["kode_tender"], _hps_xlsm, progress_cb=_hps_cb)
                if _hps_r.get("ok"):
                    _hps_st.update(label=f"✅ HPS: {_hps_r['count']} baris ke Excel", state="complete", expanded=False)
                    st.success(f"✅ {_hps_r['pesan']} — Total Rp {_hps_r['total_nilai_bulat']:,.0f}")
                    if _hps_r.get("warning"):
                        st.warning(f"⚠️ {len(_hps_r['warning'])} item selisih hitung (highlight kuning di Excel)")
                else:
                    _hps_st.update(label="❌ HPS gagal", state="error")
                    st.error(f"HPS gagal: {_hps_r.get('pesan', '-')}")
            if _hps_xlsm and st.button("💰 Scrape Penawaran → Excel", use_container_width=True, key="btn_scrape_penawaran_saja"):
                import penawaran_engine as _pen_eng
                _pen_log = []
                _pen_st = st.status("💰 Scraping Penawaran + tulis ke Excel...", expanded=True)
                _pen_area = _pen_st.empty()
                def _pen_cb(m):
                    _pen_log.append(m)
                    _pen_area.code("\n".join(_pen_log[-12:]))
                _pen_r = _pen_eng.scrape_penawaran_ke_excel(
                    _row_terpilih["kode_tender"], _hps_xlsm, progress_cb=_pen_cb)
                if _pen_r.get("peserta"):
                    _pen_st.update(label=f"✅ Penawaran: {_pen_r['peserta']} peserta → Excel", state="complete", expanded=False)
                    st.success(f"✅ {_pen_r['peserta']} peserta: " + ", ".join(_pen_r.get("nama_peserta", [])))
                    if _pen_r.get("items_per_peserta"):
                        for _pi, (_pn, _pc) in enumerate(zip(_pen_r["nama_peserta"], _pen_r["items_per_peserta"])):
                            st.caption(f"  {_pi+1}. {_pn} — {_pc} item")
                    # Update rumus kolom L di sheet 7.2
                    _pen_rumus = _pen_eng.update_rumus_penawaran_72(_hps_xlsm)
                    if _pen_rumus.get("ok"):
                        st.info(f"Rumus 7.2 diupdate: {_pen_rumus['rows_updated']} baris")
                    elif _pen_rumus.get("error"):
                        st.warning(f"Rumus 7.2: {_pen_rumus['error']}")
                else:
                    _pen_st.update(label="❌ Penawaran gagal / kosong", state="error")
                    st.error(f"Penawaran gagal: {_pen_r.get('errors', ['-'])}")

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
                        # Download dokumen (boleh dulu), lalu Scrape HPS → Excel SEQUENTIAL.
                        # HPS pakai COM Excel — JANGAN paralel dgn Playwright download (race COM init).
                        _do_dl = _dl_dokumen and _row_terpilih and _target_path
                        _do_hps = bool(_row_terpilih and _row_terpilih.get("kode_tender"))
                        _dl_msgs = []
                        _hps_res = None
                        _dl_hasil = None
                        _kt_par = _row_terpilih.get("kode_tender", "") if _row_terpilih else ""
                        _ip_par = str(_row_terpilih.get("id_pesan", "")) if _row_terpilih else ""

                        if _do_dl and _kt_par and _ip_par:
                            from streamlit.runtime.scriptrunner import get_script_run_ctx as _grc
                            _ctx_par = _grc()
                            def _dl_cb_par(msg):
                                _dl_msgs.append(msg)
                            with st.spinner("⏳ Mengunduh dokumen SPSE..."):
                                try:
                                    _dl_hasil = inbox_engine.download_dokumen_paket(
                                        _kt_par, _ip_par, _target_path,
                                        kode_pokja=_row_terpilih.get("kode_pokja",""),
                                        progress_cb=_dl_cb_par, st_ctx=_ctx_par)
                                except Exception as _dl_exc:
                                    st.warning(f"Download error: {_dl_exc}")

                        if _do_hps:
                            # Cari .xlsm di folder baru (template "0. BAPK")
                            _hps_xlsm_par = None
                            try:
                                _xl2 = [f for f in _os.listdir(_target_path) if f.lower().endswith(".xlsm")]
                                _xl2.sort(key=lambda f: (not f.lower().startswith("0. bapk"), f))
                                if _xl2:
                                    _hps_xlsm_par = _os.path.join(_target_path, _xl2[0])
                            except Exception:
                                pass
                            if _hps_xlsm_par:
                                import hps_engine as _hps_eng_par
                                with st.spinner("📊 Scraping HPS → tulis ke Excel..."):
                                    try:
                                        _hps_res = _hps_eng_par.scrape_hps_ke_excel(_kt_par, _hps_xlsm_par)
                                    except Exception as _hps_exc:
                                        st.warning(f"Scrape HPS error: {_hps_exc}")
                                # Scrape Penawaran → Excel SEQUENTIAL (setelah HPS)
                                try:
                                    import penawaran_engine as _pen_eng_par
                                    with st.spinner("💰 Scraping Penawaran → tulis ke Excel..."):
                                        _pen_res = _pen_eng_par.scrape_penawaran_ke_excel(_kt_par, _hps_xlsm_par)
                                    if _pen_res.get("peserta"):
                                        st.success(f"✅ Penawaran: {_pen_res['peserta']} peserta → Excel")
                                        _pen_rumus_par = _pen_eng_par.update_rumus_penawaran_72(_hps_xlsm_par)
                                        if _pen_rumus_par.get("ok"):
                                            st.info(f"Rumus 7.2 diupdate: {_pen_rumus_par['rows_updated']} baris")
                                    else:
                                        st.warning(f"Penawaran: {_pen_res.get('errors', ['-'])}")
                                except Exception as _pen_exc:
                                    st.warning(f"Scrape Penawaran error: {_pen_exc}")
                            else:
                                st.caption("📊 HPS dilewati — tidak ada .xlsm di folder baru.")

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
                            if _hps_res.get("ok"):
                                st.success(f"✅ {_hps_res['pesan']} — Total Rp {_hps_res.get('total_nilai_bulat',0):,.0f}")
                                if _hps_res.get("warning"):
                                    st.warning(f"⚠️ {len(_hps_res['warning'])} item selisih (highlight kuning di Excel)")
                            else:
                                st.warning(f"HPS gagal/kosong: {_hps_res.get('pesan', '-')}")
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
                            # Scrape HPS → tulis langsung ke Excel paket (tanpa DB)
                            if _bp.get("kode_tender"):
                                try:
                                    import hps_engine as _hps_eng2
                                    _xl_bulk = None
                                    try:
                                        _xlb = [f for f in _os.listdir(_bp_target) if f.lower().endswith(".xlsm")]
                                        _xlb.sort(key=lambda f: (not f.lower().startswith("0. bapk"), f))
                                        if _xlb:
                                            _xl_bulk = _os.path.join(_bp_target, _xlb[0])
                                    except Exception:
                                        pass
                                    if _xl_bulk:
                                        _hps_res2 = _hps_eng2.scrape_hps_ke_excel(_bp["kode_tender"], _xl_bulk)
                                        if _hps_res2.get("ok"):
                                            _paket_log.append(f"📊 HPS: {_hps_res2.get('count',0)} baris → Excel")
                                        else:
                                            _paket_log.append(f"⚠ HPS: {_hps_res2.get('pesan','-')}")
                                    else:
                                        _paket_log.append("⚠ HPS dilewati — tidak ada .xlsm di folder")
                                except Exception as _hps_e2:
                                    _paket_log.append(f"⚠ HPS gagal: {_hps_e2}")
                            # Scrape Penawaran → Excel per paket
                            if _bp.get("kode_tender") and _xl_bulk:
                                try:
                                    import penawaran_engine as _pen_eng_bulk
                                    _pen_res_bulk = _pen_eng_bulk.scrape_penawaran_ke_excel(_bp["kode_tender"], _xl_bulk)
                                    if _pen_res_bulk.get("peserta"):
                                        _paket_log.append(f"💰 Penawaran: {_pen_res_bulk['peserta']} peserta → Excel")
                                        _pen_rumus_bulk = _pen_eng_bulk.update_rumus_penawaran_72(_xl_bulk)
                                        if _pen_rumus_bulk.get("ok"):
                                            _paket_log.append(f"  Rumus 7.2: {_pen_rumus_bulk['rows_updated']} baris")
                                    else:
                                        _paket_log.append(f"⚠ Penawaran: {_pen_res_bulk.get('errors', ['-'])}")
                                except Exception as _pen_e:
                                    _paket_log.append(f"⚠ Penawaran gagal: {_pen_e}")
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

        # ── Refresh Template ke Folder Tender Existing ────────────────────────
        st.divider()
        with st.expander("🔄 Refresh Template ke Folder Tender Existing"):
            st.caption("Copy file template terbaru ke folder paket tender yang sudah dibuat (tanpa download ulang SPSE).")
            from refresh_template import refresh_template_paket as _rtt_refresh
            from config import POKJA_ROOT as _rtt_POKJA_ROOT
            from pathlib import Path as _rtt_Path
            _TEMPLATE_DIR_TENDER = str(_rtt_Path(_rtt_POKJA_ROOT) / "Paket Experiment")

            _rtt_rows_ada = [r for r in _draft_rows if r.get("folder_dibuat")]
            if not _rtt_rows_ada:
                st.info("Belum ada paket tender dengan folder yang sudah dibuat.")
            else:
                _rtt_opsi = {
                    f"{r.get('nama_tender','')[:70]} (Pokja {r.get('kode_pokja','?')})": r
                    for r in _rtt_rows_ada
                }
                _rtt_all = st.checkbox("Pilih Semua", key="rtt_all")
                _rtt_pilih = st.multiselect(
                    "Pilih paket tender:",
                    list(_rtt_opsi.keys()),
                    default=list(_rtt_opsi.keys()) if _rtt_all else [],
                    key="rtt_ms",
                )
                _rtt_dry = st.checkbox("Dry-run (preview saja, tidak ada perubahan)", value=True, key="rtt_dry")
                _rtt_relink = st.checkbox("Auto-relink Word → Excel setelah copy", value=True, key="rtt_relink")

                if _rtt_pilih and st.button(
                    f"🔄 Refresh Template Tender ke {len(_rtt_pilih)} Paket",
                    type="primary",
                    key="rtt_btn",
                ):
                    _rtt_folders = []
                    for _rtt_k in _rtt_pilih:
                        _rtt_r = _rtt_opsi[_rtt_k]
                        _rtt_fd = _rtt_r.get("folder_dibuat", "")
                        if _rtt_fd:
                            _rtt_folders.append(_rtt_Path(_rtt_POKJA_ROOT) / _rtt_fd)

                    _rtt_src = _rtt_Path(_TEMPLATE_DIR_TENDER)
                    _rtt_ok, _rtt_fail = 0, 0
                    _rtt_log_container = st.container(border=True)
                    _rtt_res = _rtt_refresh(
                        _rtt_folders, _rtt_src, "tender",
                        auto_relink=_rtt_relink, dry_run=_rtt_dry,
                    )
                    for _rtt_fk, _rtt_logs in _rtt_res.items():
                        _rtt_ok_f = all("❌" not in l for l in _rtt_logs)
                        if _rtt_ok_f:
                            _rtt_ok += 1
                        else:
                            _rtt_fail += 1
                        _rtt_log_container.markdown(f"**{_rtt_Path(_rtt_fk).name[:60]}**")
                        for _l in _rtt_logs:
                            _rtt_log_container.caption(_l)
                    _rtt_label = f"✅ {_rtt_ok} OK, ❌ {_rtt_fail} gagal"
                    if _rtt_dry:
                        _rtt_label = "[DRY-RUN] " + _rtt_label
                    if _rtt_fail == 0:
                        st.success(_rtt_label)
                    else:
                        st.warning(_rtt_label)

        # ── Monitor Peserta Tender ────────────────────────────────────────────
        st.divider()
        with st.expander("👀 Monitor Peserta Tender"):
            st.caption("Cek jumlah peserta per paket tender via Chrome SPSE (butuh Chrome CDP aktif + login akun PP).")
            import peserta_monitor_tender as _pmt

            _mon_rows_ada = [r for r in _draft_rows if r.get("folder_dibuat") and r.get("kode_tender")]
            if not _mon_rows_ada:
                st.info("Belum ada paket tender dengan folder yang sudah dibuat.")
            else:
                _mon_opsi = {
                    f"{r.get('nama_tender','')[:70]} (Pokja {r.get('kode_pokja','?')})": r
                    for r in _mon_rows_ada
                }
                _mon_all = st.checkbox("Pilih Semua", key="mon_all")
                _mon_pilih = st.multiselect(
                    "Pilih paket:",
                    list(_mon_opsi.keys()),
                    default=list(_mon_opsi.keys()) if _mon_all else [],
                    key="mon_ms",
                )

                if _mon_pilih and st.button("🔄 Cek Peserta", type="primary", key="mon_btn"):
                    _mon_kode_list = [_mon_opsi[k]["kode_tender"] for k in _mon_pilih]
                    _mon_nama_map  = {_mon_opsi[k]["kode_tender"]: k for k in _mon_pilih}

                    with st.spinner(f"Mengambil data {len(_mon_kode_list)} paket via browser..."):
                        _mon_hasil = _pmt.fetch_semua_paket(_mon_kode_list)

                    # Tabel ringkasan
                    _mon_tbl = []
                    for _mk, _mv in sorted(_mon_hasil.items()):
                        _mon_tbl.append({
                            "Paket": _mon_nama_map.get(_mk, _mk)[:60],
                            "Peserta": _mv["jumlah"],
                            "Status": "⚠️ Error" if _mv["error"] else ("✅ Ada" if _mv["jumlah"] > 0 else "⬜ Belum ada"),
                        })
                    st.dataframe(_mon_tbl, use_container_width=True)

                    # Detail per paket (nama peserta)
                    for _mk, _mv in sorted(_mon_hasil.items()):
                        if _mv.get("peserta"):
                            with st.container(border=True):
                                st.markdown(f"**📋 {_mon_nama_map.get(_mk,_mk)[:60]}**")
                                for _mp in _mv["peserta"]:
                                    _bintang = " ⭐ (Pemenang)" if _mp.get("is_pemenang") else ""
                                    st.caption(f"{_mp['nama']}{' — ' + _mp['npwp'] if _mp['npwp'] else ''}{_bintang}")
                        elif _mv.get("error"):
                            st.warning(f"❌ {_mon_nama_map.get(_mk,_mk)[:50]}: {_mv['error']}")

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
            if "global_paket_draft" not in st.session_state and "global_paket_aktif" not in st.session_state:
                st.info("⚠️ Klik **🔄 Sinkronkan Paket** di **Tab 0** dulu.")
            else:
                st.caption(f"📋 {len(_get_paket_gabungan())} paket tersedia (draft + aktif)")

        sp_selected = []
        if "global_paket_draft" in st.session_state or "global_paket_aktif" in st.session_state:
            paket_list_sp = _get_paket_gabungan()
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
                st.caption(f"📋 {len(_get_paket_gabungan())} paket tersedia (draft + aktif)")

        pj_selected = []
        if "global_paket_draft" in st.session_state or "global_paket_aktif" in st.session_state:
            paket_list_pj = _get_paket_gabungan()
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
                st.caption(f"📋 {len(_get_paket_gabungan())} paket tersedia (draft + aktif)")

        jd_selected = []
        if "global_paket_draft" in st.session_state or "global_paket_aktif" in st.session_state:
            paket_list = _get_paket_gabungan()
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

        if "global_paket_draft" not in st.session_state and "global_paket_aktif" not in st.session_state:
            st.info("⚠️ Data paket belum disinkronkan. Silakan ke **Tab 0** dan klik **🔄 Sinkronkan Paket**.")
        else:
            paket_list = _get_paket_gabungan()
            if not paket_list:
                st.warning("⚠️ Tidak ada paket ditemukan.")
            else:
                st.caption(f"📋 {len(paket_list)} paket tersedia (draft + aktif) — pilih target:")

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
        if "global_paket_draft" in st.session_state or "global_paket_aktif" in st.session_state:
            _ba_paket_list = _get_paket_gabungan()
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
    if "global_paket_draft" not in st.session_state and "global_paket_aktif" not in st.session_state:
        st.info("⚠️ Data paket belum disinkronkan. Silakan ke **Tab 0** dan klik **🔄 Sinkronkan Paket**.")
    else:
        paket_list_ba = _get_paket_gabungan()
        if not paket_list_ba:
            st.warning("⚠️ Tidak ada paket ditemukan.")
        else:
            st.caption(f"📋 {len(paket_list_ba)} paket tersedia (draft + aktif) — pilih:")
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

        _total_kosong = []
        st.markdown(f"### 📋 Konfirmasi Cetak & Upload — {_label_target}")
        st.caption("Tanggal sudah terisi dari GCal. Ubah langsung jika perlu, lalu **Ya, Cetak & Upload**.")

        for _pp in _pending_paket:
            _pid_k = _pp["id_lelang"]
            with st.expander(f"📁 {_pokja_label(_pp)}", expanded=True):
                for _jk in _jenis_konfirm:
                    _no   = st.session_state.get(f"ba_no_{_jk}_{_pid_k}", "")
                    _label = ba_config.JENIS_LABEL[_jk]
                    if not _no:
                        st.caption(f"⚠️ {_label}: nomor BA tidak ada — dilewati")
                        continue
                    _tgl_date_cur = st.session_state.get(f"ba_tgl_date_{_jk}_{_pid_k}")
                    _default_date = _tgl_date_cur if isinstance(_tgl_date_cur, date) else date.today()
                    _edit_key = f"ba_edit_date_{_jk}_{_pid_k}"

                    _col_label, _col_tgl = st.columns([3, 3])
                    with _col_label:
                        st.markdown(f"**{_label}**")
                        st.caption(f"`{_no}`")
                    with _col_tgl:
                        # Label di atas date_input = teks Indonesia (tidak rerun)
                        if isinstance(_default_date, date):
                            _tgl_id = f"{_HARI_NAMA[_default_date.weekday()]}, {_default_date.day} {_BULAN_NAMA[_default_date.month-1]} {_default_date.year}"
                            st.caption(f"📅 {_tgl_id}")
                        _new_date = st.date_input(
                            "Ganti tanggal",
                            value=_default_date,
                            key=_edit_key,
                            label_visibility="visible",
                            format="DD/MM/YYYY",
                        )
                    # Update session state setiap render (reactive, no rerun needed)
                    if isinstance(_new_date, date):
                        st.session_state[f"ba_tgl_date_{_jk}_{_pid_k}"] = _new_date
                        st.session_state[f"ba_tgl_{_jk}_{_pid_k}"] = _new_date.strftime("%d-%m-%Y")
                    else:
                        _total_kosong.append(f"{_pokja_label(_pp)} / {_label}")

        if _total_kosong:
            st.warning(f"⚠️ {len(_total_kosong)} jenis akan dilewati (tanggal kosong)")

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
        "hasil_pemilihan": "10. Berita Acara Hasil Pemilihan",
        "negosiasi":       "8. Berita Acara Negosiasi",
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
            import time as _time
            for jenis_key in jenis_list:
                op_idx += 1
                progress.progress(op_idx / total_ops, text=f"Proses {p['kode']} — {ba_config.JENIS_BA[jenis_key]} ({op_idx}/{total_ops})...")
                nomor = st.session_state.get(f"ba_no_{jenis_key}_{pid}", "").strip()
                tanggal = st.session_state.get(f"ba_tgl_{jenis_key}_{pid}", "").strip()
                info = ba_config.DEFAULT_INFO.get(jenis_key, "")
                ba_result = {"jenis": ba_config.JENIS_BA[jenis_key], "status": "⏭️ Lewati (nomor/tanggal kosong)"}
                if nomor and tanggal:
                    # Retry hingga 3x jika SPSE 503/timeout
                    for _attempt in range(3):
                        try:
                            r_cetak = ba_engine.cetak_ba(paket_id=pid, jenis_key=jenis_key, nomor_ba=nomor, tanggal_ba=tanggal, info=info)
                            if r_cetak["ok"]:
                                fn = f"{_FILE_LABEL_BA.get(jenis_key, jenis_key)}-{p['kode']}.pdf"
                                with open(_os.path.join(target_dir, fn), "wb") as f:
                                    f.write(r_cetak["pdf_bytes"])
                                r_up = ba_engine.upload_ba(paket_id=pid, jenis_key=jenis_key, nomor_ba=nomor, tanggal_ba=tanggal, file_bytes=r_cetak["pdf_bytes"], file_name=fn, info=info)
                                if r_up["ok"]:
                                    ba_result["status"] = f"✅ Sukses — `{fn}`"
                                elif r_up["status"] in (503, 429, 502) and _attempt < 2:
                                    progress.progress(op_idx / total_ops, text=f"⏳ Server {r_up['status']}, retry {_attempt+2}/3...")
                                    _time.sleep(3)
                                    continue
                                else:
                                    ba_result["status"] = f"❌ Upload Error {r_up['status']}"
                            else:
                                if r_cetak["status"] in (503, 429, 502) and _attempt < 2:
                                    progress.progress(op_idx / total_ops, text=f"⏳ Cetak {r_cetak['status']}, retry {_attempt+2}/3...")
                                    _time.sleep(3)
                                    continue
                                ba_result["status"] = f"❌ Cetak Error {r_cetak['status']}: {r_cetak.get('error')}"
                            break  # sukses atau error non-retryable
                        except Exception as e:
                            if _attempt < 2:
                                _time.sleep(3)
                                continue
                            ba_result["status"] = f"❌ {e}"
                    # Jeda antar BA biar SPSE ga throttle
                    _time.sleep(2)
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
    # ── Auto-fetch paket dari Supabase (tanpa CDP/Chrome) ────────────────────
    if "global_paket_draft" not in st.session_state and "global_paket_aktif" not in st.session_state:
        try:
            from config import sb as _sb_kl
            _kl_rows = _sb_kl().table("draft_paket").select(
                "kode_tender,nama_tender,kode_pokja,nomor_urut"
            ).order("nomor_urut").execute().data or []
            # Adapter: sesuaikan format dengan yang diharapkan _get_paket_gabungan()
            # field: kode, nama, id_lelang, pokja, status, tanggal
            _kl_paket_mapped = [
                {
                    "kode": r["kode_tender"],
                    "nama": r["nama_tender"] or r["kode_tender"],
                    "id_lelang": r["kode_tender"],
                    "pokja": r.get("kode_pokja") or "",
                    "status": "aktif",
                    "tanggal": "",
                }
                for r in _kl_rows
            ]
            # Masuk ke global_paket_aktif agar tab lain yang juga pakai session ini tidak terpengaruh
            st.session_state["global_paket_aktif"] = {
                "sukses": True,
                "paket": _kl_paket_mapped,
                "pesan": f"{len(_kl_paket_mapped)} paket dari Supabase",
            }
            # global_paket_draft kosong (draft belum tentu ada di Supabase)
            if "global_paket_draft" not in st.session_state:
                st.session_state["global_paket_draft"] = {"sukses": True, "paket": [], "pesan": ""}
        except Exception as _kl_fe:
            st.warning(f"⚠️ Gagal memuat paket dari Supabase: {_kl_fe}. Coba klik 'Sinkronkan Paket' di Tab 0.")

    # ── Pre-render: fetch semua paket yang dicek tapi belum ada datanya ────────
    if "global_paket_draft" in st.session_state or "global_paket_aktif" in st.session_state:
        _kl_perlu_fetch = [
            p for p in _get_paket_gabungan()
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
        if "global_paket_draft" not in st.session_state and "global_paket_aktif" not in st.session_state:
            st.info("⚠️ Data paket belum disinkronkan. Silakan ke **Tab 0** dan klik **🔄 Sinkronkan Paket**.")
        else:
            _kl_paket_list = sorted(
                [p for p in _get_paket_gabungan() if p.get("kode") != "00000000000"],
                key=lambda p: p.get("tanggal", ""),
                reverse=True,
            )
            if not _kl_paket_list:
                st.warning("⚠️ Tidak ada paket aktif ditemukan.")
            else:
                st.caption(f"📋 {len(_kl_paket_list)} paket — centang satu atau lebih:")
                for p in _kl_paket_list:
                    _kl_chk_key = f"kl_chk_{p['kode']}"
                    if _kl_chk_key not in st.session_state:
                        st.session_state[_kl_chk_key] = True
                    _checked = st.checkbox(
                        f"{_pokja_label(p)[:70]}  \n_{p.get('status', '')}_",
                        key=_kl_chk_key,
                    )

        st.divider()
        _kl_top3_col, _kl_top3_spacer = st.columns([3, 1])
        with _kl_top3_col:
            st.markdown("#### 2. Peserta per Paket")
        _kl_hanya_top3 = st.checkbox("✅ Hanya 3 peserta teratas (harga terendah)", value=True, key="kl_hanya_top3")

        if "global_paket_draft" in st.session_state or "global_paket_aktif" in st.session_state:
            _kl_paket_list2 = sorted(
                [p for p in _get_paket_gabungan() if p.get("kode") != "00000000000"],
                key=lambda p: p.get("tanggal", ""),
                reverse=True,
            )
            # Selectbox: pilih 1 paket aktif untuk tampil pesertanya
            _kl_paket_aktif_opsi = [p for p in _kl_paket_list2 if st.session_state.get(f"kl_chk_{p['kode']}", False)]
            if _kl_paket_aktif_opsi:
                _kl_kode_aktif = st.selectbox(
                    "📌 Paket aktif (pilih untuk lihat pesertanya):",
                    options=[p["kode"] for p in _kl_paket_aktif_opsi],
                    format_func=lambda k: next(
                        (f"{_pokja_label(pp)[:55]}" for pp in _kl_paket_aktif_opsi if pp["kode"] == k), k
                    ),
                    key="kl_paket_aktif",
                )
            else:
                _kl_kode_aktif = None
                st.caption("← Centang paket di Section 1 dulu.")

            _kl_ada_terpilih = False
            for p in _kl_paket_list2:
                if not st.session_state.get(f"kl_chk_{p['kode']}", False):
                    continue
                if p["kode"] != _kl_kode_aktif:
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
                    _kl_limit = min(3, n_p) if _kl_hanya_top3 else n_p
                    _kl_badge = f"Top {_kl_limit} dari {n_p}" if (_kl_hanya_top3 and n_p > 3) else str(n_p)
                    with st.expander(f"**{p['kode']}** — {_kl_badge} peserta", expanded=True):
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if st.button("🏆 Top 3", key=f"kl_top3_{p['kode']}", use_container_width=True):
                                for j, ps in enumerate(kl_res_p["peserta"], 1):
                                    st.session_state[f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}"] = (j <= 3)
                                st.rerun()
                        with c2:
                            if st.button("✅ Semua", key=f"kl_all_{p['kode']}", use_container_width=True):
                                for ps in kl_res_p["peserta"]:
                                    st.session_state[f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}"] = True
                                st.rerun()
                        with c3:
                            if st.button("⬜ Batal", key=f"kl_none_{p['kode']}", use_container_width=True):
                                for ps in kl_res_p["peserta"]:
                                    st.session_state[f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}"] = False
                                st.rerun()
                        for i, ps in enumerate(kl_res_p["peserta"], 1):
                            # Default: centang top-3 saja jika toggle aktif
                            _kl_default_cek = (i <= 3) if _kl_hanya_top3 else True
                            st.checkbox(
                                f"{i}. {ps['nama']}",
                                key=f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}",
                                value=st.session_state.get(f"kl_cek_{p['kode']}_{ps['kualifikasi_id']}", _kl_default_cek),
                            )
            if not _kl_ada_terpilih:
                st.caption("← Centang paket di atas untuk memuat peserta.")

    with _kl_col2:
        st.markdown("#### 3. Folder & Aksi")

        # ── Ringkasan paket terpilih + status folder ───────────────────────────
        _kl_paket_dipilih = []
        if "global_paket_draft" in st.session_state or "global_paket_aktif" in st.session_state:
            _kl_all_list = sorted(
                [p for p in _get_paket_gabungan() if p.get("kode") != "00000000000"],
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
            # ── Fungsi proses (dipakai tombol global + per-paket) ──────────────
            def _proses_paket_kk(items_to_run, do_download, do_kk, do_excel):
                log_area = st.empty()
                log_lines = []

                def _log_cb(msg):
                    log_lines.append(msg)
                    log_area.code("\n".join(log_lines[-30:]))

                progress = st.progress(0, text="Memulai...")
                _total_paket = len(items_to_run)
                _total_semua = sum(len(it["peserta"]) for it in items_to_run)
                _total_steps = _total_paket * (2 if (do_download and do_kk) else 1)
                _step = 0

                for item in items_to_run:
                    p = item["paket"]
                    folder_out = item["folder"]
                    peserta_list = item["peserta"]
                    kode_tender = p["kode"]
                    n_ps = len(peserta_list)

                    _log_cb(f"=== Paket {kode_tender}: {p['nama'][:50]} ({n_ps} peserta) ===")

                    # ── Download dokumen ───────────────────────────────────────
                    if do_download and folder_out:
                        kualifikasi_engine.save_last_dir(folder_out)
                        for i, ps in enumerate(peserta_list):
                            progress.progress(
                                _step / _total_steps + (i / n_ps) / _total_steps * (0.5 if do_kk else 1.0),
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
                        _step += 1

                    # ── Parse & simpan KK Evaluasi ─────────────────────────────
                    if do_kk:
                        _log_cb(f"--- [{kode_tender}] Parse KK Evaluasi ---")
                        semua_data = []
                        for i, ps in enumerate(peserta_list):
                            progress.progress(
                                _step / _total_steps + (i / n_ps) / _total_steps,
                                text=f"[{kode_tender}] Parse KK {i+1}/{n_ps}: {ps['nama'][:35]}...",
                            )
                            slug = re.sub(r'[\\/:*?"<>|]', "", ps["nama"]).strip()[:80]
                            folder_p = os.path.join(folder_out or "", f"{i+1}. {slug}")
                            data_p = kualifikasi_parser.parse_peserta_lengkap(
                                kualifikasi_id=ps["kualifikasi_id"],
                                folder_peserta=folder_p,
                                progress_cb=_log_cb,
                                kode_tender=kode_tender,
                            )
                            if data_p.get("skp_berbeda"):
                                _log_cb(f"  ⚠️ {ps['nama']}: SKP berbeda")
                            if data_p.get("sbu_tidak_sesuai"):
                                _log_cb(f"  ⚠️ {ps['nama']}: SBU tidak sesuai syarat paket (ambil baris pertama)")
                            if data_p.get("ss_tidak_sesuai"):
                                _log_cb(f"  ⚠️ {ps['nama']}: SS tidak sesuai syarat paket (ambil baris pertama)")
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

                            # Tulis langsung ke Excel folder paket
                            if do_excel and folder_out:
                                try:
                                    # folder_out = .../{folder_paket}/1. Dokumen Kualifikasi
                                    # xlsm ada di folder paket (parent), bukan subfolder kualifikasi
                                    _folder_paket = os.path.dirname(folder_out)
                                    _xlsm_list = (
                                        _glob_mod.glob(os.path.join(_folder_paket, "0. BA*.xlsm")) or
                                        _glob_mod.glob(os.path.join(_folder_paket, "*.xlsm"))
                                    )
                                    if _xlsm_list:
                                        _excel_path = _xlsm_list[0]
                                        _log_cb(f"  📝 [{kode_tender}] Menulis KK Evaluasi ke Excel: {os.path.basename(_excel_path)}")
                                        _res_xl = kk_evaluasi_engine.fill_kk_evaluasi(
                                            _excel_path, semua_data, _log_cb)
                                        if _res_xl["ok"]:
                                            _log_cb(f"✅ [{kode_tender}] KK Evaluasi ditulis ke Excel: {_res_xl['pesan']}")
                                        else:
                                            _log_cb(f"⚠️ [{kode_tender}] KK Evaluasi gagal tulis Excel: {_res_xl['pesan']}")
                                    else:
                                        _log_cb(f"⚠️ [{kode_tender}] File .xlsm tidak ditemukan di folder paket, skip tulis Excel.")
                                except Exception as _e_xl:
                                    _log_cb(f"⚠️ [{kode_tender}] Error tulis Excel: {_e_xl}")

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

                        _step += 1

                progress.progress(1.0, text="Selesai!")
                _parts = []
                if do_download: _parts.append("dokumen didownload")
                if do_kk: _parts.append("KK Evaluasi tersimpan")
                st.success(f"✅ Selesai: {' + '.join(_parts)} — {_total_paket} paket, {_total_semua} peserta. Buka Excel → **Muat Harga Penawaran**, **Muat Input BA** (jika perlu).")

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

                if st.button(
                    f"▶ Jalankan paket ini",
                    key=f"kl_run_{p['kode']}",
                    use_container_width=True,
                    disabled=(n_ps == 0) or (item.get("folder_ok") is False),
                ):
                    _proses_paket_kk(
                        [item],
                        st.session_state.get("kl_opt_download", True),
                        st.session_state.get("kl_opt_kk", True),
                        st.session_state.get("kl_opt_kk", True),  # excel ikut parse
                    )

            st.divider()

            # Hitung total peserta
            _kl_total_semua = sum(len(item["peserta"]) for item in _kl_paket_dipilih)
            _kl_total_paket = len(_kl_paket_dipilih)

            # ── Opsi aksi ──────────────────────────────────────────────────────
            _kl_do_download = st.checkbox("⬇️ Download dokumen kualifikasi", value=True, key="kl_opt_download")
            _kl_do_kk = st.checkbox("📝 Parse KK Evaluasi → tulis Excel folder paket", value=True, key="kl_opt_kk")
            _kl_do_excel = _kl_do_kk  # Excel selalu ikut parse (parse wajib utk isi Excel); Supabase upsert otomatis

            _kl_btn_label = []
            if _kl_do_download: _kl_btn_label.append("Download")
            if _kl_do_kk: _kl_btn_label.append("Parse → Excel")
            _kl_btn_text = " + ".join(_kl_btn_label) if _kl_btn_label else "Pilih minimal satu aksi"

            # Tombol global proses HANYA paket aktif (selectbox Section 2), bukan
            # semua tercentang — cegah paket lain ikut terproses tanpa sadar.
            _kl_kode_aktif_run = st.session_state.get("kl_paket_aktif")
            _kl_item_aktif = next(
                (it for it in _kl_paket_dipilih if it["paket"]["kode"] == _kl_kode_aktif_run),
                None,
            )
            _kl_n_aktif = len(_kl_item_aktif["peserta"]) if _kl_item_aktif else 0

            _kl_disabled = (
                (not _kl_btn_label) or (_kl_item_aktif is None) or (_kl_n_aktif == 0)
                or (_kl_do_download and _kl_item_aktif is not None and not _kl_item_aktif["folder_ok"])
            )
            if not _kl_semua_folder_ok and _kl_do_download:
                st.warning("⚠️ Ada paket yang foldernya belum ditemukan — buat folder di Tab 0 terlebih dahulu.")

            st.divider()

            if st.button(
                f"▶ Jalankan: {_kl_btn_text} — paket aktif ({_kl_kode_aktif_run or '-'}), {_kl_n_aktif} peserta",
                key="kl_jalankan",
                type="primary",
                use_container_width=True,
                disabled=_kl_disabled,
            ):
                _proses_paket_kk([_kl_item_aktif], _kl_do_download, _kl_do_kk, _kl_do_excel)

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

        def _render_konflik_dashboard(trigger_sync_doktek: bool = False):
            """Query + tampilkan dashboard konflik. Ringan — hanya baca Supabase."""
            try:
                import conflict_engine as _ce_dash
                if trigger_sync_doktek:
                    # Hanya sync paket yang belum ada di paket_personil
                    _ce_dash.sync_new_paket()
                # Lookup nama paket
                from config import sb as _sb_kf
                _nama_map = {
                    r["kode_tender"]: r.get("nama_tender") or r["kode_tender"]
                    for r in (_sb_kf().table("draft_paket").select("kode_tender,nama_tender").execute().data or [])
                }

                # Query konflik (selalu dari data yang sudah tersimpan di Supabase)
                _kf_p_all = _ce_dash.get_konflik_personil()
                _kf_a_all = _ce_dash.get_konflik_alat()
                if not _kf_p_all and not _kf_a_all:
                    st.success("✅ Tidak ada konflik ditemukan.")
                else:
                    if _kf_p_all:
                        st.markdown(f"**Personil konflik: {len(_kf_p_all)} nama**")
                        _rows_kf = []
                        _BULAN_ID = ["Jan","Feb","Mar","Apr","Mei","Jun","Jul","Agu","Sep","Okt","Nov","Des"]
                        def _fmt_tgl(d):
                            if d is None:
                                return "-"
                            return f"{d.day:02d} {_BULAN_ID[d.month-1]} {d.year}"
                        for k in _kf_p_all:
                            _seen = set()
                            for e in k["paket"]:
                                kt = e["kode_tender"]
                                if kt in _seen:
                                    continue
                                _seen.add(kt)
                                mulai = e.get("tgl_mulai")
                                selesai = e.get("tgl_selesai")
                                periode = f"{_fmt_tgl(mulai)} – {_fmt_tgl(selesai)}" if mulai else "-"
                                _rows_kf.append({
                                    "Nama Personil": k.get("nama_personil_display") or k["nama_personil"],
                                    "Paket": _nama_map.get(kt, kt),
                                    "Penyedia": e["nama_penyedia"] or "-",
                                    "Periode": periode,
                                })
                        st.dataframe(_rows_kf, use_container_width=True, hide_index=True)
                    if _kf_a_all:
                        st.markdown(f"**Alat konflik: {len(_kf_a_all)} nama**")
                        _rows_ka = []
                        for k in _kf_a_all:
                            for e in k["paket"]:
                                kt = e["kode_tender"]
                                _rows_ka.append({
                                    "Nama Alat": k["nama_alat"],
                                    "Paket": _nama_map.get(kt, kt),
                                    "Penyedia": e["nama_penyedia"] or "-",
                                })
                        st.dataframe(_rows_ka, use_container_width=True, hide_index=True)
            except Exception as _e_dash:
                st.error(f"Error: {_e_dash}")

        # Tombol refresh manual — juga trigger sync dari folder doktek
        if st.button("🔄 Cek Konflik (+ Sinkronkan Folder Doktek)", key="kual_cek_konflik"):
            _render_konflik_dashboard(trigger_sync_doktek=True)
        else:
            # Auto-tampil dari data Supabase yang sudah ada (tanpa sync folder)
            _render_konflik_dashboard(trigger_sync_doktek=False)

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
                    _dp_btn_col1, _dp_btn_col2 = st.columns(2)
                    with _dp_btn_col1:
                        _dp_run_key = f"dp_run_{_kt}"
                        if st.button(
                            f"🚚 Pindahkan & Gabung PDF",
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
                    with _dp_btn_col2:
                        if st.button(
                            f"📎 Gabung Dok Lengkap",
                            key=f"dp_gabung_{_kt}",
                            use_container_width=True,
                            help="Gabung DoktekFull + DokkualifFull per peserta → 1. Dokumen Gabungan/",
                        ):
                            _gab_log = []
                            _gab_hasil = _pe.gabung_dokumen_lengkap(_folder_paket, log=_gab_log.append)
                            if _gab_hasil["ok"] > 0:
                                st.success(f"✅ {_gab_hasil['ok']} peserta digabung → `1. Dokumen Gabungan/`")
                            if _gab_hasil["gagal"]:
                                st.error(f"❌ {len(_gab_hasil['gagal'])} gagal:")
                                for _e in _gab_hasil["gagal"]:
                                    st.caption(f"• {_e}")
                            for _m in _gab_log:
                                st.caption(_m)

    # ── Seksi 2: Gabung Dok Lengkap (independen dari Scan Apendo) ─────────────
    st.divider()
    st.markdown("### 📎 Gabung Dokumen Lengkap")
    st.caption("Gabung `DoktekFull` + `DokkualifFull` per peserta → `1. Dokumen Gabungan/`. Tidak perlu Scan Apendo dulu.")

    # Ambil daftar paket dari Supabase
    _gab_paket_list = []
    try:
        from config import sb as _sb_gab
        _gab_r = _sb_gab().table("draft_paket").select("kode_tender,nama_tender,folder_dibuat").not_.is_("folder_dibuat", "null").execute()
        _gab_paket_list = [r for r in (_gab_r.data or []) if r.get("folder_dibuat")]
    except Exception as _gab_e:
        st.warning(f"⚠️ Gagal ambil daftar paket: {_gab_e}")

    if _gab_paket_list:
        from config import POKJA_ROOT as _POKJA_ROOT_GAB
        _gab_valid = [
            _gp for _gp in sorted(_gab_paket_list, key=lambda x: x.get("folder_dibuat", ""))
            if os.path.isdir(os.path.join(_POKJA_ROOT_GAB, _gp["folder_dibuat"], "1. Dokumen Penawaran"))
            or os.path.isdir(os.path.join(_POKJA_ROOT_GAB, _gp["folder_dibuat"], "1. Dokumen Kualifikasi"))
        ]
        if st.button("📎 Gabung Semua Paket", key="gab2_semua", type="primary", use_container_width=False):
            _gab_all_log = st.empty()
            _gab_all_lines = []
            _gab_all_ok = 0
            for _gp in _gab_valid:
                _gp_folder = os.path.join(_POKJA_ROOT_GAB, _gp["folder_dibuat"])
                def _log_gab(m, _lines=_gab_all_lines, _area=_gab_all_log):
                    _lines.append(m)
                    _area.code("\n".join(_lines[-20:]))
                _r = _pe.gabung_dokumen_lengkap(_gp_folder, log=_log_gab)
                _gab_all_ok += _r["ok"]
            st.success(f"✅ Selesai — {_gab_all_ok} peserta digabung dari {len(_gab_valid)} paket.")
        st.divider()
        for _gp in _gab_valid:
            _gp_folder = os.path.join(_POKJA_ROOT_GAB, _gp["folder_dibuat"])
            _gp_label = _gp.get("folder_dibuat", _gp["kode_tender"])
            _gp_c1, _gp_c2 = st.columns([4, 1])
            with _gp_c1:
                st.markdown(f"**{_gp_label}**")
            with _gp_c2:
                if st.button("📎 Gabung", key=f"gab2_{_gp['kode_tender']}", use_container_width=True):
                    _gab2_log = []
                    _gab2_hasil = _pe.gabung_dokumen_lengkap(_gp_folder, log=_gab2_log.append)
                    if _gab2_hasil["ok"] > 0:
                        st.success(f"✅ {_gab2_hasil['ok']} peserta digabung → `1. Dokumen Gabungan/`")
                    elif not _gab2_hasil["gagal"]:
                        st.info("ℹ️ Tidak ada DoktekFull ditemukan di folder Dokumen Penawaran.")
                    if _gab2_hasil["gagal"]:
                        st.error(f"❌ {len(_gab2_hasil['gagal'])} gagal:")
                        for _ge in _gab2_hasil["gagal"]:
                            st.caption(f"• {_ge}")
                    for _gm in _gab2_log:
                        st.caption(_gm)
    else:
        st.info("Tidak ada paket ditemukan di Supabase.")

    # ── Seksi 3: Input BA → tulis Excel langsung via COM ─────────────────────
    st.divider()
    st.markdown("### 📋 Input BA → tulis Excel")
    st.caption(
        "Isi sheet '0. Input BA' (identitas peserta, dokumen penawaran, SKP) "
        "langsung ke file .xlsm via COM. Urutan peserta dari KK Evaluasi."
    )

    # Ambil daftar paket (folder sudah dibuat)
    _iba_paket_list = []
    try:
        from config import sb as _sb_iba, POKJA_ROOT as _POKJA_ROOT_IBA
        _iba_r = _sb_iba().table("draft_paket").select(
            "kode_tender,nama_tender,folder_dibuat"
        ).not_.is_("folder_dibuat", "null").execute()
        _iba_paket_list = [r for r in (_iba_r.data or []) if r.get("folder_dibuat")]
        _iba_paket_list = sorted(_iba_paket_list, key=lambda x: x.get("folder_dibuat", ""))
    except Exception as _iba_e:
        st.warning(f"Gagal ambil daftar paket: {_iba_e}")

    if not _iba_paket_list:
        st.info("Tidak ada paket dengan folder dibuat.")
    else:
        import input_ba_engine as _iba_eng

        # Opsi global
        _iba_col_opt1, _iba_col_opt2 = st.columns(2)
        with _iba_col_opt1:
            _iba_do_teknis = st.checkbox(
                "Parse Dok Teknis (override alat/personel)",
                value=True,
                key="iba_do_teknis",
            )
        with _iba_col_opt2:
            _iba_do_gcal = st.checkbox(
                "Sync tanggal dari Google Calendar",
                value=True,
                key="iba_do_gcal",
            )

        # Fungsi proses (dipakai per-paket maupun global)
        def _proses_input_ba(kode_tender, nama_tender, folder_kualifikasi, xlsm_path, do_teknis, do_gcal):
            """Isi sheet '0. Input BA' untuk satu paket."""
            log_area = st.empty()
            log_lines = []

            def _log_cb(msg):
                log_lines.append(msg)
                try:
                    log_area.code("\n".join(log_lines[-30:]))
                except Exception:
                    pass

            _log_cb(f"=== Input BA: {kode_tender} ===")

            # Folder dok teknis ada di "1. Dokumen Penawaran" (sibling folder kualifikasi),
            # BUKAN di "1. Dokumen Kualifikasi". Resolve dari parent folder paket.
            _folder_paket_root = os.path.dirname(folder_kualifikasi) if folder_kualifikasi else ""
            _folder_penawaran = os.path.join(_folder_paket_root, "1. Dokumen Penawaran") if _folder_paket_root else ""

            # ── 1. (Opsional) parse dok teknis untuk update alat/personel ke Supabase ──
            if do_teknis:
                try:
                    import dokumen_teknis_engine as _dte
                    from config import sb as _sb_dte
                    _ids_r = _sb_dte().table("peserta_identitas").select(
                        "peserta_id,nama_perusahaan"
                    ).eq("kode_tender", kode_tender).execute()
                    _ps_ids = _ids_r.data or []
                    # Daftar subfolder peserta di Dokumen Penawaran (mis. "1. CV SAMATA")
                    _sub_penawaran = []
                    if os.path.isdir(_folder_penawaran):
                        _sub_penawaran = [
                            d for d in os.listdir(_folder_penawaran)
                            if os.path.isdir(os.path.join(_folder_penawaran, d))
                        ]
                    else:
                        _log_cb(f"  ⚠️ Folder '1. Dokumen Penawaran' tidak ada — skip parse teknis")

                    def _cari_folder_peserta(nama):
                        """Cari subfolder yang namanya cocok peserta (abaikan prefix nomor)."""
                        _nrm = re.sub(r'[\s.,]+', '', re.sub(r'[\\/:*?"<>|]', "", nama)).lower()
                        for _d in _sub_penawaran:
                            # Buang prefix "N. " lalu normalisasi
                            _dn = re.sub(r'^\s*\d+\.\s*', '', _d)
                            _dnrm = re.sub(r'[\s.,]+', '', _dn).lower()
                            if _nrm and (_nrm in _dnrm or _dnrm in _nrm):
                                return os.path.join(_folder_penawaran, _d)
                        return None

                    for _ps_id_row in _ps_ids:
                        _pid = _ps_id_row.get("peserta_id", "")
                        _pnama = _ps_id_row.get("nama_perusahaan", "")
                        _folder_ps = _cari_folder_peserta(_pnama)
                        if not _folder_ps:
                            _log_cb(f"  ⚠️ Folder teknis {_pnama} tidak ketemu, skip")
                            continue
                        try:
                            _res_dt = _dte.parse_dan_upsert(
                                kode_tender, _pid, _folder_ps, _log_cb
                            )
                            if not _res_dt.get("ok"):
                                _log_cb(f"  ⚠️ Teknis {_pnama}: {_res_dt.get('pesan','tidak ada file teknis')}")
                        except Exception as _e_dt:
                            _log_cb(f"  ⚠️ Teknis error {_pnama}: {_e_dt}")
                except Exception as _e_dte:
                    _log_cb(f"  ⚠️ Modul teknis error: {_e_dte}")

            # ── 2. Ambil urutan peserta dari kk_evaluasi_peserta ─────────────────────
            peserta_rows = []
            skp_rows = []
            try:
                from config import sb as _sb_kk2
                _kk_r = _sb_kk2().table("kk_evaluasi_peserta").select(
                    "*"
                ).eq("kode_tender", kode_tender).order("urutan").execute()
                _kk_rows = _kk_r.data or []

                # Dict identitas by nama lowercase
                _id_r = _sb_kk2().table("peserta_identitas").select(
                    "nama_perusahaan,npwp_raw,alamat,nama_direktur,"
                    "personel_1,personel_2,alat_1,alat_2,alat_3,alat_4,alat_5,alat_6"
                ).eq("kode_tender", kode_tender).execute()
                _id_by_nama = {
                    (r.get("nama_perusahaan") or "").lower(): r
                    for r in (_id_r.data or [])
                }

                if _kk_rows:
                    # Susun peserta sesuai urutan KK Evaluasi (maks 3)
                    for _kr in _kk_rows[:3]:
                        _nama_kk = (_kr.get("nama") or "").lower()
                        _id_data = _id_by_nama.get(_nama_kk, {})
                        # Fallback: partial match
                        if not _id_data:
                            for _k, _v in _id_by_nama.items():
                                if _nama_kk and (_nama_kk in _k or _k in _nama_kk):
                                    _id_data = _v
                                    break
                        peserta_rows.append({
                            "nama_perusahaan": _id_data.get("nama_perusahaan") or _kr.get("nama", ""),
                            "npwp":         kk_evaluasi_engine._format_npwp(_id_data.get("npwp_raw") or ""),
                            "alamat":       _id_data.get("alamat", ""),
                            "nama_direktur": _id_data.get("nama_direktur", ""),
                            "personel_1":   _id_data.get("personel_1", ""),
                            "personel_2":   _id_data.get("personel_2", ""),
                            "alat_1":       _id_data.get("alat_1", ""),
                            "alat_2":       _id_data.get("alat_2", ""),
                            "alat_3":       _id_data.get("alat_3", ""),
                            "alat_4":       _id_data.get("alat_4", ""),
                            "alat_5":       _id_data.get("alat_5", ""),
                            "alat_6":       _id_data.get("alat_6", ""),
                        })
                    _log_cb(f"  Peserta (urutan KK): {len(peserta_rows)} dari {len(_kk_rows)}")
                else:
                    # Fallback: urut peserta_identitas apa adanya
                    _log_cb("  ⚠️ kk_evaluasi_peserta kosong, fallback urut peserta_identitas")
                    for _id_row in (_id_r.data or [])[:3]:
                        peserta_rows.append({
                            "nama_perusahaan": _id_row.get("nama_perusahaan", ""),
                            "npwp":         kk_evaluasi_engine._format_npwp(_id_row.get("npwp_raw") or ""),
                            "alamat":       _id_row.get("alamat", ""),
                            "nama_direktur": _id_row.get("nama_direktur", ""),
                            "personel_1":   _id_row.get("personel_1", ""),
                            "personel_2":   _id_row.get("personel_2", ""),
                            "alat_1":       _id_row.get("alat_1", ""),
                            "alat_2":       _id_row.get("alat_2", ""),
                            "alat_3":       _id_row.get("alat_3", ""),
                            "alat_4":       _id_row.get("alat_4", ""),
                            "alat_5":       _id_row.get("alat_5", ""),
                            "alat_6":       _id_row.get("alat_6", ""),
                        })

                # SKP + Hasil Pembuktian per peserta (urut sama dgn peserta_rows)
                def _hitung_hasil_ms(_kr):
                    """Tentukan Memenuhi/Tidak Memenuhi dari field KK Evaluasi."""
                    if (_kr.get("kswp_status") or "").upper() in ("TIDAK VALID", "INVALID"):
                        return "Tidak Memenuhi"
                    if not _kr.get("nib_nomor"):
                        return "Tidak Memenuhi"
                    if not _kr.get("sbu_nomor"):
                        return "Tidak Memenuhi"
                    if not _kr.get("pgl1_nama"):
                        return "Tidak Memenuhi"
                    return "Memenuhi"

                skp_rows = []
                for _kr in _kk_rows[:3]:
                    _skp_int = None
                    try:
                        _skp_int = int(_kr.get("skp")) if _kr.get("skp") is not None else None
                    except (ValueError, TypeError):
                        pass
                    skp_rows.append({
                        "skp": _skp_int,
                        "skp_catatan": _kr.get("skp_catatan") if _kr.get("skp_catatan") is not None else (5 - _skp_int if _skp_int is not None else None),
                        "hasil": _hitung_hasil_ms(_kr),
                    })

            except Exception as _e_kk:
                _log_cb(f"  ⚠️ Gagal ambil peserta dari Supabase: {_e_kk}")
                skp_rows = []

            # ── 3. Dokumen penawaran ─────────────────────────────────────────────────
            dokpen = None
            try:
                from config import sb as _sb_dp
                _dp_r = _sb_dp().table("dokumen_penawaran").select("*").eq(
                    "kode_tender", kode_tender
                ).limit(1).execute()
                if _dp_r.data:
                    dokpen = _dp_r.data[0]
                    _log_cb(f"  Dokpen: daftar={dokpen.get('jml_daftar')} kirim={dokpen.get('jml_kirim')}")
            except Exception as _e_dp:
                _log_cb(f"  ⚠️ Gagal ambil dokpen: {_e_dp}")

            # ── 4. (Opsional) Tanggal dari Google Calendar ───────────────────────────
            tgl_pembukaan = None
            tgl_pembuktian = None
            if do_gcal:
                try:
                    import gcal_helper
                    _gcal_hasil = gcal_helper.get_tanggal_ba_dari_gcal(nama_tender)
                    tgl_pembukaan  = _gcal_hasil.get("pembukaan")
                    tgl_pembuktian = _gcal_hasil.get("negosiasi")
                    _log_cb(f"  GCal pembukaan={tgl_pembukaan} pembuktian={tgl_pembuktian}")
                except Exception as _e_gc:
                    _log_cb(f"  ⚠️ GCal error (token expired?): {_e_gc} — tanggal diisi manual")

            # ── 5. Tulis ke Excel ─────────────────────────────────────────────────────
            if not peserta_rows:
                st.warning(f"Tidak ada peserta untuk {kode_tender} — skip tulis Excel.")
                return

            _res = _iba_eng.fill_input_ba(
                xlsm_path,
                peserta_rows,
                dokpen,
                tgl_pembukaan,
                tgl_pembuktian,
                skp_rows,
                _log_cb,
            )
            if _res["ok"]:
                st.success(f"Input BA {kode_tender}: {_res['pesan']}")
            else:
                st.warning(f"Input BA {kode_tender} gagal: {_res['pesan']}")

        # Tombol per-paket
        st.divider()
        for _iba_p in _iba_paket_list:
            _iba_kode  = _iba_p["kode_tender"]
            _iba_nama  = _iba_p.get("nama_tender", _iba_kode)
            _iba_label = _iba_p.get("folder_dibuat", _iba_kode)

            # Resolve folder & xlsm
            _iba_folder_res = kualifikasi_engine.resolve_folder_paket(_iba_kode)
            _iba_folder_kual = _iba_folder_res.get("path", "")
            _iba_folder_paket = os.path.dirname(_iba_folder_kual) if _iba_folder_kual else ""

            # Cari xlsm di folder paket (parent dari folder kualifikasi)
            _iba_xlsm = ""
            if _iba_folder_paket and os.path.isdir(_iba_folder_paket):
                _iba_cand = (
                    _glob_mod.glob(os.path.join(_iba_folder_paket, "0. BA*.xlsm")) or
                    _glob_mod.glob(os.path.join(_iba_folder_paket, "*.xlsm"))
                )
                if _iba_cand:
                    _iba_xlsm = _iba_cand[0]

            _iba_c1, _iba_c2 = st.columns([4, 1])
            with _iba_c1:
                _iba_info = f"**{_iba_label}**"
                if _iba_xlsm:
                    _iba_info += f"  \n`{os.path.basename(_iba_xlsm)}`"
                else:
                    _iba_info += "  \n⚠️ xlsm tidak ditemukan"
                st.markdown(_iba_info)
            with _iba_c2:
                if st.button(
                    "▶ Input BA",
                    key=f"iba_{_iba_kode}",
                    type="primary",
                    use_container_width=True,
                    disabled=not bool(_iba_xlsm),
                ):
                    if _iba_xlsm:
                        _proses_input_ba(
                            _iba_kode,
                            _iba_nama,
                            _iba_folder_kual,
                            _iba_xlsm,
                            st.session_state.get("iba_do_teknis", True),
                            st.session_state.get("iba_do_gcal", True),
                        )

