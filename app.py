"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import sys
import threading
import time

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SPSE_BASE_URL, DOWNLOAD_DIR
import spse_browser

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

    url_aktif = spse_browser.get_url()
    if url_aktif:
        st.success("Browser terhubung")

        # Pilih tab aktif
        tabs = spse_browser.daftar_tab()
        if tabs:
            tab_labels = [f"[{t['index']}] {t['title'][:40] or t['url'][:40]}" for t in tabs]
            selected = st.selectbox("Tab target:", tab_labels, key="tab_selector")
            selected_idx = tab_labels.index(selected)
            spse_browser.pilih_tab(selected_idx)

        st.caption(url_aktif[:60] + "..." if len(url_aktif) > 60 else url_aktif)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Refresh", use_container_width=True):
                page = spse_browser.halaman_aktif()
                if page:
                    page.reload()
                    st.rerun()
        with col2:
            if st.button("❌ Tutup", use_container_width=True):
                spse_browser.tutup_browser()
                st.rerun()
    else:
        st.info("Chrome SPSE belum terhubung")
        st.markdown(
            "**Langkah 1:** Buka file ini dulu:\n\n"
            "`Asisten_Pokja/Buka Chrome SPSE.bat`\n\n"
            "*(Chrome baru akan terbuka khusus SPSE — jangan tutup)*"
        )
        if st.button("🌐 Hubungkan ke Chrome SPSE", type="primary", use_container_width=True):
            try:
                with st.spinner("Menghubungkan..."):
                    spse_browser.buka_browser(SPSE_BASE_URL)
                st.success("Terhubung!")
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))

    st.divider()

    url_custom = st.text_input("Navigasi ke URL", placeholder="https://spse.tapinkab.go.id/...")
    if st.button("Pergi", use_container_width=True):
        if url_custom:
            spse_browser.navigasi(url_custom)
            st.rerun()

    if st.button("📸 Screenshot", use_container_width=True):
        try:
            img_bytes = spse_browser.screenshot()
            st.session_state["last_screenshot"] = img_bytes
            st.rerun()
        except Exception as e:
            st.error(str(e))

    if "last_screenshot" in st.session_state:
        st.image(st.session_state["last_screenshot"], caption="Screenshot terakhir")


# ============================================================
# Tabs
# ============================================================

tab1, tab2, tab3 = st.tabs(["⬇️ Download File", "✏️ Auto-Fill Form", "⬆️ Upload Dokumen"])


# ============================================================
# Tab 1: Download File
# ============================================================

