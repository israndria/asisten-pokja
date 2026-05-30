"""
Helper ringkasan akhir batch untuk Tab PL Streamlit.

API utama: render_ringkasan_batch(st, hasil_list)
Terima `st` sebagai argumen (dependency injection) agar modul tidak import streamlit
saat di-test di luar runtime Streamlit.
"""


def render_ringkasan_batch(st, hasil_list: list):
    """
    Render ringkasan akhir batch setelah loop selesai.

    hasil_list: list of dict, tiap dict 1 paket:
        {
            "nama"   : str   — nama paket,
            "status" : str   — "ok" | "skip" | "gagal",
            "detail" : str   — pesan singkat penyebab skip/gagal (boleh kosong jika ok),
        }

    Render:
    - 3 metric (OK / SKIP / GAGAL) pakai st.columns(3)
    - Paket OK cukup dihitung
    - Paket skip/gagal ditampilkan eksplisit: nama + alasan
    - Kalau semua OK: st.success
    """
    if not hasil_list:
        return

    ok_list    = [h for h in hasil_list if h.get("status") == "ok"]
    skip_list  = [h for h in hasil_list if h.get("status") == "skip"]
    gagal_list = [h for h in hasil_list if h.get("status") == "gagal"]

    n_ok    = len(ok_list)
    n_skip  = len(skip_list)
    n_gagal = len(gagal_list)

    st.markdown("---")
    st.markdown("### Ringkasan Batch")

    col_ok, col_skip, col_gagal = st.columns(3)
    col_ok.metric("Berhasil", n_ok)
    col_skip.metric("Dilewati", n_skip)
    col_gagal.metric("Gagal", n_gagal)

    if n_skip == 0 and n_gagal == 0:
        st.success(f"Semua {n_ok} paket berhasil.")
        return

    if skip_list:
        st.warning(f"**{n_skip} paket dilewati (SKIP):**")
        for h in skip_list:
            alasan = h.get("detail") or "-"
            st.markdown(f"- **{h['nama']}** — {alasan}")

    if gagal_list:
        st.error(f"**{n_gagal} paket gagal:**")
        for h in gagal_list:
            alasan = h.get("detail") or "-"
            st.markdown(f"- **{h['nama']}** — {alasan}")
