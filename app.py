"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import sys
import threading
import time

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SPSE_BASE_URL, DOWNLOAD_DIR
import spse_browser
import ldk_engine
import ldk_config

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

tab1, tab2, tab3, tab4 = st.tabs([
    "⬇️ Download File", "✏️ Auto-Fill Form", "⬆️ Upload Dokumen", "📋 LDK Auto-fill"
])


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


# ============================================================
# Tab 4: LDK Auto-fill
# ============================================================

with tab4:
    st.subheader("LDK Auto-fill — Persyaratan Kualifikasi")
    st.markdown(
        "Bot otomatis mencentang dan mengisi persyaratan kualifikasi "
        "sesuai template konstruksi Usaha Kecil."
    )

    # ── Deteksi ID paket dari URL aktif ──────────────────────────────────────
    paket_id = spse_browser.get_paket_id() if spse_browser.get_url() else None
    ldk_url_auto = (
        f"{SPSE_BASE_URL}dokumen/{paket_id}/ldk" if paket_id else None
    )

    if ldk_url_auto:
        st.info(f"ID Paket terdeteksi dari URL aktif: **{paket_id}**")
    else:
        st.warning("Buka halaman paket di browser terlebih dahulu agar ID terdeteksi otomatis.")

    # Input manual sebagai fallback / override
    with st.expander("🔧 Override URL LDK (opsional)"):
        ldk_url_manual = st.text_input(
            "URL Halaman LDK",
            value=ldk_url_auto or "",
            placeholder="https://spse.inaproc.id/tapinkab/dokumen/[ID]/ldk",
            key="ldk_url_manual",
        )
        ldk_url_final = ldk_url_manual or ldk_url_auto
    ldk_url_final = ldk_url_manual if "ldk_url_manual" in st.session_state and st.session_state["ldk_url_manual"] else ldk_url_auto

    # ── Konfigurasi teks kinerja (bisa diedit di UI) ─────────────────────────
    with st.expander("⚙️ Teks Kinerja Penyedia (konfirmasi sekali saja)"):
        kinerja_text = st.text_area(
            "Teks yang diisi pada field kinerja:",
            value=ldk_config.CHECK_AND_FILL[0]["text"],
            height=100,
            key="kinerja_text_override",
        )
        st.caption("Teks ini disimpan dalam sesi — edit jika perlu penyesuaian.")

    st.divider()

    # ── Tombol utama: Push LDK ────────────────────────────────────────────────
    col1, col2 = st.columns([2, 1])
    with col1:
        push_clicked = st.button(
            "🚀 Push LDK ke SPSE",
            type="primary",
            use_container_width=True,
            disabled=not bool(ldk_url_final),
        )
    with col2:
        scan_only = st.button(
            "🔍 Scan Saja (Preview)",
            use_container_width=True,
            disabled=not bool(ldk_url_final),
        )

    # ── Scan / Push ───────────────────────────────────────────────────────────
    if push_clicked or scan_only:
        if not spse_browser.get_url():
            st.error("Browser belum terhubung. Hubungkan di sidebar dulu.")
        elif not ldk_url_final:
            st.error("URL LDK tidak diketahui. Buka halaman paket di browser atau isi URL manual.")
        else:
            # Override teks kinerja dari UI jika ada
            ldk_config.CHECK_AND_FILL[0]["text"] = kinerja_text

            with st.spinner(f"Membuka halaman LDK {ldk_url_final} ..."):
                try:
                    spse_browser.navigasi_ldk(ldk_url_final)
                except Exception as e:
                    st.error(f"Gagal membuka halaman LDK: {e}")
                    st.stop()

            with st.spinner("Scanning form..."):
                try:
                    form_info = ldk_engine.scan_ldk_form()
                    classified = ldk_engine.classify_checkboxes(form_info)
                except Exception as e:
                    st.error(f"Gagal scan form: {e}")
                    st.stop()

            st.session_state["ldk_form"] = form_info
            st.session_state["ldk_classified"] = classified

    # ── Preview hasil scan ────────────────────────────────────────────────────
    if "ldk_classified" in st.session_state:
        classified = st.session_state["ldk_classified"]
        form_info  = st.session_state["ldk_form"]

        st.caption(f"Endpoint: `{form_info.get('action', '?')}` | Method: `{form_info.get('method', '?')}`")
        st.caption(f"CSRF: `{'ada ✅' if form_info.get('csrf') else 'tidak ditemukan ⚠️'}`")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Locked",      len(classified["locked"]))
        c2.metric("Auto-check",  len(classified["auto_check"]))
        c3.metric("Check+Fill",  len(classified["check_and_fill"]))
        c4.metric("Skip",        len(classified["skip"]))
        c5.metric("Unknown",     len(classified["unknown"]))

        with st.expander("✅ Auto-check"):
            for cb in classified["auto_check"]:
                st.write(f"• {cb['label'][:120]}")

        with st.expander("✅ Check + Fill"):
            for cb, cfg in classified["check_and_fill"]:
                st.write(f"• {cb['label'][:100]}")
                st.caption(f"  → Teks: {cfg['text'][:100]}…")

        with st.expander("🔒 Locked (dikelola SPSE, tidak disentuh)"):
            for cb in classified["locked"]:
                st.write(f"• {cb['label'][:120] or '(tanpa label)'}")

        with st.expander("⬜ Skip"):
            for cb in classified["skip"]:
                st.write(f"• {cb['label'][:120]}")

        if classified["unknown"]:
            with st.expander("❓ Unknown (tidak dikenali — tidak di-submit)"):
                for cb in classified["unknown"]:
                    fallback = f"name={cb['name']} value={cb['value']}"
                    st.write(f"• {cb['label'][:120] or fallback}")

        # Payload preview
        with st.expander("🔧 Preview Payload yang akan dikirim"):
            payload_preview = ldk_engine.build_payload(form_info, classified)
            st.json(payload_preview)

        st.divider()

        # Tombol submit (muncul setelah scan)
        if push_clicked:
            # Sudah navigate + scan → langsung submit
            payload = ldk_engine.build_payload(form_info, classified)
            with st.spinner("Mengirim ke SPSE..."):
                try:
                    result = ldk_engine.submit_ldk(form_info, payload)
                except Exception as e:
                    st.error(f"Error saat submit: {e}")
                    st.stop()

            if result["ok"]:
                st.success(
                    f"✅ Berhasil! Status {result['status']} — "
                    "silakan refresh halaman LDK di browser untuk verifikasi."
                )
            else:
                st.error(f"❌ Gagal. Status {result['status']}")

            with st.expander("Response body"):
                st.code(result["body"][:3000])

        elif scan_only:
            # Hanya preview — tombol submit manual
            n_check = len(classified["auto_check"]) + len(classified["check_and_fill"])
            if st.button(
                f"📤 Submit {n_check} item ke SPSE",
                type="primary",
                key="ldk_submit_manual",
            ):
                payload = ldk_engine.build_payload(form_info, classified)
                with st.spinner("Mengirim ke SPSE..."):
                    try:
                        result = ldk_engine.submit_ldk(form_info, payload)
                    except Exception as e:
                        st.error(f"Error saat submit: {e}")
                        st.stop()

                if result["ok"]:
                    st.success(
                        f"✅ Berhasil! Status {result['status']} — "
                        "silakan refresh halaman LDK di browser untuk verifikasi."
                    )
                else:
                    st.error(f"❌ Gagal. Status {result['status']}")

                with st.expander("Response body"):
                    st.code(result["body"][:3000])
