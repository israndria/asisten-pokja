"""Reusable sidebar and display UI for Asisten Pokja."""

import os
import logging
import time

import streamlit as st

from config import SPSE_BASE_URL, ASISTEN_FIXED_ROLE, ASISTEN_INSTANCE, SPSE_CDP_PORT
import spse_browser


_LOGIN_ROLE_OPTIONS = [ASISTEN_FIXED_ROLE] if ASISTEN_FIXED_ROLE else [
    "PP", "POKJA", "PPK", "E-Katalog"
]


def _friendly_login_error(exc: Exception) -> str:
    """Ubah error teknis login menjadi petunjuk singkat untuk user."""
    msg = str(exc or "").lower()
    if "captcha" in msg or "ditolak" in msg:
        return "CAPTCHA ditolak atau tidak terbaca. Coba gunakan CAPTCHA manual."
    if "cdp" in msg or "connection" in msg or "connect" in msg:
        return "Brave/CDP terputus. Pastikan Brave POKJA aktif, lalu coba lagi."
    if "timeout" in msg or "timed out" in msg:
        return "Login melewati batas waktu. Pastikan Brave dan SPSE siap, lalu coba lagi."
    if "credential" in msg or "secret" in msg or "password" in msg:
        return "Kredensial role belum lengkap. Periksa secret_spse.env."
    return "Login gagal. Periksa Brave, SPSE, dan kredensial role, lalu coba lagi."


def _clear_login_failure_state() -> None:
    """Hapus pesan/error pipeline lama saat user mengganti role login."""
    st.session_state.pop("login_failed", None)
    st.session_state.pop("login_failed_role", None)
    st.session_state.pop("manual_spse_captcha", None)


def _finalize_authenticated_spse_login(role: str, log_fn=None) -> None:
    """Simpan sesi valid sebelum cleanup tab yang sifatnya best-effort."""
    import spse_login as _spse_login

    _spse_login.remember_login_role(role)
    st.session_state["spse_role"] = role
    st.session_state["_spse_session_epoch"] = time.time_ns()
    _clear_login_failure_state()

    try:
        spse_browser.buka_browser(SPSE_BASE_URL, navigate=False)
        spse_browser.rapikan_tab_spse()
        spse_browser.fokuskan_tab_spse()
    except Exception as exc:
        logging.warning("Cleanup tab pasca-login dilewati: %s", exc)
        if log_fn is not None:
            log_fn(f"Sesi {role} tervalidasi; cleanup tab dilewati: {exc}")
    spse_browser.mulai_auto_refresh()


