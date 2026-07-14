"""UI renderer tab Import DPA/RKA."""

import streamlit as st


@st.fragment
def render_tab_dpa():
    import dpa_engine as _dpa
    def _rp(v):
        try: return f"Rp {int(v):,}".replace(",", ".")
        except: return str(v) if v else "-"

    st.markdown("### 📄 Import DPA / RKA ke Database")
    st.caption("Upload PDF DPA/RKA SKPD — ekstrak semua sub kegiatan dan rincian belanja ke Supabase.")

    # Ide 2: Cari dari Database (tanpa upload)
    st.markdown("### 🗄️ Cari dari Database (tanpa upload)")
    _sb_search = st.text_input("Ketik nama paket...", key="dpa_sb_search")

    @st.cache_data(ttl=60)
    def _search_sb_dpa_items(keyword: str):
        from config import sb as _sb_factory
        _sb = _sb_factory()
        return _sb.table("dpa_item_belanja").select(
            "nama_paket,uraian,spesifikasi,jumlah_sebelum,jumlah_sesudah,subkegiatan_id"
        ).ilike("nama_paket", f"%{keyword}%").limit(100).execute().data

    if st.button("🔍 Cari", key="btn_dpa_sb_search") and _sb_search.strip():
        _res_rows = _search_sb_dpa_items(_sb_search.strip())
        if _res_rows:
            from collections import defaultdict
            _grouped = defaultdict(list)
            for _row in _res_rows:
                _grouped[_row.get("nama_paket")].append(_row)

            st.write(f"Ditemukan {len(_grouped)} paket:")
            for _nama_paket, _items in _grouped.items():
                _subkeg_id = _items[0].get("subkegiatan_id") or ""
                _parts = _subkeg_id.split("|")
                _subkeg_info = _parts[-1] if len(_parts) >= 3 else _subkeg_id

                with st.expander(f"📦 **{_nama_paket or 'Tanpa Nama Paket'}**"):
                    st.caption(f"Sub Kegiatan: {_subkeg_info}")
                    _table_rows = []
                    for _it in _items:
                        _table_rows.append({
                            "Uraian / Kategori Belanja": _it.get("uraian") or "-",
                            "Spesifikasi": _it.get("spesifikasi") or "-",
                            "Sebelum": _rp(_it.get("jumlah_sebelum")),
                            "Sesudah": _rp(_it.get("jumlah_sesudah")),
                        })
                    st.table(_table_rows)
        else:
            st.info("Tidak ditemukan data di database.")
    st.divider()

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

        # Ide 1: Cari Paket dari PDF Ini
        st.divider()
        st.markdown("### 🔍 Cari Paket dari PDF Ini")
        _pdf_search_key = st.text_input("Ketik nama paket...", key="dpa_pdf_search")
        if _pdf_search_key.strip():
            _keyword = _pdf_search_key.strip().lower()
            _matches = []
            for _sk in _dpa_sk_list:
                _last_rekening_uraian = "-"
                for _it in _sk["items"]:
                    if _it["tipe"] == "rekening":
                        _last_rekening_uraian = _it["uraian"]
                    elif _it["tipe"] == "item":
                        _nama_paket = _it.get("nama_paket") or ""
                        if _keyword in _nama_paket.lower():
                            _matches.append({
                                "nama_paket": _nama_paket,
                                "sub_kode": _sk["subkegiatan_kode"],
                                "sub_nama": _sk["subkegiatan_nama"],
                                "jumlah_sebelum": _it.get("jumlah_sebelum"),
                                "jumlah_sesudah": _it.get("jumlah_sesudah"),
                                "spesifikasi": _it.get("spesifikasi"),
                                "kategori": _last_rekening_uraian
                            })

            if _matches:
                st.write(f"Ditemukan {len(_matches)} item paket:")
                for _m in _matches:
                    with st.expander(f"📦 **{_m['nama_paket']}**"):
                        st.write(f"**Sub Kegiatan:** {_m['sub_kode']} - {_m['sub_nama']}")
                        _col1, _col2 = st.columns(2)
                        _col1.write(f"**Rincian Sebelum:** {_rp(_m['jumlah_sebelum'])}")
                        _col2.write(f"**Rincian Sesudah:** {_rp(_m['jumlah_sesudah'])}")
                        if _m["spesifikasi"]:
                            st.write(f"**Spesifikasi:** {_m['spesifikasi']}")
                        st.write(f"**Kategori Belanja:** {_m['kategori']}")
            else:
                st.info("Tidak ada paket matching dalam PDF ini.")

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
                        _dpa_sb.table("dpa_subkegiatan").upsert(_sk_row).execute()
                        _dpa_sb.table("dpa_item_belanja").delete().eq("subkegiatan_id", _sk_id).execute()
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
