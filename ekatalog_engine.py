"""E-Katalog Engine — Survei Pasar Inaproc (embed di Asisten Pokja)."""
import sys
import os
import re
import time
import io
import traceback
from datetime import datetime
import streamlit as st
import pandas as pd

# Inject path ke scraper dan V22
_SCRAPER_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Inaproc_Scraper"))
_V22_PATH = r"D:\Dokumen\@ POKJA 2026\V19_Scheduler\WPy64-313110\V22_InaprocOrder"
for _p in [_SCRAPER_PATH, _V22_PATH]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scraper import search_inaproc, HAS_API_CLIENT

# ── Helpers ──────────────────────────────────────────────────────────────────

def _clean_price(value):
    if not value:
        return 0
    clean = re.sub(r'[^0-9]', '', str(value))
    return int(clean) if clean else 0

def _parse_rp(raw: str) -> int | None:
    if raw is None:
        return 0
    s = str(raw).strip().lower().replace("rp", "").strip()
    s = s.replace(".", "").replace(",", "")
    s = re.sub(r"\s+", " ", s).strip()
    m = re.fullmatch(r"(\d+)\s*(m|jt|juta)?", s)
    if not m:
        return None
    base = int(m.group(1))
    suffix = m.group(2)
    if suffix == "m":
        return base * 1_000_000_000
    if suffix in {"jt", "juta"}:
        return base * 1_000_000
    return base

def _fmt_commas(digits: str) -> str:
    if not digits:
        return ""
    parts = []
    while digits:
        parts.append(digits[-3:])
        digits = digits[:-3]
    return ",".join(reversed(parts))

def _rupiah_input(label: str, key: str, default: int = 0) -> int | None:
    display_key = f"{key}__display"
    digits_key = f"{key}__digits"
    if display_key not in st.session_state:
        st.session_state[display_key] = _fmt_commas(str(int(default)))
    if digits_key not in st.session_state:
        st.session_state[digits_key] = re.sub(r"\D+", "", st.session_state[display_key] or "") or "0"

    def _on_change():
        raw = st.session_state.get(display_key, "")
        d = re.sub(r"\D+", "", (raw or "")) or "0"
        st.session_state[digits_key] = d
        st.session_state[display_key] = _fmt_commas(d)

    st.text_input(label, key=display_key, on_change=_on_change)
    return _parse_rp(st.session_state.get(digits_key, "0"))

KALSEL_LOCATIONS = [
    "Kab. Balangan", "Kab. Banjar", "Kab. Barito Kuala", "Kab. Hulu Sungai Selatan",
    "Kab. Hulu Sungai Tengah", "Kab. Hulu Sungai Utara", "Kab. Kotabaru",
    "Kab. Tabalong", "Kab. Tanah Bumbu", "Kab. Tanah Laut", "Kab. Tapin",
    "Kota Banjarbaru", "Kota Banjarmasin",
]

# ── Main render ───────────────────────────────────────────────────────────────