@st.cache_data(show_spinner=False)
def _get_dark_css() -> str:
    return """
<style>
/* VS Code Dark+ Theme */
:root {
    color-scheme: dark;
}
.stApp {
    background-color: #141414 !important;
    color: #D4D4D4 !important;
}
[data-testid="stSidebar"] {
    background-color: #1A1A1B !important;
}
[data-testid="stHeader"] {
    background-color: #141414 !important;
}
.stTabs [data-baseweb="tab-list"] {
    background-color: #1A1A1B !important;
}
.stTabs [data-baseweb="tab"] {
    color: #D4D4D4 !important;
}
input, textarea, select, [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
    background-color: #3C3C3C !important;
    color: #D4D4D4 !important;
    border-color: #444444 !important;
}
[data-baseweb="select"] div, [data-baseweb="select"] span {
    background-color: #3C3C3C !important;
    color: #D4D4D4 !important;
}
.stDataFrame, [data-testid="stTable"] {
    background-color: #252526 !important;
}
[data-testid="stExpander"] {
    background-color: #252526 !important;
    border-color: #444444 !important;
}
/* Fix: label teks (checkbox, radio, selectbox, text_input) */
label, .stCheckbox label, .stRadio label,
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] span,
.stRadio [data-testid="stWidgetLabel"] p {
    color: #D4D4D4 !important;
}
/* Fix: radio button option text */
[data-baseweb="radio"] label, [data-baseweb="radio"] span,
[role="radio"] + div, [role="radio"] ~ span {
    color: #D4D4D4 !important;
}
/* Fix: caption / small text */
[data-testid="stCaptionContainer"] p,
.stCaption, small, .caption {
    color: #D4D4D4 !important;
}
/* Fix: semua paragraph / markdown text */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span {
    color: #D4D4D4 !important;
}
/* Fix: metric labels dan values */
[data-testid="stMetricLabel"] p,
[data-testid="stMetricValue"] div {
    color: #D4D4D4 !important;
}
/* Fix: semua input label */
[data-testid="stNumberInput"] label,
[data-testid="stDateInput"] label,
[data-testid="stSelectbox"] label,
[data-testid="stMultiSelect"] label,
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label,
[data-testid="stFileUploader"] label {
    color: #D4D4D4 !important;
}
/* Fix: info/warning/success/error box text */
[data-testid="stAlert"] p {
    color: #D4D4D4 !important;
}
/* Compact file uploader: hilang teks helper, dropzone kecil */
[data-testid="stFileUploaderDropzoneInstructions"] > div > span,
[data-testid="stFileUploaderDropzoneInstructions"] > div > small {
    display: none !important;
}
[data-testid="stFileUploaderDropzone"] {
    padding: 0.25rem 0.5rem !important;
    min-height: 0 !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] {
    padding: 0 !important;
}
[data-testid="stBaseButton-secondary"][data-testid*="FileUploader"],
[data-testid="stFileUploader"] button {
    padding: 0.15rem 0.5rem !important;
    font-size: 0.8rem !important;
    min-height: 0 !important;
}
/* Fix: warning box — amber border biar beda dari bg */
[data-testid="stAlert"][data-baseweb="notification"] {
    border-left: 4px solid #CCA700 !important;
}
/* Fix: semua st.button() → VS Code Dark+ button style */
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stBaseButton-secondary"]:focus,
[data-testid="stBaseButton-secondary"]:active {
    background-color: #0E639C !important;
    color: #ffffff !important;
    border-color: #1177BB !important;
}
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primary"]:focus,
[data-testid="stBaseButton-primary"]:active {
    background-color: #0E639C !important;
    color: #ffffff !important;
    border-color: #1177BB !important;
}
/* Fix: button text jangan wrap patah di tengah kata */
[data-testid^="stBaseButton"] p,
button p {
    white-space: nowrap !important;
    overflow: hidden;
    text-overflow: ellipsis;
}
/* Fix: expander header text */
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] details summary p {
    color: #D4D4D4 !important;
}
</style>
"""

@st.cache_data(show_spinner=False)
def _get_light_css() -> str:
    return """<style>
.stApp { background-color: #ffffff !important; color: #1e1e1e !important; }
[data-testid="stSidebar"] { background-color: #f3f3f3 !important; }
[data-testid="stHeader"] { background-color: #ffffff !important; }
.stTabs [data-baseweb="tab-list"] { background-color: #f3f3f3 !important; }
.stTabs [data-baseweb="tab"] { color: #1e1e1e !important; }
label, [data-testid="stWidgetLabel"] p, [data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] span,
[data-baseweb="radio"] label, [data-baseweb="radio"] span { color: #1e1e1e !important; }
[data-testid="stCaptionContainer"] p { color: #555555 !important; }
input, textarea, [data-baseweb="input"] input { background-color: #ffffff !important; color: #1e1e1e !important; border-color: #cccccc !important; }
[data-baseweb="select"] div, [data-baseweb="select"] span { background-color: #ffffff !important; color: #1e1e1e !important; }
[data-testid="stExpander"] { background-color: #f3f3f3 !important; border-color: #dddddd !important; }
[data-testid="stExpander"] summary p { color: #1e1e1e !important; }
</style>"""