with tab1:
    st.subheader("Download File dari Halaman SPSE")
    st.markdown(
        "Navigasikan browser ke halaman paket yang diinginkan (via sidebar), "
        "lalu klik **Scan & Download** untuk mengambil semua file di halaman tersebut."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        url_paket = st.text_input(
            "URL Halaman Paket (opsional)",
            placeholder="https://spse.tapinkab.go.id/266/lelang/...",
            help="Jika diisi, browser akan navigasi ke URL ini sebelum scan. Kosongkan untuk pakai halaman aktif.",
        )
    with col2:
        st.write("")
        st.write("")
        pindah_dan_scan = st.button("🔍 Scan & Download", type="primary", use_container_width=True)

    with st.expander("🔧 Debug — Lihat Semua Link di Halaman"):
        if st.button("Ambil Semua Link (max 60)"):
            page = spse_browser.halaman_aktif()
            if not page:
                st.error("Browser belum terhubung.")
            else:
                data = spse_browser._run(page.evaluate("""() => ({
                    url: window.location.href,
                    links: Array.from(document.querySelectorAll('a[href]'))
                        .slice(0, 60)
                        .map(a => ({ text: a.innerText.trim().substring(0,80), href: a.href }))
                })"""))
                st.write(f"**URL:** {data['url']}")
                for lnk in data["links"]:
                    st.write(f"- `{lnk['href']}` → {lnk['text']}")

    if pindah_dan_scan:
        if not spse_browser.get_url():
            st.error("Browser belum terbuka. Buka browser di sidebar dulu.")
        else:
            if url_paket:
                with st.spinner(f"Navigasi ke {url_paket}..."):
                    spse_browser.navigasi(url_paket)

            # Scan link
            with st.spinner("Scanning link file..."):
                links = spse_browser.scan_link_file()

            if not links:
                st.warning("Tidak ada link file ditemukan di halaman ini.")
                st.info("Tip: Pastikan sudah login dan berada di halaman yang benar.")
            else:
                st.write(f"**{len(links)} file ditemukan:**")
                for lnk in links:
                    st.write(f"- {lnk['text'] or '(tanpa nama)'} → `{lnk['href'][:80]}`")

                if st.button("⬇️ Download Semua", type="primary"):
                    progress = st.progress(0, "Memulai download...")
                    def cb(pct, txt): progress.progress(pct, txt)

                    hasil = spse_browser.download_semua_dari_halaman(progress_callback=cb)
                    progress.empty()

                    st.session_state["hasil_download"] = hasil
                    st.rerun()

    if "hasil_download" in st.session_state:
        st.subheader("Hasil Download")
        hasil = st.session_state["hasil_download"]
        for item in hasil:
            icon = "✅" if item["status"] == "OK" else "❌"
            st.write(f"{icon} **{item['nama']}** — {item['status']}")

        if st.button("📂 Buka Folder Download"):
            os.startfile(DOWNLOAD_DIR)


# ============================================================
# Tab 2: Auto-Fill Form
# ============================================================

with tab2:
    st.subheader("Auto-Fill Form SPSE")
    st.markdown(
        "Fitur ini dibangun **bertahap** — setelah kamu navigasi ke form yang diinginkan "
        "di browser, gunakan tombol di bawah untuk inspeksi form dan isi otomatis."
    )

    if st.button("🔍 Inspeksi Form (Scan Input Fields)"):
        if not spse_browser.get_url():
            st.error("Browser belum terbuka.")
        else:
            fields = spse_browser.scan_form_fields()
            if fields:
                st.write(f"**{len(fields)} input field ditemukan:**")
                st.json(fields)
                st.session_state["form_fields"] = fields
            else:
                st.warning("Tidak ada input field ditemukan di halaman ini.")

    if "form_fields" in st.session_state:
        st.divider()
        st.markdown("**Isi nilai untuk tiap field:**")

        fill_data = {}
        for f in st.session_state["form_fields"]:
            label = f.get("name") or f.get("id") or f.get("placeholder") or "(tanpa nama)"
            selector = f"[name='{f['name']}']" if f["name"] else f"#{f['id']}" if f["id"] else None
            if selector:
                nilai = st.text_input(f"{label} ({f['tag']})", value=f.get("value", ""), key=f"fill_{label}")
                if nilai:
                    fill_data[selector] = nilai

        if st.button("✏️ Isi Form Otomatis", type="primary"):
            if not fill_data:
                st.warning("Tidak ada nilai yang diisi.")
            else:
                errors = []
                for selector, nilai in fill_data.items():
                    try:
                        spse_browser.isi(selector, nilai)
                    except Exception as e:
                        errors.append(f"{selector}: {e}")
                if errors:
                    st.error("Beberapa field gagal diisi:\n" + "\n".join(errors))
                else:
                    st.success(f"{len(fill_data)} field berhasil diisi!")

        if st.button("📸 Screenshot Setelah Isi"):
            img = spse_browser.screenshot()
            st.image(img, caption="Form setelah diisi")


# ============================================================
# Tab 3: Upload Dokumen
# ============================================================

with tab3:
    st.subheader("Upload Dokumen ke SPSE")
    st.markdown(
        "Navigasikan browser ke halaman upload, "
        "scan input file yang tersedia, lalu pilih file untuk diupload."
    )

    if st.button("🔍 Scan Input File Upload"):
        if not spse_browser.get_url():
            st.error("Browser belum terbuka.")
        else:
            file_inputs = spse_browser.scan_file_inputs()
            if file_inputs:
                st.write(f"**{len(file_inputs)} file input ditemukan:**")
                st.json(file_inputs)
                st.session_state["file_inputs"] = file_inputs
            else:
                st.warning("Tidak ada input file ditemukan. Pastikan berada di halaman upload.")

    if "file_inputs" in st.session_state:
        st.divider()
        file_inputs = st.session_state["file_inputs"]

        for fi in file_inputs:
            label = fi.get("name") or fi.get("id") or "(tanpa nama)"
            selector = f"[name='{fi['name']}']" if fi["name"] else f"#{fi['id']}" if fi["id"] else None
            accept = fi.get("accept", "")

            uploaded = st.file_uploader(
                f"File untuk: **{label}** {('('+accept+')') if accept else ''}",
                key=f"upload_{label}",
                accept_multiple_files=fi.get("multiple", False),
            )

            if uploaded and selector:
                if st.button(f"⬆️ Upload ke '{label}'", key=f"btn_upload_{label}"):
                    # Simpan file sementara
                    files_to_upload = uploaded if isinstance(uploaded, list) else [uploaded]
                    paths = []
                    for uf in files_to_upload:
                        tmp_path = os.path.join(DOWNLOAD_DIR, uf.name)
                        with open(tmp_path, "wb") as f:
                            f.write(uf.getbuffer())
                        paths.append(tmp_path)

                    try:
                        spse_browser.set_input_files(selector, paths)
                        st.success(f"{len(paths)} file berhasil di-set ke input '{label}'!")
                        st.info("Jangan lupa klik tombol Submit/Kirim di browser untuk mengirim.")
                    except Exception as e:
                        st.error(f"Gagal upload: {e}")