def render_survei_pasar():
    """Render UI survei pasar dalam tab-tab — dipanggil dari app.py mode E-Katalog."""

    if "ek_survey_log_lines" not in st.session_state:
        st.session_state.ek_survey_log_lines = []
    if "ek_df_results" not in st.session_state:
        st.session_state.ek_df_results = None
    if "ek_keywords_used" not in st.session_state:
        st.session_state.ek_keywords_used = []

    tab_cari, tab_hasil, tab_rekom, tab_export = st.tabs([
        "🔍 Pencarian",
        "📋 Hasil",
        "⭐ Rekomendasi",
        "📥 Export",
    ])

    # ── Tab 1: Pencarian (semua config ada di sini) ───────────────────────────
    with tab_cari:
        st.markdown("##### 🛍️ Survei Pasar Katalog Inaproc")
        st.caption("Cari produk untuk Dokumen Persiapan Pengadaan (DPP). Mode API cepat & include TKDN.")

        col_left, col_right = st.columns([1, 1], gap="large")

        with col_left:
            st.markdown("**Kata Kunci**")
            search_type = st.radio(
                "Tipe", ["Single", "Batch (daftar)"],
                index=0, horizontal=True, key="ek_search_type"
            )
            if search_type == "Single":
                keywords = [st.text_input("Kata kunci", "laptop", key="ek_kw_single")]
            else:
                raw_kw = st.text_area(
                    "Daftar barang (1 baris = 1 barang)",
                    "laptop\nprinter\nscanner",
                    height=120,
                    key="ek_kw_batch"
                )
                keywords = [k.strip() for k in raw_kw.split("\n") if k.strip()]

            st.markdown("**Mode Scraping**")
            scraping_mode = st.radio(
                "Engine",
                ["API (cepat, include TKDN)", "Playwright (screenshot, lambat)"],
                index=0, key="ek_scraping_mode"
            )
            use_api = scraping_mode.startswith("API")
            if use_api and not HAS_API_CLIENT:
                st.warning("⚠️ API Client tidak ditemukan. Fallback ke Playwright.")
                use_api = False

            sort_option = st.selectbox(
                "Urutan", ["Paling Sesuai", "Harga Terendah", "Harga Tertinggi"],
                key="ek_sort"
            )
            limit_per_keyword = st.slider(
                "Maks. produk per barang", 1, 60,
                20 if use_api else 5,
                key="ek_limit"
            )

        with col_right:
            st.markdown("**Filter Harga**")
            min_price = _rupiah_input("Harga Min (Rp)", key="ek_min_price_rp", default=0)
            max_price = _rupiah_input("Harga Max (Rp)", key="ek_max_price_rp", default=0)
            if min_price is None or max_price is None:
                st.error("Format harga tidak dikenali. Contoh: 200 juta / 2 m / 200000000")
                min_price = 0
                max_price = 0
            else:
                st.caption(f"Min: Rp {min_price:,} | Max: Rp {max_price:,}")
                if max_price and max_price < min_price:
                    st.warning("Harga Max < Harga Min — filter harga diabaikan.")

            st.markdown("**Lokasi Penyedia**")

            def _toggle_all():
                val = st.session_state.ek_select_all_loc
                for loc in KALSEL_LOCATIONS:
                    st.session_state[f"ek_loc_{loc}"] = val

            selected_locations = []
            st.checkbox("Pilih Semua Kalsel", key="ek_select_all_loc", on_change=_toggle_all)
            loc_cols = st.columns(2)
            for i, loc in enumerate(KALSEL_LOCATIONS):
                if f"ek_loc_{loc}" not in st.session_state:
                    st.session_state[f"ek_loc_{loc}"] = False
                with loc_cols[i % 2]:
                    if st.checkbox(loc, key=f"ek_loc_{loc}"):
                        selected_locations.append(loc)
            if selected_locations:
                st.caption(f"✅ {len(selected_locations)} wilayah dipilih")
            location_filter = ", ".join(selected_locations) if selected_locations else ""

        st.divider()
        run_btn = st.button("🚀 Jalankan Survei", type="primary", key="ek_run_btn", use_container_width=True)

        if run_btn:
            if not any(keywords):
                st.warning("Masukkan kata kunci terlebih dahulu.")
            else:
                st.session_state.ek_df_results = None
                st.session_state.ek_keywords_used = keywords[:]
                all_results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                start_time = time.time()

                for i, kw in enumerate(keywords):
                    status_text.text(f"🔎 Scraping ({i+1}/{len(keywords)}): {kw}...")
                    try:
                        res = search_inaproc(
                            kw,
                            use_api=use_api,
                            min_price=min_price,
                            max_price=max_price,
                            location_filter=location_filter,
                            max_pages=1 if use_api else (limit_per_keyword // 10 + 1),
                            enable_comparison=(not use_api),
                            limit_products=limit_per_keyword,
                            sort_order=sort_option,
                        )
                        all_results.extend(res[:limit_per_keyword])
                    except Exception as e:
                        st.error(f"Gagal scrape '{kw}': {e}")
                        st.code(traceback.format_exc())
                    progress_bar.progress(int(((i + 1) / len(keywords)) * 100))

                status_text.empty()
                progress_bar.empty()

                if all_results:
                    df = pd.DataFrame(all_results)
                    df['Is Termurah'] = False
                    for kw in keywords:
                        mask = df['Keyword'] == kw
                        if any(mask):
                            min_p = df[mask]['Harga'].min()
                            df.loc[mask & (df['Harga'] == min_p), 'Is Termurah'] = True
                    st.session_state.ek_df_results = df
                    st.session_state.ek_duration = time.time() - start_time
                    st.success(f"✅ {len(df)} produk ditemukan dalam {st.session_state.ek_duration:.1f}s — lihat tab **Hasil**")
                else:
                    st.warning("Tidak ditemukan produk untuk kriteria tersebut.")

    # ── Tab 2: Hasil ──────────────────────────────────────────────────────────
    with tab_hasil:
        df = st.session_state.get("ek_df_results")
        if df is None:
            st.info("Belum ada hasil. Jalankan survei di tab **Pencarian**.")
        else:
            keywords = st.session_state.get("ek_keywords_used", [])
            duration = st.session_state.get("ek_duration", 0)
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            _kpi_style = "border:1px solid rgba(49,51,63,.15);border-radius:12px;padding:10px 12px;"
            with kpi1:
                st.markdown(f"<div style='{_kpi_style}'><div style='font-size:.8rem;opacity:.65'>Keyword</div><div style='font-size:1.2rem;font-weight:650'>{len(keywords)}</div></div>", unsafe_allow_html=True)
            with kpi2:
                st.markdown(f"<div style='{_kpi_style}'><div style='font-size:.8rem;opacity:.65'>Total Produk</div><div style='font-size:1.2rem;font-weight:650'>{len(df)}</div></div>", unsafe_allow_html=True)
            with kpi3:
                source = df['Source'].iloc[0] if 'Source' in df.columns else "—"
                st.markdown(f"<div style='{_kpi_style}'><div style='font-size:.8rem;opacity:.65'>Mode</div><div style='font-size:1.2rem;font-weight:650'>{source}</div></div>", unsafe_allow_html=True)
            with kpi4:
                st.markdown(f"<div style='{_kpi_style}'><div style='font-size:.8rem;opacity:.65'>Durasi</div><div style='font-size:1.2rem;font-weight:650'>{duration:.1f}s</div></div>", unsafe_allow_html=True)

            st.markdown("")
            df_display = df.copy()
            kolom_sembunyi = {"Product ID", "Slug", "Seller ID", "Seller Slug", "Link 1", "Link 2", "Link 3", "Link 4"}
            kolom_tampil = [c for c in df_display.columns if c not in kolom_sembunyi]
            urutan = ["Keyword", "Nama Produk", "Brand", "Harga", "Total TKDN+BMP", "Status PDN", "Penyedia", "Lokasi", "Link", "Score", "Source", "Is Termurah"]
            kolom_akhir = [c for c in urutan if c in kolom_tampil]
            kolom_akhir += [c for c in kolom_tampil if c not in kolom_akhir]
            df_display = df_display[kolom_akhir]

            col_config = {
                "Link": st.column_config.LinkColumn("Link Produk"),
                "Gambar": st.column_config.ImageColumn("Preview"),
                "Is Termurah": st.column_config.CheckboxColumn("Termurah?"),
            }
            if "Harga" in df_display.columns:
                df_display["Harga"] = df_display["Harga"].apply(lambda x: f"Rp {int(x):,}" if not isinstance(x, str) else x)
                col_config["Harga"] = st.column_config.TextColumn("Harga")
            if "Total TKDN+BMP" in df_display.columns:
                col_config["Total TKDN+BMP"] = st.column_config.NumberColumn("TKDN+BMP", format="%.2f%%")

            st.dataframe(df_display, use_container_width=True, column_config=col_config, hide_index=True)

            if "Screenshot" in df.columns and any(df["Screenshot"].notna()):
                st.subheader("📸 Screenshot Produk")
                cols = st.columns(3)
                for idx, row in df[df["Screenshot"].notna()].iterrows():
                    price_label = row["Harga"] if isinstance(row["Harga"], str) else f"Rp {int(row['Harga']):,}"
                    with cols[idx % 3]:
                        st.image(row["Screenshot"], caption=f"{row['Penyedia']} — {price_label}", use_container_width=True)

    # ── Tab 3: Rekomendasi ────────────────────────────────────────────────────
    with tab_rekom:
        df = st.session_state.get("ek_df_results")
        if df is None:
            st.info("Belum ada hasil. Jalankan survei di tab **Pencarian**.")
        else:
            keywords = st.session_state.get("ek_keywords_used", [])
            st.markdown("##### ⭐ Produk Terbaik per Barang")
            for kw in keywords:
                kw_data = df[df["Keyword"] == kw].copy()
                if kw_data.empty:
                    continue
                sort_cols = ["Is Termurah"]
                if "Total TKDN+BMP" in kw_data.columns:
                    sort_cols.append("Total TKDN+BMP")
                kw_data = kw_data.sort_values(by=sort_cols, ascending=False)
                best = kw_data.iloc[0]
                price_label = best.get("Harga", 0)
                if not isinstance(price_label, str):
                    price_label = f"Rp {int(price_label):,}"
                with st.expander(f"'{kw}' → {best.get('Penyedia', '-')} ({price_label})"):
                    c1, c2 = st.columns([1, 3])
                    with c1:
                        if best.get("Gambar"):
                            st.image(best["Gambar"], use_container_width=True)
                    with c2:
                        st.write(f"**Nama**: {best.get('Nama Produk', '-')}")
                        if "Total TKDN+BMP" in best:
                            st.write(f"**TKDN+BMP**: {best['Total TKDN+BMP']:.2f}% ({best.get('Status PDN', 'N/A')})")
                        st.write(f"**Lokasi**: {best.get('Lokasi', '-')}")
                        if best.get("Link"):
                            st.markdown(f"[🔗 Buka di Katalog]({best['Link']})")

    # ── Tab 4: Export ─────────────────────────────────────────────────────────
    with tab_export:
        df = st.session_state.get("ek_df_results")
        if df is None:
            st.info("Belum ada hasil. Jalankan survei di tab **Pencarian**.")
        else:
            st.markdown("##### 📥 Export ke Excel (Lampiran DPP)")
            df_export = df.copy()
            df_export.insert(0, "No.", range(1, len(df_export) + 1))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_export.to_excel(writer, index=False, sheet_name="Survei Pasar")
            st.download_button(
                label="⬇️ Download Excel Survei Pasar",
                data=output.getvalue(),
                file_name=f"survei_pasar_{timestamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="ek_download_excel",
                use_container_width=True,
            )
            st.caption(f"File: survei_pasar_{timestamp}.xlsx | {len(df_export)} baris")