@st.fragment
def _sidebar_login_form():
    if ASISTEN_FIXED_ROLE:
        st.caption(
            f"Instance {ASISTEN_INSTANCE}: login dikunci sebagai "
            f"{ASISTEN_FIXED_ROLE}; CDP port {SPSE_CDP_PORT}."
        )
    st.info("Brave SPSE belum terhubung")
    _relogin_reason = st.session_state.pop("_spse_relogin_reason", None)
    if _relogin_reason:
        st.warning(_relogin_reason)

    if st.button("🌐 Hubungkan ke Brave SPSE", type="primary", use_container_width=True):
        try:
            with st.spinner("Menghubungkan..."):
                spse_browser.buka_browser(SPSE_BASE_URL)
                if spse_browser.fokuskan_tab_spse() is None:
                    raise RuntimeError("Tidak ada tab SPSE yang dapat difokuskan di Brave.")
            st.success("Terhubung!")
            st.rerun(scope="app")
        except RuntimeError as e:
            st.error(str(e))

    st.divider()
    st.caption("💡 **Opsi otomatis:** Brave akan diluncurkan langsung dari sini")

    # Sinkronkan profil israndria ke session CDP
    with st.expander("⚙️ Profil Brave (israndria)", expanded=False):
        st.caption("Bookmark & setting dari profil israndria di-clone ke sesi CDP.\nHanya perlu dijalankan ulang jika ada perubahan bookmark/setting baru.")
        _col_sync1, _col_sync2 = st.columns(2)
        if _col_sync1.button("🔄 Sinkronkan Profil", use_container_width=True, key="btn_sync_profil"):
            with st.spinner("Menyinkronkan profil..."):
                _sync_ok, _sync_msg = spse_browser.clone_profil_ke_session(force=True)
            if _sync_ok:
                st.success(_sync_msg)
            else:
                st.error(_sync_msg)
        if _col_sync2.button("🗑️ Reset Profil", use_container_width=True, key="btn_reset_profil",
                              help="Hapus clone lama → clone ulang saat launch berikutnya"):
            _flag = os.path.join(spse_browser.BROWSER_SESSION_DIR, spse_browser._CLONE_FLAG)
            if os.path.exists(_flag):
                try:
                    os.unlink(_flag)
                    st.success("Flag clone dihapus — profil akan di-clone ulang saat launch.")
                except Exception as _fe:
                    st.error(str(_fe))
            else:
                st.info("Belum ada clone sebelumnya.")

    if st.session_state.get("header_login_role") not in _LOGIN_ROLE_OPTIONS:
        st.session_state["header_login_role"] = _LOGIN_ROLE_OPTIONS[0]
    _login_role = st.selectbox(
        "Login sebagai",
        _LOGIN_ROLE_OPTIONS,
        key="header_login_role",
        on_change=_clear_login_failure_state,
    )
    st.session_state["selected_login_role"] = _login_role

    if _login_role == "E-Katalog":
        import ekatalog_login as _ekl

        # Auto-load session dari file
        if not st.session_state.get("ekatalog_cookies"):
            _saved = _ekl.load_session()
            if _saved:
                st.session_state["ekatalog_cookies"] = _saved
                st.session_state["spse_role"] = "E-Katalog"

        _ek_logged_in = bool(st.session_state.get("ekatalog_cookies"))

        if not _ek_logged_in:
            if st.button("🚀 Launch & Login Inaproc", type="primary", use_container_width=True):
                try:
                    if not spse_browser._cek_cdp_aktif():
                        spse_browser.launch_chrome_dengan_cdp()
                        import time as _t2; _t2.sleep(3)
                        spse_browser.buka_browser(navigate=False)
                    with st.spinner("Membuka halaman login & mengisi email+password..."):
                        _status = _ekl.buka_dan_isi_login()
                    if _status == "ok":
                        _cookies = _ekl.ambil_cookies_cdp()
                        if _cookies:
                            st.session_state["ekatalog_cookies"] = _cookies
                            st.session_state["spse_role"] = "E-Katalog"
                            _ekl.save_session(_cookies)
                            st.success("✅ Login Inaproc berhasil! Session disimpan 8 jam.")
                            st.rerun(scope="app")
                    elif _status == "captcha":
                        st.session_state["ekatalog_need_captcha"] = True
                        st.rerun(scope="app")
                    else:
                        st.error(f"Login gagal: {_status}")
                except Exception as e:
                    st.error(f"Gagal: {e}")

            if st.session_state.get("ekatalog_need_captcha"):
                st.warning("⚠️ Centang **'Saya bukan robot'** di tab Brave, lalu klik **Masuk**.")
                if st.button("✅ Sudah Login Inaproc", type="primary", use_container_width=True):
                    try:
                        _cookies = _ekl.ambil_cookies_cdp()
                        if _cookies:
                            st.session_state["ekatalog_cookies"] = _cookies
                            st.session_state["spse_role"] = "E-Katalog"
                            st.session_state.pop("ekatalog_need_captcha", None)
                            _ekl.save_session(_cookies)
                            st.success("✅ Login berhasil! Session disimpan 8 jam.")
                            st.rerun(scope="app")
                        else:
                            st.warning("Cookies kosong — pastikan sudah login di tab Brave.")
                    except Exception as e:
                        st.error(f"Gagal ambil cookies: {e}")
        else:
            st.success("✅ Inaproc aktif")
            if st.button("🔄 Refresh Session", use_container_width=True):
                try:
                    _cookies = _ekl.ambil_cookies_cdp()
                    if _cookies:
                        st.session_state["ekatalog_cookies"] = _cookies
                        _ekl.save_session(_cookies)
                        st.success("Session diperbarui.")
                        st.rerun(scope="app")
                except Exception as e:
                    st.error(str(e))
            if st.button("🚪 Logout Inaproc", use_container_width=True):
                st.session_state.pop("ekatalog_cookies", None)
                st.session_state.pop("ekatalog_need_captcha", None)
                _ekl.clear_session()
                st.rerun(scope="app")
    else:
        st.caption("Auto-login: sesi aktif → Tesseract → GPT-5.6 Luna Medium → Gemini 2.5 Flash Lite.")
        if st.button(
            f"🚀 Buka Brave + Auto-Login ({_login_role})",
            type="secondary",
            use_container_width=True,
        ):
            _clear_login_failure_state()
            _login_logs: list[str] = []

            # Buffer log sejak tahap preflight; sebelumnya log baru dibuat
            # setelah connect CDP sehingga error cold-start tampil generik.
            def _log(msg: str):
                _login_logs.append(msg)

            try:
                import spse_login as _spse_login

                with st.spinner("Meluncurkan Brave SPSE..."):
                    # Pakai CDP existing bila sudah aktif; jangan launch instance kedua.
                    if not spse_browser._cek_cdp_aktif():
                        _log("CDP belum aktif; meluncurkan Brave...")
                        spse_browser.launch_chrome_dengan_cdp()
                    if not spse_browser.tunggu_cdp_ready(timeout_seconds=20):
                        raise RuntimeError(
                            f"CDP port {SPSE_CDP_PORT} belum siap setelah Brave diluncurkan."
                        )
                    _log("CDP siap; menghubungkan Playwright...")
                    # Init Playwright + connect CDP di loop spse_browser
                    spse_browser.buka_browser(navigate=False)
                    _log("Koneksi CDP berhasil; memeriksa tab SPSE...")
                    # Cold-start bisa membuat CDP sehat sebelum tab SPSE muncul
                    # di context Playwright. Jangan inspeksi/cleanup DOM di sini;
                    # _open_loginpass akan menstabilkan home setelah tab tersedia.
                    if spse_browser.tunggu_tab_spse_ready() is None:
                        raise RuntimeError("Brave hidup, tetapi tab SPSE belum tersedia.")
                    _log("Tab SPSE tersedia; melanjutkan ke pipeline login.")

                _log_box = st.empty()

                with st.spinner("Auto-login SPSE..."):
                    _login_ok = _spse_login.login_spse(role=_login_role, log_fn=_log)
                if not _login_ok:
                    raise RuntimeError("Pipeline auto-login tidak memvalidasi sesi SPSE.")

                # Tampilkan log setelah selesai (di main thread)
                _log_box.info("\n".join(_login_logs))
                _finalize_authenticated_spse_login(_login_role, log_fn=_log)
                st.success(f"✅ Brave & SPSE login sebagai {_login_role} berhasil!")
                st.rerun(scope="app")
            except Exception as e:
                logging.exception("SPSE auto-login gagal")
                st.session_state["login_failed"] = True
                st.session_state["login_failed_role"] = _login_role
                if "_login_logs" in locals() and _login_logs:
                    st.info("\n".join(_login_logs))
                st.error(_friendly_login_error(e))

    # Tombol retry — muncul kalau login gagal & browser masih di loginpass
    if st.session_state.get("login_failed") and spse_browser._cek_cdp_aktif():
        _retry_role = st.session_state.get("login_failed_role") or _LOGIN_ROLE_OPTIONS[0]
        if ASISTEN_FIXED_ROLE and _retry_role != ASISTEN_FIXED_ROLE:
            _retry_role = ASISTEN_FIXED_ROLE
        if st.button("🔄 Coba Lagi (pipeline otomatis)", type="primary", use_container_width=True):
            try:
                import spse_login as _spse_login
                _retry_logs: list[str] = []
                _rlog_box = st.empty()
                def _rlog(msg: str):
                    _retry_logs.append(msg)

                with st.spinner("Retry Tesseract → Luna → Gemini..."):
                    _spse_login.retry_captcha(role=_retry_role, log_fn=_rlog)

                _rlog_box.info("\n".join(_retry_logs))
                _spse_login.remember_login_role(_retry_role)
                spse_browser.buka_browser(SPSE_BASE_URL, navigate=False)
                st.session_state["spse_role"] = _retry_role
                st.session_state["_spse_session_epoch"] = time.time_ns()
                spse_browser.mulai_auto_refresh()
                st.session_state.pop("login_failed", None)
                st.session_state.pop("login_failed_role", None)
                st.success(f"✅ Login berhasil sebagai {_retry_role}!")
                st.rerun(scope="app")
            except Exception as e2:
                logging.exception("SPSE retry login gagal")
                st.error(_friendly_login_error(e2))

        _manual_captcha = st.text_input(
            "CAPTCHA terlihat di Brave",
            max_chars=8,
            placeholder="Isi 4-8 karakter",
            key="manual_spse_captcha",
        )
        if st.button("🔐 Login dengan CAPTCHA manual", use_container_width=True):
            if not _manual_captcha.strip():
                st.warning("Isi CAPTCHA yang terlihat di Brave terlebih dahulu.")
            else:
                try:
                    import spse_login as _spse_login
                    _manual_logs: list[str] = []
                    with st.spinner("Mengirim CAPTCHA manual..."):
                        _spse_login.submit_manual_captcha(
                            role=_retry_role,
                            captcha_text=_manual_captcha,
                            log_fn=_manual_logs.append,
                        )
                    _spse_login.remember_login_role(_retry_role)
                    st.info("\n".join(_manual_logs))
                    spse_browser.buka_browser(SPSE_BASE_URL, navigate=False)
                    st.session_state["spse_role"] = _retry_role
                    st.session_state["_spse_session_epoch"] = time.time_ns()
                    spse_browser.mulai_auto_refresh()
                    st.session_state.pop("login_failed", None)
                    st.session_state.pop("login_failed_role", None)
                    st.session_state.pop("manual_spse_captcha", None)
                    st.success(f"✅ Login berhasil sebagai {_retry_role}!")
                    st.rerun(scope="app")
                except Exception as e3:
                    st.error(f"Login manual gagal: {e3}")
