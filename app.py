"""Asisten Pokja — SPSE Automation (Streamlit)."""

import os
import sys
import threading
import time
from datetime import datetime, timedelta

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SPSE_BASE_URL, DOWNLOAD_DIR
import spse_browser
import ldk_engine
import ldk_config
import checklist_engine
import masa_berlaku_engine
import penjelasan_engine
import penjelasan_config
import jadwal_engine
import jadwal_config

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

    st.divider()

    url_custom = st.text_input("Navigasi ke URL", placeholder="https://spse.tapinkab.go.id/...", key="nav_url")
    if st.button("Pergi", use_container_width=True, key="nav_pergi"):
        if url_custom:
            spse_browser.navigasi(url_custom)
            st.rerun()

    if st.button("📸 Screenshot", use_container_width=True, key="sidebar_screenshot"):
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

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "⬇️ Download File", "✏️ Auto-Fill Form", "⬆️ Upload Dokumen",
    "📋 LDK Auto-fill", "☑️ Checklist Penawaran", "⏳ Masa Berlaku",
    "💬 Penjelasan", "📅 Auto-Fill Jadwal",
])

# Auto-start scheduler saat app dibuka (daemon thread, jalan terus)
penjelasan_engine.start_scheduler()


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
        pindah_dan_scan = st.button("🔍 Scan & Download", type="primary", use_container_width=True, key="tab1_scan_download")

    with st.expander("🔧 Debug — Lihat Semua Link di Halaman"):
        if st.button("Ambil Semua Link (max 60)", key="tab1_get_links"):
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

    if st.button("🔍 Inspeksi Form (Scan Input Fields)", key="tab2_scan_form"):
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

        if st.button("✏️ Isi Form Otomatis", type="primary", key="tab2_fill_form"):
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

        if st.button("📸 Screenshot Setelah Isi", key="tab2_screenshot"):
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

    if st.button("🔍 Scan Input File Upload", key="tab3_scan_files"):
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

    # ── Konfigurasi Izin Usaha (WAJIB) ───────────────────────────────────────
    with st.expander("📋 Izin Usaha (wajib diisi)", expanded=True):
        col_i1, col_i2 = st.columns(2)
        with col_i1:
            ijin_nama = st.text_input(
                "Jenis Izin *",
                value=ldk_config.IJIN_USAHA_DEFAULT["nama"],
                key="ijin_nama",
            )
        with col_i2:
            ijin_klas = st.text_input(
                "Bidang Usaha / Klasifikasi *",
                value=ldk_config.IJIN_USAHA_DEFAULT["klasifikasi"],
                key="ijin_klas",
            )
        st.caption("Contoh: 'Izin Usaha' + '41001 - Konstruksi Umum'")

    st.divider()

    # ── Tombol utama: Push LDK ────────────────────────────────────────────────
    col1, col2 = st.columns([2, 1])
    with col1:
        push_clicked = st.button(
            "🚀 Push LDK ke SPSE",
            type="primary",
            use_container_width=True,
            disabled=not bool(ldk_url_final),
            key="ldk_push",
        )
    with col2:
        scan_only = st.button(
            "🔍 Scan Saja (Preview)",
            use_container_width=True,
            disabled=not bool(ldk_url_final),
            key="ldk_scan",
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
            ijin_usaha_cfg = {"nama": ijin_nama, "klasifikasi": ijin_klas}
            payload_preview = ldk_engine.build_payload(form_info, classified, ijin_usaha_cfg)
            st.json(payload_preview)

        st.divider()

        # Tombol submit (muncul setelah scan)
        if push_clicked:
            # Sudah navigate + scan → langsung submit
            ijin_usaha_cfg = {"nama": ijin_nama, "klasifikasi": ijin_klas}
            payload = ldk_engine.build_payload(form_info, classified, ijin_usaha_cfg)
            with st.spinner("Mengirim ke SPSE..."):
                try:
                    result = ldk_engine.submit_ldk(form_info, payload, ijin_usaha_cfg)
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


# ============================================================
# Tab 5: Checklist Dokumen Penawaran
# ============================================================

with tab5:
    st.subheader("Checklist Dokumen Penawaran")
    st.markdown(
        "Bot otomatis mencentang dokumen penawaran sesuai template "
        "konstruksi Usaha Kecil (Administrasi + Teknis + Harga)."
    )

    # ── Deteksi ID paket dari URL aktif ──────────────────────────────────────
    ck_paket_id = spse_browser.get_paket_id() if spse_browser.get_url() else None
    ck_url_auto = (
        f"{SPSE_BASE_URL}dokumen/{ck_paket_id}/checklist" if ck_paket_id else None
    )

    if ck_url_auto:
        st.info(f"ID Paket terdeteksi dari URL aktif: **{ck_paket_id}**")
    else:
        st.warning("Buka halaman paket di browser terlebih dahulu agar ID terdeteksi otomatis.")

    with st.expander("🔧 Override URL Checklist (opsional)"):
        ck_url_manual = st.text_input(
            "URL Halaman Checklist",
            value=ck_url_auto or "",
            placeholder="https://spse.inaproc.id/tapinkab/dokumen/[ID]/checklist",
            key="ck_url_manual",
        )
    ck_url_final = (
        st.session_state.get("ck_url_manual") or ck_url_auto
    )

    st.divider()

    col1, col2 = st.columns([2, 1])
    with col1:
        ck_push = st.button(
            "🚀 Push Checklist ke SPSE",
            type="primary",
            use_container_width=True,
            disabled=not bool(ck_url_final),
            key="ck_push",
        )
    with col2:
        ck_scan_only = st.button(
            "🔍 Scan Saja (Preview)",
            use_container_width=True,
            disabled=not bool(ck_url_final),
            key="ck_scan",
        )

    if ck_push or ck_scan_only:
        if not spse_browser.get_url():
            st.error("Browser belum terhubung. Hubungkan di sidebar dulu.")
        elif not ck_url_final:
            st.error("URL Checklist tidak diketahui. Buka halaman paket di browser atau isi URL manual.")
        else:
            with st.spinner(f"Membuka halaman checklist {ck_url_final} ..."):
                try:
                    spse_browser.navigasi_ldk(ck_url_final)
                except Exception as e:
                    st.error(f"Gagal membuka halaman: {e}")
                    st.stop()

            with st.spinner("Scanning form..."):
                try:
                    ck_form = checklist_engine.scan_checklist_form()
                    ck_classified = checklist_engine.classify_checkboxes(ck_form)
                except Exception as e:
                    st.error(f"Gagal scan form: {e}")
                    st.stop()

            st.session_state["ck_form"] = ck_form
            st.session_state["ck_classified"] = ck_classified

    if "ck_classified" in st.session_state:
        ck_classified = st.session_state["ck_classified"]
        ck_form       = st.session_state["ck_form"]

        st.caption(f"Endpoint: `{ck_form.get('action', '?')}` | Method: `{ck_form.get('method', '?')}`")
        st.caption(f"CSRF: `{'ada ✅' if ck_form.get('csrf') else 'tidak ditemukan ⚠️'}`")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Locked",     len(ck_classified["locked"]))
        c2.metric("Auto-check", len(ck_classified["auto_check"]))
        c3.metric("Skip",       len(ck_classified["skip"]))
        c4.metric("Unknown",    len(ck_classified["unknown"]))

        with st.expander("✅ Auto-check"):
            for cb in ck_classified["auto_check"]:
                st.write(f"• {cb['label'][:120]}")

        with st.expander("🔒 Locked (dikelola SPSE, tidak disentuh)"):
            for cb in ck_classified["locked"]:
                st.write(f"• {cb['label'][:120] or '(tanpa label)'}")

        with st.expander("⬜ Skip (usaha besar / tidak relevan)"):
            for cb in ck_classified["skip"]:
                st.write(f"• {cb['label'][:120]}")

        if ck_classified["unknown"]:
            with st.expander("❓ Unknown (tidak dikenali — tidak di-submit)"):
                for cb in ck_classified["unknown"]:
                    fallback = f"name={cb['name']} value={cb['value']}"
                    st.write(f"• {cb['label'][:120] or fallback}")

        with st.expander("🔧 Preview Payload yang akan dikirim"):
            ck_payload_preview = checklist_engine.build_payload(ck_form, ck_classified)
            st.json(ck_payload_preview)

        st.divider()

        def _do_submit_checklist():
            payload = checklist_engine.build_payload(ck_form, ck_classified)
            with st.spinner("Mengirim ke SPSE..."):
                try:
                    result = checklist_engine.submit_checklist(ck_form, payload)
                except Exception as e:
                    st.error(f"Error saat submit: {e}")
                    return
            if result["ok"]:
                st.success(
                    f"✅ Berhasil! Status {result['status']} — "
                    "silakan refresh halaman checklist di browser untuk verifikasi."
                )
            else:
                st.error(f"❌ Gagal. Status {result['status']}")
            with st.expander("Response body"):
                st.code(result["body"][:3000])

        if ck_push:
            _do_submit_checklist()
        elif ck_scan_only:
            n_check = len(ck_classified["auto_check"])
            if st.button(
                f"📤 Submit {n_check} item ke SPSE",
                type="primary",
                key="ck_submit_manual",
            ):
                _do_submit_checklist()


# ============================================================
# Tab 6: Masa Berlaku Penawaran
# ============================================================

with tab6:
    st.subheader("Masa Berlaku Penawaran — Auto-fill Edit Lelang")
    st.markdown(
        "Navigasikan browser ke halaman **edit lelang** (`/lelang/[ID]/edit`), "
        "lalu scan form untuk deteksi otomatis field masa berlaku. "
        "Bot akan set **40 hari** sejak batas akhir pemasukan dokumen."
    )

    # ── Deteksi URL edit dari URL aktif ──────────────────────────────────────
    mb_paket_id = spse_browser.get_paket_id() if spse_browser.get_url() else None
    mb_url_auto = (
        f"{SPSE_BASE_URL}lelang/{mb_paket_id}/edit" if mb_paket_id else None
    )

    mb_url_aktif = spse_browser.get_url() if spse_browser.get_url() else ""
    is_edit_page = "/edit" in mb_url_aktif

    if is_edit_page:
        st.success(f"Browser sudah di halaman edit: `{mb_url_aktif[:80]}`")
    elif mb_url_auto:
        st.info(f"ID Paket terdeteksi: **{mb_paket_id}** — belum di halaman edit")
    else:
        st.warning("Buka halaman paket di browser agar ID terdeteksi otomatis.")

    with st.expander("🔧 Override URL Edit Lelang (opsional)"):
        mb_url_manual = st.text_input(
            "URL Halaman Edit",
            value=mb_url_aktif if is_edit_page else (mb_url_auto or ""),
            placeholder="https://spse.inaproc.id/tapinkab/lelang/[ID]/edit",
            key="mb_url_manual",
        )
    mb_url_final = st.session_state.get("mb_url_manual") or mb_url_auto

    # Nilai hari (bisa diubah user)
    mb_nilai_hari = st.number_input(
        "Nilai Masa Berlaku (hari)",
        min_value=1, max_value=365, value=40, step=1,
        help="Default 40 hari — standar konstruksi usaha kecil",
    )

    st.divider()

    col1, col2 = st.columns([2, 1])
    with col1:
        mb_push = st.button(
            "🚀 Set Masa Berlaku ke SPSE",
            type="primary",
            use_container_width=True,
            disabled=not bool(mb_url_final),
            key="mb_push",
        )
    with col2:
        mb_scan_only = st.button(
            "🔍 Scan Saja (Inspect Form)",
            use_container_width=True,
            disabled=not bool(mb_url_final),
            key="mb_scan",
        )

    if mb_push or mb_scan_only:
        if not spse_browser.get_url():
            st.error("Browser belum terhubung. Hubungkan di sidebar dulu.")
            st.stop()
        if not mb_url_final:
            st.error("URL edit lelang tidak diketahui.")
            st.stop()

        if not is_edit_page:
            with st.spinner(f"Membuka halaman edit {mb_url_final} ..."):
                try:
                    spse_browser.navigasi(mb_url_final)
                    import time; time.sleep(1)  # beri waktu render
                except Exception as e:
                    st.error(f"Gagal membuka halaman: {e}")
                    st.stop()

        with st.spinner("Scanning form..."):
            try:
                mb_form = masa_berlaku_engine.scan_edit_form()
                mb_detected = masa_berlaku_engine.auto_detect_fields(mb_form)
            except Exception as e:
                st.error(f"Gagal scan form: {e}")
                st.stop()

        st.session_state["mb_form"]     = mb_form
        st.session_state["mb_detected"] = mb_detected

    # ── Preview hasil scan ────────────────────────────────────────────────────
    if "mb_detected" in st.session_state:
        mb_form     = st.session_state["mb_form"]
        mb_detected = st.session_state["mb_detected"]

        st.caption(f"Endpoint: `{mb_form.get('action', '?')}` | Method: `{mb_form.get('method', '?')}`")
        st.caption(f"CSRF: `{'ada ✅' if mb_form.get('csrf') else 'tidak ditemukan ⚠️'}`")

        if mb_detected["confident"]:
            st.success("Field masa berlaku berhasil terdeteksi otomatis!")
        else:
            st.warning("Tidak terdeteksi otomatis — cek manual di bawah dan gunakan override.")

        # Deteksi otomatis
        col_r, col_n = st.columns(2)
        with col_r:
            st.markdown("**Radio Field:**")
            if mb_detected["radio_name"]:
                st.code(f"name = {mb_detected['radio_name']}\nvalue = {mb_detected['radio_value_40']}")
            else:
                st.info("Tidak ada radio group terdeteksi")

        with col_n:
            st.markdown("**Number Field:**")
            if mb_detected["number_name"]:
                st.code(f"name = {mb_detected['number_name']}")
            else:
                st.info("Tidak ada number field terdeteksi")

        # Semua radio groups — untuk inspeksi manual
        with st.expander("🔍 Semua Radio Buttons di Form"):
            for grp_name, options in mb_detected["radio_groups"].items():
                st.markdown(f"**Group: `{grp_name}`**")
                for opt in options:
                    check_icon = "🔵" if opt["checked"] else "⚪"
                    dis_icon   = " 🔒" if opt["disabled"] else ""
                    st.write(f"  {check_icon}{dis_icon} value=`{opt['value']}` — {opt['label'][:100]}")

        # Semua field lainnya
        with st.expander("🔍 Semua Input Fields di Form"):
            for f in mb_form.get("fields", []):
                if f["type"] not in ("radio",):
                    st.write(f"[{f['type']}] `{f['name']}` = `{f['value'][:60] if f.get('value') else ''}` — {f.get('label','')[:80]}")

        # Override manual
        with st.expander("⚙️ Override Manual (jika auto-detect salah)"):
            st.caption("Isi hanya jika deteksi otomatis keliru. Kosongkan untuk pakai auto-detect.")
            mb_radio_override  = st.text_input("Radio name (override)", key="mb_radio_name_override")
            mb_rval_override   = st.text_input("Radio value untuk 40 hari (override)", key="mb_radio_val_override")
            mb_number_override = st.text_input("Number field name (override)", key="mb_number_name_override")

        # Payload preview
        with st.expander("🔧 Preview Payload yang akan dikirim"):
            payload_preview = masa_berlaku_engine.build_payload(
                form_info   = mb_form,
                detected    = mb_detected,
                nilai_hari  = int(mb_nilai_hari),
                radio_name  = st.session_state.get("mb_radio_name_override") or None,
                radio_value = st.session_state.get("mb_radio_val_override")  or None,
                number_name = st.session_state.get("mb_number_name_override") or None,
            )
            st.json(payload_preview)

        st.divider()

        def _do_submit_masa_berlaku():
            payload = masa_berlaku_engine.build_payload(
                form_info   = mb_form,
                detected    = mb_detected,
                nilai_hari  = int(mb_nilai_hari),
                radio_name  = st.session_state.get("mb_radio_name_override") or None,
                radio_value = st.session_state.get("mb_radio_val_override")  or None,
                number_name = st.session_state.get("mb_number_name_override") or None,
            )
            with st.spinner("Mengirim ke SPSE..."):
                try:
                    result = masa_berlaku_engine.submit_masa_berlaku(mb_form, payload)
                except Exception as e:
                    st.error(f"Error saat submit: {e}")
                    return
            if result["ok"]:
                st.success(
                    f"✅ Berhasil! Status {result['status']} — "
                    "silakan verifikasi di browser bahwa masa berlaku sudah tersimpan."
                )
            else:
                st.error(f"❌ Gagal. Status {result['status']}")
            with st.expander("Response body"):
                st.code(result["body"][:3000])

        if mb_push:
            _do_submit_masa_berlaku()
        elif mb_scan_only:
            if st.button(
                f"📤 Submit Masa Berlaku {int(mb_nilai_hari)} Hari ke SPSE",
                type="primary",
                key="mb_submit_manual",
                disabled=not mb_detected["confident"],
            ):
                _do_submit_masa_berlaku()


# ============================================================
# Tab 7: Jadwal Penjelasan
# ============================================================

with tab7:
    st.subheader("Jadwal Pemberian Penjelasan — Auto POST")
    st.markdown(
        "Bot akan **POST penjelasan otomatis** tepat saat jadwal pemberian penjelasan dimulai. "
        "Pastikan Chrome SPSE dan Streamlit ini tetap terbuka saat jadwal tiba."
    )

    # ── Status scheduler ──────────────────────────────────────────────────────
    sched_running = penjelasan_engine.is_scheduler_running()
    if sched_running:
        st.success("🟢 Scheduler aktif — monitoring setiap 15 detik")
    else:
        st.error("🔴 Scheduler tidak aktif")
        if st.button("▶️ Aktifkan Scheduler"):
            penjelasan_engine.start_scheduler()
            st.rerun()

    st.divider()

    # ── Form tambah paket ─────────────────────────────────────────────────────
    st.markdown("### Daftarkan Paket")

    with st.form("form_tambah_penjelasan"):
        col_id, col_nama = st.columns([1, 2])
        with col_id:
            input_paket_ids = st.text_area(
                "ID Paket (satu per baris, bisa banyak)",
                placeholder="10096884000\n10096884001\n10096884002",
                height=120,
                help="Salin dari URL: /lelang/[ID]/jadwal",
            )
        with col_nama:
            input_nama = st.text_input(
                "Nama / Keterangan Paket (opsional)",
                placeholder="Paket Jalan Kabupaten, dll.",
            )

        jenis_options = {v: k for k, v in penjelasan_config.JENIS_PAKET.items()}
        jenis_label = st.selectbox(
            "Jenis Penjelasan",
            options=list(jenis_options.keys()),
        )
        jenis_key = jenis_options[jenis_label]

        col_dt1, col_dt2 = st.columns(2)
        with col_dt1:
            waktu_scan = st.checkbox(
                "Scan jadwal otomatis dari SPSE",
                value=True,
                help="Navigasi ke /lelang/[ID]/jadwal untuk ambil datetime penjelasan",
            )
        with col_dt2:
            waktu_manual = st.text_input(
                "Atau isi waktu manual (dd/mm/yyyy HH:MM)",
                placeholder="10/04/2026 10:00",
                disabled=waktu_scan,
            )

        with st.expander("✏️ Override teks penjelasan (opsional — default pakai template)"):
            teks_override_input = st.text_area(
                "Teks penjelasan custom",
                value="",
                height=200,
                placeholder="Kosongkan untuk pakai template bawaan",
            )

        submitted = st.form_submit_button("➕ Daftarkan", type="primary")

    if submitted:
        paket_ids_raw = [x.strip() for x in input_paket_ids.strip().splitlines() if x.strip()]
        if not paket_ids_raw:
            st.error("Isi minimal satu ID paket.")
        elif not waktu_scan and not waktu_manual:
            st.error("Isi waktu manual atau centang scan otomatis.")
        elif not spse_browser.get_url() and waktu_scan:
            st.error("Browser belum terhubung — tidak bisa scan jadwal.")
        else:
            teks_ov = teks_override_input.strip() or None
            nama    = input_nama.strip() or f"Paket {', '.join(paket_ids_raw)}"

            for paket_id in paket_ids_raw:
                waktu_fire = None

                if waktu_scan:
                    with st.spinner(f"Scan jadwal paket {paket_id}..."):
                        try:
                            jadwal_list = penjelasan_engine.parse_jadwal(paket_id)
                            if jadwal_list:
                                # Untuk seleksi_kualifikasi → ambil baris pertama
                                # Untuk seleksi_seleksi → baris kedua (jika ada)
                                idx = 1 if (jenis_key == "seleksi_seleksi" and len(jadwal_list) >= 2) else 0
                                waktu_fire = jadwal_list[idx]["mulai_dt"]
                                st.success(
                                    f"Paket {paket_id}: jadwal ditemukan → "
                                    f"{waktu_fire.strftime('%d/%m/%Y %H:%M')} WIB"
                                )
                            else:
                                st.warning(f"Paket {paket_id}: jadwal pemberian penjelasan tidak ditemukan di halaman jadwal.")
                        except Exception as e:
                            st.error(f"Paket {paket_id}: gagal scan jadwal — {e}")
                else:
                    from penjelasan_engine import _parse_datetime_str
                    waktu_fire = _parse_datetime_str(waktu_manual)
                    if not waktu_fire:
                        st.error(f"Format waktu tidak dikenali: {waktu_manual}")

                if waktu_fire:
                    job = penjelasan_engine.tambah_job(
                        paket_id      = paket_id,
                        nama_paket    = nama,
                        jenis         = jenis_key,
                        waktu_fire    = waktu_fire,
                        teks_override = teks_ov,
                    )
                    from datetime import datetime
                    from penjelasan_engine import TZ_WIB
                    now = datetime.now(TZ_WIB)
                    delta = waktu_fire - now
                    total_seconds = int(delta.total_seconds())
                    if total_seconds > 0:
                        jam   = total_seconds // 3600
                        menit = (total_seconds % 3600) // 60
                        detik = total_seconds % 60
                        st.info(
                            f"✅ Paket **{paket_id}** dijadwalkan pukul "
                            f"**{waktu_fire.strftime('%d/%m/%Y %H:%M')} WIB** "
                            f"(dalam {jam}j {menit}m {detik}d)"
                        )
                    else:
                        st.warning(f"⚠️ Paket {paket_id}: waktu sudah lewat! Pertimbangkan submit manual.")

    # ── Daftar jobs terjadwal ─────────────────────────────────────────────────
    st.divider()
    st.markdown("### Jobs Terjadwal")

    jobs = penjelasan_engine.get_jobs()
    if not jobs:
        st.info("Belum ada job terdaftar.")
    else:
        from datetime import datetime
        from penjelasan_engine import TZ_WIB
        now = datetime.now(TZ_WIB)

        for job in sorted(jobs, key=lambda j: j["waktu_fire"]):
            waktu_fire = datetime.fromisoformat(job["waktu_fire"])
            delta      = waktu_fire - now
            sisa_secs  = int(delta.total_seconds())

            status = job["status"]
            if status == "fired":
                icon = "✅"
            elif status == "gagal":
                icon = "❌"
            elif sisa_secs <= 0:
                icon = "⏰"
            else:
                jam   = sisa_secs // 3600
                menit = (sisa_secs % 3600) // 60
                icon  = f"⏳ {jam}j {menit}m"

            jenis_label = penjelasan_config.JENIS_PAKET.get(job["jenis"], job["jenis"])

            col_info, col_hapus, col_test = st.columns([4, 1, 1])
            with col_info:
                st.markdown(
                    f"**{icon}** `{job['paket_id']}` — {job['nama_paket'][:50]}  \n"
                    f"  {jenis_label} | "
                    f"  {waktu_fire.strftime('%d/%m/%Y %H:%M')} WIB | status: `{status}`"
                )
                if status == "gagal" and job.get("result"):
                    with st.expander(f"Detail error {job['paket_id']}"):
                        st.json(job["result"])
                if status == "fired" and job.get("result"):
                    with st.expander(f"Detail result {job['paket_id']}"):
                        st.json(job["result"])

            with col_hapus:
                if st.button("🗑️", key=f"hapus_{job['paket_id']}_{job['jenis']}", help="Hapus job"):
                    penjelasan_engine.hapus_job(job["paket_id"], job["jenis"])
                    st.rerun()

            with col_test:
                if st.button("🧪", key=f"test_{job['paket_id']}_{job['jenis']}", help="Test submit sekarang"):
                    with st.spinner(f"Test submit paket {job['paket_id']}..."):
                        try:
                            result = penjelasan_engine.submit_penjelasan(
                                paket_id      = job["paket_id"],
                                jenis         = job["jenis"],
                                teks_override = job.get("teks_override"),
                            )
                            if result["ok"]:
                                st.success(f"✅ HTTP {result['status']}")
                            else:
                                st.error(f"❌ HTTP {result['status']}")
                            with st.expander("Response"):
                                st.code(result["body"][:2000])
                        except Exception as e:
                            st.error(str(e))

    # ── Preview template ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("### Preview Template Teks")
    prev_jenis = st.selectbox(
        "Pilih template:",
        options=list(penjelasan_config.JENIS_PAKET.keys()),
        format_func=lambda k: penjelasan_config.JENIS_PAKET[k],
        key="prev_template_jenis",
    )
    st.text_area("Isi template:", value=penjelasan_config.TEMPLATE[prev_jenis], height=300, disabled=True)

    # ── Log scheduler ─────────────────────────────────────────────────────────
    st.divider()
    with st.expander("📋 Log Scheduler"):
        log_lines = penjelasan_engine.get_log()
        if log_lines:
            st.code("\n".join(reversed(log_lines[-50:])))
        else:
            st.info("Log kosong.")
        if st.button("🔄 Refresh Log"):
            st.rerun()


# ============================================================
# Tab 8: Auto-Fill Jadwal
# ============================================================

with tab8:
    st.subheader("📅 Auto-Fill Jadwal Tender")
    st.markdown(
        "Buat **12 tahapan jadwal tender** secara otomatis sesuai peraturan. "
        "Cukup masukkan **Kode Paket** + **Tanggal Mulai**, sistem akan menghitung "
        "semua tanggal dan submit langsung ke SPSE (tanpa perlu buka halaman edit manual)."
    )

    # ── Info aturan ───────────────────────────────────────────────────────────
    with st.expander("📖 Lihat Aturan 12 Tahapan"):
        for t in jadwal_config.TAHAPAN:
            st.write(f"**{t['id']}. {t['nama']}**")
            st.caption(t["aturan"])
            st.write("")

    st.divider()

    # ── Input ─────────────────────────────────────────────────────────────────
    col_kode, col_date, col_time = st.columns([3, 2, 2])
    with col_kode:
        paket_id = st.text_input(
            "🔢 Kode Tender",
            placeholder="Contoh: 4618177",
            help="Kode tender dari SPSE",
        )
    with col_date:
        default_date = datetime.now().date() + timedelta(days=1)
        tgl_input = st.date_input(
            "📆 Tanggal Mulai",
            value=default_date,
            help="Tanggal mulai Pengumuman Pascakualifikasi",
        )
    with col_time:
        jam_input = st.time_input(
            "🕐 Jam Mulai",
            value=datetime.strptime("08:00", "%H:%M").time(),
            help="Jam mulai (default 08:00)",
        )

    # ── Tombol ────────────────────────────────────────────────────────────────
    col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 1])
    with col_btn1:
        jd_preview = st.button(
            "🔍 Hitung & Preview (Dry Run)",
            use_container_width=True,
            disabled=not bool(paket_id),
            help="Hitung jadwal + simpan payload ke file JSON, TIDAK submit ke SPSE",
        )
    with col_btn2:
        jd_submit = st.button(
            "🚀 Set Jadwal ke SPSE",
            type="primary",
            use_container_width=True,
            disabled=not bool(paket_id),
        )
    with col_btn3:
        jd_save_file = st.button(
            "💾 Simpan JSON",
            use_container_width=True,
            disabled=not bool(paket_id),
            help="Simpan payload ke file JSON untuk inspeksi manual",
        )

    # ── Proses ────────────────────────────────────────────────────────────────
    if jd_preview or jd_submit or jd_save_file:
        tgl_mulai = datetime.combine(tgl_input, jam_input)

        with st.spinner(f"Scrap hidden fields + hitung jadwal untuk paket {paket_id}..."):
            try:
                result = jadwal_engine.auto_fill_jadwal(paket_id, tgl_mulai)
            except Exception as e:
                st.error(f"❌ Gagal: {e}")
                st.stop()

        st.session_state["jadwal_result"] = result
        st.session_state["jadwal_tgl_mulai"] = tgl_mulai
        st.session_state["jadwal_paket_id"] = paket_id

    # ── Save to JSON file (dry run only) ──────────────────────────────────────
    if jd_save_file and "jadwal_result" in st.session_state:
        result = st.session_state["jadwal_result"]
        paket_id = st.session_state["jadwal_paket_id"]
        payload = result["payload"]

        import json
        from pathlib import Path
        save_dir = Path(__file__).parent / "jadwal_output"
        save_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = save_dir / f"jadwal_{paket_id}_{timestamp}.json"

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump({
                "paket_id": paket_id,
                "tanggal_mulai": st.session_state["jadwal_tgl_mulai"].strftime("%d/%m/%Y %H:%M"),
                "jadwal_list": [
                    {
                        "nama": j["nama"],
                        "mulai": j["mulai"].strftime("%d/%m/%Y %H:%M"),
                        "selesai": j["selesai"].strftime("%d/%m/%Y %H:%M"),
                    }
                    for j in result["jadwal_list"]
                ],
                "payload": payload,
                "mode": "DRY_RUN — belum disubmit ke SPSE",
            }, f, indent=2, ensure_ascii=False)

        st.success(f"✅ Payload disimpan ke: `{save_path}`")
        st.info("📝 File JSON ini berisi semua data yang AKAN disubmit — bisa diinspeksi manual sebelum submit sungguhan.")

    if "jadwal_result" in st.session_state:
        result = st.session_state["jadwal_result"]
        tgl_mulai = st.session_state["jadwal_tgl_mulai"]
        paket_id = st.session_state["jadwal_paket_id"]
        jadwal_list = result["jadwal_list"]
        scraped = result["scraped"]
        payload = result["payload"]

        st.divider()
        st.success(f"✅ Jadwal dihitung dari: **{tgl_mulai.strftime('%d/%m/%Y %H:%M')}**")

        # ── Tabel preview ────────────────────────────────────────────────────
        st.markdown("### Preview Jadwal")

        df_data = []
        for j in jadwal_list:
            df_data.append({
                "Tahap": j["nama"][:50],
                "Mulai": j["mulai"].strftime("%d/%m/%Y %H:%M"),
                "Selesai": j["selesai"].strftime("%d/%m/%Y %H:%M"),
                "Selisih": str(j["selesai"] - j["mulai"]),
            })

        st.dataframe(
            df_data,
            use_container_width=True,
            column_config={
                "Tahap": st.column_config.TextColumn("Tahap", width="large"),
                "Mulai": st.column_config.TextColumn("Mulai"),
                "Selesai": st.column_config.TextColumn("Selesai"),
                "Selisih": st.column_config.TextColumn("Durasi"),
            },
            hide_index=True,
        )

        # ── Info ─────────────────────────────────────────────────────────────
        st.caption(
            f"CSRF: {'✅ ada' if scraped.get('csrf') else '⚠️ tidak ada'} | "
            f"Rows: {len(scraped.get('rows', []))} | "
            f"Paket: `{scraped.get('id', '?')}`"
        )

        # ── Submit ───────────────────────────────────────────────────────────
        if jd_submit:
            if not spse_browser.get_url():
                st.error("Browser belum terhubung. Hubungkan di sidebar dulu.")
            elif not scraped.get("csrf"):
                st.error("CSRF token tidak ditemukan. Pastikan Chrome sudah login SPSE.")
            else:
                with st.spinner("Submitting jadwal ke SPSE..."):
                    try:
                        submit_result = jadwal_engine.submit_jadwal(paket_id, payload)
                        if submit_result.get("ok"):
                            st.success(
                                f"✅ Jadwal berhasil disubmit! Status: {submit_result['status']}"
                            )
                            with st.expander("Response body"):
                                st.code(submit_result["body"][:2000])
                        else:
                            st.error(
                                f"❌ Gagal submit. Status: {submit_result['status']}"
                            )
                            with st.expander("Response body"):
                                st.code(submit_result["body"][:2000])
                    except Exception as e:
                        st.error(f"❌ Error submit: {e}")

    # ── Libur nasional info ──────────────────────────────────────────────────
    st.divider()
    with st.expander("ℹ️ Info Libur Nasional"):
        tahun = datetime.now().year
        try:
            liburs = jadwal_engine._fetch_libur_nasional(tahun)
            if liburs:
                st.success(f"✅ {len(liburs)} hari libur nasional {tahun} berhasil di-fetch")
                for l in sorted(liburs)[:10]:
                    hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
                    st.write(f"• {l.strftime('%d/%m/%Y')} ({hari[l.weekday()]})")
                if len(liburs) > 10:
                    st.write(f"... dan {len(liburs) - 10} lainnya")
            else:
                st.warning(f"⚠️ Tidak ada data libur nasional {tahun}")
        except Exception as e:
            st.error(f"❌ Gagal fetch libur nasional: {e}")
            st.info("Perhitungan tetap jalan tanpa filter libur.")
